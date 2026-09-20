"""音符列 + プロファイル → セント偏差カーブ c(t) の生成（L0: ルール + 統計）。

各音符について、目標音からの偏差（セント）を hop_ms 刻みでサンプルする。
成分は CONCEPT.md §2 の分解に対応:

    c(t) = intonation + transition(t) + attack(t) + vibrato(t) + drift(t) + release(t) + jitter(t)

``generate_note`` が 1 音符分を生成する中核で、オフライン（``generate_contour``）と
リアルタイム（``realtime.py``）の両方がこれを使う。前の音との関係は ``NoteContext`` で渡す。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .key import degree_bias, detect_key
from .notes import Note, split_phrases
from .profile import Profile


@dataclass
class NoteContext:
    """1 音符を生成するときに必要な前後関係。"""

    prev_pitch: int | None = None       # 前の音（なければ None）
    gap_s: float = 1e9                  # 前の音の終わりからこの音までの隙間（重なりは負）
    prev_end_cents: float = 0.0         # 前の音の終端偏差（前の音の目標音基準）
    prev_intonation: float = 0.0
    next_legato: bool | None = None     # 次の音がレガートで続くか。None = 不明（リアルタイム）
    phrase_end: bool | None = None      # フレーズ末か。None = 不明
    phrase_first: bool = False
    is_climax: bool = False
    arc_pos: float | None = None        # フレーズ内の位置: 0 = 始まり/終わり, 1 = 山（クライマックス）。None = 不明
    key: tuple[int, str] | None = None  # (tonic_pc, 'major'|'minor')。None = 調不明（度数バイアスなし）


@dataclass
class NoteContour:
    note: Note
    t: np.ndarray                 # 音符開始からの秒
    cents: np.ndarray             # 合計偏差（セント）
    parts: dict[str, np.ndarray]  # 成分ごとの内訳
    vib_env: np.ndarray           # ビブラート深さの包絡（セント）
    params: dict                  # サンプリングされたパラメータ（解析との突き合わせ用）
    dyn: np.ndarray = None        # 音量レベル（0..1）。type: ignore[assignment]
    # 次の音のポルタメント開始点に使う終端偏差（intonation + drift + release。ビブラートは中心のみ）。
    # amount を掛ける前の値。次の音の生成時に他の成分と一緒に amount が掛かる
    end_track: np.ndarray = None  # type: ignore[assignment]

    @property
    def end_cents(self) -> float:
        """次の音のポルタメント開始点に使う終端偏差（amount 適用前）。"""
        return float(self.end_track[-1])

    def end_cents_at(self, k: int) -> float:
        k = int(np.clip(k, 0, len(self.t) - 1))
        return float(self.end_track[k])


@dataclass
class Contour:
    notes: list[NoteContour]
    hop_s: float
    key: tuple[int, str] | None = None

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
    """1 次 IIR で低域通過した白色雑音（分散 1 に正規化）。畳み込みでベクトル化。"""
    if n == 0:
        return np.zeros(0)
    if cutoff_hz <= 0:
        return np.zeros(n)
    white = rng.normal(size=n)
    a = np.exp(-2.0 * np.pi * cutoff_hz * hop_s)
    klen = min(int(np.ceil(np.log(1e-4) / np.log(a))) + 1, n) if a < 1 else n
    kernel = (1.0 - a) * a ** np.arange(klen)
    out = np.convolve(white, kernel)[:n]
    std = out.std()
    return out / std if std > 1e-9 else out


def _moving_average(x: np.ndarray, win: int) -> np.ndarray:
    if win <= 1 or len(x) == 0:
        return x
    k = np.ones(win) / win
    pad = win // 2
    xp = np.pad(x, (pad, win - 1 - pad), mode="edge")
    return np.convolve(xp, k, mode="valid")


def generate_note(
    n: Note,
    ctx: NoteContext,
    profile: Profile,
    rng: np.random.Generator,
    amount: float = 1.0,
    duration_s: float | None = None,
) -> NoteContour:
    """1 音符分のセント偏差カーブを生成する。

    duration_s: 生成する長さ（既定は n.duration）。リアルタイムでは音長が未知なので、
                長めに生成してノートオフで打ち切る。
    """
    P = profile
    hop_s = P.hop_ms / 1000.0
    dur = n.duration if duration_s is None else duration_s
    n_samples = max(int(round(dur / hop_s)), 2)
    t = np.arange(n_samples) * hop_s
    parts: dict[str, np.ndarray] = {}
    params: dict = {}

    # --- イントネーション ------------------------------------------------
    # ランダム成分（前の音との連続性あり）+ 調に対する度数バイアス（決定的）
    rand = P.intonation.cents.sample(rng)
    if ctx.prev_pitch is not None:
        rand = P.intonation.continuity * ctx.prev_intonation + (1 - P.intonation.continuity) * rand
    bias = 0.0
    if ctx.key is not None and P.intonation.key_bias_amount != 0.0:
        bias = P.intonation.key_bias_amount * degree_bias(n.pitch, ctx.key[0], ctx.key[1],
                                                          P.intonation.major_bias_cents, P.intonation.minor_bias_cents)
    into = rand + bias
    parts["intonation"] = np.full(n_samples, into)
    params["intonation_cents"] = into
    params["intonation_random"] = rand
    params["intonation_key_bias"] = bias

    # --- 遷移（ポルタメント） / アタック ----------------------------------
    trans = np.zeros(n_samples)
    attack = np.zeros(n_samples)
    legato = ctx.prev_pitch is not None and ctx.gap_s <= P.transition.max_gap_ms / 1000.0
    did_port = False
    if legato and rng.random() < P.transition.prob:
        interval = ctx.prev_pitch - n.pitch  # 前の音の位置（この音の基準でのセント / 100）
        start = interval * 100.0 + ctx.prev_end_cents
        dur2080 = (P.transition.duration_ms.sample(rng) + P.transition.duration_per_semitone_ms * abs(interval)) / 1000.0
        k = max(P.transition.sharpness.sample(rng), 0.5)  # 0 以下だとシグモイドが定義できない
        full = max(dur2080 / _sigmoid_2080_fraction(k), 2 * hop_s)  # 20→80% 時間 → 全体の長さ
        s = _sigmoid((t / full - 0.5) * k)
        s0, s1 = _sigmoid(-0.5 * k), _sigmoid(0.5 * k)
        s = np.clip((s - s0) / max(s1 - s0, 1e-9), 0, 1)
        # 合計は intonation + trans なので、開始点が前の音の終端（start）に一致するよう into を差し引く
        trans = (start - into) * (1.0 - s)
        over = P.transition.overshoot_cents.sample(rng) * (-1.0 if interval > 0 else 1.0 if interval < 0 else 0.0)
        if over != 0.0:
            settle = P.transition.overshoot_settle_ms / 1000.0
            tt = np.clip(t - full, 0, None)
            trans += over * s * np.exp(-tt / settle)
        did_port = True
        params.update(portamento_ms=dur2080 * 1000, portamento_full_ms=full * 1000, portamento_from_cents=start, overshoot_cents=float(over))
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
    if dur * 1000 >= V.min_note_ms and rng.random() < V.prob:
        rate = V.rate_hz.sample(rng)
        depth = V.depth_cents.sample(rng)
        depth *= min(1.0, 0.5 + 0.5 * (dur * 1000 / max(V.full_depth_at_ms, 1)))
        if ctx.is_climax:
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

    # --- リリース（音長と次の音が分かっているときだけ） -----------------------
    rel = np.zeros(n_samples)
    R = P.release
    if ctx.next_legato is not None and duration_s is None:
        phrase_end = bool(ctx.phrase_end)
        gain = R.phrase_end_gain if phrase_end else 1.0
        if not ctx.next_legato and rng.random() < min(1.0, R.prob * gain):
            amt = R.cents.sample(rng) * gain
            rdur = min(R.duration_ms.sample(rng) / 1000.0, dur * 0.6)
            tt = np.clip((t - (dur - rdur)) / max(rdur, hop_s), 0, 1)
            rel = amt * tt * tt
            params.update(release_cents=amt, release_ms=rdur * 1000)
    parts["release"] = rel

    # --- ジッタ -----------------------------------------------------------
    J = P.jitter
    jit = rng.normal(size=n_samples) * J.cents
    jit = _moving_average(jit, max(int(J.smooth_ms / 1000.0 / hop_s), 1))
    parts["jitter"] = jit

    # --- ダイナミクス（0..1） ------------------------------------------------
    D = P.dynamics
    vel_f = (n.velocity / 100.0) ** D.velocity_weight if D.velocity_weight > 0 else 1.0
    level = D.base * vel_f
    if ctx.arc_pos is not None:
        level *= 1.0 + D.phrase_arc * (ctx.arc_pos - 0.5)
    dyn = np.full(n_samples, level)
    if D.enabled:
        a_ms = D.attack_ms.sample(rng)
        a_from = D.attack_from.sample(rng)
        ta = np.clip(t / max(a_ms / 1000.0, hop_s), 0, 1)
        ta = ta * ta * (3 - 2 * ta)
        shape = a_from + (1.0 - a_from) * ta
        slope = D.sustain_slope.sample(rng)
        shape *= np.clip(1.0 + slope * t, 0.2, 2.0)
        if ctx.next_legato is not None and duration_s is None and not ctx.next_legato:
            r_ms = D.release_ms.sample(rng)
            r_to = D.release_to.sample(rng)
            rdur = min(r_ms / 1000.0, dur * 0.5)
            tr = np.clip((t - (dur - rdur)) / max(rdur, hop_s), 0, 1)
            shape *= 1.0 - (1.0 - r_to) * tr * tr
            params.update(dyn_release_ms=r_ms, dyn_release_to=r_to)
        if D.wobble > 0:
            shape *= 1.0 + D.wobble * _lowpass_noise(rng, n_samples, hop_s, 0.5)
        dyn = level * shape
        params.update(dyn_level=level, dyn_attack_ms=a_ms, dyn_attack_from=a_from, dyn_sustain_slope=slope)
    dyn = np.clip(dyn, D.min, D.max)
    # amount で「平坦（一定レベル）」との間を補間する
    dyn = level * (1.0 - amount) + dyn * amount

    # --- タイミング（オフライン専用。リアルタイムでは duration_s が渡るので付けない） ----
    T = P.timing
    shift_ms = 0.0
    dur_delta_ms = 0.0
    if T.enabled and duration_s is None:
        shift_ms = T.onset_ms.sample(rng)
        if legato:
            shift_ms -= T.legato_lead_ms.sample(rng)
        if ctx.phrase_first:
            shift_ms += T.phrase_first_delay_ms.sample(rng)
        if ctx.next_legato is False:
            dur_delta_ms = -min(T.detach_gap_ms.sample(rng), dur * 1000 * 0.3)
    params["timing_shift_ms"] = shift_ms * amount
    params["timing_duration_delta_ms"] = dur_delta_ms * amount

    end_track = parts["intonation"] + parts["drift"] + parts["release"]
    parts = {k: v * amount for k, v in parts.items()}
    cents = sum(parts.values())
    return NoteContour(note=n, t=t, cents=cents, parts=parts, vib_env=vib_env * amount, params=params, end_track=end_track, dyn=dyn)


def generate_contour(
    notes: list[Note],
    profile: Profile,
    seed: int | None = 0,
    amount: float = 1.0,
    phrase_gap_s: float = 0.3,
    lookahead: bool = True,
    key: tuple[int, str] | None | str = "auto",
) -> Contour:
    """音符列からセント偏差カーブを生成する。

    amount: 全成分の量（0 = 静止ピッチ、1 = プロファイル通り）
    lookahead: False にすると「次の音」を使う判断（フレーズ末のリリース、クライマックス）を
               行わない。リアルタイム動作の挙動を模擬する。
    key: "auto" で音符列から調を判定、(tonic_pc, mode) で指定、None で度数バイアスなし
    """
    rng = np.random.default_rng(seed)
    hop_s = profile.hop_ms / 1000.0
    split_phrases(notes, gap_s=phrase_gap_s)
    max_gap = profile.transition.max_gap_ms / 1000.0
    if key == "auto":
        key = detect_key(notes)[:2] if notes else None

    # フレーズ内の位置（山までの進み具合）
    arc: dict[int, float] = {}
    if lookahead:
        by_phrase: dict[int, list[int]] = {}
        for i, n in enumerate(notes):
            by_phrase.setdefault(n.phrase, []).append(i)
        for idxs in by_phrase.values():
            cl = next((j for j, i in enumerate(idxs) if notes[i].is_climax), None)
            L = len(idxs)
            for j, i in enumerate(idxs):
                if L <= 2 or cl is None:
                    arc[i] = 0.5
                elif j <= cl:
                    arc[i] = j / max(cl, 1)
                else:
                    arc[i] = 1.0 - (j - cl) / max(L - 1 - cl, 1)

    out: list[NoteContour] = []
    ctx = NoteContext()
    for idx, n in enumerate(notes):
        nxt = notes[idx + 1] if idx + 1 < len(notes) else None
        if lookahead:
            ctx.next_legato = nxt is not None and (nxt.onset - n.offset) <= max_gap
            ctx.phrase_end = n.phrase_pos in ("last", "single")
            ctx.phrase_first = n.phrase_pos in ("first", "single")
            ctx.is_climax = n.is_climax
            ctx.arc_pos = arc.get(idx)
            ctx.key = key
        else:
            ctx.next_legato = False  # 次の音は不明: リリースは「単独音」扱いで付ける
            ctx.phrase_end = False
            ctx.phrase_first = False
            ctx.is_climax = False
            ctx.arc_pos = None
            ctx.key = key
        nc = generate_note(n, ctx, profile, rng, amount=amount)
        out.append(nc)
        ctx = NoteContext(prev_pitch=n.pitch, gap_s=(nxt.onset - n.offset) if nxt else 1e9,
                          prev_end_cents=nc.end_cents, prev_intonation=nc.params["intonation_random"])
    c = Contour(notes=out, hop_s=hop_s)
    c.key = key
    return c
