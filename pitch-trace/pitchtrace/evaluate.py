"""客観評価（構想メモ §7、仕様書 §60）。

1. roundtrip: プロファイルから音符列を生成 → 合成 → 解析 → 生成時の真値と比較。
   解析器の精度と「生成 → 解析 → プロファイル」の往復の忠実度を数値化する。改良の物差し
2. compare: 2 つの IGF（例: 参照演奏と、転写結果を再解析したもの）のパラメータ分布を比較する
"""

from __future__ import annotations

import numpy as np

from .analyze import analyze_audio, build_profile
from .generate import generate_contour
from .notes import Note
from .profile import Profile, load_profile
from .synth import synthesize

SR = 44100


def random_phrase(rng: np.random.Generator, n: int = 40, lo: int = 55, hi: int = 84) -> list[Note]:
    notes = []
    t = 0.0
    pitch = (lo + hi) // 2
    for i in range(n):
        dur = float(rng.choice([0.25, 0.4, 0.6, 0.9, 1.2, 1.8]))
        notes.append(Note(pitch, t, dur, velocity=int(rng.integers(70, 110))))
        pitch = int(np.clip(pitch + int(rng.choice([-7, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 7])), lo, hi))
        t += dur + (0.0 if rng.random() < 0.6 else 0.15)
        if i % 8 == 7:
            t += 0.5
    return notes


def _stats(xs) -> dict:
    xs = np.asarray([x for x in xs if x is not None and np.isfinite(x)], dtype=float)
    if len(xs) == 0:
        return {"n": 0}
    return {"n": int(len(xs)), "mean": round(float(xs.mean()), 3), "std": round(float(xs.std()), 3),
            "abs_mean": round(float(np.abs(xs).mean()), 3)}


def roundtrip(profile: Profile | str, seed: int = 0, n_notes: int = 40, register: tuple[int, int] | None = None, **analyze_kw) -> dict:
    """生成 → 合成 → 解析 の往復評価。"""
    p = load_profile(profile) if isinstance(profile, str) else profile
    rng = np.random.default_rng(seed)
    lo, hi = register or {"cello": (36, 67), "violin": (55, 88), "oboe": (58, 86), "alto_sax": (49, 80)}.get(p.instrument, (55, 84))
    notes = random_phrase(rng, n_notes, lo, hi)
    c = generate_contour(notes, p, seed=seed)
    an, tr = analyze_audio(synthesize(c), SR, **analyze_kw)

    matched = []
    used = set()
    for g in c.notes:
        best = None
        for j, a in enumerate(an):
            if j in used:
                continue
            d = abs(a.onset - g.note.onset)
            if d < 0.08 and (best is None or d < best[0]):
                best = (d, j)
        if best:
            used.add(best[1])
            matched.append((g, an[best[1]]))
    n_gen, n_found = len(c.notes), len(an)
    onset_err = [a.onset - g.note.onset for g, a in matched]
    pitch_ok = sum(1 for g, a in matched if a.pitch == g.note.pitch)
    # 解析側は推定した基準ピッチ基準、生成側は A=440 基準なので、差し引いた分を戻して比べる
    tuning_offset = 1200.0 * np.log2(tr.tuning_hz / 440.0)
    into_err = [a.params["intonation_cents"] + tuning_offset - g.params["intonation_cents"] for g, a in matched]

    vib_tp = vib_fp = vib_fn = vib_tn = 0
    rate_err, depth_ratio, onset_ms_err = [], [], []
    for g, a in matched:
        gv = "vibrato_rate_hz" in g.params and g.note.duration >= 0.6
        av = bool(a.params.get("vibrato"))
        if g.note.duration < 0.6:
            continue
        vib_tp += gv and av
        vib_fp += (not gv) and av
        vib_fn += gv and (not av)
        vib_tn += (not gv) and (not av)
        if gv and av:
            rate_err.append(a.params["vibrato_rate_hz"] - g.params["vibrato_rate_hz"])
            depth_ratio.append(a.params["vibrato_depth_cents"] / max(g.params["vibrato_depth_cents"], 1e-6))
            onset_ms_err.append(a.params["vibrato_onset_ms"] - g.params["vibrato_onset_ms"])
    port_tp = port_fn = port_fp = 0
    port_ratio = []
    for g, a in matched:
        gp = bool(g.params.get("portamento"))
        ap = bool(a.params.get("transition_portamento"))
        port_tp += gp and ap
        port_fn += gp and (not ap)
        port_fp += (not gp) and ap
        if gp and ap:
            port_ratio.append(a.params["transition_duration_ms"] / max(g.params["portamento_ms"], 1e-6))
    att_err = [a.params["attack_cents"] - g.params["attack_cents"] for g, a in matched
               if "attack_cents" in g.params and "attack_cents" in a.params]

    prof = build_profile(an, base=p, name="rt", tuning_hz=tr.tuning_hz)
    return {
        "profile": p.name, "seed": seed,
        "notes": {"generated": n_gen, "found": n_found, "matched": len(matched), "pitch_ok": pitch_ok,
                  "recall": round(len(matched) / max(n_gen, 1), 3), "precision": round(len(matched) / max(n_found, 1), 3)},
        "onset_ms": _stats([e * 1000 for e in onset_err]),
        "tuning_hz": round(float(tr.tuning_hz), 2),
        "tuning_err_cents": round(float(tuning_offset), 2),
        "intonation_err_cents": _stats(into_err),
        "vibrato": {"tp": vib_tp, "fp": vib_fp, "fn": vib_fn, "tn": vib_tn,
                    "recall": round(vib_tp / max(vib_tp + vib_fn, 1), 3), "precision": round(vib_tp / max(vib_tp + vib_fp, 1), 3),
                    "rate_err_hz": _stats(rate_err), "depth_ratio": _stats(depth_ratio), "onset_err_ms": _stats(onset_ms_err)},
        "portamento": {"tp": port_tp, "fn": port_fn, "fp": port_fp,
                       "recall": round(port_tp / max(port_tp + port_fn, 1), 3), "duration_ratio": _stats(port_ratio)},
        "attack_err_cents": _stats(att_err),
        "profile_recovery": {
            "vibrato_rate_hz": [round(p.vibrato.rate_hz.mean, 2), round(prof.vibrato.rate_hz.mean, 2)],
            "vibrato_depth_cents": [round(p.vibrato.depth_cents.mean, 1), round(prof.vibrato.depth_cents.mean, 1)],
            "intonation_std": [round(p.intonation.cents.std, 1), round(prof.intonation.cents.std, 1)],
            "portamento_prob": [round(p.transition.prob, 2), round(prof.transition.prob, 2)],
        },
    }


def compare_igf(a: dict, b: dict) -> dict:
    """2 つの IGF のパラメータ分布を比べる（平均・標準偏差と、正規化した差）。"""
    def col(igf, getter):
        vals = []
        for n in igf["notes"]:
            try:
                v = getter(n)
            except (KeyError, TypeError):
                v = None
            if v is not None:
                vals.append(float(v))
        return np.asarray(vals)

    fields = {
        "intonation_cents": lambda n: n["pitch_center_cents"],
        "vibrato_rate_hz": lambda n: n["vibrato"]["mean_rate_hz"],
        "vibrato_depth_cents": lambda n: n["vibrato"]["mean_depth_cents"],
        "vibrato_onset_ms": lambda n: n["vibrato"]["onset_ms"],
        "attack_cents": lambda n: n["attack"]["deviation_cents"],
        "transition_ms": lambda n: n["transition_in"]["duration_ms"] if n["transition_in"]["portamento"] else None,
        "drift_cents": lambda n: n["sustain"]["drift_cents"],
        "release_cents": lambda n: n["release"]["cents"],
    }
    out = {}
    for name, g in fields.items():
        xa, xb = col(a, g), col(b, g)
        row = {"a": _stats(xa), "b": _stats(xb)}
        if len(xa) and len(xb):
            pooled = np.sqrt((xa.var() + xb.var()) / 2) or 1.0
            row["mean_diff_norm"] = round(float((xb.mean() - xa.mean()) / pooled), 3)
        out[name] = row
    out["vibrato_fraction"] = {"a": round(sum(1 for n in a["notes"] if n["vibrato"]) / max(len(a["notes"]), 1), 3),
                               "b": round(sum(1 for n in b["notes"] if n["vibrato"]) / max(len(b["notes"]), 1), 3)}
    out["portamento_fraction"] = {"a": round(sum(1 for n in a["notes"] if (n["transition_in"] or {}).get("portamento")) / max(len(a["notes"]), 1), 3),
                                  "b": round(sum(1 for n in b["notes"] if (n["transition_in"] or {}).get("portamento")) / max(len(b["notes"]), 1), 3)}
    return out


def format_roundtrip(r: dict) -> str:
    n, v, pt = r["notes"], r["vibrato"], r["portamento"]
    lines = [
        f"[{r['profile']} seed {r['seed']}]",
        f"  音符: 生成 {n['generated']} / 検出 {n['found']} / 対応 {n['matched']} (recall {n['recall']}, precision {n['precision']}), 音高一致 {n['pitch_ok']}",
        f"  オンセット誤差: {r['onset_ms'].get('mean', 0):+.0f} ± {r['onset_ms'].get('std', 0):.0f} ms   基準ピッチ推定: A={r['tuning_hz']} Hz",
        f"  イントネーション誤差: {r['intonation_err_cents'].get('mean', 0):+.1f} ± {r['intonation_err_cents'].get('std', 0):.1f} cent",
        f"  ビブラート(>=0.6s): recall {v['recall']} precision {v['precision']} | レート誤差 {v['rate_err_hz'].get('mean', 0):+.2f} ± {v['rate_err_hz'].get('std', 0):.2f} Hz | 深さ比 {v['depth_ratio'].get('mean', 0):.2f} | 開始誤差 {v['onset_err_ms'].get('mean', 0):+.0f} ms",
        f"  ポルタメント: recall {pt['recall']} (tp {pt['tp']} fn {pt['fn']} fp {pt['fp']}) | 時間比 {pt['duration_ratio'].get('mean', 0):.2f}",
        f"  アタック誤差: {r['attack_err_cents'].get('mean', 0):+.1f} ± {r['attack_err_cents'].get('std', 0):.1f} cent (n={r['attack_err_cents'].get('n', 0)})",
        "  プロファイル復元 [真値, 推定]: " + ", ".join(f"{k} {v}" for k, v in r["profile_recovery"].items()),
    ]
    return "\n".join(lines)
