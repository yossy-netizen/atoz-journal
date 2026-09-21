# AI合議_馬鈞・Cursor_実装検証（council-bakin-cursor）

Mac mini M4 の launchd から木曜 06:00 に起動する工房タスク。Cowork のスケジュールタスクではない（CLI を叩くため）。
Phase 3 で稼働。Phase 0 で `which cursor-agent codex claude` を確認し、無ければ半自動運用（`cursor_rules_council-bakin.mdc` を Cursor の `.cursor/rules/` に置き、阿藤さんが週1回「今週の議題を検証して」と投げる）。

| ファイル | 用途 |
|---|---|
| run.sh | launchd が実行。対象議題を探し、CLI にプロンプトを渡し、提出物と `_status.json` を更新 |
| prompt_bakin.md | 馬鈞（Cursor）へのプロンプト本文 |
| prompt_hogen.md | 蒲元（Codex）へのプロンプト本文（招集時のみ） |
| com.atoz.council-bakin-cursor.plist | launchd 定義（`~/Library/LaunchAgents/` に配置） |
| cursor_rules_council-bakin.mdc | 半自動運用用の Cursor ルール |

配置先：`~/Documents/Claude/Scheduled/council-bakin-cursor/`（他のスケジュールタスクと同じ場所に置き、名称対応表に「AI合議_馬鈞・Cursor_実装検証（council-bakin-cursor）／launchd」と追記）。
