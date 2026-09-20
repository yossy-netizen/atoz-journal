"""セント偏差カーブ → ピッチベンド / MPE / CC 付き MIDI の書き出し。

モード:
- single: 1 チャンネル。重なった音は切り詰めて単旋律にし、ピッチベンドを 1 本出す。
- mpe:    MIDI Polyphonic Expression。ch1 をマスタ、ch2〜16 をメンバーとしてノートごとに
          チャンネルを回し、ノート単位のピッチベンドを出す。レガートの重なりを保てる。

ベンドレンジは RPN 0 (Pitch Bend Sensitivity) で各チャンネルに書き込む。
ビブラート成分を CC に出す場合（profile.output.vibrato_lane == "cc"）は、ベンドから
ビブラートを除き、その深さ包絡を CC 値にして出す。
"""

from __future__ import annotations

from pathlib import Path

import mido
import numpy as np

from .generate import Contour
from .profile import Profile


BEND_MAX = 8191
BEND_MIN = -8192


def cents_to_bend(cents: np.ndarray, bend_range_semitones: float) -> np.ndarray:
    v = np.round(cents / (bend_range_semitones * 100.0) * BEND_MAX)
    return np.clip(v, BEND_MIN, BEND_MAX).astype(int)


def _rpn_bend_range(channel: int, semitones: int, time: int = 0) -> list[mido.Message]:
    return [
        mido.Message("control_change", channel=channel, control=101, value=0, time=time),
        mido.Message("control_change", channel=channel, control=100, value=0, time=0),
        mido.Message("control_change", channel=channel, control=6, value=int(semitones), time=0),
        mido.Message("control_change", channel=channel, control=38, value=0, time=0),
        mido.Message("control_change", channel=channel, control=101, value=127, time=0),
        mido.Message("control_change", channel=channel, control=100, value=127, time=0),
    ]


def _mpe_config(master: int, members: int) -> list[mido.Message]:
    # RPN 6: MCM (MPE Configuration Message)
    return [
        mido.Message("control_change", channel=master, control=101, value=0, time=0),
        mido.Message("control_change", channel=master, control=100, value=6, time=0),
        mido.Message("control_change", channel=master, control=6, value=int(members), time=0),
        mido.Message("control_change", channel=master, control=101, value=127, time=0),
        mido.Message("control_change", channel=master, control=100, value=127, time=0),
    ]


def render_midi(
    contour: Contour,
    profile: Profile,
    out_path: str | Path,
    mode: str = "single",
    bend_range: int = 12,
    ticks_per_beat: int = 960,
    tempo_bpm: float = 120.0,
    channel: int = 0,
    legato_overlap_s: float = 0.0,
    max_events_per_s: float | None = None,
) -> mido.MidiFile:
    """Contour を MIDI ファイルに書き出す。

    mode: "single" | "mpe"
    bend_range: 半音単位のベンドレンジ（音源側と揃える）
    legato_overlap_s: single モードで残す重なり（レガート検出に重なりが要る音源向け）
    max_events_per_s: ベンド・CC イベントの上限密度（None = hop ごと）
    """
    if mode not in ("single", "mpe"):
        raise ValueError("mode は 'single' か 'mpe'")
    mf = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    mf.tracks.append(track)
    tempo = mido.bpm2tempo(tempo_bpm)
    track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    track.append(mido.MetaMessage("track_name", name=f"PitchTrace {profile.name}", time=0))

    def sec2tick(s: float) -> int:
        return int(round(mido.second2tick(s, ticks_per_beat, tempo)))

    events: list[tuple[int, int, mido.Message]] = []  # (tick, priority, msg)
    # 同 tick での並び順:
    #   0 = note_off, 1 = ベンドのリセット（前の音の後始末）, 2 = 設定/ベンド/CC, 3 = note_on
    # 次の音のベンドは、前の音のリセットより後・ノートオンより前に出す
    PRI_OFF, PRI_RESET, PRI_BEND, PRI_ON = 0, 1, 2, 3

    if mode == "single":
        member_channels = [channel]
        for m in _rpn_bend_range(channel, bend_range):
            events.append((0, PRI_BEND, m))
    else:
        master = 0
        member_channels = list(range(1, 16))
        for m in _mpe_config(master, len(member_channels)):
            events.append((0, PRI_BEND, m))
        for ch in member_channels:
            for m in _rpn_bend_range(ch, bend_range):
                events.append((0, PRI_BEND, m))

    use_cc = profile.output.vibrato_lane == "cc"
    cc_num = profile.output.cc_number
    cc_full = max(profile.output.cc_full_depth_cents, 1e-6)
    min_dt = (1.0 / max_events_per_s) if max_events_per_s else 0.0

    notes = contour.notes
    for i, nc in enumerate(notes):
        n = nc.note
        ch = member_channels[i % len(member_channels)]
        onset = n.onset
        end = n.offset
        nxt = notes[i + 1].note if i + 1 < len(notes) else None
        if mode == "single" and nxt is not None:
            # 同音の連打は重ねられない（前の note_off が次の音を消してしまう）
            overlap = 0.0 if nxt.pitch == n.pitch else legato_overlap_s
            if end > nxt.onset + overlap:
                end = max(nxt.onset + overlap, onset + 0.01)

        cents = nc.cents - (nc.parts["vibrato"] if use_cc else 0.0)
        bend = cents_to_bend(cents, bend_range)
        # ベンドはノートオンの直前から。値が変わったときだけ出す
        last_val = None
        last_t = -1e9
        for k, (ti, val) in enumerate(zip(nc.t, bend)):
            t_abs = onset + ti
            if t_abs >= end:
                break
            if val == last_val:
                continue
            if k > 0 and (t_abs - last_t) < min_dt:
                continue
            events.append((sec2tick(t_abs), PRI_BEND, mido.Message("pitchwheel", channel=ch, pitch=int(val))))
            last_val, last_t = int(val), t_abs
        if use_cc:
            last_cc = None
            last_t = -1e9
            for k, (ti, dep) in enumerate(zip(nc.t, nc.vib_env)):
                t_abs = onset + ti
                if t_abs >= end:
                    break
                cc = int(np.clip(round(dep / cc_full * 127), 0, 127))
                if cc == last_cc or (k > 0 and (t_abs - last_t) < min_dt):
                    continue
                events.append((sec2tick(t_abs), PRI_BEND, mido.Message("control_change", channel=ch, control=cc_num, value=cc)))
                last_cc, last_t = cc, t_abs
        events.append((sec2tick(onset), PRI_ON, mido.Message("note_on", channel=ch, note=n.pitch, velocity=int(np.clip(n.velocity, 1, 127)))))
        events.append((sec2tick(end), PRI_OFF, mido.Message("note_off", channel=ch, note=n.pitch, velocity=0)))
        # ノート終了後にベンドを 0 に戻す（次の音に備える）。single モードで次の音が
        # 終了前に同じチャンネルで始まっている（重なり）ときは、その音のベンドを壊すので出さない
        if not (mode == "single" and nxt is not None and nxt.onset <= end):
            events.append((sec2tick(end), PRI_RESET, mido.Message("pitchwheel", channel=ch, pitch=0)))

    events.sort(key=lambda e: (e[0], e[1]))
    last_tick = 0
    for tick, _, msg in events:
        msg.time = tick - last_tick
        last_tick = tick
        track.append(msg)
    track.append(mido.MetaMessage("end_of_track", time=0))
    mf.save(str(out_path))
    return mf
