"""環境診断（doctor）とベンドレンジ検査（bendcheck）、セットアップスクリプトの引数。"""

import json
import re
import subprocess
import sys
from pathlib import Path

import mido
import pytest

from pitchtrace.bendcheck import build_bendcheck, instructions
from pitchtrace.cli import main
from pitchtrace import doctor
from pitchtrace.doctor import FAIL, OK, WARN, format_report, run_checks
from pitchtrace.render_midi import BEND_MAX, BEND_MIN

ROOT = Path(__file__).resolve().parents[1]


# --- doctor -------------------------------------------------------------

def test_doctor_runs_without_midi_and_reports_core_items():
    r = run_checks(midi=False)
    names = " ".join(c.name for c in r.checks)
    for expected in ("Python", "pitchtrace", "numpy", "mido"):
        assert expected in names
    assert all(c.status in (OK, WARN, FAIL) for c in r.checks)
    # このテストが動いている時点で必須項目は満たされている
    assert not r.failed, [c.name for c in r.failed]


def test_doctor_every_problem_has_a_fix():
    r = run_checks(midi=False)
    for c in r.failed + r.warned:
        assert c.fix, f"{c.name} に対処方法が書かれていません"


def test_doctor_format_is_text_and_mentions_conclusion():
    text = format_report(run_checks(midi=False))
    assert isinstance(text, str) and len(text) > 50
    assert "通りました" in text or "失敗" in text


def test_doctor_cli_writes_json(tmp_path, capsys):
    out = tmp_path / "doctor.json"
    rc = main(["doctor", "--no-midi", "--json", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["checks"] and "failed" in data and "warned" in data
    assert all({"name", "status"} <= set(c) for c in data["checks"])


def test_doctor_survives_midi_probe():
    """MIDI が使えない環境（CI の Linux コンテナ等）でも落ちず、必須項目を落とさない。"""
    r = run_checks(midi=True)
    assert not r.failed, [c.name for c in r.failed]


def test_probe_survives_a_child_process_that_aborts():
    """RtMidi は初期化失敗時に C++ 例外のままプロセスを落とす。

    Python の try/except では捕まえられないので、子プロセスに隔離して
    「異常終了した」という結果に変換できている必要がある。
    """
    data, why = doctor._probe("import os; os.abort()")
    assert data is None
    assert "異常終了" in why


def test_probe_reports_a_child_that_raises():
    data, why = doctor._probe("raise RuntimeError('壊れています')")
    assert data is None and "壊れています" in why


def test_probe_reports_a_child_that_hangs():
    data, why = doctor._probe("import time; time.sleep(30)", timeout=1.0)
    assert data is None and "タイムアウト" in why


def test_probe_returns_parsed_json():
    data, why = doctor._probe("import json; print(json.dumps({'a': 1}))")
    assert why == "" and data == {"a": 1}


def test_probe_ports_never_raises():
    ins, outs, why = doctor.probe_ports()
    assert isinstance(ins, list) and isinstance(outs, list) and isinstance(why, str)


def test_ports_command_does_not_crash():
    """MIDI が使えない環境でも、異常終了ではなく通常の終了コードで返る。"""
    r = subprocess.run([sys.executable, "-m", "pitchtrace.cli", "ports"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode in (0, 1), f"異常終了しました: {r.returncode}"


def test_doctor_command_does_not_crash():
    r = subprocess.run([sys.executable, "-m", "pitchtrace.cli", "doctor"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode in (0, 1), f"異常終了しました: {r.returncode}\n{r.stderr[-2000:]}"


# --- bendcheck ----------------------------------------------------------

def _effective_pitches(mf: mido.MidiFile, bend_range: int) -> list[float]:
    """ノートオン時点の「実際に鳴る高さ」を半音単位で返す（ベンドを反映）。"""
    bend = 0
    out = []
    for msg in mf.tracks[0]:
        if msg.type == "pitchwheel":
            bend = msg.pitch
        elif msg.type == "note_on" and msg.velocity > 0:
            span = BEND_MAX if bend >= 0 else -BEND_MIN
            out.append(msg.note + bend / span * bend_range)
    return out


@pytest.mark.parametrize("bend_range", [12, 2, 7, 24])
def test_bendcheck_pairs_land_on_the_same_pitch(bend_range):
    mf = build_bendcheck(bend_range=bend_range, note=48)
    pitches = _effective_pitches(mf, bend_range)
    top = 48 + bend_range
    # 区間 1: 基準の 2 音
    assert pitches[0] == pytest.approx(48)
    assert pitches[1] == pytest.approx(top)
    # 区間 2: 上げ切り → 目標音。同じ高さでなければ検査にならない
    assert pitches[2] == pytest.approx(top)
    assert pitches[3] == pytest.approx(top)
    # 区間 3: 下げ切り → 目標音
    assert pitches[4] == pytest.approx(48)
    assert pitches[5] == pytest.approx(48)


def test_bendcheck_declares_the_bend_range_via_rpn():
    mf = build_bendcheck(bend_range=7)
    cc = [m for m in mf.tracks[0] if m.type == "control_change"]
    # RPN 0 (Pitch Bend Sensitivity) の Data Entry MSB が半音数
    assert cc[0].control == 101 and cc[0].value == 0
    assert cc[1].control == 100 and cc[1].value == 0
    assert cc[2].control == 6 and cc[2].value == 7


def test_bendcheck_sweep_is_monotonic_and_reaches_the_top():
    mf = build_bendcheck(bend_range=12)
    bends = [m.pitch for m in mf.tracks[0] if m.type == "pitchwheel"]
    sweep = bends[bends.index(BEND_MIN) + 1:]  # 区間 3 の後ろ = 区間 4
    rising = [v for v in sweep if v >= 0]
    assert max(rising) == BEND_MAX
    ramp = rising[:rising.index(BEND_MAX) + 1]
    assert ramp == sorted(ramp), "スイープが単調に上がっていません"
    assert rising[-1] == 0, "最後にベンドを 0 に戻していません（次の音がずれる）"


def test_bendcheck_markers_are_ascii_so_daws_can_read_them():
    mf = build_bendcheck()
    markers = [m for m in mf.tracks[0] if m.type == "marker"]
    assert len(markers) == 4
    for m in markers:
        m.text.encode("latin-1")  # 例外が出なければ保存できる


def test_bendcheck_rejects_impossible_settings():
    with pytest.raises(ValueError):
        build_bendcheck(bend_range=0)
    with pytest.raises(ValueError):
        build_bendcheck(bend_range=24, note=120)  # 上の音が 127 を超える


def test_bendcheck_cli_writes_file_and_prints_how_to_listen(tmp_path, capsys):
    out = tmp_path / "bc.mid"
    assert main(["bendcheck", str(out), "--bend-range", "12"]) == 0
    assert out.exists() and mido.MidiFile(str(out)).length > 1.0
    printed = capsys.readouterr().out
    assert "C4" in printed and "C5" in printed


def test_bendcheck_cli_reports_bad_input(tmp_path, capsys):
    assert main(["bendcheck", str(tmp_path / "x.mid"), "--bend-range", "99"]) == 1


def test_instructions_name_the_two_pitches():
    text = instructions(12, 60)
    assert "C4" in text and "C5" in text


# --- setup_mac.sh -------------------------------------------------------

SCRIPT = ROOT / "scripts" / "setup_mac.sh"


def test_setup_script_help_and_unknown_argument():
    ok = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert ok.returncode == 0 and "--logic" in ok.stdout
    bad = subprocess.run(["bash", str(SCRIPT), "--nope"], capture_output=True, text=True)
    assert bad.returncode == 2 and "不明な引数" in bad.stderr


def _arg_parsing_block() -> str:
    """引数解析の部分だけを切り出す（インストールを走らせずに検証するため）。"""
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("LIVE=0")
    end = text.index("fail_hint()")
    return text[start:end]


@pytest.mark.parametrize("argv", [[], ["--live"], ["--logic"], ["--no-test"], ["--logic", "--no-test"]])
def test_setup_script_arg_parsing_is_safe_without_arguments(argv):
    """macOS 標準の bash 3.2 は set -u のもとで引数ゼロの "$@" を未定義として落とす。

    引数なしでの実行は手順書に載っている呼び方なので、ここが落ちるとインストールできない。
    """
    body = "set -euo pipefail\n" + _arg_parsing_block() + '\necho "$LIVE $LOGIC $RUN_TEST"\n'
    r = subprocess.run(["bash", "-c", body, "setup_mac.sh", *argv], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert len(r.stdout.split()) == 3


def test_setup_script_disarms_err_trap_before_diagnosis():
    """ERR トラップは set +e のもとでも発火する。

    診断で失敗が出たときに「セットアップが途中で止まりました」と誤表示しないよう、
    診断の前にトラップを外しておく必要がある。
    """
    text = SCRIPT.read_text(encoding="utf-8")
    # 実行行そのものを探す（案内文の中の "pitchtrace doctor" と区別する）
    run = re.search(r"^pitchtrace doctor$", text, re.MULTILINE)
    disarm = re.search(r"^trap - ERR$", text, re.MULTILINE)
    assert run and disarm, "環境診断の実行行、または trap - ERR が見つかりません"
    assert disarm.start() < run.start(), "環境診断より前に trap - ERR を置いてください"
