"""音符列の表現、MIDI 読み込み、フレーズ分割。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import mido


@dataclass
class Note:
    pitch: int          # MIDI ノート番号
    onset: float        # 秒
    duration: float     # 秒
    velocity: int = 90
    # 以下は split_phrases / generate が埋める
    phrase: int = 0
    phrase_pos: str = "mid"     # "first" | "mid" | "last" | "single"
    is_climax: bool = False

    @property
    def offset(self) -> float:
        return self.onset + self.duration


def load_midi_notes(path: str | Path, track: int | None = None, channel: int | None = None) -> tuple[list[Note], mido.MidiFile]:
    """MIDI ファイルから音符列を読み込む（単旋律前提。重なりはそのまま返す）。"""
    mf = mido.MidiFile(str(path))
    events: list[tuple[float, int, int, int]] = []  # (time, kind(0=off,1=on), pitch, vel)
    tracks = mf.tracks if track is None else [mf.tracks[track]]
    tempo = 500000
    # テンポは全トラック共通なので、まず全メッセージを絶対 tick に並べて再生順に処理する
    merged = []
    for ti, tr in enumerate(mf.tracks):
        t = 0
        for msg in tr:
            t += msg.time
            merged.append((t, ti, msg))
    merged.sort(key=lambda x: x[0])
    sec = 0.0
    last_tick = 0
    for tick, ti, msg in merged:
        sec += mido.tick2second(tick - last_tick, mf.ticks_per_beat, tempo)
        last_tick = tick
        if msg.type == "set_tempo":
            tempo = msg.tempo
            continue
        if track is not None and mf.tracks[ti] is not tracks[0]:
            continue
        if msg.type in ("note_on", "note_off"):
            if channel is not None and msg.channel != channel:
                continue
            on = msg.type == "note_on" and msg.velocity > 0
            events.append((sec, 1 if on else 0, msg.note, msg.velocity))

    notes: list[Note] = []
    active: dict[int, Note] = {}
    for t, kind, pitch, vel in events:
        if kind == 1:
            if pitch in active:  # 同音の連打
                n = active.pop(pitch)
                n.duration = max(t - n.onset, 0.01)
                notes.append(n)
            active[pitch] = Note(pitch=pitch, onset=t, duration=0.0, velocity=vel)
        else:
            n = active.pop(pitch, None)
            if n is not None:
                n.duration = max(t - n.onset, 0.01)
                notes.append(n)
    for n in active.values():
        n.duration = 0.5
        notes.append(n)
    notes.sort(key=lambda n: (n.onset, n.pitch))
    return notes, mf


def make_monophonic(notes: list[Note], overlap_s: float = 0.0) -> list[Note]:
    """重なった音を切り詰めて単旋律にする。overlap_s > 0 なら、その長さだけ重なりを残す
    （レガート検出に重なりを要求する音源向け）。"""
    out = [Note(**{k: getattr(n, k) for k in n.__dataclass_fields__}) for n in notes]
    for a, b in zip(out, out[1:]):
        if a.offset > b.onset + overlap_s:
            a.duration = max(b.onset + overlap_s - a.onset, 0.01)
    return out


def split_phrases(notes: list[Note], gap_s: float = 0.3) -> list[list[Note]]:
    """休符（gap_s 以上）でフレーズに分け、各音の phrase / phrase_pos / is_climax を埋める。"""
    phrases: list[list[Note]] = []
    cur: list[Note] = []
    for n in notes:
        if cur and n.onset - cur[-1].offset > gap_s:
            phrases.append(cur)
            cur = []
        cur.append(n)
    if cur:
        phrases.append(cur)
    for pi, ph in enumerate(phrases):
        for i, n in enumerate(ph):
            n.phrase = pi
            if len(ph) == 1:
                n.phrase_pos = "single"
            elif i == 0:
                n.phrase_pos = "first"
            elif i == len(ph) - 1:
                n.phrase_pos = "last"
            else:
                n.phrase_pos = "mid"
            n.is_climax = False
        if len(ph) >= 3:
            top = max(ph, key=lambda n: (n.pitch, n.duration))
            top.is_climax = True
    return phrases
