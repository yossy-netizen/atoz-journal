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


class TempoMap:
    """MIDI ファイルのテンポマップ。秒 ⇄ tick を区分的に変換する（テンポチェンジ対応）。"""

    def __init__(self, ticks_per_beat: int, changes: list[tuple[int, int]] | None = None):
        self.ticks_per_beat = ticks_per_beat
        # (tick, tempo[us/beat]) を tick 昇順で。先頭は必ず tick 0
        ch = sorted(changes or [])
        if not ch or ch[0][0] != 0:
            ch = [(0, 500000)] + [c for c in ch if c[0] != 0]
        self.changes = ch
        # 各変化点の秒
        self._secs = [0.0]
        for (t0, tempo0), (t1, _) in zip(ch, ch[1:]):
            self._secs.append(self._secs[-1] + mido.tick2second(t1 - t0, ticks_per_beat, tempo0))

    @classmethod
    def from_midifile(cls, mf: mido.MidiFile) -> "TempoMap":
        changes = []
        for tr in mf.tracks:
            t = 0
            for msg in tr:
                t += msg.time
                if msg.type == "set_tempo":
                    changes.append((t, msg.tempo))
        # 同じ tick に複数あれば最後のものを採用
        by_tick: dict[int, int] = {}
        for t, tempo in sorted(changes):
            by_tick[t] = tempo
        return cls(mf.ticks_per_beat, sorted(by_tick.items()))

    @classmethod
    def constant(cls, ticks_per_beat: int, bpm: float) -> "TempoMap":
        return cls(ticks_per_beat, [(0, mido.bpm2tempo(bpm))])

    @property
    def initial_bpm(self) -> float:
        return float(mido.tempo2bpm(self.changes[0][1]))

    def tick2sec(self, tick: float) -> float:
        i = 0
        for j, (t, _) in enumerate(self.changes):
            if t <= tick:
                i = j
            else:
                break
        t0, tempo = self.changes[i]
        return self._secs[i] + mido.tick2second(tick - t0, self.ticks_per_beat, tempo)

    def sec2tick(self, sec: float) -> int:
        i = 0
        for j, s in enumerate(self._secs):
            if s <= sec:
                i = j
            else:
                break
        t0, tempo = self.changes[i]
        return int(round(t0 + mido.second2tick(sec - self._secs[i], self.ticks_per_beat, tempo)))


def describe_midi(path: str | Path) -> list[dict]:
    """トラックごとの概要（名前・チャンネル・音符数・音域・長さ）。info コマンド用。"""
    mf = mido.MidiFile(str(path))
    tm = TempoMap.from_midifile(mf)
    rows = []
    for ti, tr in enumerate(mf.tracks):
        name = next((m.name for m in tr if m.type == "track_name"), "")
        t = 0
        ons = []
        chans = set()
        tempos = 0
        for m in tr:
            t += m.time
            if m.type == "note_on" and m.velocity > 0:
                ons.append((t, m.note))
                chans.add(m.channel)
            elif m.type == "set_tempo":
                tempos += 1
        rows.append({
            "track": ti, "name": name, "channels": sorted(chans), "notes": len(ons),
            "pitch_range": (min(n for _, n in ons), max(n for _, n in ons)) if ons else None,
            "start_s": round(tm.tick2sec(ons[0][0]), 3) if ons else None,
            "end_s": round(tm.tick2sec(t), 3), "tempo_changes": tempos,
        })
    return rows


def load_midi_notes(path: str | Path, track: int | None = None, channel: int | None = None) -> tuple[list[Note], mido.MidiFile]:
    """MIDI ファイルから音符列を読み込む（単旋律前提。重なりはそのまま返す）。
    テンポチェンジはテンポマップで秒に変換する。"""
    mf = mido.MidiFile(str(path))
    tm = TempoMap.from_midifile(mf)
    events: list[tuple[float, int, int, int]] = []  # (time, kind(0=off,1=on), pitch, vel)
    for ti, tr in enumerate(mf.tracks):
        if track is not None and ti != track:
            continue
        t = 0
        for msg in tr:
            t += msg.time
            if msg.type in ("note_on", "note_off"):
                if channel is not None and msg.channel != channel:
                    continue
                on = msg.type == "note_on" and msg.velocity > 0
                events.append((tm.tick2sec(t), 1 if on else 0, msg.note, msg.velocity))
    events.sort(key=lambda e: (e[0], e[1]))

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
