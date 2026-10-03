import numpy as np

from pitchtrace.evaluate import compare_igf, format_roundtrip, roundtrip


def test_roundtrip_quality_guard():
    """往復精度の回帰ガード。しきい値は v0.2 時点の実測に余裕を持たせた値。"""
    r = roundtrip("violin_classical", seed=0, n_notes=40)
    assert r["notes"]["recall"] >= 0.85 and r["notes"]["precision"] >= 0.85
    assert abs(r["onset_ms"]["mean"]) < 30
    assert abs(r["intonation_err_cents"]["mean"]) < 6
    assert r["vibrato"]["recall"] >= 0.7
    assert abs(r["vibrato"]["rate_err_hz"]["mean"]) < 0.4
    assert 0.6 < r["vibrato"]["depth_ratio"]["mean"] < 1.4
    assert 430 < r["tuning_hz"] < 450
    assert isinstance(format_roundtrip(r), str)


def test_compare_igf_self_is_zero(tmp_path):
    from tests.test_transfer import reference_igf
    igf, _ = reference_igf(tmp_path)
    rep = compare_igf(igf, igf)
    assert rep["vibrato_rate_hz"]["mean_diff_norm"] == 0.0
    assert rep["vibrato_fraction"]["a"] == rep["vibrato_fraction"]["b"]
