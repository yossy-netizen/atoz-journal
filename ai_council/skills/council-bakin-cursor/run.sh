#!/bin/bash
# AI合議_馬鈞・Cursor_実装検証（council-bakin-cursor）— launchd から木曜 06:00 に起動
# 草案：Phase 0 で CLI の有無とオプション名を確認してから有効化する。
set -u
ROOT="/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0"
SUMM="/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/スケジュールタスク_セッションサマリー/業務系"
HERE="$(cd "$(dirname "$0")" && pwd)"
TODAY="$(date +%Y-%m-%d)"
LOG="$HERE/logs/$TODAY.log"; mkdir -p "$HERE/logs"
exec >>"$LOG" 2>&1
echo "== start $(date)"

# 0. LIVE マーカー（ゴースト判定）
[ -f "$ROOT/_正規フォルダ_LIVE_マーカー.txt" ] || { echo "LIVEマーカー無し。中断"; exit 0; }

# 1. CLI の検出（優先順：cursor-agent → codex → claude）
AGENT=""
for c in cursor-agent codex claude; do command -v "$c" >/dev/null 2>&1 && { AGENT="$c"; break; }; done
if [ -z "$AGENT" ]; then
  echo "CLI 未検出" > "$ROOT/_alerts/${TODAY}_bakin_cli_missing.md"
  echo "CLI 未検出。半自動運用へ"; exit 0
fi

# 2. 対象議題（assignments.bakin == required かつ responses.bakin 未登録）
TARGETS=$(python3 - "$ROOT" <<'PY'
import sys, json, glob, os, unicodedata
root=sys.argv[1]
for st in sorted(glob.glob(os.path.join(root,"01_進行中","*","_status.json"))):
    try: d=json.load(open(st,encoding="utf-8"))
    except Exception: continue
    if d.get("state") in ("issued","in_progress") and d.get("assignments",{}).get("bakin")=="required" and "bakin" not in d.get("responses",{}):
        print(os.path.dirname(st))
PY
)
[ -z "$TARGETS" ] && { echo "対象議題なし"; exit 0; }

# 3. 議題ごとに工房で検証
while IFS= read -r DIR; do
  [ -z "$DIR" ] && continue
  SLUG="$(basename "$DIR")"
  WORK="$ROOT/08_工房/${TODAY}_${SLUG}"; mkdir -p "$WORK"
  PROMPT="$WORK/_prompt_bakin.md"
  {
    cat "$ROOT/06_ペルソナ台帳/馬鈞.md"
    echo; echo "---"; echo "議題フォルダ: $DIR"; echo "作業場所（ここ以外に書かない）: $WORK"; echo "出力: $DIR/22_馬鈞_実装検証.md"; echo
    cat "$HERE/prompt_bakin.md"
    echo; echo "## 軍令状"; cat "$DIR/00_軍令状.md"
    [ -f "$DIR/20_趙雲_意見.md" ] && { echo; echo "## 趙雲の意見書"; cat "$DIR/20_趙雲_意見.md"; }
  } > "$PROMPT"
  case "$AGENT" in
    cursor-agent) (cd "$WORK" && timeout 900 cursor-agent -p "$(cat "$PROMPT")") ;;   # オプション名は Phase 0 で確認
    codex)        (cd "$WORK" && timeout 900 codex exec "$(cat "$PROMPT")") ;;
    claude)       (cd "$WORK" && timeout 900 claude -p "$(cat "$PROMPT")") ;;
  esac
  if [ -f "$DIR/22_馬鈞_実装検証.md" ]; then STATUS=done; else STATUS=absent; echo "CLI $AGENT がタイムアウトまたは出力なし" > "$DIR/22_馬鈞_欠席.md"; fi
  python3 - "$DIR/_status.json" "$STATUS" "$AGENT" <<'PY'
import sys, json, os, datetime
p, status, agent = sys.argv[1:4]
with open(p, "r+b") as f:
    d = json.loads(f.read().decode("utf-8"))
    d.setdefault("responses",{})["bakin"] = {"file": "22_馬鈞_実装検証.md" if status=="done" else "22_馬鈞_欠席.md",
        "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "status": status, "relay": "local_cli:"+agent}
    d["state"] = "in_progress"
    d.setdefault("history",[]).append({"at": d["responses"]["bakin"]["at"], "by": "council-bakin-cursor", "event": "bakin_"+status})
    b = json.dumps(d, ensure_ascii=False, indent=2).encode("utf-8")
    f.seek(0); f.write(b); f.truncate(); f.flush(); os.fsync(f.fileno())
PY
  # 蒲元（Codex）招集時
  if python3 -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); sys.exit(0 if d.get('assignments',{}).get('hogen')=='summoned' and 'hogen' not in d.get('responses',{}) else 1)" "$DIR/_status.json" \
     && command -v codex >/dev/null 2>&1; then
    P2="$WORK/_prompt_hogen.md"
    { cat "$ROOT/06_ペルソナ台帳/蒲元.md"; echo; echo "---"; echo "議題フォルダ: $DIR"; echo "作業場所: $WORK"; echo "出力: $DIR/26_蒲元_別実装案.md"; echo; cat "$HERE/prompt_hogen.md"; echo; cat "$DIR/22_馬鈞_実装検証.md" 2>/dev/null; } > "$P2"
    (cd "$WORK" && timeout 900 codex exec "$(cat "$P2")")
  fi
done <<< "$TARGETS"

# 4. セッションサマリー
S="$SUMM/${TODAY}_Cowork_council-bakin-cursor_サマリー.md"; n=1
while [ -f "$S" ]; do n=$((n+1)); S="$SUMM/${TODAY}_Cowork_council-bakin-cursor_サマリーv${n}.md"; done
{ echo "# council-bakin-cursor サマリー $TODAY"; echo; echo "- CLI: $AGENT"; echo "- 対象議題:"; echo "$TARGETS" | sed 's/^/  - /'; echo "- ログ: $LOG"; } > "$S"
echo "== end $(date)"
