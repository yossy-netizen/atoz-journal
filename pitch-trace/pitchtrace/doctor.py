"""環境診断。

「入ったつもりで入っていない」「Logic から見えない」を切り分けるための自己点検。
各項目は OK / 注意 / 失敗 の 3 段階で、失敗には必ず直し方を添える。
リモートで相談するときは ``pitchtrace doctor --json`` の出力を貼れば、
こちらで環境を再現しなくても原因を絞り込める。
"""

from __future__ import annotations

import importlib
import platform
import shutil
import sys
from dataclasses import dataclass, field, asdict

OK = "ok"
WARN = "warn"
FAIL = "fail"

_MARK = {OK: "OK  ", WARN: "注意", FAIL: "失敗"}


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    fix: str = ""

    def line(self) -> str:
        s = f"[{_MARK[self.status]}] {self.name}"
        if self.detail:
            s += f": {self.detail}"
        return s


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "", fix: str = "") -> Check:
        c = Check(name, status, detail, fix)
        self.checks.append(c)
        return c

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def warned(self) -> list[Check]:
        return [c for c in self.checks if c.status == WARN]

    def to_dict(self) -> dict:
        return {"checks": [asdict(c) for c in self.checks],
                "failed": len(self.failed), "warned": len(self.warned)}


def _version(mod_name: str) -> str:
    try:
        from importlib.metadata import version
        return version(mod_name)
    except Exception:
        try:
            return getattr(importlib.import_module(mod_name), "__version__", "不明")
        except Exception:
            return "不明"


def _check_python(r: Report) -> None:
    v = sys.version_info
    detail = f"{v.major}.{v.minor}.{v.micro}  ({sys.executable})"
    if v >= (3, 10):
        r.add("Python のバージョン", OK, detail)
    else:
        r.add("Python のバージョン", FAIL, detail,
              "3.10 以上が必要です。 brew install python@3.12 の後、"
              "pitch-trace フォルダで .venv を作り直してください")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if in_venv:
        r.add("仮想環境 (venv)", OK, sys.prefix)
    else:
        r.add("仮想環境 (venv)", WARN, "システムの Python を直接使っています",
              "pitch-trace フォルダで source .venv/bin/activate を実行してください")


def _check_platform(r: Report) -> None:
    sysname = platform.system()
    if sysname == "Darwin":
        mac, _, _ = platform.mac_ver()
        r.add("OS", OK, f"macOS {mac} / {platform.machine()}")
    else:
        r.add("OS", WARN, f"{sysname} / {platform.machine()}",
              "リアルタイム連携 (live) と DAW 連携は macOS を想定しています")


def _check_core_packages(r: Report) -> None:
    try:
        import pitchtrace
        loc = getattr(pitchtrace, "__file__", "?")
        r.add("pitchtrace 本体", OK, f"{pitchtrace.__version__}  ({loc})")
    except Exception as e:
        r.add("pitchtrace 本体", FAIL, str(e),
              "pitch-trace フォルダで python -m pip install -e '.[dev,live,viz]' を実行してください")
    for name, why in (("numpy", "計算に必須"), ("mido", "MIDI 読み書きに必須")):
        try:
            importlib.import_module(name)
            r.add(f"{name}（{why}）", OK, _version(name))
        except Exception as e:
            r.add(f"{name}（{why}）", FAIL, str(e),
                  f"python -m pip install {name} を実行してください")
    if shutil.which("pitchtrace"):
        r.add("pitchtrace コマンド", OK, shutil.which("pitchtrace"))
    else:
        r.add("pitchtrace コマンド", WARN, "PATH にありません",
              "source .venv/bin/activate を実行するか、python -m pitchtrace.cli で代用できます")


def _check_optional(r: Report) -> None:
    opt = (("rtmidi", "python-rtmidi", "リアルタイム連携 (live / ports)", "pip install python-rtmidi"),
           ("matplotlib", "matplotlib", "可視化 (plot)", "pip install matplotlib"),
           ("librosa", "librosa", "pYIN 検出器 (analyze --detector pyin)", "pip install librosa"))
    for mod, dist, why, fix in opt:
        try:
            importlib.import_module(mod)
            r.add(f"{dist}（{why}）", OK, _version(dist))
        except Exception:
            r.add(f"{dist}（{why}）", WARN, "未インストール", fix)


def _check_midi_ports(r: Report) -> None:
    try:
        import mido
    except Exception:
        return
    try:
        ins = mido.get_input_names()
        outs = mido.get_output_names()
    except Exception as e:
        try:
            importlib.import_module("rtmidi")
            fix = ("MIDI の仕組み自体が使えません。macOS なら Logic などを一度起動してから "
                   "もう一度試してください。Linux コンテナでは ALSA がないため出ません。"
                   "オフラインの render だけを使うなら問題ありません")
        except Exception:
            fix = "python-rtmidi が要ります。 bash scripts/setup_mac.sh --live で入ります"
        r.add("MIDI ポートの列挙", WARN, str(e), fix)
        return
    r.add("MIDI 入力ポート", OK if ins else WARN,
          "、".join(ins) if ins else "見つかりません",
          "" if ins else "Logic を起動していれば通常は何か見えます。IAC ドライバを有効にすると確実です")
    r.add("MIDI 出力ポート", OK if outs else WARN,
          "、".join(outs) if outs else "見つかりません",
          "" if outs else "DAW や MIDI 機器が 1 つも見えていません。pitchtrace live は自前で"
                          "仮想ポートを作るので動きますが、既存ポートへ繋ぐ場合は Audio MIDI 設定で"
                          "IAC ドライバを有効にしてください")
    iac = [n for n in ins + outs if "IAC" in n.upper()]
    if iac:
        r.add("IAC ドライバ", OK, "、".join(sorted(set(iac))))
    else:
        r.add("IAC ドライバ", WARN, "無効または未作成",
              "Audio MIDI 設定 > ウインドウ > MIDI スタジオ > IAC ドライバ > 「装置はオンライン」に"
              "チェック。PitchTrace の仮想ポートだけを使うなら不要です")


def _check_virtual_port(r: Report) -> None:
    """CoreMIDI に仮想ポートを作れるか。Logic から PitchTrace が見えるかの実地テスト。"""
    try:
        import mido
    except Exception:
        return
    name = "PitchTrace Doctor"
    try:
        port = mido.open_output(name, virtual=True)
    except Exception as e:
        r.add("仮想 MIDI ポートの作成", WARN, str(e),
              "macOS では python-rtmidi があれば作れます。Linux では ALSA が必要です。"
              "オフラインの render だけを使うなら問題ありません")
        return
    try:
        port.close()
    except Exception:
        pass
    r.add("仮想 MIDI ポートの作成", OK, f"'{name}' を作成して閉じました")


def run_checks(midi: bool = True) -> Report:
    r = Report()
    _check_platform(r)
    _check_python(r)
    _check_core_packages(r)
    _check_optional(r)
    if midi:
        _check_midi_ports(r)
        _check_virtual_port(r)
    return r


def format_report(r: Report) -> str:
    lines = [c.line() for c in r.checks]
    problems = r.failed + r.warned
    if problems:
        lines.append("")
        lines.append("--- 対処 ---")
        for c in problems:
            if c.fix:
                lines.append(f"・{c.name}: {c.fix}")
    lines.append("")
    if r.failed:
        lines.append(f"失敗 {len(r.failed)} 件。上の対処を行ってから、もう一度 pitchtrace doctor を実行してください。")
    elif r.warned:
        lines.append(f"必須項目はすべて通りました（注意 {len(r.warned)} 件）。オフラインの render は使えます。")
    else:
        lines.append("すべて通りました。Logic との連携に進めます（docs/MAC_SETUP.md の「Logic Pro で使う」）。")
    return "\n".join(lines)
