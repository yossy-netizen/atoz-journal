"""音声 → F0 → ノート分割 → 成分推定 → プロファイル。

generate.py の分解モデルの逆問題を、ルールベースで解く（L0 相当）。
各推定は近似であり、フェーズ 0 の実測で妥当性を確認しながら精度を上げる前提。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np

from .f0 import F0Track, detect_f0
from .key import detect_key
from .notes import Note
from .generate import _moving_average
from .profile import Dist, Profile


@dataclass
class AnalyzedNote:
    pitch: int
    onset: float
    offset: float
    t: np.ndarray          # 絶対秒
    dev: np.ndarray        # 目標音（pitch）からの偏差（セント）
    params: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.offset - self.onset


# ----------------------------------------------------------------------------
# ノート分割
# ----------------------------------------------------------------------------

def _median_filter(x: np.ndarray, win: int) -> np.ndarray:
    if win <= 1 or len(x) < win:
        return x
    pad = win // 2
    xp = np.pad(x, (pad, win - 1 - pad), mode="edge")
    idx = np.arange(len(x))[:, None] + np.arange(win)[None, :]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(xp[idx], axis=1)


def _fill_nan(x: np.ndarray) -> np.ndarray:
    x = x.copy()
    bad = np.isnan(x)
    if bad.all():
        return np.zeros_like(x)
    if bad.any():
        idx = np.arange(len(x))
        x[bad] = np.interp(idx[bad], idx[~bad], x[~bad])
    return x


def fix_octave_errors(track: F0Track, window: int = 15, jump_cents: float = 900.0, accept_cents: float = 250.0) -> int:
    """時間的連続性に基づくオクターブ誤検出の補正。近傍の中央値から 1 オクターブ前後ずれた
    フレームを、±1200 セントで近傍に収まるなら移す。修正前の値は track.raw_f0_hz に残る。戻り値は修正数。"""
    mc = track.midicents
    voiced = ~np.isnan(mc)
    if voiced.sum() < window:
        return 0
    filled = _fill_nan(mc)
    ref = _median_filter(filled, window)
    fixed = 0
    f0 = track.f0_hz
    for i in np.nonzero(voiced)[0]:
        d = mc[i] - ref[i]
        if abs(d) < jump_cents:
            continue
        for shift in (-1200.0, 1200.0, -2400.0, 2400.0):
            if abs(d + shift) < accept_cents:
                f0[i] = f0[i] * 2.0 ** (shift / 1200.0)
                fixed += 1
                break
    return fixed


def estimate_tuning(notes: list[AnalyzedNote], track: F0Track) -> float:
    """音符ごとのイントネーション推定値（ビブラート開始前の区間を優先した中央値）の
    音長重み付き中央値から基準ピッチ A4 を推定する。442 Hz の録音を「常に +8 セント高い奏者」と
    誤認しないため。estimate_note_params の後に呼ぶ（params が無い音符は安定区間の中央値を使う）。"""
    hop = track.hop_s
    vals = []
    weights = []
    for n in notes:
        if "intonation_novib_cents" in n.params:
            vals.append(float(n.params["intonation_novib_cents"]))
            weights.append(n.params["novib_frames"] * hop)
            continue
        if "intonation_cents" in n.params:
            vals.append(float(n.params["intonation_cents"]))
            # ビブラートの中心ずれを含む推定値は重みを下げる
            w = 0.25 if n.params.get("intonation_source") == "stable_with_vibrato" else 1.0
            weights.append(n.duration * w)
            continue
        dev = _fill_nan(n.dev)
        L = len(dev)
        a0 = min(int(0.08 / hop), L // 3)
        a1 = max(L - int(0.06 / hop), a0 + 2)
        seg = dev[a0:a1] if a1 > a0 else dev
        if len(seg):
            vals.append(float(np.median(seg)))
            weights.append(n.duration)
    if not vals:
        return 440.0
    order = np.argsort(vals)
    v = np.array(vals)[order]
    w = np.array(weights)[order]
    cum = np.cumsum(w) / w.sum()
    offset = float(v[int(np.searchsorted(cum, 0.5))])
    return float(440.0 * 2.0 ** (offset / 1200.0))


def segment_notes(
    track: F0Track,
    min_note_s: float = 0.06,
    split_cents: float = 55.0,
    split_hold_s: float = 0.03,
    gap_s: float = 0.03,
    ref_window_s: float = 0.3,
    refractory_s: float = 0.15,
    smooth_s: float = 0.12,
) -> list[AnalyzedNote]:
    """F0 軌跡を音符に分割する。

    - 無声が gap_s 以上続いたら音符を閉じる
    - 直近 ref_window_s の中央値から split_cents 以上離れた状態が split_hold_s 続いたら
      その離れ始めで音符を切る（ポルタメントの途中で切れる）
    - 切った直後 refractory_s の間は再分割しない（長いポルタメントの途中で細切れになるのを防ぐ）
    """
    hop = track.hop_s
    mc = _median_filter(track.midicents, 5)
    voiced = ~np.isnan(mc)
    # 分割判定はビブラートを平均化した軌跡で行い、分割点は生の軌跡がしきい値を越えた位置に戻す
    smooth_n = max(int(round(smooth_s / hop)), 1)
    mc_s = _moving_average(_fill_nan(mc), smooth_n) if voiced.any() else mc
    hold = max(int(round(split_hold_s / hop)), 1)
    gap = max(int(round(gap_s / hop)), 1)
    ref_n = max(int(round(ref_window_s / hop)), 2)
    refractory = max(int(round(refractory_s / hop)), 1)

    notes: list[AnalyzedNote] = []
    start = None
    unvoiced_run = 0
    dev_run_start = None

    def close(s: int, e: int):
        if e - s < max(int(round(min_note_s / hop)), 2):
            return
        seg = mc[s:e]
        good = seg[~np.isnan(seg)]
        if len(good) < 2:
            return
        pitch = int(round(np.median(good) / 100.0))
        dev = seg - pitch * 100.0
        notes.append(AnalyzedNote(pitch=pitch, onset=float(track.times[s]), offset=float(track.times[e - 1] + hop),
                                  t=track.times[s:e].copy(), dev=dev))

    for i in range(len(mc)):
        if not voiced[i]:
            unvoiced_run += 1
            if start is not None and unvoiced_run >= gap:
                close(start, i - unvoiced_run + 1)
                start = None
            dev_run_start = None
            continue
        unvoiced_run = 0
        if start is None:
            start = i
            dev_run_start = None
            continue
        if i - start < refractory:
            continue
        ref_seg = mc[max(start, i - ref_n):i]
        ref_seg = ref_seg[~np.isnan(ref_seg)]
        if len(ref_seg) == 0:
            continue
        ref = np.median(ref_seg)
        if abs(mc_s[i] - ref) > split_cents:
            if dev_run_start is None:
                dev_run_start = i
            elif i - dev_run_start + 1 >= hold:
                # 生の軌跡がしきい値を越え始めた位置（平滑化の遅れ分だけ前）まで戻る
                cut = dev_run_start
                lo = max(start + 1, dev_run_start - smooth_n)
                for j in range(dev_run_start, lo - 1, -1):
                    if voiced[j] and abs(mc[j] - ref) > split_cents:
                        cut = j
                    else:
                        break
                close(start, cut)
                start = cut
                dev_run_start = None
        else:
            dev_run_start = None
    if start is not None:
        close(start, len(mc) - unvoiced_run)
    notes = merge_glides(notes)
    if track.rms is not None and len(track.rms) == len(mc):
        notes = split_on_energy_dips(notes, track, min_note_s=min_note_s)
    return notes


def split_on_energy_dips(notes: list[AnalyzedNote], track: F0Track, min_note_s: float = 0.06,
                         dip_ratio: float = 0.5, recover_ratio: float = 0.8, window_s: float = 0.08,
                         guard_s: float = 0.12) -> list[AnalyzedNote]:
    """同じ音高が続く連打はピッチでは分けられないので、音量（RMS）の落ち込みで分ける。
    直前の水準から dip_ratio 以下（約 -6 dB）に落ち、window_s 以内に recover_ratio まで戻る点を
    新しい音符の開始とみなす。両側が min_note_s 以上あるときだけ分割する。"""
    hop = track.hop_s
    win = max(int(window_s / hop), 2)
    min_n = max(int(round(min_note_s / hop)), 2)
    out: list[AnalyzedNote] = []
    carry: AnalyzedNote | None = None   # 次の音の頭に付ける短い末尾片（次の音への滑り）

    def prepend(piece: AnalyzedNote, n: AnalyzedNote) -> AnalyzedNote:
        return AnalyzedNote(pitch=n.pitch, onset=piece.onset, offset=n.offset,
                            t=np.concatenate([piece.t, n.t]),
                            dev=np.concatenate([piece.dev + (piece.pitch - n.pitch) * 100.0, n.dev]))

    for idx, n in enumerate(notes):
        if carry is not None:
            n = prepend(carry, n)
            carry = None
        nxt = notes[idx + 1] if idx + 1 < len(notes) else None
        i0 = int(np.searchsorted(track.times, n.onset))
        i1 = i0 + len(n.t)
        rms = track.rms[i0:i1]
        if len(rms) < 3 * min_n:
            out.append(n)
            continue
        cuts = []
        last_cut = 0
        # 先頭 guard_s はピッチ境界の直後なので見ない（境界がずれて二重に切るのを防ぐ）
        k = max(win, int(guard_s / hop))
        while k < len(rms) - win:
            before = rms[max(k - win, last_cut):k].max()
            if before > 0 and rms[k] <= dip_ratio * before:
                # 落ち込みの底を探し、その後の回復を確認
                j = k + int(np.argmin(rms[k:k + win]))
                after = rms[j:j + win].max()
                if after >= recover_ratio * before and j - last_cut >= min_n and len(rms) - j >= min_n:
                    cuts.append(j)
                    last_cut = j
                    k = j + win
                    continue
            k += 1
        if not cuts:
            out.append(n)
            continue
        bounds = [0] + cuts + [len(n.t)]
        pieces: list[AnalyzedNote] = []
        for a, b in zip(bounds, bounds[1:]):
            seg = n.dev[a:b]
            good = seg[~np.isnan(seg)]
            if len(good) < 2:
                continue
            pitch = int(round(np.median(good + n.pitch * 100.0) / 100.0))
            pieces.append(AnalyzedNote(pitch=pitch, onset=float(n.t[a]), offset=float(n.t[b - 1] + hop),
                                       t=n.t[a:b].copy(), dev=seg + (n.pitch - pitch) * 100.0))
        # 末尾の短い片が次の音に隣接しているなら、それはピッチ境界が遅れた分（次の音への滑り）。
        # 独立した音符にせず次の音の頭に付ける
        if (len(pieces) >= 2 and nxt is not None and pieces[-1].duration <= 0.2
                and nxt.onset - pieces[-1].offset <= 0.03):
            carry = pieces.pop()
        out.extend(pieces)
    if carry is not None:
        out.append(carry)
    return out


def merge_glides(notes: list[AnalyzedNote], max_len_s: float = 0.25, min_slope_cents_s: float = 400.0, gap_s: float = 0.03) -> list[AnalyzedNote]:
    """短くて一方向に急変する区間（アタックのしゃくり、音末のフォール）は独立した音符ではなく
    隣の音符の一部として併合する。上向きなら次の音へ、下向きなら前の音へ。"""
    if len(notes) < 2:
        return notes
    out: list[AnalyzedNote] = []
    i = 0
    while i < len(notes):
        n = notes[i]
        slope = tail_slope = 0.0
        if n.duration <= max_len_s and len(n.t) >= 5:
            dev = _fill_nan(n.dev)
            tt = n.t - n.t[0]
            slope = float(np.polyfit(tt, dev, 1)[0])
            k = max(len(tt) * 6 // 10, 2)
            tail_slope = float(np.polyfit(tt[k:], dev[k:], 1)[0]) if len(tt) - k >= 2 else slope
        span = float(np.nanmax(n.dev) - np.nanmin(n.dev)) if len(n.t) else 0.0
        # 全体も後半も同じ向きに動き続けている（＝落ち着く平坦部がない）ものだけを滑りとみなす。
        # 頭にポルタメントが付いた短い音符は後半が平坦なので併合しない
        is_glide = (n.duration <= max_len_s and abs(slope) >= min_slope_cents_s and span >= 60.0
                    and np.sign(tail_slope) == np.sign(slope) and abs(tail_slope) >= min_slope_cents_s * 0.5)
        nxt = notes[i + 1] if i + 1 < len(notes) else None
        prv = out[-1] if out else None
        # 向きで振り分ける（上向き = 次の音へのしゃくり、下向き = 前の音のフォール）。
        # 音高の近さで振り分ける案は往復評価で悪化したため採用していない
        to_next = is_glide and slope > 0 and nxt is not None and nxt.onset - n.offset <= gap_s
        to_prev = is_glide and slope < 0 and prv is not None and n.onset - prv.offset <= gap_s
        if to_next:
            # 上向きのしゃくり → 次の音の頭に付ける
            merged = AnalyzedNote(pitch=nxt.pitch, onset=n.onset, offset=nxt.offset,
                                  t=np.concatenate([n.t, nxt.t]),
                                  dev=np.concatenate([n.dev + (n.pitch - nxt.pitch) * 100.0, nxt.dev]))
            notes[i + 1] = merged
            i += 1
            continue
        if to_prev:
            # 下向きのフォール → 前の音の尻に付ける
            prv.offset = n.offset
            prv.t = np.concatenate([prv.t, n.t])
            prv.dev = np.concatenate([prv.dev, n.dev + (n.pitch - prv.pitch) * 100.0])
            i += 1
            continue
        out.append(n)
        i += 1
    return out


# ----------------------------------------------------------------------------
# 成分推定
# ----------------------------------------------------------------------------

def vibrato_envelope(dev: np.ndarray, hop_s: float, fmin: float = 3.0, fmax: float = 9.5) -> np.ndarray:
    """ビブラート帯域（fmin〜fmax Hz）の解析信号の包絡（セント）。検出の可否に関わらず使える。"""
    n = len(dev)
    if n < 8:
        return np.zeros(n)
    x = _fill_nan(dev)
    tt = np.arange(n)
    x = x - np.polyval(np.polyfit(tt, x, 1), tt)
    nfft = 1 << int(np.ceil(np.log2(n * 4)))
    X = np.fft.rfft(x, nfft)
    freqs = np.fft.rfftfreq(nfft, hop_s)
    keep = (freqs >= fmin) & (freqs <= fmax)
    bp = np.where(keep, X, 0)
    analytic = np.fft.ifft(np.concatenate([bp * 2, np.zeros(nfft - len(bp), dtype=complex)]))[:n]
    return np.abs(analytic)


def estimate_attack(y: np.ndarray, hop_s: float, conf: np.ndarray | None = None, window_s: float = 0.12,
                    min_conf: float = 0.9, max_skip_s: float = 0.03) -> tuple[float, float]:
    """発音直後の偏差 y（イントネーション差し引き後）から、発音時点の偏差（セント）と
    収束時間（ms）を推定する。

    F0 抽出の窓が発音点をまたぐ最初の 15〜20 ms は信頼できない（信頼度が低い）ので捨て、
    その後の指数減衰 y = A·exp(-t/τ) を対数線形回帰で当てはめて t=0（発音点）へ外挿する。"""
    L = len(y)
    settled = np.nonzero(np.abs(y) < 10.0)[0]
    settle_ms = float(settled[0] * hop_s * 1000.0) if len(settled) else float(L * hop_s * 1000.0)
    k0 = 0
    if conf is not None and len(conf) >= len(y):
        good = np.nonzero(conf[:L] >= min_conf)[0]
        k0 = int(min(good[0], int(max_skip_s / hop_s))) if len(good) else int(max_skip_s / hop_s)
    k1 = max(min(int(window_s / hop_s), L), k0 + 2)
    seg = y[k0:k1]
    if len(seg) == 0:
        return 0.0, settle_ms
    first = float(np.mean(seg[: min(3, len(seg))]))
    sign = 1.0 if first >= 0 else -1.0
    ok = (sign * seg > 3.0)
    run = 0
    while run < len(seg) and ok[run]:
        run += 1
    if run >= 3:
        t = (k0 + np.arange(run)) * hop_s
        coef = np.polyfit(t, np.log(sign * seg[:run]), 1)
        if coef[0] < 0:  # 減衰している
            A = sign * float(np.exp(coef[1]))
            tau_ms = -1000.0 / coef[0]
            if abs(A) <= 4.0 * max(abs(first), 3.0) and 5.0 <= tau_ms <= 600.0:
                return A, settle_ms
    return first, settle_ms


def estimate_vibrato(dev: np.ndarray, hop_s: float, fmin: float = 3.5, fmax: float = 9.0, prominence: float = 2.5) -> dict | None:
    """安定区間の偏差からビブラート（rate / depth / onset）を推定する。なければ None。"""
    n = len(dev)
    if n * hop_s < 0.3:
        return None
    x = _fill_nan(dev)
    tt = np.arange(n)
    x = x - np.polyval(np.polyfit(tt, x, 1), tt)  # 線形トレンド除去
    win = np.hanning(n)
    nfft = 1 << int(np.ceil(np.log2(n * 8)))
    X = np.fft.rfft(x * win, nfft)
    freqs = np.fft.rfftfreq(nfft, hop_s)
    mag = np.abs(X)
    band = (freqs >= 2.5) & (freqs <= 12.0)
    search = (freqs >= fmin) & (freqs <= fmax)
    if not search.any():
        return None
    k = int(np.argmax(np.where(search, mag, -1)))
    peak_pow = mag[k] ** 2
    band_mean = (mag[band] ** 2).mean() if band.any() else 0.0
    if band_mean <= 0 or peak_pow / band_mean < prominence:
        return None
    rate = float(freqs[k])
    depth_fft = float(2.0 * mag[k] / win.sum())
    # 帯域通過 → 解析信号の包絡で深さと立ち上がりを見る
    Xf = np.fft.rfft(x, nfft)
    bp = np.zeros_like(Xf)
    keep = (freqs >= max(rate - 1.5, 2.5)) & (freqs <= rate + 1.5)
    bp[keep] = Xf[keep]
    analytic = np.fft.ifft(np.concatenate([bp * 2, np.zeros(nfft - len(bp), dtype=complex)]))[:n]
    env = np.abs(analytic)
    depth = float(np.median(env[n // 2:]))
    if depth < 3.0:
        return None
    # 開始とランプ: 包絡が 15% → 85% を越える時刻から、線形近似でランプの始点と長さを推定
    lo_idx = np.nonzero(env > 0.15 * depth)[0]
    t_lo = float(lo_idx[0] * hop_s) if len(lo_idx) else 0.0
    hi_idx = np.nonzero(env[lo_idx[0]:] > 0.85 * depth)[0] if len(lo_idx) else np.zeros(0, dtype=int)
    t_hi = float((lo_idx[0] + hi_idx[0]) * hop_s) if len(hi_idx) else t_lo
    ramp = max((t_hi - t_lo) / 0.7, 0.02)
    onset = max(t_lo - 0.15 * ramp, 0.0)
    # レートの精密化: 包絡が立った区間の瞬時周波数（位相の微分）の中央値。短い音では
    # スペクトルのピークより精度が高い
    phase = np.unwrap(np.angle(analytic))
    inst = np.diff(phase) / (2.0 * np.pi * hop_s)
    mask = env[1:] > 0.5 * depth
    if mask.sum() >= int(0.25 / hop_s):
        r_inst = float(np.median(inst[mask]))
        if fmin <= r_inst <= fmax:
            rate = r_inst
    return {"rate_hz": rate, "depth_cents": depth, "depth_fft_cents": depth_fft, "onset_ms": onset * 1000.0,
            "ramp_ms": ramp * 1000.0, "env": env}


def estimate_transition(track_mc: np.ndarray, times: np.ndarray, prev: AnalyzedNote, cur: AnalyzedNote, window_s: float = 0.15, smear_s: float = 0.03) -> dict | None:
    """前後の音符の境界周辺で、ポルタメントの所要時間とオーバーシュートを推定する。"""
    frm, to = prev.pitch * 100.0, cur.pitch * 100.0
    interval = to - frm
    if abs(interval) < 100:
        return None
    tb = cur.onset
    sel = (times >= tb - window_s) & (times <= tb + window_s)
    if sel.sum() < 4:
        return None
    mc = _fill_nan(track_mc[sel])
    tt = times[sel]
    prog = (mc - frm) / interval
    reach = np.nonzero(prog >= 0.8)[0]
    if not len(reach):
        return None
    i80 = reach[0]
    before = np.nonzero(prog[:i80] <= 0.2)[0]
    if not len(before):
        return None
    i20 = before[-1]
    dur = tt[i80] - tt[i20]  # 進行率 20%→80% の所要時間（profile.transition.duration_ms と同じ定義）
    # F0 抽出窓とメディアンフィルタによる時間のにじみを二乗和で差し引く
    dur = float(np.sqrt(max(dur ** 2 - smear_s ** 2, 0.0)))
    hop = float(np.median(np.diff(tt))) if len(tt) > 1 else 0.005
    after = prog[i80: i80 + int(0.1 / hop) + 1]
    overshoot = max(float(after.max() - 1.0), 0.0) * abs(interval) if len(after) else 0.0
    span = max(tt[i80] - tt[i20], hop)
    # 20→80% から 0→100% の位置を外挿（遷移境界はノート境界と別に持つ）
    return {"portamento": dur > 0.012, "duration_ms": dur * 1000.0, "interval": interval / 100.0, "overshoot_cents": overshoot,
            "start_sec": float(tt[i20] - span / 3.0), "end_sec": float(tt[i80] + span / 3.0)}


def estimate_note_params(notes: list[AnalyzedNote], track: F0Track, max_gap_s: float = 0.04) -> None:
    """各音符の params を埋める（in place）。"""
    hop = track.hop_s
    mc = _median_filter(track.midicents, 5)
    for i, n in enumerate(notes):
        p: dict = {}
        dev = _fill_nan(n.dev)
        L = len(dev)
        a0 = min(int(0.08 / hop), L // 3)
        a1 = max(L - int(0.06 / hop), a0 + 2)
        stable = dev[a0:a1] if a1 > a0 else dev
        into = float(np.median(stable))
        # アタックのしゃくりが長い（ジャズのスクープ等）ときは、収束してから安定区間を始める
        settled0 = np.nonzero(np.abs(dev - into) < 10.0)[0]
        if len(settled0) and settled0[0] > a0:
            a0 = min(int(settled0[0]) + 4, max(L // 2, a0))
            a1 = max(L - int(0.06 / hop), a0 + 2)
            stable = dev[a0:a1] if a1 > a0 else dev[a0:]
            into = float(np.median(stable)) if len(stable) else into
        p["intonation_cents"] = into
        p["intonation_source"] = "stable"

        prev = notes[i - 1] if i > 0 else None
        nxt = notes[i + 1] if i + 1 < len(notes) else None
        legato = prev is not None and (n.onset - prev.offset) <= max_gap_s
        next_legato = nxt is not None and (nxt.onset - n.offset) <= max_gap_s
        p["legato"] = legato
        if legato:
            tr = estimate_transition(mc, track.times, prev, n)
            if tr:
                p.update({f"transition_{k}": v for k, v in tr.items()})
                # 遷移が終わってから安定区間を始める（短い音で滑りが大半を占めるときの誤りを防ぐ）
                k_end = int((tr["end_sec"] - n.onset) / hop) + 2
                if k_end > a0 and k_end < L - 2:
                    a0 = min(k_end, max(L * 2 // 3, a0))
                    a1 = max(L - int(0.06 / hop), a0 + 2)
                    stable = dev[a0:a1] if a1 > a0 else dev[a0:]
                    if len(stable):
                        into = float(np.median(stable))
                        p["intonation_cents"] = into
        else:
            i0c = int(np.searchsorted(track.times, n.onset))
            p["attack_cents"], p["attack_settle_ms"] = estimate_attack(dev - into, hop, conf=track.confidence[i0c:i0c + L])

        # 信頼度: 音符全体と発音直後（アタックの推定が当てになるか）
        i0 = int(np.searchsorted(track.times, n.onset))
        i1 = max(int(np.searchsorted(track.times, n.offset)), i0 + 1)
        conf = track.confidence[i0:i1]
        p["confidence"] = float(np.mean(conf)) if len(conf) else 0.0
        k40 = max(int(0.04 / hop), 1)
        p["attack_confidence"] = float(np.mean(conf[:k40])) if len(conf) else 0.0

        vib_src, vib_off = (stable, a0) if len(stable) * hop >= 0.3 else (dev[a0:], a0)
        vib = estimate_vibrato(vib_src, hop)
        if vib:
            p["vibrato"] = True
            p["vibrato_rate_hz"] = vib["rate_hz"]
            p["vibrato_depth_cents"] = vib["depth_cents"]
            p["vibrato_onset_ms"] = vib["onset_ms"] + vib_off * hop * 1000.0
            p["vibrato_ramp_ms"] = vib["ramp_ms"]
            # 中心のずれ: ビブラート前の中央値と、ビブラート中の中央値の差（depth 比）。
            # ビブラート前の区間が取れるなら、イントネーションはそこで測り直す
            k_on = int(vib["onset_ms"] / 1000.0 / hop)
            if k_on >= int(0.06 / hop):
                pre = float(np.median(vib_src[:k_on]))
                dur_med = float(np.median(vib_src[k_on:]))
                p["vibrato_center_offset"] = float(np.clip((dur_med - pre) / max(vib["depth_cents"], 1e-6), -1, 1))
                into = pre
                p["intonation_cents"] = into
                p["intonation_source"] = "pre_vibrato"
            else:
                # ビブラート開始前の区間が取れない: 中央値はビブラートの中心ずれを含む
                p["intonation_source"] = "stable_with_vibrato"
        else:
            p["vibrato"] = False
        # ビブラートの振幅が小さいフレームだけの中央値: 検出しきい値未満のビブラートでも中心ずれを含まない。
        # 基準ピッチ推定に使う
        env = vibrato_envelope(vib_src, hop)
        quiet = vib_src[env < 6.0] if len(env) == len(vib_src) else vib_src
        if len(quiet) >= int(0.04 / hop):
            p["intonation_novib_cents"] = float(np.median(quiet))
            p["novib_frames"] = int(len(quiet))

        lp = _moving_average(stable, max(int(0.4 / hop), 1))
        p["drift_cents"] = float(np.std(lp - into)) if len(lp) > 2 else 0.0
        hp = stable - _moving_average(stable, max(int(0.03 / hop), 1))
        p["jitter_cents"] = float(np.std(hp))
        if not next_legato:
            tail = dev[-max(min(int(0.04 / hop), L), 1):]
            p["release_cents"] = float(np.mean(tail)) - into

        # --- ダイナミクス（RMS 包絡） ---
        if track.rms is not None and len(track.rms):
            i0 = int(np.searchsorted(track.times, n.onset))
            i1 = max(int(np.searchsorted(track.times, n.offset)), i0 + 2)
            env = track.rms[i0:i1]
            peak = float(env.max()) if len(env) else 0.0
            if peak > 0 and len(env) >= 4:
                rel = env / peak
                # アタック: ピーク（の 90%）に達するまでの時間と、開始レベル
                k90 = int(np.argmax(rel >= 0.9))
                p["dyn_attack_ms"] = float(k90 * hop * 1000.0)
                p["dyn_attack_from"] = float(np.clip(rel[0] / max(rel[min(k90, len(rel) - 1)], 1e-6), 0.0, 1.0))
                # サステインの傾き（1 秒あたりの比率）: 安定区間の線形回帰
                s0 = min(max(k90, a0), len(rel) - 2)
                s1 = max(len(rel) - int(0.06 / hop), s0 + 2) if not next_legato else len(rel)
                seg = rel[s0:s1]
                if len(seg) >= 4:
                    tt = np.arange(len(seg)) * hop
                    slope, icpt = np.polyfit(tt, seg, 1)
                    p["dyn_sustain_slope"] = float(slope / max(icpt, 1e-6))
                if not next_legato and len(rel) - s1 >= 2:
                    p["dyn_release_to"] = float(np.clip(rel[-1] / max(rel[s1 - 1], 1e-6), 0.0, 1.0))
        n.params = {k: (bool(v) if isinstance(v, (bool, np.bool_)) else float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in p.items()}


# ----------------------------------------------------------------------------
# プロファイル構築
# ----------------------------------------------------------------------------

def _dist(values, default: Dist, lo=None, hi=None) -> Dist:
    v = np.asarray([x for x in values if x is not None and np.isfinite(x)], dtype=float)
    if len(v) == 0:
        return default
    d = Dist(mean=float(v.mean()), std=float(v.std()) if len(v) > 1 else default.std,
             min=float(v.min()) if lo is None else lo, max=float(v.max()) if hi is None else hi)
    return d


def build_profile(notes: list[AnalyzedNote], base: Profile | None = None, name: str = "analyzed", instrument: str = "unknown", style: str = "unknown", hop_s: float = 0.005, tuning_hz: float | None = None) -> Profile:
    """解析済み音符列から Profile を作る。推定できない項目は base（または既定値）を使う。"""
    P = Profile.from_dict(base.to_dict()) if base else Profile()
    P.name, P.instrument, P.style = name, instrument, style
    P.version = (base.version + 1) if base else 1
    P.source = f"analyze: {len(notes)} notes"
    P.hop_ms = hop_s * 1000.0
    ps = [n.params for n in notes]

    # 調を判定し、度数ごとの中央値をバイアス表に、残りをランダム成分の分布にする
    key = detect_key([Note(n.pitch, n.onset, n.duration) for n in notes]) if notes else (0, "major", 0.0)
    tonic, mode = key[0], key[1]
    intos = np.array([p.get("intonation_cents", 0.0) for p in ps], dtype=float)
    degs = np.array([(n.pitch - tonic) % 12 for n in notes])
    table = list(P.intonation.major_bias_cents if mode == "major" else P.intonation.minor_bias_cents)
    if len(table) != 12:
        table = [0.0] * 12
    global_med = float(np.median(intos)) if len(intos) else 0.0
    filled = 0
    for d in range(12):
        sel = intos[degs == d]
        if len(sel) >= 3:
            table[d] = float(np.median(sel) - global_med)
            filled += 1
    if mode == "major":
        P.intonation.major_bias_cents = table
    else:
        P.intonation.minor_bias_cents = table
    resid = intos - np.array([table[d] for d in degs]) if len(intos) else intos
    P.intonation.cents = _dist(resid, P.intonation.cents)
    if len(ps) > 2:
        ints = np.array([p.get("intonation_cents", 0.0) for p in ps])
        # どちらかの側が定数だと相関が NaN になる（生成側に NaN が伝播する）ので両側を確認する
        if ints[:-1].std() > 1e-6 and ints[1:].std() > 1e-6:
            r = float(np.corrcoef(ints[:-1], ints[1:])[0, 1])
            if np.isfinite(r):
                P.intonation.continuity = float(np.clip(r, 0, 1))

    leg = [p for p in ps if p.get("legato")]
    port = [p for p in leg if p.get("transition_portamento")]
    if leg:
        P.transition.prob = len(port) / len(leg)
    if len(port) >= 2:
        d = np.array([p["transition_duration_ms"] for p in port])
        iv = np.array([abs(p["transition_interval"]) for p in port])
        if iv.std() > 1e-6:
            slope, intercept = np.polyfit(iv, d, 1)
            P.transition.duration_per_semitone_ms = float(np.clip(slope, 0, 30))
            resid = d - slope * iv
            P.transition.duration_ms = Dist(float(max(intercept, 10.0)), float(resid.std()), 10.0, float(max(d.max(), 20.0)))
        else:
            P.transition.duration_ms = _dist(d, P.transition.duration_ms, 10.0, None)
        P.transition.overshoot_cents = _dist([p["transition_overshoot_cents"] for p in port], P.transition.overshoot_cents, 0.0, None)

    det = [p for p in ps if not p.get("legato") and "attack_cents" in p]
    att = [p for p in det if abs(p["attack_cents"]) > 8.0]
    if det:
        P.attack.prob = len(att) / len(det)
    if att:
        P.attack.offset_cents = _dist([p["attack_cents"] for p in att], P.attack.offset_cents)
        P.attack.settle_ms = _dist([p["attack_settle_ms"] for p in att], P.attack.settle_ms, 5.0, None)

    long_notes = [(n, n.params) for n in notes if n.duration * 1000 >= P.vibrato.min_note_ms]
    vib = [p for _, p in long_notes if p.get("vibrato")]
    if long_notes:
        P.vibrato.prob = len(vib) / len(long_notes)
    if vib:
        P.vibrato.rate_hz = _dist([p["vibrato_rate_hz"] for p in vib], P.vibrato.rate_hz)
        # 生成側は音長に応じて深さを 0.5〜1.0 倍にするので、測った深さを同じ係数で割り戻す
        full = max(P.vibrato.full_depth_at_ms, 1.0)
        depths = [p["vibrato_depth_cents"] / min(1.0, 0.5 + 0.5 * n.duration * 1000.0 / full)
                  for n, p in long_notes if p.get("vibrato")]
        P.vibrato.depth_cents = _dist(depths, P.vibrato.depth_cents)
        P.vibrato.onset_ms = _dist([p["vibrato_onset_ms"] for p in vib], P.vibrato.onset_ms, 0.0, None)
        P.vibrato.ramp_ms = _dist([p["vibrato_ramp_ms"] for p in vib if "vibrato_ramp_ms" in p], P.vibrato.ramp_ms, 20.0, None)
        co = [p["vibrato_center_offset"] for p in vib if "vibrato_center_offset" in p]
        if co:
            P.vibrato.center_offset = float(np.median(co))

    P.drift.cents = _dist([p.get("drift_cents") for p in ps], P.drift.cents, 0.0, None)
    P.jitter.cents = float(np.median([p["jitter_cents"] for p in ps])) if ps else P.jitter.cents
    rel_all = [p["release_cents"] for p in ps if "release_cents" in p]
    rel = [r for r in rel_all if abs(r) > 8.0]
    if rel_all:
        P.release.prob = len(rel) / len(rel_all)
    if rel:
        P.release.cents = _dist(rel, P.release.cents)

    dyn_att = [p["dyn_attack_ms"] for p in ps if "dyn_attack_ms" in p]
    if dyn_att:
        P.dynamics.attack_ms = _dist(dyn_att, P.dynamics.attack_ms, 5.0, None)
        P.dynamics.attack_from = _dist([p["dyn_attack_from"] for p in ps if "dyn_attack_from" in p], P.dynamics.attack_from, 0.05, 1.0)
        P.dynamics.sustain_slope = _dist([p["dyn_sustain_slope"] for p in ps if "dyn_sustain_slope" in p], P.dynamics.sustain_slope, -0.6, 0.6)
        rel_to = [p["dyn_release_to"] for p in ps if "dyn_release_to" in p]
        if rel_to:
            P.dynamics.release_to = _dist(rel_to, P.dynamics.release_to, 0.02, 1.0)

    P.stats = {
        "reference_tuning_hz": round(float(tuning_hz), 2) if tuning_hz else None,
        "key": f"{tonic}:{mode}",
        "key_degrees_filled": filled,
        "n_notes": len(notes),
        "n_legato": len(leg),
        "n_portamento": len(port),
        "n_detached": len(det),
        "n_long_notes": len(long_notes),
        "n_vibrato": len(vib),
        "total_seconds": round(float(sum(n.duration for n in notes)), 2),
    }
    return P


def analyze_audio(x: np.ndarray, sr: int, hop_s: float = 0.005, fmin: float = 55.0, fmax: float = 1500.0,
                  detector: str = "yin", tuning: float | None = None, octave_fix: bool = True, **detector_kw) -> tuple[list[AnalyzedNote], F0Track]:
    """音声 → 音符列（params 付き）と F0 軌跡。

    detector: 'yin'（内蔵）または 'pyin'（librosa）
    tuning: 基準ピッチ A4（Hz）。None なら録音から推定し、その分を偏差から差し引く
    octave_fix: 時間的連続性によるオクターブ誤検出の補正
    """
    track = detect_f0(x, sr, detector=detector, hop_s=hop_s, fmin=fmin, fmax=fmax, **detector_kw)
    if octave_fix:
        fix_octave_errors(track)
    notes = segment_notes(track)
    if tuning:
        tuning_hz = float(tuning)
    else:
        estimate_note_params(notes, track)   # 1 回目: 基準ピッチ推定のためのイントネーション
        tuning_hz = estimate_tuning(notes, track)
    offset = 1200.0 * np.log2(tuning_hz / 440.0)
    track.tuning_hz = tuning_hz
    if abs(offset) > 1e-9:
        for n in notes:
            n.dev = n.dev - offset
    estimate_note_params(notes, track)       # 基準ピッチを差し引いた偏差で確定
    return notes, track
