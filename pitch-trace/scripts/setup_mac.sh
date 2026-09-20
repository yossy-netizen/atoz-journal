#!/bin/bash
# PitchTrace を macOS（Apple Silicon）にセットアップする。
#   bash scripts/setup_mac.sh          … venv 作成・インストール・テスト・デモ生成
#   bash scripts/setup_mac.sh --live   … さらにリアルタイム用の python-rtmidi を入れる
set -euo pipefail
cd "$(dirname "$0")/.."

PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
      PY="$cand"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 以上が見つかりません。Homebrew で入れてください:"
  echo "  brew install python@3.12"
  exit 1
fi
echo "Python: $($PY --version) ($PY)"

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip --quiet
if [ "${1:-}" = "--live" ]; then
  python -m pip install -e ".[dev,live]" --quiet
else
  python -m pip install -e ".[dev]" --quiet
fi

echo "--- テスト ---"
python -m pytest -q
echo "--- デモ生成 ---"
pitchtrace demo demo_out --profile violin_classical
echo
echo "完了。次回からは:  source .venv/bin/activate"
echo "  demo_out/demo_static.wav と demo_out/demo_violin_classical.wav を聴き比べてください"
if [ "${1:-}" = "--live" ]; then
  echo "  リアルタイム:  pitchtrace live --profile violin_classical   （docs/MAC_SETUP.md 参照）"
fi
