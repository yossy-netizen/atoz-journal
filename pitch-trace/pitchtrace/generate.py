"""音符列 + プロファイル → セント偏差カーブ c(t) の生成（L0: ルール + 統計）。

各音符について、目標音からの偏差（セント）を hop_ms 刻みでサンプルする。
成分は CONCEPT.md §2 の分解に対応:

    c(t) = intonation + transition(t) + attack(t) + vibrato(t) + drift(t) + release(t) + jitter(t)

``Contour`` は音符ごとの偏差配列に加えて、成分ごとの内訳（デバッグ・可視化用）と
ビブラート深さの包絡（CC レーン出力用）を持つ。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .notes import Note, split_phrases
from .profile import Profile


@dataclass
class NoteContour:
    note: Note
    t: np.ndarray                 # 音符開始からの秒
    cents: np.ndarray             # 合計偏差（セント）
    parts: dict[str, np.ndarray]  # 成分ごとの内訳
    vib_env: np.ndarray           # ビブラート深さの包絡（セント）
    params: dict                  # サンプリングされたパラメータ（解析との突き合わせ用）


@dataclass
class Contour:
    notes: list[NoteContour]
    hop_s: float

    def to_rows(self):
        """(絶対秒, ノート番号, セント) の列を返す。CSV 出力用。"""
        for nc in self.notes:
            for ti, c in zip(nc.t, nc.cents):
                yield (nc.note.onset + ti, nc.note.pitch, float(c))


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _sigmoid_2080_fraction(k: float) -> float:
    """正規化シグモイド（鋭さ k）で進行率 20%→80% にかかる時間の、全体に対する割合。"""
    s0, s1 = _sigmoid(-0.5 * k), _sigmoid(0.5 * k)

    def u(p):
        q = s0 + p * (s1 - s0)
        return 0.5 + np.log(q / (1 - q)) / k

    return float(max(u(0.8) - u(0.2), 1e-3))


def _lowpass_noise(rng: np.random.Generator, n: int, hop_s: float, cutoff_hz: float) -> np.ndarray:
    """1 次 IIR で低域通過した白色雑音（分散 1 に正規化）。"""
    if n == 0:
        return np.zeros(0)
    white = rng.normal(size=n)
    if cutoff_hz <= 0:
        return np.zeros(n)
    a = np.exp(-2.0 * np.pi * cutoff_hz * hop_s)
    out = np.empty(n)
    acc = 0.0
    for i in range(n):
        acc = a * acc + (1.0 - a) * white[i]
        out[i] = acc
    std = out.std()
    return out / std if std > 1e-9 else out


def _moving_average(x: np.ndarray, win: int) -> np.ndarray:
    if win <= 1 or len(x) == 0:
        return x
    k = np.ones(win) / win
    pad = win // 2
    xp = np.pad(x, (pad, win - 1 - pad), mode="edge")
    return np.convolve(xp, k, mode="valid")


def generate_contour(
    notes: list[Note],
    profile: Profile,
    seed: int | None = 0,
    amount: float = 1.0,
    phrase_gap_s: float = 0.3,
    lookahead: bool = True,
) -> Contour:
    """音符列からセント偏差カーブを生成する。

    amount: 全成分の量（0 = 静止ピッチ、1 = プロファイル通り）
    lookahead: False にすると「次の音」を使う判断（フレーズ末のリリース、クライマックス）を
               行わない。リアルタイム動作の挙動を模擬する。
    """
    rng = np.random.default_rng(seed)
    hop_s = profile.hop_ms / 1000.0
    split_phrases(notes, gap_s=phrase_gap_s)

    out: list[NoteContour] = []
    prev: Note | None = None
    prev_end_cents = 0.0   # 前の音の終端での偏差（前の音の目標音基準）
    prev_intonation = 0.0

    for idx, n in enumerate(notes):
        n_samples = max(int(round(n.duration / hop_s)), 2)
        t = np.arange(n_samples) * hop_s
        parts: dict[str, np.ndarray] = {}
        params: dict = {}
        P = profile

        # --- イントネーション ------------------------------------------------
        into = P.intonation.cents.sample(rng)
        if prev is not None:
            into = P.intonation.continuity * prev_intonation + (1 - P.intonation.continuity) * into
        parts["intonation"] = np.full(n_samples, into)
        params["intonation_cents"] = into

        # --- 遷移（ポルタメント） / アタック ----------------------------------
        trans = np.zeros(n_samples)
        attack = np.zeros(n_samples)
        legato = prev is not None and (n.onset - prev.offset) <= P.transition.max_gap_ms / 1000.0
        did_port = False
        if legato and rng.random() < P.transition.prob:
            interval = prev.pitch - n.pitch  # 前の音の位置（この音の基準でのセント / 100）
            start = interval * 100.0 + prev_end_cents
            dur2080 = (P.transition.duration_ms.sample(rng) + P.transition.duration_per_semitone_ms * abs(interval)) / 1000.0
            k = P.transition.sharpness.sample(rng)
            dur = max(dur2080 / _sigmoid_2080_fraction(k), 2 * hop_s)  # 20→80% 時間 → 全体の長さ
            s = _sigmoid((t / dur - 0.5) * k)
            s0, s1 = _sigmoid(-0.5 * k), _sigmoid(0.5 * k)
            s = np.clip((s - s0) / max(s1 - s0, 1e-9), 0, 1)
            trans = start * (1.0 - s)
            over = P.transition.overshoot_cents.sample(rng) * (-1.0 if interval > 0 else 1.0 if interval < 0 else 0.0)
            if over != 0.0:
                settle = P.transition.overshoot_settle_ms / 1000.0
                tt = np.clip(t - dur, 0, None)
                trans += over * s * np.exp(-tt / settle)
            did_port = True
            params.update(portamento_ms=dur2080 * 1000, portamento_full_ms=dur * 1000, portamento_from_cents=start, overshoot_cents=float(over))
        elif rng.random() < P.attack.prob:
            off = P.attack.offset_cents.sample(rng)
            settle = P.attack.settle_ms.sample(rng) / 1000.0
            attack = off * np.exp(-t / max(settle, hop_s))
            params.update(attack_cents=off, attack_settle_ms=settle * 1000)
        parts["transition"] = trans
        parts["attack"] = attack
        params["legato"] = legato
        params["portamento"] = did_port

        # --- ビブラート -----------------------------------------------------
        vib = np.zeros(n_samples)
        vib_env = np.zeros(n_samples)
        V = P.vibrato
        if n.duration * 1000 >= V.min_note_ms and rng.random() < V.prob:
            rate = V.rate_hz.sample(rng)
            depth = V.depth_cents.sample(rng)
            depth *= min(1.0, 0.5 + 0.5 * (n.duration * 1000 / max(V.full_depth_at_ms, 1)))
            if lookahead and n.is_climax:
                depth *= V.climax_gain
            onset = V.onset_ms.sample(rng) / 1000.0
            ramp = max(V.ramp_ms.sample(rng) / 1000.0, hop_s)
            env = np.clip((t - onset) / ramp, 0, 1)
            env = env * env * (3 - 2 * env)  # smoothstep
            env *= depth * (1.0 + V.depth_wobble * _lowpass_noise(rng, n_samples, hop_s, 0.7))
            env = np.clip(env, 0, None)
            inst_rate = rate * (1.0 + V.rate_wobble * _lowpass_noise(rng, n_samples, hop_s, 0.5))
            phase = 2 * np.pi * np.cumsum(inst_rate) * hop_s + rng.uniform(0, 2 * np.pi)
            wave = np.sin(phase)
            if V.asymmetry != 0.0:
                wave = np.sin(phase + V.asymmetry * np.sin(phase))
            vib = env * (wave + V.center_offset)
            vib_env = env
            params.update(vibrato_rate_hz=rate, vibrato_depth_cents=depth, vibrato_onset_ms=onset * 1000, vibrato_ramp_ms=ramp * 1000)
        parts["vibrato"] = vib

        # --- ドリフト ---------------------------------------------------------
        d_std = P.drift.cents.sample(rng)
        drift = d_std * _lowpass_noise(rng, n_samples, hop_s, P.drift.cutoff_hz)
        drift -= drift[0]  # 発音時点では 0 から始める
        parts["drift"] = drift
        params["drift_cents"] = d_std

        # --- リリース ---------------------------------------------------------
        rel = np.zeros(n_samples)
        R = P.release
        phrase_end = n.phrase_pos in ("last", "single")
        rel_prob = min(1.0, R.prob * (R.phrase_end_gain if (lookahead and phrase_end) else 1.0))
        next_legato = idx + 1 < len(notes) and (notes[idx + 1].onset - n.offset) <= P.transition.max_gap_ms / 1000.0
        if not (lookahead and next_legato) and rng.random() < rel_prob:
            amt = R.cents.sample(rng) * (R.phrase_end_gain if (lookahead and phrase_end) else 1.0)
            dur = min(R.duration_ms.sample(rng) / 1000.0, n.duration * 0.6)
            tt = np.clip((t - (n.duration - dur)) / max(dur, hop_s), 0, 1)
            rel = amt * tt * tt
            params.update(release_cents=amt, release_ms=dur * 1000)
        parts["release"] = rel

        # --- ジッタ -----------------------------------------------------------
        J = P.jitter
        jit = rng.normal(size=n_samples) * J.cents
        jit = _moving_average(jit, max(int(J.smooth_ms / 1000.0 / hop_s), 1))
        parts["jitter"] = jit

        cents = sum(parts.values()) * amount
        vib_env = vib_env * amount
        out.append(NoteContour(note=n, t=t, cents=cents, parts={k: v * amount for k, v in parts.items()}, vib_env=vib_env, params=params))

        prev = n
        prev_intonation = into
        # 次の音のポルタメント開始点: この音の終端偏差（ビブラートは中心のみ引き継ぐ）
        prev_end_cents = float((parts["intonation"][-1] + parts["drift"][-1] + parts["release"][-1]) * amount)

    return Contour(notes=out, hop_s=hop_s)
