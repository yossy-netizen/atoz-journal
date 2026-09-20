# CV Rider — 子音 / 母音を別々にライドする Vocal Rider 系プラグイン

ボーカルトラックを **子音（無声音・摩擦音・破裂音）** と **母音（有声音）** にリアルタイム分類し、
それぞれ独立したターゲット・レンジ・速度で自動フェーダーライドを行うプラグインです。
Waves Vocal Rider のような「ゲインライド」を、歯擦音だけ抑える / 子音だけ持ち上げるといった
使い分けができるように拡張したものです。

```
plugin/
├── cpp/            DSP コア（ヘッダのみ・依存なし・C++17）と挙動テスト
│   ├── CVRider.h
│   └── test/test_cvrider.cpp
├── juce/           DAW 用プラグイン（VST3 / AU / Standalone、JUCE 8 + CMake）
├── web/            ブラウザ版デモ（AudioWorklet 移植 + UI）と Playwright テスト
└── README.md
```

DSP コアは `cpp/CVRider.h` が正本で、JUCE 版は薄いラッパー、Web 版は同じ信号処理を JS に移植したものです。

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
ルックアヘッド遅延・モニターモードを検証します。

### DAW 用プラグイン（JUCE）

```bash
cd plugin/juce
cmake -B build -DCMAKE_BUILD_TYPE=Release      # JUCE 8.0.4 を自動取得
cmake --build build --config Release
```

- 生成物: `build/CVRider_artefacts/Release/VST3/CV Rider.vst3`（macOS では AU も）、Standalone アプリ
- 手元に JUCE がある場合は `-DJUCE_DIR=/path/to/JUCE` を指定
- Linux では `libasound2-dev libxrandr-dev libxinerama-dev libxcursor-dev libxext-dev libfreetype-dev libfontconfig-dev` が必要
- GUI は JUCE の汎用パラメータエディタ + 子音確率 / ゲインの簡易メーターです

### ブラウザ版デモ

```bash
cd plugin/web
python3 -m http.server 8080     # AudioWorklet は file:// では動かないため HTTP で
# → http://localhost:8080/
```

ファイルを読み込む / マイク入力 / 内蔵テスト信号のいずれかで動作を確認できます。
オフラインレンダリングによるテスト:

```bash
node plugin/web/test/run.mjs    # Playwright + Chromium が必要
```

## 今後の拡張候補

- 有声/無声の判定精度向上（自己相関によるピッチ有無、ZCR の併用）
- 子音種別（歯擦音 / 破裂音 / 気音）ごとのターゲット
- サイドチェイン（オケ）レベルに追従する Music Sensitivity
- 専用 GUI とプリセット
