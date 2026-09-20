"""F0 抽出: YIN（de Cheveigné & Kawahara, 2002）の numpy 実装。

依存を増やさないための自前実装。精度が要る段階では CREPE / PESTO / pYIN に
差し替える前提で、インターフェース（times, f0_hz, confidence）だけ揃えている。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class F0Track:
    times: np.ndarray        # 秒（フレーム中心）
    f0_hz: np.ndarray        # Hz。無声は nan
    confidence: np.ndarray   # 0..1（1 - CMNDF 最小値）
    hop_s: float
    rms: np.ndarray | None = None  # フレームごとの RMS（ダイナミクス解析用）

    @property
    def voiced(self) -> np.ndarray:
        return ~np.isnan(self.f0_hz)

    @property
    def midicents(self) -> np.ndarray:
        """MIDI ノート番号 × 100 のセント尺度（無声は nan）。"""
        with np.errstate(divide="ignore", invalid="ignore"):
            return 100.0 * (69.0 + 12.0 * np.log2(self.f0_hz / 440.0))


def yin_f0(
    x: np.ndarray,
    sr: int,
    hop_s: float = 0.005,
    fmin: float = 80.0,
    fmax: float = 1500.0,
    window_s: float = 0.023,
    threshold: float = 0.15,
    rms_gate: float = 0.005,
    batch: int = 256,
) -> F0Track:
    if fmax <= fmin:
        raise ValueError(f"fmax ({fmax}) は fmin ({fmin}) より大きい必要があります")
    x = np.asarray(x, dtype=np.float64)
    hop = max(int(round(sr * hop_s)), 1)
    W = max(int(sr * window_s), 64)
    max_lag = int(sr / fmin)
    min_lag = max(int(sr / fmax), 2)
    L = W + max_lag + 1
    n_frames = max((len(x) - L) // hop + 1, 0)
    if n_frames == 0:
        return F0Track(np.zeros(0), np.zeros(0), np.zeros(0), hop / sr)

    N = 1 << int(np.ceil(np.log2(2 * L)))
    f0 = np.full(n_frames, np.nan)
    conf = np.zeros(n_frames)
    rms_all = np.zeros(n_frames)
    taus = np.arange(max_lag + 1)

    for b0 in range(0, n_frames, batch):
        b1 = min(b0 + batch, n_frames)
        idx = (np.arange(b0, b1) * hop)[:, None] + np.arange(L)[None, :]
        frames = x[idx]
        a = frames[:, :W]
        rms = np.sqrt((a ** 2).mean(axis=1))
        rms_all[b0:b1] = rms
        # 相関 corr[tau] = sum_j a[j] * frames[j + tau]
        A = np.fft.rfft(a, N, axis=1)
        B = np.fft.rfft(frames, N, axis=1)
        corr = np.fft.irfft(np.conj(A) * B, N, axis=1)[:, : max_lag + 1]
        e0 = (a ** 2).sum(axis=1, keepdims=True)
        cs = np.concatenate([np.zeros((b1 - b0, 1)), np.cumsum(frames ** 2, axis=1)], axis=1)
        e_tau = cs[:, W + taus] - cs[:, taus]
        d = np.maximum(e0 + e_tau - 2.0 * corr, 0.0)
        # CMNDF
        cum = np.cumsum(d[:, 1:], axis=1)
        cmndf = np.ones_like(d)
        cmndf[:, 1:] = d[:, 1:] * np.arange(1, max_lag + 1)[None, :] / np.maximum(cum, 1e-12)

        for i in range(b1 - b0):
            row = cmndf[i]
            if rms[i] < rms_gate:
                continue
            seg = row[min_lag:max_lag]
            below = np.nonzero(seg < threshold)[0]
            if len(below):
                tau = min_lag + below[0]
                while tau + 1 < max_lag and row[tau + 1] < row[tau]:
                    tau += 1
            else:
                tau = min_lag + int(np.argmin(seg))
                if row[tau] > 0.5:  # 周期性が弱い → 無声
                    conf[b0 + i] = max(0.0, 1.0 - row[tau])
                    continue
            # 放物線補間
            if 1 <= tau < max_lag:
                y0, y1, y2 = row[tau - 1], row[tau], row[tau + 1]
                denom = y0 - 2 * y1 + y2
                delta = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
                delta = float(np.clip(delta, -1, 1))
            else:
                delta = 0.0
            f0[b0 + i] = sr / (tau + delta)
            conf[b0 + i] = max(0.0, 1.0 - row[tau])

    times = (np.arange(n_frames) * hop + W / 2) / sr
    return F0Track(times=times, f0_hz=f0, confidence=conf, hop_s=hop / sr, rms=rms_all)
