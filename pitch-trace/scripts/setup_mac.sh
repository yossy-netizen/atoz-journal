#!/bin/bash
# PitchTrace を macOS（Apple Silicon）にセットアップする。
#
#   bash scripts/setup_mac.sh           venv 作成・インストール・テスト・デモ生成・環境診断
#   bash scripts/setup_mac.sh --live    さらにリアルタイム連携用の python-rtmidi を入れる
#   bash scripts/setup_mac.sh --logic   --live に加えて Logic Pro 用の確認ファイル一式を作る
#   bash scripts/setup_mac.sh --no-test テストを省く（再実行を急ぐとき）
set -euo pipefail
cd "$(dirname "$0")/.."

# macOS 標準の bash は 3.2 で、set -u のもとでは引数ゼロの "$@" が未定義エラーになる。
# $# を使う while ループならどちらのバージョンでも安全。
LIVE=0; LOGIC=0; RUN_TEST=1
while [ $# -gt 0 ]; do
  case "$1" in
    --live) LIVE=1 ;;
    --logic) LIVE=1; LOGIC=1 ;;
    --no-test) RUN_TEST=0 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "不明な引数: $1 （--live / --logic / --no-test）" >&2; exit 2 ;;
  esac
  shift
done

fail_hint() {
  echo
  echo "--- セットアップが途中で止まりました ---"
  echo "何が足りないかを調べます:"
  echo "  source .venv/bin/activate && pitchtrace doctor"
  echo "その出力をそのまま相談に貼ってください。"
}
trap fail_hint ERR

PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
      PY="$cand"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 以上が見つかりません。Homebrew で入れてください:" >&2
  echo "  brew install python@3.12" >&2
  echo "Homebrew 自体が無い場合は https://brew.sh の 1 行をターミナルに貼ります。" >&2
  trap - ERR
  exit 1
fi
echo "Python: $($PY --version) ($PY)"

if [ ! -d .venv ]; then
  echo "--- 仮想環境を作成 ---"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip --quiet

echo "--- インストール ---"
python -m pip install -e ".[dev,viz]" --quiet

# リアルタイム連携は python-rtmidi に依存する。Apple Silicon では wheel が配られているので
# 通常はすぐ入るが、環境によってはソースからのビルドに失敗する。オフラインの render には
# 不要なので、ここで失敗してもセットアップ全体は止めない。
LIVE_OK=0
if [ "$LIVE" = "1" ]; then
  if python -m pip install -e ".[dev,viz,live]" --quiet; then
    LIVE_OK=1
  else
    echo >&2
    echo "注意: python-rtmidi を入れられませんでした。" >&2
    echo "      オフライン（render / bendcheck / analyze）はこのまま使えます。" >&2
    echo "      リアルタイム（live / ports）だけが使えません。詳細は上のログを参照。" >&2
    echo >&2
  fi
fi

if [ "$RUN_TEST" = "1" ]; then
  echo "--- テスト ---"
  python -m pytest -q
fi

echo "--- デモ生成 ---"
pitchtrace demo demo_out --profile violin_classical

if [ "$LOGIC" = "1" ]; then
  echo "--- Logic Pro 用ファイル ---"
  mkdir -p logic_start
  pitchtrace bendcheck logic_start/01_bendcheck.mid --bend-range 12 >/dev/null
  cp demo_out/demo_static.mid logic_start/02_static.mid
  cp demo_out/demo_violin_classical.mid logic_start/03_traced.mid
  echo "  logic_start/01_bendcheck.mid … ベンドレンジ合わせ（最初にこれ）"
  echo "  logic_start/02_static.mid    … 表情なし（比較用）"
  echo "  logic_start/03_traced.mid    … 表情あり"
fi

# ここから先の失敗は「セットアップの失敗」ではなく「診断結果」なので、先にトラップを外す。
# ERR トラップは set +e のもとでも発火するため、set +e だけでは足りない。
trap - ERR
echo "--- 環境診断 ---"
set +e
pitchtrace doctor
DOC=$?
set -e

echo
echo "完了。次回からは:  source .venv/bin/activate"
if [ "$LOGIC" = "1" ]; then
  echo
  echo "Logic Pro での手順（詳しくは docs/MAC_SETUP.md の「Logic Pro で使う」）:"
  echo "  1. 空のプロジェクトにソフトウェア音源トラックを 1 本作る"
  echo "  2. logic_start/01_bendcheck.mid をそのトラックにドラッグして再生"
  echo "  3. 音源のベンドレンジ（Pitch Bend Up/Down）を 12 半音に設定し、"
  echo "     マーカー 2 と 3 の 2 音が同じ高さに聞こえるまで直す"
  echo "  4. 合ったら 02_static.mid と 03_traced.mid を聴き比べる"
else
  echo "  demo_out/demo_static.wav と demo_out/demo_violin_classical.wav を聴き比べてください"
fi
if [ "$LIVE_OK" = "1" ]; then
  echo "  リアルタイム:  pitchtrace live --profile violin_classical"
elif [ "$LIVE" = "1" ]; then
  echo "  リアルタイム連携は未導入です（python-rtmidi のインストールに失敗）"
fi
exit $DOC
