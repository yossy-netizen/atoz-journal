# AI合議_事務局_人間の声取込（council-clerk-human-voice-intake）

役割：事務局。人間（スタッフ・客席・生徒・関係者）の言葉を、原文のまま議題に添える。AIの意見と混ぜない。
実行：Mac mini M4／日曜 22:00／所要 5〜10分

## 0. 共通ルール（全タスク）
- 会議室ルート（実体パス）：`/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0/`。`.tmp/` 経由は使わない。
- 起動時に `/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0/_正規フォルダ_LIVE_マーカー.txt` の存在を確認する。無ければ **何も書かずに中断** し、サマリーに「LIVEマーカー無し」と記す。
- 日本語ファイル名の照合は Python の `unicodedata.normalize('NFC', name)` を通す。grep/find に日本語を渡さない。
- ファイルは削除しない。処理済みは `_完了/` へのコピーで示す。
- `_status.json` の更新は `open(path,'r+b')` → `seek(0)` → `write` → `truncate` → `flush` → `os.fsync` で同一 inode に書き戻す。新規作成→置換はしない。
- Drive のフォルダID／ファイルIDを本文に書かない。名前で辿る。
- 契約の具体金額・分配率・個人の連絡先を、軍令状にも提出物にも書かない。
- 無人実行。承認ダイアログを要する操作（allow_cowork_file_delete、computer-use の request_access 等）は使わない。Chrome MCP は使ってよい。
- 終了時に必ずセッションサマリーを書く：`/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/スケジュールタスク_セッションサマリー/業務系/YYYY-MM-DD_Cowork_council-clerk-human-voice-intake_サマリー.md`（同日2回目以降は `…_サマリーv2.md`）。内容：対象議題ID、提出/発行ファイル名、relay結果（成功・再試行回数・欠席）、字数、所要時間、警報の有無。

## 1. 入力
1. `/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0/05_人間意見箱/` の未処理ファイル（`_完了/` に同名が無いもの）。雛形：冒頭に「議題：」「発言者：」「公開範囲：」の3行、以下本文。
2. `AtoZ_Cowork/Other_Services/Notta_Export/` の分類済み会議録（notta-transcript-processor の出力）のうち、直近7日で「スクール」「制作」「経営」に分類されたもの。
3. `AtoZ_Cowork/School/` の問い合わせ収集結果（inquiry-mail-collector）と体験申込チェックの直近7日分。
4. （Phase 2）講師向け意見箱フォーム・生徒アンケートの回答スプレッドシート。

## 2. 議題への紐づけ
- 「議題：」行があればその議題（`01_進行中/` の title または id で照合）。無ければ、翌日発行分の全議題に共通の「現場の声（今週）」として `00_議題箱/_現場の声_今週.md` に置き、council-clerk-agenda-issue が各議題の `05_現場の声.md` に転記する。

## 3. 書き方（`05_現場の声.md`）
- 見出し：`## 発言者表記｜日付｜経路`。発言者表記は「講師 庄子」「スタッフ（匿名希望）」「元請A社（阿藤さん経由）」「生徒の声（n件）」。
- 本文：**原文のまま**。Notta・問い合わせは要点のみ抜き、先頭に【要約】。
- 生徒個人が特定できる記述（氏名・校舎＋曜日＋楽器などの組合せ）は削り、件数と傾向に均す。
- 「公開範囲：本人名を伏せる」があれば表記を「スタッフ（匿名希望）」にする。
- 末尾に `件数：スタッフn／関係者n／生徒n`。

## 4. 終了
- 処理済みを `05_人間意見箱/_完了/` にコピー。`_status.json` の `human_voice` を更新。
- サマリー（取り込んだ件数・議題ID・匿名化した件数）。
