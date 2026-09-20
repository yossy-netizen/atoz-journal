"""A/B 試聴用の簡易シンセ。DAW なしでカーブの効果を確認するためのもの。

倍音を数本重ねた減衰付きの波形に ADSR をかけ、セント偏差カーブでピッチを変調する。
音源としての品質は目的ではなく、「静止ピッチ」との差が聴き取れれば十分。
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from .generate import Contour


def midi_to_hz(p: float) -> float:
    return 440.0 * 2.0 ** ((p - 69.0) / 12.0)


def _adsr(n: int, sr: int, a: float = 0.02, d: float = 0.05, s: float = 0.85, r: float = 0.08) -> np.ndarray:
    env = np.ones(n)
    na, nd, nr = int(a * sr), int(d * sr), int(r * sr)
    na, nd, nr = min(na, n), min(nd, max(n - na, 0)), min(nr, n)
    if na:
        env[:na] = np.linspace(0, 1, na)
    if nd:
        env[na:na + nd] = np.linspace(1, s, nd)
    env[na + nd:] = s
    if nr:
        env[-nr:] *= np.linspace(1, 0, nr)
    return env


def synthesize(contour: Contour, sr: int = 44100, harmonics: int = 8, tail_s: float = 0.3, gain: float = 0.5) -> np.ndarray:
    """Contour を float32 のモノラル波形にする。"""
    total = max(nc.note.offset for nc in contour.notes) + tail_s if contour.notes else 1.0
    out = np.zeros(int(total * sr) + 1, dtype=np.float64)
    amps = np.array([0.7 ** k / (k + 1) for k in range(harmonics)])
    for nc in contour.notes:
        n = nc.note
        n_samp = int(n.duration * sr)
        if n_samp < 2:
            continue
        # hop 刻みのセント偏差をサンプル単位に線形補間
        t_samp = np.arange(n_samp) / sr
        cents = np.interp(t_samp, nc.t, nc.cents)
        freq = midi_to_hz(n.pitch) * 2.0 ** (cents / 1200.0)
        phase = 2 * np.pi * np.cumsum(freq) / sr
        sig = np.zeros(n_samp)
        for k, a in enumerate(amps):
            if midi_to_hz(n.pitch) * (k + 1) < sr / 2:
                sig += a * np.sin(phase * (k + 1))
        sig *= _adsr(n_samp, sr) * (n.velocity / 127.0)
        start = int(n.onset * sr)
        out[start:start + n_samp] += sig
    peak = np.abs(out).max()
    if peak > 0:
        out *= gain / peak
    return out.astype(np.float32)


def write_wav(path: str | Path, audio: np.ndarray, sr: int = 44100) -> None:
    pcm = np.clip(audio, -1, 1)
    pcm = (pcm * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """16/24/32bit PCM の WAV をモノラル float32 で読む（ステレオは平均）。"""
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sw == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    elif sw == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v & 0x800000, v - 0x1000000, v)
        x = v.astype(np.float32) / 8388608.0
    else:
        raise ValueError(f"未対応のサンプル幅: {sw}")
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr
