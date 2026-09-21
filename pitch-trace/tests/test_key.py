import numpy as np

from pitchtrace.generate import generate_contour
from pitchtrace.key import degree_bias, detect_key, key_name, parse_key
from pitchtrace.notes import Note
from pitchtrace.profile import load_profile


def scale(pitches, dur=0.4):
    return [Note(p, i * dur, dur) for i, p in enumerate(pitches)]


def test_parse_key():
    assert parse_key("C") == (0, "major")
    assert parse_key("F#") == (6, "major")
    assert parse_key("Bb") == (10, "major")
    assert parse_key("Am") == (9, "minor")
    assert parse_key("Ebm") == (3, "minor")
    assert key_name(9, "minor") == "Am"


def test_detect_key_major_and_minor():
    c_major = scale([60, 62, 64, 65, 67, 69, 71, 72, 71, 67, 64, 60])
    pc, mode, r = detect_key(c_major)
    assert (pc, mode) == (0, "major") and r > 0.7
    a_minor = scale([57, 59, 60, 62, 64, 65, 68, 69, 68, 64, 60, 57, 57])
    pc, mode, _ = detect_key(a_minor)
    assert (pc, mode) == (9, "minor")


def test_degree_bias_applied_in_contour():
    p = load_profile("violin_classical")
    p.intonation.cents.std = 0.0
    p.intonation.cents.mean = 0.0
    notes = scale([60, 62, 64, 65, 67, 69, 71, 72])
    c = generate_contour(notes, p, seed=0, key=(0, "major"))
    assert c.key == (0, "major")
    biases = [nc.params["intonation_key_bias"] for nc in c.notes]
    assert biases[6] == p.intonation.major_bias_cents[11]   # B = 導音は高め
    assert biases[0] == 0.0 and biases[7] == 0.0            # 主音
    assert all(nc.params["intonation_cents"] == nc.params["intonation_key_bias"] for nc in c.notes)
    off = generate_contour(scale([60, 62, 64, 65, 67, 69, 71, 72]), p, seed=0, key=None)
    assert all(nc.params["intonation_key_bias"] == 0.0 for nc in off.notes)


def test_auto_key_and_jazz_has_no_bias():
    p = load_profile("alto_sax_jazz")
    c = generate_contour(scale([60, 62, 64, 65, 67, 69, 71, 72]), p, seed=0)
    assert c.key == (0, "major")
    assert all(nc.params["intonation_key_bias"] == 0.0 for nc in c.notes)
