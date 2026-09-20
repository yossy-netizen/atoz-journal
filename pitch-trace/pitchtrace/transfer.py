"""Reference Performance Transfer: 参照演奏（IGF）のジェスチャーを別の MIDI へ転写する。

Reference audio / IGF
    → 音符ごとのジェスチャー（意味パラメータ + 正規化カーブ）
    → Target MIDI の音符と対応付け（positional / context / 手動）
    → 時間・音程の適応（アタックと遷移は元の長さを保ち、サステインだけ伸縮）
    → Contour（render_midi / synth へ）

2 つの適応モード:
- param: 参照音符の意味パラメータ（ビブラートのレート・深さ・開始、アタック、ポルタメント、
         ドリフト、リリース）を固定値として生成器に渡し、ターゲットの音長で再生成する。
         ビブラートのレートは自然に保たれる。頑健で、音数や音長が大きく違っても破綻しにくい
- raw:   参照の生カーブをそのまま使う。アタック区間と遷移区間は元の時間を保ち、サステインは
         切り詰め／継ぎ足し（クロスフェード）で合わせる。ビブラートの形（非対称・揺らぎ）を
         そのまま持ち込めるが、参照の癖が強く出る
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .generate import Contour, NoteContext, NoteContour, generate_note
from .igf import igf_note_curve
from .key import detect_key
from .notes import Note, split_phrases
from .profile import Profile


# ----------------------------------------------------------------------------
# 対応付け
# ----------------------------------------------------------------------------

def _features(duration: float, prev_iv: float | None, next_iv: float | None, legato_in: bool, legato_out: bool, pitch: int) -> np.ndarray:
    return np.array([
        np.log(max(duration, 0.05)),
        0.0 if prev_iv is None else float(np.clip(prev_iv, -12, 12)) / 4.0,
        0.0 if next_iv is None else float(np.clip(next_iv, -12, 12)) / 4.0,
        1.0 if legato_in else 0.0,
        1.0 if legato_out else 0.0,
        pitch / 24.0,
    ])


_WEIGHTS = np.array([2.0, 1.0, 1.0, 1.5, 1.0, 0.5])


def map_notes(ref_notes: list[dict], target: list[Note], mode: str = "positional", top_k: int = 3,
              rng: np.random.Generator | None = None, max_gap_s: float = 0.04, manual: list[int | None] | None = None) -> list[int | None]:
    """ターゲット音符ごとに参照音符の index を返す。

    positional: i → i（参照が短ければ循環）
    context:    音長・前後の音程差・レガート・音域が近い参照音符の上位 top_k からランダムに選ぶ
    manual:     明示的な対応表（None の要素は通常生成）
    """
    if manual is not None:
        return [None if m is None else int(m) for m in manual] + [None] * max(len(target) - len(manual), 0)
    if not ref_notes:
        return [None] * len(target)
    if mode == "positional":
        return [i % len(ref_notes) for i in range(len(target))]
    if mode != "context":
        raise ValueError("mode は 'positional' / 'context'")
    rng = rng or np.random.default_rng(0)
    ref_feats = np.array([_features(r["duration_sec"], r["context"]["previous_interval"], r["context"]["next_interval"],
                                    r["context"]["legato_in"], r["context"]["legato_out"], r["midi_note"]) for r in ref_notes])
    out = []
    for i, n in enumerate(target):
        prev = target[i - 1] if i > 0 else None
        nxt = target[i + 1] if i + 1 < len(target) else None
        f = _features(n.duration, (n.pitch - prev.pitch) if prev else None, (nxt.pitch - n.pitch) if nxt else None,
                      prev is not None and n.onset - prev.offset <= max_gap_s,
                      nxt is not None and nxt.onset - n.offset <= max_gap_s, n.pitch)
        d = np.sqrt((((ref_feats - f) * _WEIGHTS) ** 2).sum(axis=1))
        cand = np.argsort(d)[: max(1, min(top_k, len(d)))]
        out.append(int(rng.choice(cand)))
    return out


# ----------------------------------------------------------------------------
# param モード: 意味パラメータ → 固定値
# ----------------------------------------------------------------------------

def igf_to_fixed(r: dict, target_legato_in: bool) -> dict:
    fx: dict = {}
    if r.get("pitch_center_cents") is not None:
        fx["intonation_cents"] = r["pitch_center_cents"]
        fx["intonation_random"] = r["pitch_center_cents"]
    tr = r.get("transition_in")
    if target_legato_in:
        if tr and tr.get("portamento"):
            fx["portamento"] = True
            fx["portamento_ms"] = max(float(tr.get("duration_ms") or 20.0), 5.0)
            fx["overshoot_abs_cents"] = float(tr.get("overshoot_cents") or 0.0)
        else:
            fx["portamento"] = False
    at = r.get("attack")
    if at is not None:
        fx["attack"] = abs(float(at.get("deviation_cents") or 0.0)) > 3.0
        fx["attack_cents"] = float(at.get("deviation_cents") or 0.0)
        fx["attack_settle_ms"] = max(float(at.get("settlement_ms") or 30.0), 5.0)
    vb = r.get("vibrato")
    if vb:
        fx["vibrato"] = True
        fx["vibrato_rate_hz"] = float(vb["mean_rate_hz"])
        fx["vibrato_depth_cents"] = float(vb["mean_depth_cents"])
        fx["vibrato_onset_ms"] = float(vb.get("onset_ms") or 0.0)
        if vb.get("ramp_ms"):
            fx["vibrato_ramp_ms"] = float(vb["ramp_ms"])
    else:
        fx["vibrato"] = False
    su = r.get("sustain") or {}
    if su.get("drift_cents") is not None:
        fx["drift_cents"] = float(su["drift_cents"])
    rl = r.get("release")
    if rl is not None:
        fx["release"] = abs(float(rl.get("cents") or 0.0)) > 3.0
        fx["release_cents"] = float(rl.get("cents") or 0.0)
    dy = r.get("dynamics")
    if dy:
        if dy.get("attack_ms") is not None:
            fx["dyn_attack_ms"] = max(float(dy["attack_ms"]), 5.0)
        if dy.get("attack_from") is not None:
            fx["dyn_attack_from"] = float(np.clip(dy["attack_from"], 0.05, 1.0))
        if dy.get("sustain_slope") is not None:
            fx["dyn_sustain_slope"] = float(np.clip(dy["sustain_slope"], -0.6, 0.6))
        if dy.get("release_to") is not None:
            fx["dyn_release_to"] = float(np.clip(dy["release_to"], 0.02, 1.0))
    return fx


# ----------------------------------------------------------------------------
# raw モード: 生カーブの時間適応
# ----------------------------------------------------------------------------

def _crossfade_tile(seg: np.ndarray, n_out: int, fade: int) -> np.ndarray:
    """seg を n_out 長になるまで継ぎ足す（継ぎ目はクロスフェード）。"""
    if n_out <= len(seg):
        return seg[:n_out].copy()
    if len(seg) < 2:
        return np.full(n_out, seg[0] if len(seg) else 0.0)
    fade = int(min(fade, len(seg) // 2))
    out = seg.copy()
    while len(out) < n_out:
        if fade > 0:
            w = np.linspace(0, 1, fade)
            joined = out[:-fade].tolist()
            joined += (out[-fade:] * (1 - w) + seg[:fade] * w).tolist()
            out = np.concatenate([np.array(joined), seg[fade:]])
        else:
            out = np.concatenate([out, seg])
    return out[:n_out]


def adapt_raw_curve(ref: dict, target_dur: float, hop_s: float, target_legato_in: bool, target_interval: float | None,
                    attack_s: float | None = None, tail_s: float = 0.06) -> np.ndarray:
    """参照音符の生カーブをターゲットの音長に合わせる。

    - 遷移区間（transition_in）: ターゲットもレガートなら残し、音程差の比で振幅をスケール。
      ターゲットがレガートでなければ切り落とす
    - アタック区間: 元の時間を保つ
    - サステイン: 切り詰め or クロスフェードで継ぎ足し（ビブラートのレートは変わらない）
    - 末尾 tail_s: 元の時間を保つ（リリース・次への移行）
    """
    t, c = igf_note_curve(ref, hop_s)
    n_out = max(int(round(target_dur / hop_s)), 2)
    if len(c) < 4:
        return np.zeros(n_out)
    center = float(ref.get("pitch_center_cents") or 0.0)
    # 遷移区間
    tr = ref.get("transition_in")
    k_tr = 0
    if tr and tr.get("end_sec") is not None and ref.get("start_sec") is not None:
        k_tr = int(np.clip((tr["end_sec"] - ref["start_sec"]) / hop_s, 0, len(c) // 2))
    if k_tr > 0:
        if target_legato_in and target_interval is not None and tr.get("interval"):
            scale = float(np.clip(target_interval / tr["interval"], -3.0, 3.0))
            c = c.copy()
            c[:k_tr] = center + (c[:k_tr] - center) * scale
        elif not target_legato_in:
            c = c[k_tr:]
            t = t[: len(c)]
    # アタック区間
    if attack_s is None:
        at = ref.get("attack") or {}
        vb = ref.get("vibrato") or {}
        attack_s = max(float(at.get("settlement_ms") or 0.0), float(vb.get("onset_ms") or 0.0), 80.0) / 1000.0
    k_a = int(min(attack_s / hop_s, 0.4 * len(c), 0.4 * n_out))
    k_t = int(min(tail_s / hop_s, 0.2 * len(c), 0.2 * n_out))
    head = c[:k_a]
    tail = c[len(c) - k_t:] if k_t > 0 else np.zeros(0)
    sustain = c[k_a: len(c) - k_t] if len(c) - k_t > k_a else c[k_a:k_a + 1]
    n_sus = n_out - k_a - k_t
    if n_sus <= 0:
        return np.concatenate([head, tail])[:n_out]
    body = _crossfade_tile(sustain, n_sus, fade=int(0.1 / hop_s))
    return np.concatenate([head, body, tail])[:n_out]


# ----------------------------------------------------------------------------
# 転写本体
# ----------------------------------------------------------------------------

@dataclass
class TransferReport:
    mapping: list[int | None]
    n_ref: int
    n_target: int
    mode: str
    warnings: list[str]


def transfer(ref_igf: dict, target: list[Note], profile: Profile, mode: str = "param", mapping: str = "positional",
             manual_map: list[int | None] | None = None, seed: int | None = 0, amount: float = 1.0,
             amounts: dict[str, float] | None = None, key="auto", phrase_gap_s: float = 0.3,
             top_k: int = 3) -> tuple[Contour, TransferReport]:
    rng = np.random.default_rng(seed)
    hop_s = profile.hop_ms / 1000.0
    max_gap = profile.transition.max_gap_ms / 1000.0
    ref_notes = ref_igf.get("notes", [])
    warnings: list[str] = []
    if len(ref_notes) != len(target) and mapping == "positional" and manual_map is None:
        warnings.append(f"参照 {len(ref_notes)} 音 / ターゲット {len(target)} 音: 位置対応は循環します。--mapping context や --map の利用を検討してください")
    idx = map_notes(ref_notes, target, mode=mapping, top_k=top_k, rng=rng, max_gap_s=max_gap, manual=manual_map)
    split_phrases(target, gap_s=phrase_gap_s)
    if key == "auto":
        key = detect_key(target)[:2] if target else None

    out: list[NoteContour] = []
    ctx = NoteContext()
    amounts = amounts or {}
    for i, n in enumerate(target):
        nxt = target[i + 1] if i + 1 < len(target) else None
        ctx.next_legato = nxt is not None and (nxt.onset - n.offset) <= max_gap
        ctx.phrase_end = n.phrase_pos in ("last", "single")
        ctx.phrase_first = n.phrase_pos in ("first", "single")
        ctx.is_climax = n.is_climax
        ctx.key = key
        legato_in = ctx.prev_pitch is not None and ctx.gap_s <= max_gap
        r = ref_notes[idx[i]] if idx[i] is not None and idx[i] < len(ref_notes) else None
        fixed = igf_to_fixed(r, legato_in) if r is not None else None
        if r is not None and mode == "raw":
            # 参照の音程差と大きく違うときは警告
            tr = r.get("transition_in") or {}
            if legato_in and tr.get("portamento") and tr.get("interval") and ctx.prev_pitch is not None:
                tgt_iv = n.pitch - ctx.prev_pitch
                if abs(tgt_iv) > 2 * abs(tr["interval"]) + 2:
                    warnings.append(f"音符 {i}: 参照の遷移 {tr['interval']:+.0f} 半音をターゲット {tgt_iv:+d} 半音へ伸ばしています")
        nc = generate_note(n, ctx, profile, rng, amount=amount, amounts=amounts, fixed=fixed)
        if r is not None and mode == "raw":
            tgt_iv = (n.pitch - ctx.prev_pitch) if ctx.prev_pitch is not None else None
            raw = adapt_raw_curve(r, n.duration, hop_s, legato_in, tgt_iv)
            raw = raw[: len(nc.t)]
            if len(raw) < len(nc.t):
                raw = np.concatenate([raw, np.full(len(nc.t) - len(raw), raw[-1] if len(raw) else 0.0)])
            center = float(r.get("pitch_center_cents") or 0.0)
            a_into = amount * float(amounts.get("intonation", 1.0))
            a_rest = amount
            into = np.full(len(nc.t), center * a_into)
            rest = (raw - center) * a_rest
            nc.parts = {"intonation": into, "transition": np.zeros(len(nc.t)), "attack": np.zeros(len(nc.t)),
                        "vibrato": np.zeros(len(nc.t)), "drift": rest, "release": np.zeros(len(nc.t)), "jitter": np.zeros(len(nc.t))}
            nc.cents = into + rest
            nc.end_track = np.full(len(nc.t), center) + (raw - center)
            nc.params["raw_transfer"] = True
        nc.params["ref_index"] = idx[i]
        out.append(nc)
        ctx = NoteContext(prev_pitch=n.pitch, gap_s=(nxt.onset - n.offset) if nxt else 1e9,
                          prev_end_cents=nc.end_cents, prev_intonation=nc.params.get("intonation_random", 0.0))
    c = Contour(notes=out, hop_s=hop_s)
    c.key = key
    return c, TransferReport(mapping=idx, n_ref=len(ref_notes), n_target=len(target), mode=mode, warnings=warnings)
