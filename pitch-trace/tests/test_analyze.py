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
    assert abs(prof.intonation.cents.mean - p.intonation.cents.mean) < 5.0
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
