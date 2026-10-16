import numpy as np

from pitchtrace.analyze import analyze_audio, build_profile, estimate_vibrato, segment_notes
from pitchtrace.f0 import yin_f0
from pitchtrace.generate import generate_contour
from pitchtrace.notes import Note
from pitchtrace.profile import load_profile
from pitchtrace.synth import synthesize

SR = 44100


def test_yin_tracks_pure_tone():
    t = np.arange(int(SR * 0.5)) / SR
    x = 0.5 * np.sin(2 * np.pi * 440.0 * t)
    tr = yin_f0(x, SR)
    f = tr.f0_hz[tr.voiced]
    assert len(f) > 50
    assert abs(np.median(f) - 440.0) < 1.0


def test_yin_marks_silence_unvoiced():
    x = np.zeros(SR)
    tr = yin_f0(x, SR)
    assert not tr.voiced.any()


def test_estimate_vibrato_recovers_rate_and_depth():
    hop = 0.005
    t = np.arange(int(1.0 / hop)) * hop
    dev = 3.0 + 25.0 * np.sin(2 * np.pi * 5.5 * t)
    v = estimate_vibrato(dev, hop)
    assert v is not None
    assert abs(v["rate_hz"] - 5.5) < 0.2
    assert abs(v["depth_cents"] - 25.0) < 5.0


def test_estimate_vibrato_rejects_flat():
    hop = 0.005
    dev = np.random.default_rng(0).normal(0, 1.0, 200)
    assert estimate_vibrato(dev, hop) is None


def test_segmentation_finds_steps():
    p = load_profile("oboe_classical")
    notes = [Note(64, 0.0, 0.5), Note(67, 0.5, 0.5), Note(62, 1.0, 0.7)]
    c = generate_contour(notes, p, seed=0, amount=0.0)
    x = synthesize(c)
    tr = yin_f0(x, SR)
    segs = segment_notes(tr)
    assert [s.pitch for s in segs] == [64, 67, 62]
    for s, n in zip(segs, notes):
        assert abs(s.onset - n.onset) < 0.05


def _random_phrase(rng, n=40):
    notes = []
    t = 0.0
    pitch = 67
    for i in range(n):
        dur = float(rng.choice([0.4, 0.6, 0.9, 1.2]))
        notes.append(Note(pitch, t, dur))
        pitch = int(np.clip(pitch + int(rng.choice([-5, -4, -3, -2, -1, 1, 2, 3, 4, 5])), 55, 84))
        t += dur + (0.0 if rng.random() < 0.6 else 0.15)
        if i % 8 == 7:
            t += 0.5
    return notes


def test_generate_synth_analyze_recovers_profile():
    """生成 → 合成 → 解析 の往復で、主要パラメータがプロファイルに戻ること。"""
    p = load_profile("violin_classical")
    notes = _random_phrase(np.random.default_rng(3))
    c = generate_contour(notes, p, seed=5)
    an, tr = analyze_audio(synthesize(c), SR)
    assert abs(len(an) - len(notes)) <= 3
    matched = 0
    for g in c.notes:
        a = min(an, key=lambda a: abs(a.onset - g.note.onset))
        if abs(a.onset - g.note.onset) < 0.08 and a.pitch == g.note.pitch:
            matched += 1
    assert matched >= len(notes) - 4
    prof = build_profile(an, base=p, name="t")
    assert abs(prof.vibrato.rate_hz.mean - p.vibrato.rate_hz.mean) < 0.5
    tuning_offset = 1200.0 * np.log2(tr.tuning_hz / 440.0)
    assert abs(prof.intonation.cents.mean + tuning_offset - p.intonation.cents.mean) < 6.0
    assert 0.6 < prof.vibrato.depth_cents.mean / p.vibrato.depth_cents.mean < 1.4
    assert prof.stats["n_notes"] == len(an)
    # 出力がそのまま render に使える
    c2 = generate_contour(notes[:5], prof, seed=1)
    assert len(c2.notes) == 5


def test_build_profile_continuity_is_finite_when_one_side_is_constant():
    from pitchtrace.analyze import AnalyzedNote
    z = np.zeros(3)
    notes = [AnalyzedNote(60, i, i + 0.5, z, z, {"intonation_cents": v, "jitter_cents": 1.0})
             for i, v in enumerate([0.0, 0.0, 0.0, 5.0])]
    prof = build_profile(notes)
    assert np.isfinite(prof.intonation.continuity)


def test_dynamics_estimation_from_audio():
    p = load_profile("cello_classical")
    p.dynamics.wobble = 0.0
    notes = [Note(48, 0.0, 1.2), Note(50, 1.5, 1.2), Note(52, 3.0, 1.2), Note(55, 4.5, 1.2)]
    c = generate_contour(notes, p, seed=2)
    an, tr = analyze_audio(synthesize(c), SR)
    assert tr.rms is not None and len(tr.rms) == len(tr.times)
    assert len(an) == 4
    for a in an:
        assert "dyn_attack_ms" in a.params and "dyn_sustain_slope" in a.params
        assert 0.0 <= a.params["dyn_attack_from"] <= 1.0
    prof = build_profile(an, base=p, name="t")
    assert prof.dynamics.attack_ms.mean > 0
    assert -0.6 <= prof.dynamics.sustain_slope.mean <= 0.6


def test_analyze_recovers_degree_bias():
    """度数バイアスを付けて合成した音から、解析が同じ向きのバイアス表を得ること。"""
    p = load_profile("violin_classical")
    p.intonation.cents.std = 1.0
    p.vibrato.prob = 0.0
    p.attack.prob = 0.0
    p.transition.prob = 0.0
    p.drift.cents.mean = p.drift.cents.std = 0.0
    p.release.prob = 0.0
    pitches = [60, 62, 64, 65, 67, 69, 71, 72] * 4
    notes = [Note(pch, i * 0.5, 0.4) for i, pch in enumerate(pitches)]
    c = generate_contour(notes, p, seed=1, key=(0, "major"))
    an, tr = analyze_audio(synthesize(c), SR)
    prof = build_profile(an, base=p, name="t")
    assert prof.stats["key"] == "0:major"
    tbl = prof.intonation.major_bias_cents
    assert tbl[11] > tbl[0] + 4      # 導音は主音より明確に高い
    assert abs(tbl[11] - p.intonation.major_bias_cents[11]) < 5


def test_tuning_estimate_separates_442_from_intonation():
    """A=442 相当（+7.85 セント）で合成した録音から基準ピッチを推定し、イントネーションを 0 付近に戻す。"""
    p = load_profile("cello_classical")
    p.intonation.cents.mean, p.intonation.cents.std = 7.85, 1.0
    p.intonation.key_bias_amount = 0.0
    p.vibrato.prob = 0.0
    p.attack.prob = 0.0
    p.transition.prob = 0.0
    p.release.prob = 0.0
    p.drift.cents.mean = p.drift.cents.std = 0.0
    notes = [Note(48 + i, i * 0.6, 0.5) for i in range(8)]
    c = generate_contour(notes, p, seed=0, key=None)
    an, tr = analyze_audio(synthesize(c), SR)
    assert abs(tr.tuning_hz - 442.0) < 1.0
    prof = build_profile(an, base=p, name="t", tuning_hz=tr.tuning_hz)
    assert abs(prof.intonation.cents.mean) < 3.0
    assert prof.stats["reference_tuning_hz"] == round(tr.tuning_hz, 2)
    an2, tr2 = analyze_audio(synthesize(c), SR, tuning=440.0)
    assert tr2.tuning_hz == 440.0
    assert np.median([a.params["intonation_cents"] for a in an2]) > 5.0


def test_octave_error_fix():
    from pitchtrace.analyze import fix_octave_errors
    p = load_profile("oboe_classical")
    c = generate_contour([Note(64, 0.0, 1.0)], p, seed=0, amount=0.0)
    tr = yin_f0(synthesize(c), SR)
    raw = tr.f0_hz.copy()
    tr.f0_hz[60:66] *= 2.0
    tr.f0_hz[90:93] *= 0.5
    n = fix_octave_errors(tr)
    assert n == 9
    good = ~np.isnan(raw)
    assert np.allclose(tr.f0_hz[good], raw[good], rtol=1e-6)
    assert tr.raw_f0_hz is not None


def test_random_humanize_profile_ignores_context():
    p = load_profile("random_humanize")
    c = generate_contour([Note(60, 0.0, 0.5), Note(62, 0.5, 0.5)], p, seed=0)
    assert not c.notes[1].params.get("portamento")
    assert "attack_cents" not in c.notes[1].params
    assert all(nc.params["intonation_key_bias"] == 0.0 for nc in c.notes)


def test_repeated_pitch_split_by_energy_dip():
    """同音連打は音量の落ち込みで分割される。"""
    p = load_profile("oboe_classical")
    p.vibrato.prob = 0.0
    notes = [Note(64, 0.0, 0.5), Note(64, 0.5, 0.5), Note(64, 1.0, 0.5)]
    c = generate_contour(notes, p, seed=0, amount=0.0)
    an, tr = analyze_audio(synthesize(c), SR)
    assert len(an) == 3
    assert [a.pitch for a in an] == [64, 64, 64]
    for a, n in zip(an, notes):
        assert abs(a.onset - n.onset) < 0.05
