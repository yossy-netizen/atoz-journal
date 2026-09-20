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
