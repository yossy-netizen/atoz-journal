# atoz-journal — 作業ルール

## plugin/（CV Rider）を変更するときの必須ルール

CV Rider（子音 / 母音ライダー）に機能追加・挙動変更・パラメータ変更を行うときは、コードと同じコミットで
**必ず以下の 4 つのドキュメントを更新する**。更新がない場合も「変更なし」と判断した理由を PR に書く。

| ファイル | 読者 | 内容 |
|---|---|---|
| `plugin/docs/manual.md` | エンジニア・上級ユーザー | 詳細マニュアル。全パラメータの意味・範囲・既定値、信号処理の仕組み、導入手順、トラブルシューティング、仕様 |
| `plugin/docs/guide-for-everyone.md` | スタッフ・生徒（中学生でも分かる） | 噛み砕いた説明。何をする道具か、たとえ話、3 ステップの使い方、困ったとき |
| `plugin/docs/background.md` | 使う人全員 | 使用に必要な周辺知識。dB / RMS、子音と母音の音響、ディエッサー、レイテンシ、AU / VST3 など |
| `plugin/docs/CHANGELOG.md` | 全員 | 変更履歴。日付・変更点・ユーザーから見える影響・検証結果 |

書き方の基準:
- `guide-for-everyone.md` は専門用語を使うたびに一言で言い換える（例: 「dB（音の大きさの単位）」）。
- 新しいパラメータやプリセットは 4 つすべてに反映する（manual: 仕様、guide: 使いどころ、background: 必要なら用語、CHANGELOG: 変更点）。
- スクリーンショットや図を差し替えたら `plugin/docs/` 配下に置く。

## テストと検証

- C++: `plugin/cpp/test/test_cvrider.cpp` と `test_phonemes.cpp` を `-Werror` でビルドして実行する。
- Web: `node plugin/web/test/run.mjs` と `node plugin/web/test/ui.mjs`。
- JUCE: ビルド後に pluginval（strictness 10）を通す。CI（`.github/workflows/plugin-tests.yml`）でも同じことが走る。
- DSP の変更は `plugin/cpp/CVRider.h`（正本）と `plugin/web/cv-rider-processor.js`（移植）の両方に入れる。プリセットは `plugin/cpp/Presets.h` と `plugin/web/index.html` の `PRESETS` の両方。

## サイト（docs/）

`docs/` は GitHub Pages の公開ルートで `tools/build.py` が生成する。プラグインの成果物やドキュメントは `docs/` に置かない。
