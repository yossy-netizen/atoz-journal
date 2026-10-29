# AI合議_馬良・Perplexity_調査（council-baryo-perplexity）

役割：馬良（Perplexity）の **伝令**。馬良本人は Perplexity の常設会話にいる。本タスクは軍令状を届け、意見書を持ち帰り、Drive に保存するだけで、意見の中身を改変しない。
実行：Mac mini M4（Cowork ローカルのスケジュールタスク）／火曜 05:30／所要 10分前後
設計：`2026-09-21_AI合議制2.0_設計書_v1.md`・`…_スケジュールタスク仕様_v1.md`（AtoZ_Cowork/Documents/AI会議/合議2.0/ 配下に配置予定）

## 0. 共通ルール（全タスク）
- 会議室ルート（実体パス）：`/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0/`。`.tmp/` 経由は使わない。
- 起動時に `/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0/_正規フォルダ_LIVE_マーカー.txt` の存在を確認する。無ければ **何も書かずに中断** し、サマリーに「LIVEマーカー無し」と記す。
- 日本語ファイル名の照合は Python の `unicodedata.normalize('NFC', name)` を通す。grep/find に日本語を渡さない。
- ファイルは削除しない。処理済みは `_完了/` へのコピーで示す。
- `_status.json` の更新は `open(path,'r+b')` → `seek(0)` → `write` → `truncate` → `flush` → `os.fsync` で同一 inode に書き戻す。新規作成→置換はしない。
- Drive のフォルダID／ファイルIDを本文に書かない。名前で辿る。
- 契約の具体金額・分配率・個人の連絡先を、軍令状にも提出物にも書かない。
- 無人実行。承認ダイアログを要する操作（allow_cowork_file_delete、computer-use の request_access 等）は使わない。Chrome MCP は使ってよい。
- 終了時に必ずセッションサマリーを書く：`/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/スケジュールタスク_セッションサマリー/業務系/YYYY-MM-DD_Cowork_council-baryo-perplexity_サマリー.md`（同日2回目以降は `…_サマリーv2.md`）。内容：対象議題ID、提出/発行ファイル名、relay結果（成功・再試行回数・欠席）、字数、所要時間、警報の有無。

## 1. 対象議題の特定
- `/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0/01_進行中/*/_status.json` を全て読む。
- 対象：`state` が `issued` または `in_progress`、かつ `assignments.baryo` が `none`／`excused` 以外、かつ `responses.baryo` が未登録のもの。
- 該当なしなら、サマリーに「該当議題なし」と書いて終了。
- 対象があれば `state` を `in_progress` に更新し、`history` に `{"at":…, "by":"council-baryo-perplexity", "event":"started"}` を追記。

## 2. この将に固有の指示（軍令状に必ず添える）
- 「意見は不要。素材と論点だけ」
- 「(A)事実・数字（出典2件以上・一次資料優先）(B)同種事例（国内外）(C)慣行・相場の幅 (D)論点メモ（対立しそうな点2〜3・折衷例）」
- 馬良の提出物は4見出しではなく A〜D の見出しで検査する（手順7の検査対象を A〜D に読み替える）
- 「AtoZ の契約金額は書かない」

## 3. 伝令手順（Chrome MCP relay）
AI軍議運用手順書v1 §3〜§4 を手順化。各段階は最大2回まで再試行。
1. ペルソナ台帳 `/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0/06_ペルソナ台帳/馬良.md` を読み、「常設会話URL」と「投入プロンプト」を取る。
2. 軍令状を組み立てる（上限6,000字）：
   - `00_軍令状.md` 全文
   - 台帳の「投入プロンプト」
   - 先行提出物の要旨（なし（火曜は先頭。前ラウンドがあれば前ラウンドの `40_諸葛亮_統合_C案.md` の要旨））：各400字以内に圧縮。原文はファイル名で参照させる
   - `05_現場の声.md` があれば原文（長い場合は前半2,000字＋「以下略、原文はファイル参照」）
   - `00_軍令状.md` §5「劉備の前回の言葉」のうち自分宛て
   - 末尾に「発言の型：【結論】【根拠】【懸念と対案】【劉備への一言】の4見出し。800〜1,500字。」
3. Chrome MCP で常設会話URLを開く。ログイン画面・別ページに飛んだら `/Volumes/Cloud_Drive/Google_Drive_My_Drive/AtoZ_Cowork/Documents/AI会議/合議2.0/_alerts/YYYY-MM-DD_baryo_login.md`（症状とスクリーンショット名）を書き、手順8の欠席処理へ。
4. 入力欄を `triple_click → cmd+a → Delete` でクリア。軍令状を投入する。日本語は `execCommand('insertText')` ＋ `InputEvent` 発火で入れる（type は IME で崩れる）。CDP タイムアウトが出ても、スクリーンショットで入力済みなら進む。
5. 送信ボタンを `find` で特定し **明示的に click**（Enter は改行になる）。送信後にスクリーンショットで「入力欄が空」「新しい応答が始まった」を確認。未送信なら手順4から再試行。
6. `wait` 10秒×4〜6回。応答の停止を確認。応答を **上から順に** 全文取得（DOM が取れるなら DOM、無理ならスクロール＋スクリーンショット。中央部の見落としに注意）。
7. 4見出しの有無を検査。欠けていれば「【〇〇】が抜けています。その見出しだけ答えてください」と1回だけ補充投入し、応答を末尾に結合する。
8. 保存：``10_馬良_調査.md`` を templates の意見書ヘッダ付きで書く（経路 `chrome_mcp`、モデル/版は画面表示から。不明なら unknown）。`_status.json` の `responses.baryo` を `{"file": "...", "at": ISO8601, "status": "done", "relay": "chrome_mcp"}` に更新。
   失敗（再試行後も応答が得られない）なら ``10_馬良_欠席.md`` に理由とスクリーンショット名を書き、`responses.baryo.status` を `absent` にする。会議は止めない。
9. 複数議題がある場合は、`type=urgent` → 発行が古い順に処理する。1議題ごとに手順2〜8を繰り返す（会話は同じ常設会話で続けてよい）。

## 4. サイト固有の注意（perplexity.ai）
- Space「AtoZ合議_馬良」を使う。出典リンクは本文中の番号と URL を両方保存する。
- 「Pro」等の検索モード切替には触らない。

## 5. 終了
- セッションサマリーを書く（共通ルール）。
- `_alerts/` に自分が書いた警報があれば、サマリーの先頭に「⚠ 警報あり」と記す。
