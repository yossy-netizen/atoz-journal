import json

import numpy as np
import pytest

from pitchtrace.profile import Dist, Profile, list_builtin_profiles, load_profile


def test_builtin_profiles_load():
    names = list_builtin_profiles()
    assert {"violin_classical", "cello_classical", "oboe_classical", "alto_sax_classical", "alto_sax_jazz"} <= set(names)
    for n in names:
        p = load_profile(n)
        assert p.name == n
        assert 3.0 <= p.vibrato.rate_hz.mean <= 8.0


def test_dist_sampling_is_clamped():
    d = Dist(mean=0.0, std=100.0, min=-5.0, max=5.0)
    rng = np.random.default_rng(0)
    xs = [d.sample(rng) for _ in range(200)]
    assert min(xs) >= -5.0 and max(xs) <= 5.0


def test_profile_roundtrip(tmp_path):
    p = load_profile("alto_sax_jazz")
    path = tmp_path / "p.json"
    p.save(path)
    q = load_profile(path)
    assert q.to_dict() == p.to_dict()
    assert json.loads(path.read_text())["vibrato"]["rate_hz"]["mean"] == p.vibrato.rate_hz.mean


def test_unknown_param_rejected():
    with pytest.raises(KeyError):
        Profile.from_dict({"vibrato": {"nope": 1}})
