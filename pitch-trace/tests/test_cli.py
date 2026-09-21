import json

from pitchtrace.cli import main


def test_cli_demo_render_analyze_roundtrip(tmp_path):
    out = tmp_path / "demo"
    assert main(["demo", str(out), "--profile", "alto_sax_jazz", "--seed", "1"]) == 0
    assert (out / "demo_alto_sax_jazz.wav").exists() and (out / "demo_static.mid").exists()

    rendered = tmp_path / "r.mid"
    assert main(["render", str(out / "demo_static.mid"), str(rendered), "--profile", "cello_classical", "--mode", "mpe"]) == 0
    assert rendered.stat().st_size > 500

    csv = tmp_path / "c.csv"
    assert main(["dump", str(out / "demo_static.mid"), str(csv), "--profile", "oboe_classical"]) == 0
    header = csv.read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("time_s,note,cents,intonation")

    prof = tmp_path / "learned.json"
    notes_json = tmp_path / "notes.json"
    assert main(["analyze", str(out / "demo_alto_sax_jazz.wav"), "-o", str(prof), "--base", "alto_sax_jazz", "--notes-json", str(notes_json)]) == 0
    d = json.loads(prof.read_text(encoding="utf-8"))
    assert d["stats"]["n_notes"] >= 10
    assert isinstance(json.loads(notes_json.read_text(encoding="utf-8")), list)
    # 学習したプロファイルで再レンダリングできる
    assert main(["render", str(out / "demo_static.mid"), str(tmp_path / "r2.mid"), "--profile", str(prof)]) == 0


def test_cli_profiles(capsys):
    assert main(["profiles"]) == 0
    assert "violin_classical" in capsys.readouterr().out


def test_cli_info_and_track_render(tmp_path):
    from tests.test_render_midi import _tempo_change_file
    src = tmp_path / "song.mid"
    _tempo_change_file(src)
    assert main(["info", str(src)]) == 0
    out = tmp_path / "out.mid"
    assert main(["render", str(src), str(out), "--track", "2", "--profile", "oboe_classical"]) == 0
    import mido
    mf = mido.MidiFile(out)
    assert len(mf.tracks) == 3
    assert any(m.type == "pitchwheel" for m in mf.tracks[2])
    assert not any(m.type == "pitchwheel" for m in mf.tracks[1])


def test_cli_analyze_igf_and_blind_demo(tmp_path):
    out = tmp_path / "demo"
    assert main(["demo", str(out), "--profile", "cello_classical", "--seed", "2", "--blind"]) == 0
    names = {p.name for p in out.iterdir()}
    assert {"blind_X.wav", "blind_Y.wav", "blind_Z.wav", "blind_answer.json"} <= names
    assert set(json.loads((out / "blind_answer.json").read_text()).values()) == {"static", "random_humanize", "cello_classical"}
    igf = tmp_path / "ref.igf.json"
    assert main(["analyze", str(out / "demo_cello_classical.wav"), "--igf", str(igf), "--instrument", "cello"]) == 0
    d = json.loads(igf.read_text(encoding="utf-8"))
    assert d["schema"] == "IGF" and d["instrument"] == "cello" and len(d["notes"]) >= 10
    assert d["analyzer"]["pitch_detector"] == "yin"
    # 成分ごとの量
    assert main(["render", str(out / "demo_static.mid"), str(tmp_path / "r.mid"), "--profile", "violin_classical",
                 "--amount-vibrato", "1.5", "--amount-attack", "0", "--amount-timing", "0"]) == 0


def test_cli_plot_if_matplotlib(tmp_path):
    import pytest
    pytest.importorskip("matplotlib")
    out = tmp_path / "demo"
    main(["demo", str(out), "--profile", "cello_classical"])
    igf = tmp_path / "ref.igf.json"
    main(["analyze", str(out / "demo_cello_classical.wav"), "--igf", str(igf)])
    png = tmp_path / "p.png"
    assert main(["plot", str(png), "--igf", str(igf), "--midi", str(out / "demo_static.mid"), "--profile", "cello_classical"]) == 0
    assert png.stat().st_size > 1000
