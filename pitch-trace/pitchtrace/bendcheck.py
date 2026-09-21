"""ベンドレンジ合わせ用の検査 MIDI を作る。

PitchTrace はピッチの動きを「ピッチベンド」で書き出す。ベンドの最大値がどれだけの
音程に対応するかを決める設定が「ベンドレンジ」で、既定では 12 半音（1 オクターブ）。
DAW と音源の側がこれと違う値（多くの音源の初期値は 2 半音）になっていると、
表情の量がそのまま音程の狂いになる。RPN という MIDI の仕組みで音源に通知しているが、
無視する音源が多いので、最後は耳で確かめるのが確実。

このモジュールは「正しく設定できていれば同じ高さに聞こえる音のペア」を並べた
MIDI ファイルを作る。ずれて聞こえたら音源側のベンドレンジが合っていない。
"""

from __future__ import annotations

from pathlib import Path

import mido

from .render_midi import BEND_MAX, BEND_MIN, _rpn_bend_range


def _note_name(pitch: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{names[pitch % 12]}{pitch // 12 - 1}"


def build_bendcheck(bend_range: int = 12, note: int = 60, tempo_bpm: float = 90.0,
                    channel: int = 0, ticks_per_beat: int = 960,
                    velocity: int = 80) -> mido.MidiFile:
    """検査用 MIDI を組み立てる。

    区間 1 …… 基準の 2 音を素のまま鳴らす（ベンドなし）
    区間 2 …… 下の音をベンドで上げ切る → 直後に上の音。同じ高さなら正しい
    区間 3 …… 上の音をベンドで下げ切る → 直後に下の音。同じ高さなら正しい
    区間 4 …… 連続的に上げる。段差やざらつきが出ないかを聴く
    """
    if not 1 <= bend_range <= 48:
        raise ValueError("bend_range は 1〜48 半音の範囲で指定してください")
    top = note + bend_range
    if not 0 <= note <= 127 or not 0 <= top <= 127:
        raise ValueError(f"音域が MIDI の範囲を超えます（{note} と {top}）")

    ev: list[tuple[int, int, mido.Message | mido.MetaMessage]] = []
    b = lambda beats: int(round(beats * ticks_per_beat))  # noqa: E731

    # 同じ tick に並んだときの順序。音を切る → ベンドを戻す → ベンドを掛ける → 鳴らす
    P_OFF, P_MARK, P_BEND, P_ON = 0, 1, 2, 3

    def add(beat: float, prio: int, msg) -> None:
        ev.append((b(beat), prio, msg))

    def marker(beat: float, text: str) -> None:
        # MIDI のマーカーは latin-1 しか入らないので英数字で書く（Logic のマーカー表示用）
        add(beat, P_MARK, mido.MetaMessage("marker", text=text.encode("ascii", "replace").decode("ascii")))

    def bend(beat: float, value: int) -> None:
        add(beat, P_BEND, mido.Message("pitchwheel", channel=channel, pitch=int(value)))

    def play(beat: float, pitch: int, length: float = 0.9) -> None:
        add(beat, P_ON, mido.Message("note_on", channel=channel, note=pitch, velocity=velocity))
        add(beat + length, P_OFF, mido.Message("note_off", channel=channel, note=pitch, velocity=0))

    for m in _rpn_bend_range(channel, bend_range):
        add(0.0, P_BEND, m)

    lo, hi = _note_name(note), _note_name(top)

    # 1. 基準
    marker(0.0, f"1 reference: {lo} then {hi}")
    bend(0.0, 0)
    play(0.0, note)
    play(1.0, top)

    # 2. 上げ切り（ベンド最大）→ 目標音
    marker(2.5, f"2 bend up: must equal {hi}")
    bend(2.5, BEND_MAX)
    play(2.5, note)
    bend(3.5, 0)
    play(3.5, top)

    # 3. 下げ切り（ベンド最小）→ 目標音
    marker(5.0, f"3 bend down: must equal {lo}")
    bend(5.0, BEND_MIN)
    play(5.0, top)
    bend(6.0, 0)
    play(6.0, note)

    # 4. なめらかさ（連続スイープ）
    marker(7.5, "4 smooth sweep")
    bend(7.5, 0)
    play(7.5, note, length=4.0)
    steps = 96
    for i in range(1, steps + 1):
        bend(7.5 + 2.0 * i / steps, int(round(BEND_MAX * i / steps)))
    bend(11.5, 0)

    mf = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    tr = mido.MidiTrack()
    mf.tracks.append(tr)
    tr.append(mido.MetaMessage("track_name", name=f"PitchTrace bendcheck {bend_range}st", time=0))
    tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo_bpm), time=0))

    ev.sort(key=lambda t: (t[0], t[1]))
    prev = 0
    for tick, _prio, msg in ev:
        msg = msg.copy(time=tick - prev)
        prev = tick
        tr.append(msg)
    tr.append(mido.MetaMessage("end_of_track", time=b(0.5)))
    return mf


def save_bendcheck(path: str | Path, **kw) -> mido.MidiFile:
    mf = build_bendcheck(**kw)
    mf.save(str(path))
    return mf


def instructions(bend_range: int = 12, note: int = 60) -> str:
    lo, hi = _note_name(note), _note_name(note + bend_range)
    return "\n".join([
        f"聴き方（音源のベンドレンジを {bend_range} 半音に設定してから再生）",
        f"  区間 1  {lo} と {hi} が続けて鳴る。この 2 つの高さを覚える",
        f"  区間 2  1 音目が {hi} と同じ高さなら正しい。低く聞こえたらベンドレンジが小さい",
        f"  区間 3  1 音目が {lo} と同じ高さなら正しい",
        "  区間 4  途切れず滑らかに上がるか。段差が聞こえたら音源のベンド解像度の問題",
        "",
        "ずれていたときの直し方は docs/MAC_SETUP.md の「Logic Pro で使う」を参照。",
    ])
