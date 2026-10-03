# リポジトリのルール

## pitch-trace（PitchTrace）を改良するとき

機能や挙動を変えたら、同じコミットで必ず次を更新する。

1. `pitch-trace/docs/MANUAL.md` … 詳細マニュアル（全コマンド・全オプション・仕様）
2. `pitch-trace/docs/GUIDE_FOR_EVERYONE.md` … スタッフや中学生でも分かる噛み砕いた解説
3. `pitch-trace/docs/BACKGROUND.md` … 使用に必要な周辺知識（音楽・MIDI・音声解析・統計・操作）
4. `pitch-trace/docs/MAC_SETUP.md` … Mac でのセットアップと DAW 連携（該当する変更のとき）
5. `notes/pitch-trace/CONCEPT.md` … 設計上の判断と採否

コミット前に `cd pitch-trace && python -m pytest -q` と `pitchtrace eval --all` を実行し、
往復評価（音符の recall / precision、ビブラートのレート誤差、イントネーション誤差）が
悪化していないことを確認する。`tests/test_docs.py` がマニュアルとコマンドの食い違いを検出する。

`pitch-trace/docs/feedback/` は実機（Mac mini / Mac Studio）側の作業者が書く場所なので、
開発側からは書き込まない。同じブランチを共有しても内容が衝突しないようにするための取り決め。
実機側への依頼内容は `pitch-trace/docs/HANDOFF.md` にまとめる。

文書は日本語で書く。専門用語を初出で使うときは一言の説明を添える。

## サイト（AtoZ Sound Journal）

`src/articles/*.md` が記事の正本、`tools/build.py` が `docs/` を生成する。
`notes/` と `pitch-trace/` はビルド対象外。
