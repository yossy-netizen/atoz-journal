# CV Rider — 子音 / 母音を別々にライドする Vocal Rider 系プラグイン

ボーカルトラックを **子音（無声音・摩擦音・破裂音）** と **母音（有声音）** にリアルタイム分類し、
それぞれ独立したターゲット・レンジ・速度で自動フェーダーライドを行うプラグインです。
Waves Vocal Rider のような「ゲインライド」を、歯擦音だけ抑える / 子音だけ持ち上げるといった
使い分けができるように拡張したものです。

```
plugin/
├── cpp/            DSP コア（ヘッダのみ・依存なし・C++17）と挙動テスト
│   ├── CVRider.h
│   ├── Presets.h
│   └── test/（test_cvrider.cpp, test_phonemes.cpp, test_util.h）
├── juce/           DAW 用プラグイン（VST3 / AU / Standalone、JUCE 8 + CMake）
├── web/            ブラウザ版デモ（AudioWorklet 移植 + UI + WAV 書き出し）と Playwright テスト
├── docs/           マニュアル・説明資料・周辺知識・変更履歴
└── README.md
```

CI（`.github/workflows/plugin-tests.yml`）で C++ テスト、Web テスト、JUCE の Linux ビルドが `plugin/` 変更時に走ります。

DSP コアは `cpp/CVRider.h` が正本で、JUCE 版は薄いラッパー、Web 版は同じ信号処理を JS に移植したものです。

**ドキュメント**（`docs/`）

| 読者 | ファイル |
|---|---|
| エンジニア・上級ユーザー | [docs/manual.md](docs/manual.md) — 詳細マニュアル |
| スタッフ・生徒（中学生でも分かる） | [docs/guide-for-everyone.md](docs/guide-for-everyone.md) — 噛み砕いた説明 |
| 使う人全員 | [docs/background.md](docs/background.md) — 周辺知識（dB、子音と母音、ライダーとコンプ、レイテンシ、AU / VST3） |
| Logic Pro で使う人 | [docs/logic-setup.md](docs/logic-setup.md) — ダウンロードから最初の音出しまで |
| 全員 | [docs/CHANGELOG.md](docs/CHANGELOG.md) — 変更履歴 |

## 信号処理の仕組み

```
in ──┬─► ルックアヘッド遅延 ─────────────────────────────► × gain ─► out
     │
     └─► 検出器（モノミックス）
           ├─ HP バンド (Split Freq) ─► hf エネルギー ─┐
           ├─ 全帯域 ─────────────────► 全エネルギー ──┴─► 帯域比 ─────┐
           ├─ HP バンドの fast/slow エンベロープ ─► トランジェント ──┴─► c（子音確率 0..1）
           ├─ 遅い RMS (40 ms) ─► 母音ライダー  gv = clamp(TargetV − Lv, ±RangeV) + TrimV
           └─ 速い RMS  (5 ms) ─► 子音ライダー  gc = clamp(TargetC − Lc, ±RangeC) + TrimC

gain(dB) = c·gc + (1 − c)·gv + Output
```

- **子音判定**: HP バンド（既定 4 kHz）と全帯域のエネルギー比を使います。母音は −20〜−30 dB、
  サ行などの歯擦音はほぼ 0 dB になるので、しきい値（既定 −9 dB、Sensitivity で移動）を挟んだ
  smoothstep で 0..1 に写像します。タ行・カ行の破裂音は HP バンド内のトランジェント検出で補います。
- **2 本のライダーが並走**: 母音側は 40 ms の RMS でゆっくり、子音側は 5 ms の RMS で素早く追従します。
  子音が検出されている間、母音側のゲインは **ホールド** されるので、大きな「s」が母音のゲインを
  引きずり下ろすことはありません。
- **クロスフェード**: 最終ゲインは c で 2 本のゲインを dB 領域で混ぜたものです。
- **Idle**: 入力が Idle Threshold を下回るとどちらのゲインも 0 dB に戻り、ノイズフロアを持ち上げません。
- **ルックアヘッド**: 音声側だけを最大 10 ms 遅らせ、検出器は遅延前の信号を見るので、子音の頭が
  削れる前にゲインが動けます（その分のレイテンシをホストに報告します）。
- **細部**: 検出器の入口に DC ブロッカー（約 20 Hz）を置き、DC オフセットで子音が埋もれないようにしています。
  Trim / Output の変更は約 10 ms で滑らかに追従するのでオートメーションでクリックしません。
  エンベロープにはデノーマル対策の微小値を足しています。

## パラメータ

| グループ | パラメータ | 既定値 | 説明 |
|---|---|---|---|
| Vowel | Target | −18 dB | 母音をこのレベルに近づける |
| | Range | 6 dB | 母音ライダーが動かせる最大 ± ゲイン |
| | Attack / Release | 60 / 300 ms | ゲインが下がる / 上がる速さ |
| | Trim | 0 dB | 母音だけに掛かる固定オフセット |
| Consonant | Target | −24 dB | 子音をこのレベルに近づける |
| | Range | 6 dB | 子音ライダーが動かせる最大 ± ゲイン |
| | Attack / Release | 2 / 40 ms | 同上（子音用なので速い） |
| | Trim | 0 dB | 子音だけに掛かる固定オフセット（ディエッサー的に使える） |
| Detector | Sensitivity | 0 dB | + で子音と判定されやすくなる |
| | Split Freq | 4000 Hz | 子音バンドの HP カットオフ |
| | Idle Threshold | −50 dB | これ以下では両ライダーが 0 dB に戻る |
| | Lookahead | 3 ms | 音声側の遅延（= レイテンシ） |
| Global | Output | 0 dB | 出力トリム |
| | Monitor | Off | Consonants / Vowels で判定結果だけをソロ試聴 |
| | Bypass | Off | |

### 使い方の目安

1. **Monitor = Consonants** にして、Sensitivity と Split Freq を「サ行・タ行・ハ行だけが聞こえる」ところに合わせる。
2. Monitor を戻し、Vowel Target をボーカルの狙い（例 −18 dB）、Consonant Target をその 4〜8 dB 下に置く。
3. 歯擦音が耳障りなら Consonant Trim を下げる。子音が埋もれる歌い手なら上げる。母音のライドには影響しない。
4. 子音の頭が削れるなら Lookahead を増やす。

## ビルドと実行

### DSP コアのテスト（依存なし）

```bash
cd plugin/cpp
g++ -std=c++17 -O2 -I. test/test_cvrider.cpp -o test_cvrider && ./test_cvrider
```

合成信号（倍音トーン = 母音、白色雑音 = 子音）で、分類・各ライダーの到達レベル・トリム・Idle・
ルックアヘッド遅延・モニターモード・ステレオ一致・DC オフセット耐性・パラメータ変更時のクリック有無を、
44.1 / 48 / 96 kHz の各サンプルレートで検証します（26 項目 × 3）。

### DAW 用プラグイン（JUCE）

```bash
cd plugin/juce
cmake -B build -DCMAKE_BUILD_TYPE=Release      # JUCE 8.0.4 を自動取得
cmake --build build --config Release
```

- 生成物: `build/CVRider_artefacts/Release/VST3/CV Rider.vst3`（macOS では AU も）、Standalone アプリ
- 手元に JUCE がある場合は `-DJUCE_DIR=/path/to/JUCE` を指定
- Linux では `libasound2-dev libxrandr-dev libxinerama-dev libxcursor-dev libxext-dev libfreetype-dev libfontconfig-dev` が必要
- GUI は専用エディタ（母音 / 子音 / 検出器 / 出力のノブ群、子音確率バー、ゲイン・レベルのスコープ）

#### macOS（Mac mini M4 でのテスト運用 → Mac Studio M2 での本番使用）

**A. ビルド済みを使う（ビルド環境不要）** — 詳細は [docs/logic-setup.md](docs/logic-setup.md)

1. https://github.com/yossy-netizen/atoz-journal/releases/download/cvrider-latest/cvrider-macos.zip をダウンロードして展開
2. `Install CV Rider.command` をダブルクリック（AU / VST3 を `~/Library/Audio/Plug-Ins/` にコピーし、隔離属性を外してアドホック署名し、`auval` で検証）
3. DAW を再起動してプラグインを再スキャン（Logic は自動、Cubase / Studio One は設定から）

**B. Mac 上でビルドする**

```bash
xcode-select --install          # 初回のみ
brew install cmake              # 初回のみ
cd plugin/juce && ./build-mac.sh
```

`build-mac.sh` は AU + VST3 + Standalone をユニバーサル（arm64 + x86_64、macOS 11 以降）でビルドし、
アドホック署名してユーザーのプラグインフォルダにインストール、`auval` を実行します。

**運用メモ**

- CI（`macos-latest` = Apple Silicon）で毎回 `auval -v aufx Cvrd AtoZ` と pluginval（strictness 10）を AU / VST3 の両方に通しています。
- Developer ID 署名 / 公証はしていないので、他の Mac に配る場合も `install-mac.sh` の手順（隔離属性の除去 + アドホック署名）が必要です。
- ルックアヘッド（既定 3 ms）分のレイテンシをホストに報告するので、DAW の自動遅延補償が効きます。
- 本番投入の前に、Mac mini 側で以下を確認することを推奨します: AU / VST3 の両方でプロジェクト保存→再読込後にパラメータが復元されること、44.1 / 48 / 96 kHz、バウンス（オフラインレンダリング）の結果がリアルタイム再生と一致すること。

### ブラウザ版デモ

```bash
cd plugin/web
python3 -m http.server 8080     # AudioWorklet は file:// では動かないため HTTP で
# → http://localhost:8080/
```

ファイルを読み込む / マイク入力 / 内蔵テスト信号のいずれかで動作を確認できます。
「書き出し (WAV 24bit)」で、現在のパラメータで処理した結果をルックアヘッド分の遅れを補正した状態で
ダウンロードできます（DAW に貼り戻して比較する用途）。WAV / AIFF はファイル自身のサンプルレートで
デコード・書き出しされます（それ以外の形式はブラウザの再生レートになります）。

テスト（Playwright + Chromium が必要）:

```bash
node plugin/web/test/run.mjs    # OfflineAudioContext で DSP の挙動を検証
node plugin/web/test/ui.mjs     # ページの再生・メーター・書き出しのスモークテスト
```

## 今後の拡張候補

- 有声/無声の判定精度向上（自己相関によるピッチ有無、ZCR の併用）
- 子音種別（歯擦音 / 破裂音 / 気音）ごとのターゲット
- サイドチェイン（オケ）レベルに追従する Music Sensitivity
- 専用 GUI とプリセット
