"""IGF — Instrument Gesture Format（中間表現）v0.1。

解析結果を、特定のモデルや MIDI 規格に依存しない形で保存する。
音符ごとに「生カーブ（時間・セント・信頼度）」と「意味パラメータ」と「文脈」を持ち、
解析器・スキーマのバージョンを記録する。転写（transfer）とプロファイル構築の共通入力。
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import numpy as np

from . import __version__ as _pkg_version
from .analyze import AnalyzedNote
from .f0 import F0Track
from .key import detect_key
from .notes import Note

SCHEMA_VERSION = "0.1"


def _f(v, nd=3):
    return None if v is None else round(float(v), nd)


def build_igf(notes: list[AnalyzedNote], track: F0Track, source: str = "", instrument: str = "unknown",
              style: str = "unknown", sample_rate: int | None = None, max_gap_s: float = 0.04) -> dict:
    key = detect_key([Note(n.pitch, n.onset, n.duration) for n in notes]) if notes else (0, "major", 0.0)
    out = {
        "schema": "IGF",
        "schema_version": SCHEMA_VERSION,
        "analyzer": {"name": "pitchtrace", "version": _pkg_version, "pitch_detector": track.detector,
                     "hop_ms": round(track.hop_s * 1000.0, 3), "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")},
        "source": {"file": str(source), "sample_rate": sample_rate, "reference_tuning_hz": _f(track.tuning_hz, 2),
                   "duration_s": _f(track.times[-1] + track.hop_s) if len(track.times) else 0.0},
        "instrument": instrument,
        "style": style,
        "key": {"tonic": int(key[0]), "mode": key[1], "confidence": _f(key[2])},
        "notes": [],
    }
    hop = track.hop_s
    for i, n in enumerate(notes):
        p = n.params
        prev = notes[i - 1] if i > 0 else None
        nxt = notes[i + 1] if i + 1 < len(notes) else None
        i0 = int(np.searchsorted(track.times, n.onset))
        i1 = max(int(np.searchsorted(track.times, n.offset)), i0 + 1)
        conf = track.confidence[i0:i1]
        raw = track.raw_f0_hz[i0:i1] if track.raw_f0_hz is not None else track.f0_hz[i0:i1]
        L = min(len(n.t), len(conf), len(raw))
        note = {
            "id": i,
            "midi_note": int(n.pitch),
            "start_sec": _f(n.onset, 4),
            "end_sec": _f(n.offset, 4),
            "duration_sec": _f(n.duration, 4),
            "pitch_center_cents": _f(p.get("intonation_cents")),
            "confidence": _f(p.get("confidence")),
            "context": {
                "previous_interval": (n.pitch - prev.pitch) if prev else None,
                "next_interval": (nxt.pitch - n.pitch) if nxt else None,
                "legato_in": bool(p.get("legato", False)),
                "legato_out": bool(nxt is not None and (nxt.onset - n.offset) <= max_gap_s),
                "gap_before_sec": _f(n.onset - prev.offset, 4) if prev else None,
                "gap_after_sec": _f(nxt.onset - n.offset, 4) if nxt else None,
            },
            "attack": None if "attack_cents" not in p else {
                "deviation_cents": _f(p["attack_cents"]), "settlement_ms": _f(p["attack_settle_ms"], 1),
                "confidence": _f(p.get("attack_confidence")),
            },
            "transition_in": None if "transition_duration_ms" not in p else {
                "portamento": bool(p.get("transition_portamento")),
                "duration_ms": _f(p["transition_duration_ms"], 1),
                "interval": _f(p.get("transition_interval"), 2),
                "overshoot_cents": _f(p.get("transition_overshoot_cents")),
                "start_sec": _f(p.get("transition_start_sec"), 4),
                "end_sec": _f(p.get("transition_end_sec"), 4),
            },
            "sustain": {"drift_cents": _f(p.get("drift_cents")), "jitter_cents": _f(p.get("jitter_cents"))},
            "vibrato": None if not p.get("vibrato") else {
                "onset_ms": _f(p.get("vibrato_onset_ms"), 1), "mean_rate_hz": _f(p.get("vibrato_rate_hz")),
                "mean_depth_cents": _f(p.get("vibrato_depth_cents")), "center_offset": _f(p.get("vibrato_center_offset")),
            },
            "release": None if "release_cents" not in p else {"cents": _f(p["release_cents"])},
            "dynamics": None if "dyn_attack_ms" not in p else {
                "attack_ms": _f(p["dyn_attack_ms"], 1), "attack_from": _f(p.get("dyn_attack_from")),
                "sustain_slope": _f(p.get("dyn_sustain_slope"), 4), "release_to": _f(p.get("dyn_release_to")),
            },
            "curve": {
                "time_sec": [round(float(t), 4) for t in n.t[:L]],
                "cents": [None if np.isnan(c) else round(float(c), 2) for c in n.dev[:L]],
                "confidence": [round(float(c), 3) for c in conf[:L]],
                "raw_f0_hz": [None if np.isnan(f) else round(float(f), 3) for f in raw[:L]],
            },
        }
        out["notes"].append(note)
    return out


def save_igf(igf: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(igf, ensure_ascii=False, indent=1), encoding="utf-8")


def load_igf(path: str | Path) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("schema") != "IGF":
        raise ValueError(f"{path} は IGF ファイルではありません")
    return d


def igf_note_curve(note: dict, hop_s: float) -> tuple[np.ndarray, np.ndarray]:
    """IGF の音符から、音符開始基準の (t, cents) を hop_s 刻みで返す（欠損は補間）。"""
    t = np.asarray(note["curve"]["time_sec"], dtype=float)
    c = np.asarray([np.nan if v is None else v for v in note["curve"]["cents"]], dtype=float)
    if len(t) == 0:
        return np.zeros(0), np.zeros(0)
    t = t - t[0]
    bad = np.isnan(c)
    if bad.all():
        c = np.zeros_like(c)
    elif bad.any():
        c[bad] = np.interp(t[bad], t[~bad], c[~bad])
    grid = np.arange(0, t[-1] + 1e-9, hop_s)
    return grid, np.interp(grid, t, c)
