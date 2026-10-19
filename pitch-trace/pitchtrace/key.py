"""調の判定（Krumhansl-Schmuckler 法）と音階度数ごとのイントネーション・バイアス。"""

from __future__ import annotations

import numpy as np

from .notes import Note

PC_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLAT = {"DB": 1, "EB": 3, "GB": 6, "AB": 8, "BB": 10, "CB": 11, "FB": 4}

# Krumhansl & Kessler (1982) のキープロファイル
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def parse_key(text: str) -> tuple[int, str]:
    """'C', 'F#', 'Bb', 'Am', 'F#m', 'Ebm' などを (tonic_pc, 'major'|'minor') にする。"""
    t = text.strip()
    mode = "major"
    if t.endswith("m") and not t.lower().endswith("maj"):
        mode = "minor"
        t = t[:-1]
    t = t.replace("♯", "#").replace("♭", "b")
    up = t.upper()
    if up in _FLAT:
        pc = _FLAT[up]
    elif up in PC_NAMES:
        pc = PC_NAMES.index(up)
    elif len(up) == 2 and up[1] == "#" and up[0] in PC_NAMES:
        pc = (PC_NAMES.index(up[0]) + 1) % 12
    else:
        raise ValueError(f"調名を解釈できません: {text!r}（例: C, F#, Bb, Am, F#m）")
    return pc, mode


def key_name(pc: int, mode: str) -> str:
    return PC_NAMES[pc] + ("m" if mode == "minor" else "")


def detect_key(notes: list[Note]) -> tuple[int, str, float]:
    """音符列から (tonic_pc, mode, 相関係数) を返す。音長で重み付けした音名ヒストグラムを使う。"""
    hist = np.zeros(12)
    for n in notes:
        hist[n.pitch % 12] += max(n.duration, 0.05)
    if hist.sum() <= 0:
        return 0, "major", 0.0
    best = (0, "major", -2.0)
    for pc in range(12):
        for mode, prof in (("major", _MAJOR), ("minor", _MINOR)):
            r = np.corrcoef(np.roll(prof, pc), hist)[0, 1]
            if np.isfinite(r) and r > best[2]:
                best = (pc, mode, float(r))
    return best


def degree_bias(pitch: int, tonic_pc: int, mode: str, major_table: list[float], minor_table: list[float]) -> float:
    """音（MIDI 番号）の、調に対する度数バイアス（セント）。表は主音からの半音数で引く。"""
    d = (pitch - tonic_pc) % 12
    table = major_table if mode == "major" else minor_table
    if not table or len(table) != 12:
        return 0.0
    return float(table[d])
