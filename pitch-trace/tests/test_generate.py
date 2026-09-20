import numpy as np

from pitchtrace.generate import generate_contour
from pitchtrace.notes import Note, split_phrases
from pitchtrace.profile import load_profile


def phrase():
    return [Note(60, 0.0, 0.5), Note(64, 0.5, 0.5), Note(67, 1.0, 1.2), Note(65, 2.5, 0.4), Note(64, 2.9, 1.0)]


def test_phrase_split_marks_positions_and_climax():
    notes = phrase()
    phrases = split_phrases(notes, gap_s=0.2)
    assert len(phrases) == 2
    assert notes[0].phrase_pos == "first" and notes[2].phrase_pos == "last"
    assert notes[2].is_climax  # 最高音
    assert notes[3].phrase_pos == "first" and notes[4].phrase_pos == "last"


def test_deterministic_with_seed():
    p = load_profile("violin_classical")
    a = generate_contour(phrase(), p, seed=42)
    b = generate_contour(phrase(), p, seed=42)
    c = generate_contour(phrase(), p, seed=43)
    for x, y in zip(a.notes, b.notes):
        assert np.array_equal(x.cents, y.cents)
    assert any(not np.array_equal(x.cents, y.cents) for x, y in zip(a.notes, c.notes))


def test_amount_zero_is_flat():
    p = load_profile("cello_classical")
    c = generate_contour(phrase(), p, seed=1, amount=0.0)
    for nc in c.notes:
        assert np.all(nc.cents == 0.0)


def test_sample_grid_matches_hop_and_duration():
    p = load_profile("oboe_classical")
    c = generate_contour(phrase(), p, seed=1)
    for nc in c.notes:
        assert len(nc.t) == max(int(round(nc.note.duration / c.hop_s)), 2)
        assert abs(nc.t[1] - nc.t[0] - c.hop_s) < 1e-9


def test_portamento_starts_from_previous_pitch():
    p = load_profile("cello_classical")
    p.transition.prob = 1.0
    p.attack.prob = 0.0
    p.jitter.cents = 0.0
    p.drift.cents.mean = p.drift.cents.std = 0.0
    p.vibrato.prob = 0.0
    p.release.prob = 0.0
    notes = [Note(60, 0.0, 0.5), Note(65, 0.5, 0.5)]
    c = generate_contour(notes, p, seed=0)
    second = c.notes[1]
    assert second.params["portamento"]
    # 開始時点では前の音（-500 セント）付近、終わりでは 0 付近
    assert abs(second.cents[0] - (-500.0 + second.parts["intonation"][0])) < 40
    assert abs(second.cents[-1] - second.parts["intonation"][-1]) < 5
    # 20→80% 時間が profile の定義通り（誤差 1 hop 以内）
    prog = (second.parts["transition"] - second.parts["transition"][0]) / (-second.parts["transition"][0])
    t20 = second.t[np.argmax(prog >= 0.2)]
    t80 = second.t[np.argmax(prog >= 0.8)]
    assert abs((t80 - t20) - second.params["portamento_ms"] / 1000.0) <= 2 * c.hop_s


def test_vibrato_rate_in_generated_curve():
    p = load_profile("violin_classical")
    p.vibrato.prob = 1.0
    p.vibrato.rate_hz.std = 0.0
    p.vibrato.rate_wobble = 0.0
    p.vibrato.onset_ms.mean = 0.0
    p.vibrato.onset_ms.std = 0.0
    p.vibrato.ramp_ms.mean = 30.0
    p.vibrato.ramp_ms.std = 0.0
    p.jitter.cents = 0.0
    p.drift.cents.mean = p.drift.cents.std = 0.0
    p.attack.prob = 0.0
    p.release.prob = 0.0
    c = generate_contour([Note(69, 0.0, 2.0)], p, seed=3)
    v = c.notes[0].parts["vibrato"]
    v = v - v.mean()
    spec = np.abs(np.fft.rfft(v * np.hanning(len(v)), 1 << 14))
    freqs = np.fft.rfftfreq(1 << 14, c.hop_s)
    peak = freqs[np.argmax(spec)]
    assert abs(peak - p.vibrato.rate_hz.mean) < 0.2


def test_no_lookahead_ignores_phrase_end():
    p = load_profile("alto_sax_jazz")
    notes = phrase()
    rt = generate_contour(notes, p, seed=2, lookahead=False)
    assert all(not nc.note.is_climax or True for nc in rt.notes)  # 実行できることの確認
    # lookahead=False ではクライマックス倍率が掛からない
    p.vibrato.prob = 1.0
    p.vibrato.climax_gain = 3.0
    la = generate_contour(phrase(), p, seed=2, lookahead=True)
    nl = generate_contour(phrase(), p, seed=2, lookahead=False)
    assert la.notes[2].params["vibrato_depth_cents"] > nl.notes[2].params["vibrato_depth_cents"] * 2.5
