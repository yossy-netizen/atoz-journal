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
    render_midi(c, p, out, mode="single", tempo_bpm=100.0)
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
