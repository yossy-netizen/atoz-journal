# CV Rider 変更履歴

日付は UTC。各項目に「ユーザーから見える影響」と「検証」を書く。

## 0.2.1 — 2026-09-21

### 追加
- **ワンクリック配布**: CI が `push` のたびに GitHub Releases の rolling pre-release `cvrider-latest` を更新。固定リンク
  https://github.com/yossy-netizen/atoz-journal/releases/download/cvrider-latest/cvrider-macos.zip からブラウザで直接ダウンロードできる（Actions のログイン画面を経由しない）。
- **ダブルクリックでインストール**: zip に `Install CV Rider.command` を同梱。ターミナル操作なしで AU / VST3 の導入、隔離解除、署名、`auval` まで実行。
- **Logic Pro 向け導入手順** `docs/logic-setup.md`（Mac Studio M2 / Sequoia 想定。ダウンロード場所、Gatekeeper の通し方、プラグインマネージャーでの再スキャン、最初の音出し、PDC の確認、アンインストール）。zip 内にも `README-INSTALL.txt` を同梱。

### 修正
- **配布 zip で実行ビットが落ちる問題**: Actions の Artifact 圧縮は実行権限を保持しないため、展開後の AU が読み込めない可能性があった。`ditto` で zip を作るよう変更し、`install-mac.sh` でも実行ビットを復元するようにした。

### 検証
- Linux CI は変更なし（C++ / Web / JUCE + pluginval）。macOS ジョブで zip 生成と Release 公開を追加。

## 0.2.0 — 2026-09-20

### 追加
- **専用エディタ**（JUCE 版）: 母音 / 子音 / 検出器 / 出力のノブ群、子音確率バー、ゲインとレベルのスコープ、プリセット選択。
- **ファクトリープリセット** 7 種（Default / Lead Vocal / Gentle / De-ess Only / Clarity / Breathy / Narration）。JUCE 版は DAW のプログラムとしても見える。Web 版にも同じものを搭載。
- **Web 版の WAV 書き出し**（24bit、ルックアヘッド分の遅れを補正、ファイル自身のサンプルレートを維持）。
- **macOS ビルドパイプライン**: ユニバーサル（arm64 + x86_64）の AU / VST3 / Standalone、`build-mac.sh`・`install-mac.sh`、CI での `auval` と pluginval、成果物 `cvrider-macos` のダウンロード。
- **フォネーム風テスト**（`test_phonemes.cpp`）: フォルマント合成の母音（男声 / 女声）、歯擦音、弱い摩擦音、破裂音、息混じりの母音で分類器を検証。
- ドキュメント一式（本ファイル、`manual.md`、`guide-for-everyone.md`、`background.md`）と作業ルール（リポジトリ直下の `CLAUDE.md`）。

### 変更（音が変わるもの）
- **子音検出中は母音用レベル検出器を止める**ようにした。以前は大きな「s」の直後 150 ms ほど母音レベルを高く見積もり、直後の母音の持ち上げが 3 dB ほど足りなかった。
- **起動時のゲインランプを修正**: 再生 / バウンス開始直後の約 50 ms のレベルがずれていた（スムーザーが古い値から動き出していた）。
- **バイパス / モニター切替のクリック**をなくした（最終ゲインに 1 ms のスムーザー）。
- 検出器入口に **DC ブロッカー**（約 20 Hz）。DC オフセットのある録音で子音が埋もれなくなった。
- Trim / Output の変更は 10 ms で滑らかに追従（オートメーションでクリックしない）。

### 修正
- **ホストのバイパスと状態復元**: JUCE ラッパーが自動追加するバイパスパラメータが保存状態に含まれず、pluginval の状態復元テストが乱数シード次第で失敗していた。プラグイン自身の Bypass をホストのバイパスとして公開するよう修正。DAW のバイパスボタンもクリックなしで効くようになった。
- `M_PI` 依存を除去（Windows / MSVC でビルド可能に）。
- Web 書き出しがデバイスのサンプルレートに変換されていた問題、RIFF の奇数長チャンクのパディング。
- デノーマル対策（エンベロープとフィルタ状態）。

### 検証
- C++ 挙動テスト 90 項目 + フォネームテスト 60 項目（44.1 / 48 / 96 kHz）、`-Werror`。
- Web: DSP 9 件 + UI 15 件（headless Chromium）。
- JUCE: Linux / macOS ビルド警告なし、pluginval strictness 10 SUCCESS（AU / VST3）、`auval` 合格。

## 0.1.0 — 2026-09-20

初版。DSP コア（`CVRider.h`）、JUCE ラッパー（汎用エディタ）、Web Audio 版デモ、挙動テスト。
