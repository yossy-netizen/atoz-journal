import json

import numpy as np

from pitchtrace.analyze import analyze_audio
from pitchtrace.generate import generate_contour
from pitchtrace.igf import build_igf, igf_note_curve, load_igf, save_igf
from pitchtrace.notes import Note
from pitchtrace.profile import load_profile
from pitchtrace.synth import synthesize
from pitchtrace.transfer import adapt_raw_curve, map_notes, transfer

SR = 44100


def reference_igf(tmp_path, rate=4.3, depth=28.0):
    """既知のビブラートを持つチェロ参照演奏を合成して IGF にする。"""
    p = load_profile("cello_classical")
    p.vibrato.prob = 1.0
    p.vibrato.rate_hz.mean, p.vibrato.rate_hz.std = rate, 0.0
    p.vibrato.depth_cents.mean, p.vibrato.depth_cents.std = depth, 0.0
    p.vibrato.onset_ms.mean, p.vibrato.onset_ms.std = 120.0, 0.0
    p.vibrato.full_depth_at_ms = 1.0
    p.vibrato.rate_wobble = 0.0
    p.vibrato.depth_wobble = 0.0
    p.transition.prob = 1.0
    p.attack.prob = 0.0
    p.release.prob = 0.0
    notes = [Note(48, 0.0, 1.5), Note(52, 1.5, 1.5), Note(55, 3.0, 1.5), Note(50, 4.8, 1.5)]
    c = generate_contour(notes, p, seed=1, key=None)
    an, tr = analyze_audio(synthesize(c), SR)
    igf = build_igf(an, tr, source="ref", instrument="cello")
    path = tmp_path / "ref.igf.json"
    save_igf(igf, path)
    return load_igf(path), notes


def _peak_hz(x, hop):
    x = x - x.mean()
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)), 1 << 14))
    f = np.fft.rfftfreq(1 << 14, hop)
    band = (f >= 2.5) & (f <= 10)
    return float(f[band][np.argmax(spec[band])])


def test_igf_roundtrip_has_curves_and_semantics(tmp_path):
    igf, notes = reference_igf(tmp_path)
    assert igf["schema"] == "IGF" and igf["schema_version"] == "0.1"
    assert len(igf["notes"]) == 4
    n = igf["notes"][1]
    assert n["vibrato"] is not None and abs(n["vibrato"]["mean_rate_hz"] - 4.3) < 0.4
    assert n["transition_in"] is not None and n["context"]["legato_in"]
    assert n["transition_in"]["start_sec"] < n["transition_in"]["end_sec"]
    assert len(n["curve"]["cents"]) == len(n["curve"]["time_sec"]) == len(n["curve"]["confidence"]) == len(n["curve"]["raw_f0_hz"])
    assert 0.5 <= n["confidence"] <= 1.0
    assert 430 < igf["source"]["reference_tuning_hz"] < 450
    t, c = igf_note_curve(n, 0.005)
    assert len(t) > 100 and np.isfinite(c).all()


def test_param_transfer_carries_vibrato_rate_to_target(tmp_path):
    igf, _ = reference_igf(tmp_path, rate=4.3)
    p = load_profile("cello_classical")
    p.vibrato.rate_wobble = 0.0
    target = [Note(60, 0.0, 1.0), Note(62, 1.0, 1.0), Note(64, 2.0, 2.0), Note(67, 4.0, 1.0)]
    c, rep = transfer(igf, target, p, mode="param", mapping="positional", seed=0)
    assert rep.mapping == [0, 1, 2, 3]
    third = c.notes[2]
    assert third.params.get("vibrato_rate_hz") is not None
    assert abs(third.params["vibrato_rate_hz"] - 4.3) < 0.4
    assert abs(_peak_hz(third.parts["vibrato"], c.hop_s) - 4.3) < 0.4
    assert c.notes[1].params.get("portamento") is True   # 参照のレガート遷移が転写される


def test_raw_transfer_preserves_vibrato_rate_when_stretched(tmp_path):
    igf, _ = reference_igf(tmp_path, rate=4.3)
    p = load_profile("cello_classical")
    # 参照 1.5 秒 → ターゲット 3.0 秒（継ぎ足し）と 0.7 秒（切り詰め）
    target = [Note(60, 0.0, 3.0), Note(64, 3.0, 0.7)]
    c, rep = transfer(igf, target, p, mode="raw", mapping="positional", seed=0)
    long_note = c.notes[0]
    assert len(long_note.cents) == int(round(3.0 / c.hop_s))
    sustain = long_note.cents[int(0.4 / c.hop_s): int(2.8 / c.hop_s)]
    assert abs(_peak_hz(sustain, c.hop_s) - 4.3) < 0.5
    assert long_note.params.get("raw_transfer")
    short = c.notes[1]
    assert len(short.cents) == int(round(0.7 / c.hop_s))


def test_adapt_raw_curve_scales_transition_to_target_interval(tmp_path):
    igf, _ = reference_igf(tmp_path)
    ref = igf["notes"][1]           # +4 半音のレガート遷移を持つ
    hop = 0.005
    same = adapt_raw_curve(ref, 1.0, hop, target_legato_in=True, target_interval=4.0)
    wider = adapt_raw_curve(ref, 1.0, hop, target_legato_in=True, target_interval=8.0)
    cut = adapt_raw_curve(ref, 1.0, hop, target_legato_in=False, target_interval=None)
    assert same[0] < -150            # 前の音の位置（約 -400 セント）から始まる
    assert wider[0] < same[0] - 100  # 音程差が倍なら開始点も遠くなる
    assert abs(cut[0]) < 120         # 非レガートなら遷移を切り落とす


def test_context_mapping_prefers_similar_notes(tmp_path):
    igf, _ = reference_igf(tmp_path)
    ref_notes = igf["notes"]
    target = [Note(60, 0.0, 1.5), Note(64, 1.5, 1.5)]
    m = map_notes(ref_notes, target, mode="context", top_k=1)
    assert all(isinstance(i, int) and 0 <= i < len(ref_notes) for i in m)
    manual = map_notes(ref_notes, target, manual=[3, None])
    assert manual == [3, None]


def test_transfer_cli_roundtrip(tmp_path):
    from pitchtrace.cli import main
    igf, _ = reference_igf(tmp_path)
    main(["demo", str(tmp_path / "d"), "--profile", "cello_classical"])
    out = tmp_path / "t.mid"
    assert main(["transfer", str(tmp_path / "ref.igf.json"), str(tmp_path / "d" / "demo_static.mid"), str(out),
                 "--mapping", "context", "--amount-vibrato", "0.5", "--wav", str(tmp_path / "t.wav")]) == 0
    assert out.stat().st_size > 500 and (tmp_path / "t.wav").exists()
    # WAV 参照からの転写（解析込み）と IGF 保存
    wav = tmp_path / "ref.wav"
    p = load_profile("cello_classical")
    notes = [Note(48, 0.0, 1.0), Note(50, 1.0, 1.0)]
    from pitchtrace.synth import write_wav
    write_wav(wav, synthesize(generate_contour(notes, p, seed=2)))
    assert main(["transfer", str(wav), str(tmp_path / "d" / "demo_static.mid"), str(tmp_path / "t2.mid"),
                 "--adapt", "raw", "--save-igf", str(tmp_path / "saved.igf.json")]) == 0
    assert json.loads((tmp_path / "saved.igf.json").read_text())["schema"] == "IGF"
