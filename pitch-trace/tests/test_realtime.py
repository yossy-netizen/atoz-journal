import mido
import numpy as np

from pitchtrace.profile import load_profile
from pitchtrace.realtime import RealtimeTracer


def make(mode="single", **kw):
    out = []
    p = load_profile(kw.pop("profile", "cello_classical"))
    for k, v in kw.pop("overrides", {}).items():
        sec, name = k.split(".")
        setattr(getattr(p, sec), name, v)
    tr = RealtimeTracer(profile=p, send=out.append, mode=mode, seed=0, **kw)
    tr.start()
    return tr, out


def on(pitch, vel=100):
    return mido.Message("note_on", note=pitch, velocity=vel)


def off(pitch):
    return mido.Message("note_off", note=pitch, velocity=0)


def test_setup_writes_bend_range():
    tr, out = make(bend_range=24)
    rpn = [m for m in out if m.type == "control_change" and m.control == 6]
    assert rpn and rpn[0].value == 24


def test_bend_precedes_note_on_and_streams_over_time():
    tr, out = make()
    n0 = len(out)
    tr.handle(on(60), 0.0)
    kinds = [m.type for m in out[n0:]]
    assert kinds[0] == "pitchwheel" and "note_on" in kinds
    n1 = len(out)
    tr.tick(0.5)
    bends = [m for m in out[n1:] if m.type == "pitchwheel"]
    assert len(bends) > 10
    tr.handle(off(60), 0.6)
    assert out[-2].type == "note_off" or out[-1].type == "note_off"
    assert tr.active == {}


def test_single_mode_is_monophonic_and_legato_glides():
    tr, out = make(overrides={"transition.prob": 1.0, "attack.prob": 0.0, "jitter.cents": 0.0})
    tr.handle(on(60), 0.0)
    tr.tick(0.5)
    n = len(out)
    tr.handle(on(67), 0.5)   # 前の音が鳴ったまま → レガート
    seq = [m.type for m in out[n:]]
    assert seq.index("note_off") < seq.index("note_on")          # 先に前の音を切る
    first_bend = next(m for m in out[n:] if m.type == "pitchwheel" and m.pitch != 0)
    # 新しい音は前の音（-700 セント）付近から始まる
    assert first_bend.pitch < -3000
    assert tr.stats["portamento"] == 1


def test_mpe_mode_uses_separate_channels_and_keeps_overlap():
    tr, out = make(mode="mpe")
    tr.handle(on(60), 0.0)
    tr.handle(on(64), 0.1)
    ons = [m for m in out if m.type == "note_on"]
    assert [m.channel for m in ons] == [1, 2]
    assert set(tr.active) == {60, 64}
    tr.handle(off(60), 0.5)
    tr.handle(off(64), 0.6)
    assert tr.active == {} and sorted(tr._free_channels) == list(range(1, 16))


def test_legato_overlap_delays_note_off():
    tr, out = make(legato_overlap_s=0.05)
    tr.handle(on(60), 0.0)
    n = len(out)
    tr.handle(on(62), 1.0)
    assert not any(m.type == "note_off" for m in out[n:])
    tr.tick(1.04)
    assert not any(m.type == "note_off" for m in out[n:])
    tr.tick(1.06)
    assert any(m.type == "note_off" and m.note == 60 for m in out[n:])


def test_cc_lane_and_passthrough():
    tr, out = make(overrides={"output.vibrato_lane": "cc", "vibrato.prob": 1.0, "vibrato.onset_ms": load_profile("cello_classical").vibrato.onset_ms})
    tr.handle(on(69), 0.0)
    tr.tick(2.0)
    assert any(m.type == "control_change" and m.control == 1 and m.value > 0 for m in out)
    n = len(out)
    tr.handle(mido.Message("control_change", channel=5, control=11, value=90), 2.0)
    assert out[-1].type == "control_change" and out[-1].control == 11 and out[-1].channel == 0


def test_all_notes_off_clears():
    tr, out = make(mode="mpe")
    for p in (60, 64, 67):
        tr.handle(on(p), 0.0)
    tr.handle(mido.Message("control_change", control=123, value=0), 0.1)
    assert tr.active == {}
    assert sum(1 for m in out if m.type == "note_off") == 3


def test_note_on_cost_is_small():
    import time
    tr, out = make()
    t0 = time.perf_counter()
    for i in range(20):
        tr.handle(on(60 + i % 12), i * 0.1)
        tr.handle(off(60 + i % 12), i * 0.1 + 0.05)
    per = (time.perf_counter() - t0) / 20
    assert per < 0.02  # 1 音あたり 20 ms 未満（30 秒分のカーブ生成込み）


def test_mpe_overlapping_legato_glides_from_sounding_note():
    tr, out = make(mode="mpe", overrides={"transition.prob": 1.0, "attack.prob": 0.0, "jitter.cents": 0.0})
    tr.handle(on(60), 0.0)
    tr.tick(0.5)
    n = len(out)
    tr.handle(on(67), 0.5)   # 60 が鳴ったまま → 重なりレガート
    first_bend = next(m for m in out[n:] if m.type == "pitchwheel")
    assert first_bend.pitch < -3000
    assert tr.stats["portamento"] == 1


def test_pending_note_off_is_flushed_before_same_pitch_note_on():
    tr, out = make(legato_overlap_s=0.05)
    tr.handle(on(60), 0.0)
    tr.handle(on(62), 1.0)          # 60 の note_off は 1.05 まで保留
    n = len(out)
    tr.handle(on(60), 1.02)         # 保留中の 60 が来た
    tr.tick(1.06)
    seq = [(m.type, m.note) for m in out[n:] if m.type in ("note_on", "note_off")]
    assert seq.index(("note_off", 60)) < seq.index(("note_on", 60))
    assert seq.count(("note_off", 60)) == 1   # 保留分が後から来て新しい音を消さない
    assert 60 in tr.active


def test_all_notes_off_resets_bend_with_pending_off():
    tr, out = make(legato_overlap_s=0.05)
    tr.handle(on(60), 0.0)
    tr.handle(on(62), 1.0)
    tr.handle(off(62), 1.01)
    n = len(out)
    tr.all_notes_off(1.02)
    assert out[-1].type == "pitchwheel" and out[-1].pitch == 0
    assert tr._pending_off == [] and tr.active == {}


def test_realtime_emits_dynamics_cc():
    tr, out = make()
    tr.handle(on(64), 0.0)
    tr.tick(1.0)
    cc = [m for m in out if m.type == "control_change" and m.control == 11]
    assert len(cc) > 3
    tr2, out2 = make(dynamics=False)
    tr2.handle(on(64), 0.0)
    tr2.tick(1.0)
    assert not any(m.type == "control_change" and m.control == 11 for m in out2)


def test_key_auto_detects_from_recent_notes():
    tr, out = make(key_auto=True)
    t = 0.0
    for pitch in (60, 62, 64, 65, 67, 69, 71, 72):
        tr.handle(on(pitch), t)
        tr.handle(off(pitch), t + 0.4)
        t += 0.5
    assert tr.key == (0, "major")
