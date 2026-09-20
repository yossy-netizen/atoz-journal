"""マニュアルとコマンドの食い違いを検出する。機能を足したら文書も更新する、というルールの機械的な担保。"""

import argparse
import re
from pathlib import Path

from pitchtrace.cli import build_parser

DOCS = Path(__file__).resolve().parents[1] / "docs"


def _subparsers(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def test_manual_covers_every_command_and_option():
    manual = (DOCS / "MANUAL.md").read_text(encoding="utf-8")
    missing = []
    for name, sub in _subparsers(build_parser()).items():
        if f"`{name}" not in manual and f"### 4.{name}" not in manual and f" {name} " not in manual:
            missing.append(name)
        for action in sub._actions:
            for opt in action.option_strings:
                if opt.startswith("--") and opt not in manual:
                    missing.append(f"{name} {opt}")
    assert not missing, f"MANUAL.md に載っていないコマンド / オプション: {missing}"


def test_guide_and_background_exist_and_are_substantial():
    for name, min_chars in (("GUIDE_FOR_EVERYONE.md", 3000), ("BACKGROUND.md", 4000), ("MANUAL.md", 6000), ("MAC_SETUP.md", 2000)):
        text = (DOCS / name).read_text(encoding="utf-8")
        assert len(text) >= min_chars, f"{name} が短すぎます ({len(text)} 文字)"


def test_docs_index_links_all_docs():
    index = (DOCS / "README.md").read_text(encoding="utf-8")
    for name in ("GUIDE_FOR_EVERYONE.md", "BACKGROUND.md", "MAC_SETUP.md", "MANUAL.md"):
        assert name in index


def test_builtin_profiles_listed_in_manual_and_guide():
    from pitchtrace.profile import list_builtin_profiles
    manual = (DOCS / "MANUAL.md").read_text(encoding="utf-8")
    for name in list_builtin_profiles():
        assert name in manual, f"MANUAL.md にプロファイル {name} がありません"


def test_repo_rule_file_exists():
    rule = Path(__file__).resolve().parents[2] / "CLAUDE.md"
    assert rule.exists()
    text = rule.read_text(encoding="utf-8")
    for name in ("MANUAL.md", "GUIDE_FOR_EVERYONE.md", "BACKGROUND.md"):
        assert name in text
