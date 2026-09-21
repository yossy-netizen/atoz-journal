# AI合議_事務局_採決取込（council-clerk-decision-intake）

役割：事務局。阿藤さんの採決を検知して状態を進め、承認された案件だけを実行系（今日のタスクリスト_DATA）へ起票する。【至急】議題の即時発行も担う。
実行：Mac mini M4／毎日 06:30／所要 2〜5分

## 0. 共通ルール（全タスク）
- 会議室ルート（実体パス）：`/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0/`。`.tmp/` 経由は使わない。
- 起動時に `/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0/_正規フォルダ_LIVE_マーカー.txt` の存在を確認する。無ければ **何も書かずに中断** し、サマリーに「LIVEマーカー無し」と記す。
- 日本語ファイル名の照合は Python の `unicodedata.normalize('NFC', name)` を通す。grep/find に日本語を渡さない。
- ファイルは削除しない。処理済みは `_完了/` へのコピーで示す。
- `_status.json` の更新は `open(path,'r+b')` → `seek(0)` → `write` → `truncate` → `flush` → `os.fsync` で同一 inode に書き戻す。新規作成→置換はしない。
- Drive のフォルダID／ファイルIDを本文に書かない。名前で辿る。
- 契約の具体金額・分配率・個人の連絡先を、軍令状にも提出物にも書かない。
- 無人実行。承認ダイアログを要する操作（allow_cowork_file_delete、computer-use の request_access 等）は使わない。Chrome MCP は使ってよい。
- 終了時に必ずセッションサマリーを書く：`/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/スケジュールタスク_セッションサマリー/業務系/YYYY-MM-DD_Cowork_council-clerk-decision-intake_サマリー.md`（同日2回目以降は `…_サマリーv2.md`）。内容：対象議題ID、提出/発行ファイル名、relay結果（成功・再試行回数・欠席）、字数、所要時間、警報の有無。

## 1. 採決の検知
- `/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0/01_進行中/*/90_採決.md` を読む。雛形のまま（「決定：」行に複数の選択肢が残っている）なら未採決として何もしない。
- 「決定：」行が1つに絞られていれば採決済み。

## 2. 状態を進める
| 決定 | 処理 |
|---|---|
| 承認／条件付き承認 | `state=approved`／`approved_with_conditions`。`40_諸葛亮_統合_C案.md` の「実行した場合のタスク案」を、`AtoZ_Cowork/今日のタスクリスト/今日のタスクリスト_DATA/` に **チャット側Claude向け_タスクリスト作成手順（Operations_Manual）** の書式で起票する（ファイル名 `YYYY-MM-DD_今日のタスクリスト_NN.md`、条件付きなら条件を先頭に転記）。議題フォルダ全体を `03_決定済み/` にコピー。 |
| 差戻し | `state=returned`。次の月曜に council-clerk-agenda-issue が round+1 で再発行する。何も起票しない。 |
| 却下／保留 | `state=rejected`／`held`。議題フォルダを `04_差戻し・却下/` にコピー。何も起票しない。 |
- 「各将への返答」「人間の客席への返答」は `99_返答配信_素材.md` として議題フォルダに保存（諸葛亮が金曜に整える）。
- `_status.json` の `decision` に `{"result": …, "at": …, "file": "90_採決.md"}`、`history` に追記。

## 3. 【至急】議題
- `00_議題箱/` に【至急】で始まる未処理ファイルがあれば、council-clerk-agenda-issue の §3 と同じ手順で **その場で** 議題フォルダを作る。`type=urgent`、担当は既定（諸葛亮・趙雲・関羽・張飛 required、他 none。議題箱に「担当：」があればそれに従う）。`report_due` は48時間後。
- 伝令タスクは各自の曜日に `type=urgent` を最優先で処理する。より早く回したい場合は阿藤さんがデスクトップアプリで該当伝令を「今すぐ実行」する（Phase 3 で tasklist-monitor に検知を追加）。

## 4. 舞さん共有（Dropbox）の更新
- 実体パス：`/Volumes/Cloud_Drive/StudioATO Dropbox/阿藤芳史/AI合議/阿藤舞共有AI合議/`。無ければ `_alerts/YYYY-MM-DD_mai_share_missing.md` を書いてこの節を飛ばす（選択型同期の可能性。存在しないと結論しない）。
- `index.html` を雛形 `06_ペルソナ台帳/_templates/mai_share_index.html` から再生成：進行中の議題（タイトル・状態・採決期限）、各将の要旨1行（`40_諸葛亮_統合_C案.md` の「各将の要旨」から）、直近の決定と阿藤さんからの返答、投稿の仕方。既存 index.html と内容が同じなら書かない。書くときは `r+b` で上書き（inode維持）。
- `02_定期報告/` の最新週次報告を `01_お知らせ/` に `.md` と `.html`（Markdown を最小限のHTMLに変換、外部依存なし）でコピー。同名があればスキップ。
- 採決に「人間の客席への返答」があれば `01_お知らせ/YYYY-MM-DD_阿藤さんからの返答.md` を置く（原文のまま）。
- `03_これまでの決定/決定一覧.md` に今回の決定を1行追記（議題・決定・日付）。
- 契約の具体金額・生徒個人情報はここに書かない。

## 5. 終了
- サマリー（採決を取り込んだ議題ID・決定・起票したタスクリスト名・至急発行の有無・舞さん共有の更新有無）。
- 承認前の案件を一切起票していないことを再確認して終了。
