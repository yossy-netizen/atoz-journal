import mido
import numpy as np

from pitchtrace.generate import generate_contour
from pitchtrace.notes import Note, load_midi_notes, make_monophonic
from pitchtrace.profile import load_profile
from pitchtrace.render_midi import cents_to_bend, render_midi


def notes():
    return [Note(60, 0.0, 0.5), Note(64, 0.5, 0.5), Note(67, 1.0, 1.0)]


def test_cents_to_bend_scaling():
    assert cents_to_bend(np.array([0.0]), 12)[0] == 0
    assert cents_to_bend(np.array([1200.0]), 12)[0] == 8191
    assert cents_to_bend(np.array([-100.0]), 2)[0] == -4096
    assert cents_to_bend(np.array([5000.0]), 2)[0] == 8191  # クランプ


def test_single_mode_writes_bend_range_and_notes(tmp_path):
    p = load_profile("violin_classical")
    c = generate_contour(notes(), p, seed=0)
    out = tmp_path / "o.mid"
    render_midi(c, p, out, mode="single", bend_range=24)
    mf = mido.MidiFile(out)
    msgs = list(mf.tracks[0])
    ons = [m for m in msgs if m.type == "note_on"]
    assert len(ons) == 3 and all(m.channel == 0 for m in ons)
    rpn = [m for m in msgs if m.type == "control_change" and m.control == 6]
    assert rpn and rpn[0].value == 24
    assert any(m.type == "pitchwheel" for m in msgs)
    # ノートオンの前にベンドが出ている（同 tick で先に並ぶ）
    first_on = next(i for i, m in enumerate(msgs) if m.type == "note_on")
    assert any(m.type == "pitchwheel" for m in msgs[:first_on])


def test_mpe_mode_rotates_channels(tmp_path):
    p = load_profile("cello_classical")
    c = generate_contour(notes(), p, seed=0)
    out = tmp_path / "o.mid"
    render_midi(c, p, out, mode="mpe")
    msgs = list(mido.MidiFile(out).tracks[0])
    on_ch = [m.channel for m in msgs if m.type == "note_on"]
    assert on_ch == [1, 2, 3]
    mcm = [m for m in msgs if m.type == "control_change" and m.channel == 0 and m.control == 6]
    assert mcm and mcm[0].value == 15


def test_cc_lane_emits_cc_and_removes_vibrato_from_bend(tmp_path):
    p = load_profile("violin_classical")
    p.vibrato.prob = 1.0
    p.output.vibrato_lane = "cc"
    c = generate_contour([Note(69, 0.0, 2.0)], p, seed=1)
    out = tmp_path / "o.mid"
    render_midi(c, p, out, mode="single")
    msgs = list(mido.MidiFile(out).tracks[0])
    ccs = [m for m in msgs if m.type == "control_change" and m.control == 1]
    assert len(ccs) > 5 and max(m.value for m in ccs) > 0


def test_roundtrip_midi_notes(tmp_path):
    p = load_profile("oboe_classical")
    c = generate_contour(notes(), p, seed=0)
    out = tmp_path / "o.mid"
    render_midi(c, p, out, mode="single", tempo_bpm=100.0, timing=False)
    loaded, _ = load_midi_notes(out)
    assert [n.pitch for n in loaded] == [60, 64, 67]
    for a, b in zip(loaded, notes()):
        assert abs(a.onset - b.onset) < 0.005
        assert abs(a.duration - b.duration) < 0.01


def test_make_monophonic_trims_overlap():
    ns = [Note(60, 0.0, 1.0), Note(62, 0.5, 0.5)]
    mono = make_monophonic(ns)
    assert abs(mono[0].duration - 0.5) < 1e-9
    keep = make_monophonic(ns, overlap_s=0.05)
    assert abs(keep[0].duration - 0.55) < 1e-9


def _abs_ticks(path):
    t = 0
    for m in mido.MidiFile(path).tracks[0]:
        t += m.time
        yield t, m


def test_single_mode_legato_join_keeps_portamento_start(tmp_path):
    """同 tick では 前の note_off → 次の音のベンド → note_on の順。ベンドのリセットが次の音を壊さない。"""
    p = load_profile("cello_classical")
    p.transition.prob = 1.0
    p.attack.prob = 0.0
    c = generate_contour([Note(60, 0.0, 0.5), Note(67, 0.5, 0.5)], p, seed=0)
    out = tmp_path / "o.mid"
    render_midi(c, p, out, mode="single")
    rows = list(_abs_ticks(out))
    t_on = next(t for t, m in rows if m.type == "note_on" and m.note == 67)
    same_tick = [m for t, m in rows if t == t_on and m.type in ("note_on", "note_off", "pitchwheel")]
    assert [m.type for m in same_tick] == ["note_off", "pitchwheel", "note_on"]
    assert same_tick[1].pitch < -3000  # 前の音（-700 セント）付近から始まる。0 ではない


def test_single_mode_repeated_pitch_does_not_overlap(tmp_path):
    """同音の連打は legato_overlap_s があっても重ねない（前の note_off が次の音を消すため）。"""
    p = load_profile("cello_classical")
    ns = make_monophonic([Note(60, 0.0, 0.6), Note(60, 0.5, 0.5)], overlap_s=0.02)
    c = generate_contour(ns, p, seed=0)
    out = tmp_path / "o.mid"
    render_midi(c, p, out, mode="single", legato_overlap_s=0.02, timing=False)
    notes_ev = [(t, m.type) for t, m in _abs_ticks(out) if m.type in ("note_on", "note_off")]
    assert notes_ev == [(0, "note_on"), (960, "note_off"), (960, "note_on"), (1920, "note_off")]


def test_dynamics_cc_and_timing(tmp_path):
    p = load_profile("violin_classical")
    c = generate_contour(notes(), p, seed=3)
    out = tmp_path / "o.mid"
    render_midi(c, p, out, mode="single")
    msgs = list(mido.MidiFile(out).tracks[0])
    cc11 = [m for m in msgs if m.type == "control_change" and m.control == 11]
    assert len(cc11) > 3 and 0 < max(m.value for m in cc11) <= 127
    # タイミング: ノートの順序は保たれ、開始は元の位置から大きく離れない
    loaded, _ = load_midi_notes(out)
    assert [n.pitch for n in loaded] == [60, 64, 67]
    for a, b in zip(loaded, notes()):
        assert abs(a.onset - b.onset) < 0.08
    # 無効化すると CC11 が出ず、タイミングも元通り
    out2 = tmp_path / "o2.mid"
    render_midi(c, p, out2, mode="single", dynamics=False, timing=False)
    msgs2 = list(mido.MidiFile(out2).tracks[0])
    assert not any(m.type == "control_change" and m.control == 11 for m in msgs2)
    loaded2, _ = load_midi_notes(out2)
    for a, b in zip(loaded2, notes()):
        assert abs(a.onset - b.onset) < 0.005


def _tempo_change_file(path):
    """120 bpm で 2 拍、その後 60 bpm。トラック 0 = テンポ、1 = 伴奏、2 = メロディ。"""
    mf = mido.MidiFile(ticks_per_beat=480)
    t0 = mido.MidiTrack(); mf.tracks.append(t0)
    t0.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    t0.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(60), time=960))
    acc = mido.MidiTrack(); mf.tracks.append(acc)
    acc.append(mido.MetaMessage("track_name", name="Piano", time=0))
    acc.append(mido.Message("note_on", channel=1, note=48, velocity=80, time=0))
    acc.append(mido.Message("note_off", channel=1, note=48, velocity=0, time=1920))
    mel = mido.MidiTrack(); mf.tracks.append(mel)
    mel.append(mido.MetaMessage("track_name", name="Violin", time=0))
    for pitch in (60, 62, 64, 65):
        mel.append(mido.Message("note_on", channel=0, note=pitch, velocity=100, time=0))
        mel.append(mido.Message("note_off", channel=0, note=pitch, velocity=0, time=480))
    mf.save(str(path))
    return mf


def test_tempo_map_roundtrip_and_track_replacement(tmp_path):
    from pitchtrace.notes import TempoMap, describe_midi
    src = tmp_path / "song.mid"
    _tempo_change_file(src)
    notes_in, mf = load_midi_notes(src, track=2)
    # 120bpm で 2 拍 = 1.0 s、その後 60bpm で 1 拍 = 1.0 s
    assert [round(n.onset, 3) for n in notes_in] == [0.0, 0.5, 1.0, 2.0]
    tm = TempoMap.from_midifile(mf)
    assert tm.sec2tick(2.0) == 1440 and abs(tm.tick2sec(1440) - 2.0) < 1e-9

    p = load_profile("violin_classical")
    c = generate_contour(notes_in, p, seed=0)
    out = tmp_path / "out.mid"
    render_midi(c, p, out, mode="single", tempo_map=tm, base_file=mf, replace_track=2, timing=False)
    rows = describe_midi(out)
    assert len(rows) == 3
    assert rows[1]["name"] == "Piano" and rows[1]["notes"] == 1        # 他トラック保持
    assert rows[2]["name"] == "Violin" and rows[2]["notes"] == 4       # 差し替え
    back, _ = load_midi_notes(out, track=2)
    assert [round(n.onset, 3) for n in back] == [0.0, 0.5, 1.0, 2.0]   # テンポチェンジ越しでも秒位置が一致
    assert any(m.type == "pitchwheel" for m in mido.MidiFile(out).tracks[2])

    # 単独出力でもテンポマップを書き込む
    out2 = tmp_path / "solo.mid"
    render_midi(c, p, out2, mode="single", tempo_map=tm, timing=False)
    back2, mf2 = load_midi_notes(out2)
    assert [round(n.onset, 3) for n in back2] == [0.0, 0.5, 1.0, 2.0]
    assert len(TempoMap.from_midifile(mf2).changes) == 2
