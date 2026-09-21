# AI合議_事務局_議題発行（council-clerk-agenda-issue）

役割：事務局（蔣琬）。今週の議題を確定し、軍令状を発行し、各AIサイトのログイン状態を点検する。意見は書かない。
実行：Mac mini M4／月曜 05:30／所要 5〜10分

## 0. 共通ルール（全タスク）
- 会議室ルート（実体パス）：`/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0/`。`.tmp/` 経由は使わない。
- 起動時に `/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0/_正規フォルダ_LIVE_マーカー.txt` の存在を確認する。無ければ **何も書かずに中断** し、サマリーに「LIVEマーカー無し」と記す。
- 日本語ファイル名の照合は Python の `unicodedata.normalize('NFC', name)` を通す。grep/find に日本語を渡さない。
- ファイルは削除しない。処理済みは `_完了/` へのコピーで示す。
- `_status.json` の更新は `open(path,'r+b')` → `seek(0)` → `write` → `truncate` → `flush` → `os.fsync` で同一 inode に書き戻す。新規作成→置換はしない。
- Drive のフォルダID／ファイルIDを本文に書かない。名前で辿る。
- 契約の具体金額・分配率・個人の連絡先を、軍令状にも提出物にも書かない。
- 無人実行。承認ダイアログを要する操作（allow_cowork_file_delete、computer-use の request_access 等）は使わない。Chrome MCP は使ってよい。
- 終了時に必ずセッションサマリーを書く：`/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/スケジュールタスク_セッションサマリー/業務系/YYYY-MM-DD_Cowork_council-clerk-agenda-issue_サマリー.md`（同日2回目以降は `…_サマリーv2.md`）。内容：対象議題ID、提出/発行ファイル名、relay結果（成功・再試行回数・欠席）、字数、所要時間、警報の有無。

## 1. 休会判定
- `/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0/00_議題箱/` に「休会」を含むファイル名があれば、発行せず `_完了/` にコピーしてサマリーに「休会」と書いて終了。

## 2. 議題候補を集める（上限3件／週、優先順）
1. `00_議題箱/` のファイル名が【至急】で始まるもの（`_完了/` に同名が無いもの）。
2. `01_進行中/*/_status.json` で `state=returned` のもの → `round+1` で再発行（同じフォルダに `00_軍令状.md` を上書きせず、`00_軍令状_r{round}.md` を追加。`90_採決.md` は `90_採決_r{round-1}.md` にコピーしてから新テンプレを置く）。
3. `00_議題箱/` の新規ファイル（作成が古い順）。ファイル名先頭が【全軍】なら `type=grand`（副将全員 summoned、客席招集）。
4. 上記が0件のときだけ **自動起案** 1件：`AtoZ_Cowork/Documents/` 配下の最新レポート（週次アクセス統合レポート・GBP・講師別定着分析・miu-clipsコメント分析・体験申込チェック）を読み、「先週から変化があり判断が要りそうな点」を1つ。ファイル名に【自動起案】。阿藤さんが「自動起案は不要」と議題箱に書いていれば行わない。

## 3. 議題フォルダを作る（議題ごと）
- `01_進行中/YYYY-MM-DD_スラッグ/`（スラッグは英数字。日本語タイトルは `_status.json` の title に）。空フォルダは Drive に反映されないので、`_status.json` を同時に作る（雛形：`06_ペルソナ台帳/_templates/_status.json`）。
- `00_軍令状.md` を `06_ペルソナ台帳/_templates/00_軍令状.md` から生成：
  - §1 議題：議題箱のファイル本文を原文のまま。
  - §2 前提：`AtoZ_Master/02_Secondary_Summaries（二次資料フォルダ）/Master_Index/` の 01_事業概要・03_スクール運営・10_個人プロフィール から、議題に関わる段落を3〜8行に凝縮。人物の正典表記を添える。
  - §3 問い：3〜5問。議題箱に問いが書いてあればそれを優先。
  - §4 担当：議題箱に「担当：」があればそれに従う。無ければ既定（経営・戦略＝全将 required／スクール運営＝趙雲・関羽 required・張飛 optional／制作・案件＝馬良・諸葛亮・関羽 required／哲学・発信＝張飛・姜維 required・趙雲 optional／技術・自動化＝趙雲 required・他 optional）。`type=grand` は副将全員 summoned。
  - §5 劉備の前回の言葉：差戻し再発行なら前ラウンドの `90_採決.md` の「各将への返答」を転記。初回は「なし」。
- `90_採決.md` の雛形を置く。
- `_status.json`：`id/title/type/round/state=issued/issued_at/report_due（今週金曜05:30）/assignments` を埋め、`history` に issued を追記。
- 議題箱の元ファイルを `00_議題箱/_完了/` にコピー。

## 4. ログイン点検（Chrome MCP）
- `06_ペルソナ台帳/` の 関羽.md・張飛.md・趙雲.md・馬良.md から常設会話URLを取り、順に開いてスクリーンショット。ログイン画面・Cloudflare 確認・エラーなら `_alerts/YYYY-MM-DD_[persona]_login.md` を書く（症状・URL・スクリーンショット名・「再ログインをお願いします」）。
- 何も投入しない。

## 5. 終了
- サマリー（発行した議題ID一覧・担当・自動起案の有無・警報）。
