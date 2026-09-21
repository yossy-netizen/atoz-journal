# PitchTrace 詳細マニュアル

対象読者: 実際に操作するスタッフ・制作者。用語の意味が分からないときは
[`BACKGROUND.md`（周辺知識）](BACKGROUND.md)、全体像を掴みたいときは
[`GUIDE_FOR_EVERYONE.md`（やさしい解説）](GUIDE_FOR_EVERYONE.md) を先に読んでください。

このマニュアルはコマンドとオプションの説明を網羅しています。`tests/test_docs.py` が、
すべてのサブコマンドとオプション名がこのファイルに載っていることを自動で確認します。

---

## 1. PitchTrace とは

打ち込み（MIDI）の音程は「点」ですが、生楽器の演奏の音程は「線」です。発音の瞬間のしゃくり、
前の音からの滑らかな移行、ビブラート、ゆっくりした揺れ、音の終わりの落ち込み。
PitchTrace はこれらを**楽器・奏法ごとの統計（プロファイル）**または**実際の録音（参照演奏）**から
再現し、MIDI にピッチベンドと音量表情（CC11）として書き加えます。

```
[MIDI]  ──render──▶  [表情付き MIDI]  ──▶ DAW の音源で再生
[録音]  ──analyze──▶ [IGF / プロファイル]
[録音] + [MIDI] ──transfer──▶ [表情付き MIDI]   … 参照演奏の転写
[DAW] ⇄ live ⇄ [音源]                          … リアルタイム
```

構成（`pitchtrace/` パッケージ）:

| モジュール | 役割 |
|---|---|
| `profile.py` | 楽器 × スタイルのパラメータ分布（JSON）。`profiles/*.json` が組み込み |
| `notes.py` | 音符列、MIDI 読み込み、テンポマップ、フレーズ分割 |
| `key.py` | 調の判定と度数バイアス |
| `generate.py` | 音符列 + プロファイル → セント偏差カーブ・ダイナミクス・タイミング |
| `render_midi.py` | カーブ → ピッチベンド / MPE / CC 付き MIDI |
| `f0.py` | F0（基本周波数）抽出（YIN 内蔵、pYIN 任意） |
| `analyze.py` | 音声 → ノート分割 → 成分推定 → プロファイル |
| `igf.py` | IGF（中間表現）の読み書き |
| `transfer.py` | 参照演奏の転写 |
| `realtime.py` | リアルタイム処理と仮想 MIDI ポート |
| `evaluate.py` | 客観評価（往復精度、IGF 比較） |
| `plot.py` | 可視化 |
| `synth.py` | 試聴用の簡易シンセ、WAV 読み書き |
| `doctor.py` | 環境診断（何が入っていて何が足りないか） |
| `bendcheck.py` | ベンドレンジ合わせの検査 MIDI |
| `cli.py` | コマンドライン |

---

## 2. インストール

### 2.1 Mac（Apple Silicon）

```bash
cd atoz-journal/pitch-trace
bash scripts/setup_mac.sh --logic     # Logic Pro で使うならこれ
source .venv/bin/activate
```

`scripts/setup_mac.sh` は Python 3.10 以上を探し、仮想環境 `.venv` を作り、パッケージをインストールし、
テストを実行し、`demo_out/` に試聴用ファイルを作り、最後に `pitchtrace doctor`（環境診断）を実行します。

| 引数 | 効果 |
|---|---|
| なし | インストール・テスト・デモ生成・診断 |
| `--live` | リアルタイム連携用の `python-rtmidi` も入れる |
| `--logic` | `--live` に加えて `logic_start/` に Logic 用の確認ファイル 3 つを作り、手順を表示する |
| `--no-test` | テストを省く（2 回目以降、急ぐとき） |
| `--help` | 使い方を表示 |

`python-rtmidi` のインストールに失敗した場合も中断せず、警告を出して続行します（オフラインの
`render` / `bendcheck` / `analyze` は rtmidi 不要のため）。この場合 `live` と `ports` だけが使えません。

途中で止まったときは `pitchtrace doctor` の出力を見ます。詳しい手順と DAW の設定は
[`MAC_SETUP.md`](MAC_SETUP.md)。Logic Pro については同ファイルの「Logic Pro で使う」。

### 2.2 手動（Mac / Linux 共通）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,live,viz]"
python -m pytest -q
```

| 追加パッケージ（extras） | 内容 | 必要なコマンド |
|---|---|---|
| `dev` | pytest | テスト |
| `live` | python-rtmidi | `live`, `ports` |
| `viz` | matplotlib | `plot` |
| `analysis` | librosa | `analyze --detector pyin` |

必須依存は numpy と mido だけです。

---

## 3. 基本概念

### 3.1 セント偏差カーブ

音符ごとに「目標音からのずれ（セント）」を 5 ms 刻み（`hop_ms`）で持ちます。
100 セント = 半音。ピッチベンドに変換するときにベンドレンジで割ります。

### 3.2 7 つの成分

| 成分 | 意味 | 主なパラメータ |
|---|---|---|
| intonation | 音ごとの中心ピッチのずれ（ランダム成分 + 調に対する度数バイアス） | `intonation.cents`, `key_bias_amount`, `major/minor_bias_cents` |
| transition | 前の音からの滑り（ポルタメント） | `transition.prob`, `duration_ms`（20→80% 時間）, `overshoot_cents` |
| attack | 発音直後のしゃくり・オーバーシュート | `attack.prob`, `offset_cents`, `settle_ms` |
| vibrato | 周期的な揺れ | `vibrato.rate_hz`, `depth_cents`（片側振幅）, `onset_ms`, `ramp_ms`, `center_offset` |
| drift | ゆっくりした不規則な揺れ | `drift.cents`, `cutoff_hz` |
| release | 音の終わりの落ち込み | `release.prob`, `cents`, `duration_ms` |
| jitter | 微細なざらつき | `jitter.cents` |

ピッチ以外に **dynamics**（音量表情、CC11）と **timing**（前後のずれ、オフライン専用）があります。

### 3.3 プロファイル

楽器 × スタイルごとに、各パラメータの分布（平均・標準偏差・最小・最大）を JSON で持ちます。
音符ごとにこの分布からサンプルし、音程差・音長・レガート・フレーズ内の位置で条件付けします。
組み込み: `violin_classical` `cello_classical` `oboe_classical` `alto_sax_classical` `alto_sax_jazz`、
比較用 `random_humanize`。`--profile` には組み込み名か JSON ファイルのパスを渡せます。
JSON の全キーは §7。

### 3.4 IGF（Instrument Gesture Format）

録音を解析した結果を、音符ごとに「生カーブ + 意味パラメータ + 前後関係 + 信頼度」で保存する
中間表現（JSON）。`analyze --igf` で作り、`transfer` と `plot` と `eval` が読みます。仕様は §8。

### 3.5 量（amount）

`--amount` が全体の量（0 = 静止ピッチ、1 = プロファイル通り、1.5 = 誇張）。
`--amount-vibrato` などで成分ごとに変えられます。成分名: `intonation` `transition` `attack`
`vibrato` `drift` `release` `jitter` `dynamics` `timing`。

---

## 4. コマンドリファレンス

すべて `pitchtrace <サブコマンド> ...`（`python -m pitchtrace ...` でも同じ）。
`pitchtrace <サブコマンド> --help` で最新のヘルプが出ます。

### 4.1 共通オプション（render / dump / demo / transfer / plot / live）

| オプション | 既定 | 説明 |
|---|---|---|
| `--profile`, `-p` | `violin_classical`（transfer は参照の楽器から自動） | 組み込み名または JSON パス |
| `--seed` | 0 | 乱数の種。同じ種なら同じ結果。気に入らなければ変える |
| `--amount` | 1.0 | 全体の量 |
| `--amount-intonation` `--amount-transition` `--amount-attack` `--amount-vibrato` `--amount-drift` `--amount-release` `--amount-jitter` `--amount-dynamics` `--amount-timing` | 1.0 | 成分ごとの量 |
| `--mode` | `single` | `single`: 1 チャンネルのピッチベンド（単旋律に切り詰め）/ `mpe`: ノートごとにチャンネルを回す MPE |
| `--bend-range` | 12 | ベンドレンジ（半音）。**音源側と必ず揃える** |
| `--legato-overlap-ms` | 0 | single モードで前の音を残す時間（レガート検出に重なりが要る音源向け） |
| `--no-lookahead` | off | 次の音を見ない（リアルタイム動作の模擬） |
| `--max-events-per-s` | なし | ベンド・CC の最大密度（イベント数を減らしたいとき） |
| `--vibrato-lane` | プロファイル通り | `bend`（ピッチベンドに含める）/ `cc`（ビブラートだけ CC1 に分離） |
| `--key` | 自動判定 | 調（`C`, `F#`, `Bb`, `Am` など）。`live` では `auto` で直近の音符から推定 |
| `--no-key-bias` | off | 調に対する度数バイアスを付けない |
| `--no-dynamics` | off | CC11 を出さない |
| `--no-timing` | off | マイクロタイミングを適用しない |
| `--dyn-cc` | 11 | ダイナミクスの CC 番号（CC1 で受ける音源なら `--dyn-cc 1`） |
| `--tempo` | 入力から継承 | 出力テンポを固定（BPM） |

### 4.2 `profiles`

組み込みプロファイルの一覧。

### 4.3 `info in.mid`

MIDI ファイルのトラック一覧（番号、音符数、チャンネル、音域、開始・終了秒、名前、テンポチェンジ数）。
`render --track` の番号を調べるのに使います。

### 4.4 `render in.mid out.mid`

MIDI に表情を付けます。

| オプション | 説明 |
|---|---|
| `--track N` | 処理するトラック（0 始まり）。指定すると**他のトラックとテンポマップ・拍子を保持したまま**そのトラックだけ差し替える |
| `--channel N` | 処理する MIDI チャンネル（0 始まり） |
| `--only-track` | `--track` 指定時に他トラックを捨てて単独ファイルにする |
| 共通オプション | §4.1 |

出力には、ベンドレンジを設定する RPN、ピッチベンド、CC11、ノートが書かれます。
表示される `key G` は判定した調です。

### 4.5 `dump in.mid out.csv`

生成したカーブを成分ごとに CSV へ（列: time_s, note, cents, intonation, transition, attack, vibrato,
drift, release, jitter, dyn）。表計算で確認したいときに。`--track` `--channel` と共通オプション。

### 4.6 `analyze in.wav`

ソロ録音（無伴奏・単旋律）を解析します。出力は 2 種類で、どちらか一方以上を指定します。

| オプション | 説明 |
|---|---|
| `-o`, `--output prof.json` | プロファイル（統計）。そのまま `--profile` に渡せる |
| `--igf ref.igf.json` | IGF（音符ごとのジェスチャー + 生カーブ） |
| `--base NAME` | 推定できない項目の既定値に使う組み込みプロファイル |
| `--name` `--instrument` `--style` | 出力のメタ情報 |
| `--detector yin|pyin` | F0 検出器。`pyin` は librosa が必要 |
| `--tuning 442` | 基準ピッチ A4（Hz）。省略時は録音から推定 |
| `--no-octave-fix` | オクターブ誤検出の補正をしない |
| `--hop-ms` | 解析の時間刻み（既定 5 ms） |
| `--fmin` `--fmax` | F0 の範囲（既定 55〜1500 Hz。チェロの最低音 C2 = 65 Hz を含む） |
| `--notes-json` | 音符ごとの推定値を JSON で書き出す |

入力は WAV（16/24/32bit PCM、モノラル推奨。ステレオは平均）。

### 4.7 `transfer reference target.mid out.mid`

参照演奏（WAV または IGF）のジェスチャーをターゲット MIDI へ転写します。

| オプション | 説明 |
|---|---|
| `reference` | WAV（その場で解析）または `.json`（IGF） |
| `--adapt param|raw` | `param`（既定）: 参照の意味パラメータを固定して再生成。`raw`: 生カーブを時間適応 |
| `--mapping positional|context` | `positional`（既定）: i 番目 → i 番目（参照が短ければ循環）。`context`: 音長・前後の音程差・レガート・音域が近い参照音符の上位 K からランダム |
| `--map 0,1,3,-` | 手動対応（参照 index 列。`-` は通常生成）または JSON ファイル |
| `--top-k` | `context` の候補数（既定 3） |
| `--track` `--channel` `--only-track` | render と同じ |
| `--instrument` | 参照の楽器名（WAV 入力時。既定プロファイルの選択にも使う） |
| `--detector` `--tuning` | 解析設定（WAV 入力時） |
| `--save-igf path` | 参照を解析した IGF を保存（次回から IGF を渡すと速い） |
| `--wav path` | 試聴用 WAV（簡易シンセ） |
| 共通オプション | §4.1 |

`raw` は遷移区間をターゲットの音程差でスケールし、アタック区間と末尾は元の時間を保ち、
サステインだけ切り詰め／クロスフェードで継ぎ足します（ビブラートのレートは変わりません）。
参照と音程差が大きく違う跳躍では警告を出します。

### 4.8 `demo out_dir`

内蔵フレーズ（または `--input in.mid`）から、静止ピッチ版とトレース版の WAV / MIDI を作ります。
`--blind` を付けると、静止 / `random_humanize` / プロファイル の 3 種を X/Y/Z にシャッフルした
WAV と、答え `blind_answer.json` を出します。

### 4.9 `eval`

客観評価。

| オプション | 説明 |
|---|---|
| `--profile NAME` | 往復評価（生成 → 合成 → 解析 → 真値と比較）するプロファイル |
| `--all` | 組み込みすべて |
| `--seeds N` `--notes N` | 試行回数と音符数 |
| `--igf A --igf2 B` | 2 つの IGF のパラメータ分布を比較（例: 参照と、転写結果を再解析したもの） |
| `--json path` | 結果を保存 |

出力の読み方: 音符の recall / precision（見つけた割合 / 余分に切らなかった割合）、
オンセット誤差、基準ピッチ推定、イントネーション誤差、ビブラートの検出率とレート誤差、
ポルタメントの検出率と時間比、アタック誤差、プロファイルの復元値。

### 4.10 `plot out.png`

可視化（matplotlib）。`--igf` で解析結果、`--midi` + `--profile` で生成カーブ。両方渡すと上下に並びます。
`--t0` `--t1` で時間範囲。`--track` `--channel` と共通オプション。

### 4.11 `ports`

MIDI ポート一覧（python-rtmidi が必要）。列挙は別プロセスで行うため、MIDI の初期化に失敗しても
異常終了せず、終了コード 1 とエラー文を返します。原因の詳細は `doctor` で調べてください。

### 4.12 `live`

仮想 MIDI ポートを作り、DAW からのノートにその場でピッチベンドとダイナミクスを付けて返します。

| オプション | 説明 |
|---|---|
| `--in NAME` | 入力ポート名（部分一致）。既定 `virtual` = `PitchTrace In` を作る |
| `--out NAME` | 出力ポート名。既定 `virtual` = `PitchTrace Out` を作る |
| `--in-channel N` | このチャンネルの入力だけ処理（0 始まり） |
| `--out-channel N` | single モードの出力チャンネル（0 始まり） |
| `--no-passthrough` | ノート以外のメッセージを通さない |
| `--verbose`, `-v` | 受信メッセージを表示 |
| `--key auto` | 直近の音符から調を推定して度数バイアスを付ける |
| 共通オプション | §4.1（`--no-timing` `--no-lookahead` `--tempo` は無効） |

制約: 次の音と音長を知らないので、フレーズ末のリリース、クライマックスの強調、マイクロタイミングは
付きません。ノートオン時の処理は 1 音あたり約 2 ms。Ctrl+C で終了（全ノートオフを送ります）。

### 4.13 `doctor`

環境診断。何が入っていて何が足りないか、DAW から PitchTrace が見える状態かを一覧にします。
各項目は `OK` / `注意` / `失敗` の 3 段階で、`注意` と `失敗` には必ず対処方法が付きます。

| オプション | 説明 |
|---|---|
| `--json path` | 診断結果を JSON で保存。離れた場所に相談するときはこれを貼る |
| `--no-midi` | MIDI ポートの確認を省く（DAW を起動していないときなど） |

終了コードは、必須項目（Python 3.10 以上・`pitchtrace` 本体・numpy・mido）がすべて通れば 0、
1 つでも失敗していれば 1。`注意` だけなら 0 です。`注意` のままでも `render` は使えます。

確認する項目:

| 分類 | 項目 |
|---|---|
| 必須 | OS とアーキテクチャ、Python のバージョン、仮想環境かどうか、`pitchtrace` 本体、numpy、mido、`pitchtrace` コマンドの場所 |
| 任意 | python-rtmidi（`live` / `ports`）、matplotlib（`plot`）、librosa（`analyze --detector pyin`） |
| MIDI | 入力ポート一覧、出力ポート一覧、IAC ドライバの有無、仮想ポートを実際に作れるか |

「仮想ポートを実際に作れるか」は、`PitchTrace Doctor` という CoreMIDI ポートを一瞬だけ作って閉じる
実地テストです。ここが `OK` なら、`pitchtrace live` の仮想ポートも Logic から見えます。

MIDI に触る 2 項目は**別プロセスで実行**します。RtMidi は CoreMIDI や ALSA の初期化に失敗したとき、
C++ の例外のままプロセスを異常終了させることがあり（`libc++abi: terminating due to unexpected
exception of type RtMidiError`）、Python の `try` / `except` では捕まえられないためです。
環境を診断するコマンドが、まさに診断したい壊れた環境で落ちては意味がないので隔離しています。
`ports` も同じ理由で別プロセス経由です。macOS では画面にログインしたセッションが必要なため、
SSH 越しや自動実行ではこの 2 項目が `注意` になることがあります。

### 4.14 `bendcheck out.mid`

ベンドレンジ合わせの検査 MIDI を作ります。音源側のベンドレンジが `--bend-range` と違っていると、
表情の量がそのまま音程の狂いになります。RPN 0 で通知はしていますが無視する音源が多いので、
最後は耳で確かめます。

| オプション | 説明 |
|---|---|
| `--bend-range N` | 確かめたいベンドレンジ（半音、既定 12） |
| `--note N` | 基準にする音の MIDI ノート番号（既定 60 = C4） |
| `--tempo BPM` | テンポ（既定 90） |
| `--channel N` | MIDI チャンネル（0 始まり） |

できる MIDI は 4 つの区間に分かれます（DAW のマーカーに `1`〜`4` として出ます。MIDI の
マーカーは latin-1 しか入らないため英数字です）。

| 区間 | 内容 | 正しいときの聞こえ方 |
|---|---|---|
| 1 | 基準の 2 音（`--note` と、その `--bend-range` 半音上）をベンドなしで鳴らす | 2 つの高さを覚えるための区間 |
| 2 | 下の音をベンド最大で上げ切る → 直後に上の音 | **2 音が同じ高さ**。低ければ音源のベンドレンジが小さい |
| 3 | 上の音をベンド最小で下げ切る → 直後に下の音 | **2 音が同じ高さ** |
| 4 | 下の音を 2 拍かけて連続的に上げる | 段差やざらつきがなく滑らか |

区間 2 が低く聞こえるなら音源側の値が小さすぎ、高く聞こえるなら大きすぎます。既定の 12 半音に
合わせられない音源では、代わりに `render --bend-range` を音源の値に合わせてください。

---

## 5. ワークフロー

### 5.1 MIDI に表情を付ける（一番基本）

```bash
pitchtrace render melody.mid melody_traced.mid --profile violin_classical --bend-range 12
```
DAW に読み込み、音源のベンドレンジを 12 に。エクスプレッションを CC11 に。

### 5.2 曲全体の MIDI から 1 トラックだけ

```bash
pitchtrace info song.mid
pitchtrace render song.mid song_traced.mid --track 2 --profile cello_classical
```

### 5.3 録音から自分のプロファイルを作る

```bash
pitchtrace analyze my_cello.wav -o my_cello.json --base cello_classical --igf my_cello.igf.json
pitchtrace plot check.png --igf my_cello.igf.json      # 解析が妥当か目で確認
pitchtrace render melody.mid out.mid --profile my_cello.json
```

### 5.4 参照演奏の転写

```bash
pitchtrace transfer my_cello.igf.json melody.mid out.mid --mapping context --wav preview.wav
pitchtrace transfer my_cello.igf.json melody.mid out_raw.mid --adapt raw
```

### 5.5 リアルタイム

```bash
pitchtrace live --profile alto_sax_jazz --key auto
```
DAW 側: メロディトラックの出力を `PitchTrace In`、音源トラックの入力を `PitchTrace Out`。

### 5.6 評価とブラインド比較

```bash
pitchtrace eval --all
pitchtrace demo out --profile cello_classical --blind
```

### 5.7 改良したときの確認

```bash
python -m pytest -q          # 単体テスト
pitchtrace eval --all        # 往復精度が落ちていないか
```

---

## 6. 音源側の設定

- **ベンドレンジ**: `--bend-range`（既定 12 半音）と同じ値を音源に設定する。RPN 0 で MIDI にも書いているが、無視する音源がある
- **ダイナミクス**: CC11（エクスプレッション）に割り当てる。CC1 で受ける音源なら `--dyn-cc 1`
- **ビブラート**: 録音に焼き込まれた音源（Kontakt 系の多く）では二重にかかる。音源のビブラートを切るか、`--vibrato-lane cc` で音源側のビブラート量を CC1 で動かす
- **MPE**: 対応音源（SWAM、Sample Modeling 等）では `--mode mpe`。重なった音も正しく扱える
- **レガート**: 重なりでレガートを検出する音源は `--legato-overlap-ms 20` 程度

---

## 7. プロファイル JSON 仕様

各分布は `{"mean": 平均, "std": 標準偏差, "min": 下限, "max": 上限}`。数値 1 つでも可（std 0）。

| セクション.キー | 単位 | 意味 |
|---|---|---|
| `name` `instrument` `style` `version` `source` | | メタ情報 |
| `hop_ms` | ms | カーブの時間刻み |
| `intonation.cents` | cent | 音ごとのランダムなずれ |
| `intonation.continuity` | 0–1 | 前の音のずれを引き継ぐ割合 |
| `intonation.key_bias_amount` | 倍率 | 度数バイアスの量 |
| `intonation.major_bias_cents` / `minor_bias_cents` | cent × 12 | 主音からの半音数ごとのバイアス |
| `transition.prob` | 0–1 | レガート時にポルタメントを付ける確率 |
| `transition.max_gap_ms` | ms | この隙間以下ならレガート |
| `transition.duration_ms` | ms | 進行率 20→80% の時間 |
| `transition.duration_per_semitone_ms` | ms | 音程差 1 半音あたりの加算 |
| `transition.sharpness` | | シグモイドの鋭さ |
| `transition.overshoot_cents` / `overshoot_settle_ms` | cent / ms | 行き過ぎとその収束 |
| `attack.prob` / `offset_cents` / `settle_ms` | | 非レガート時のしゃくり |
| `vibrato.prob` / `min_note_ms` | | 付ける確率 / 最低音長 |
| `vibrato.rate_hz` / `depth_cents` | Hz / cent | レート / 片側振幅 |
| `vibrato.onset_ms` / `ramp_ms` | ms | 開始までの時間 / 深さの立ち上がり |
| `vibrato.center_offset` | 比 | 中心のずれ（−1 = 目標音より完全に下側） |
| `vibrato.rate_wobble` / `depth_wobble` / `asymmetry` | | 揺らぎと非対称 |
| `vibrato.climax_gain` / `full_depth_at_ms` | | 山での倍率 / 深さが最大になる音長 |
| `drift.cents` / `cutoff_hz` | cent / Hz | ゆっくりした揺れの大きさ / 速さ |
| `release.prob` / `cents` / `duration_ms` / `phrase_end_gain` | | 音末の落ち込み |
| `jitter.cents` / `smooth_ms` | | 微細なざらつき |
| `dynamics.enabled` / `cc_number` | | CC11 を出すか / 番号 |
| `dynamics.base` / `velocity_weight` | 0–1 | 基準レベル / ベロシティの効き |
| `dynamics.attack_ms` / `attack_from` | ms / 比 | ふくらみの時間 / 開始レベル |
| `dynamics.sustain_slope` | /s | サステインの傾き（負で減衰） |
| `dynamics.release_ms` / `release_to` | ms / 比 | 音末の減衰 |
| `dynamics.phrase_arc` / `wobble` / `min` / `max` | | 山へのクレッシェンド / 揺らぎ / 範囲 |
| `timing.enabled` | | 適用するか（オフライン専用） |
| `timing.onset_ms` / `legato_lead_ms` / `phrase_first_delay_ms` / `detach_gap_ms` | ms | ずれ / レガート先行 / 先頭の遅れ / 非レガート音の短縮 |
| `output.vibrato_lane` / `cc_number` / `cc_full_depth_cents` | | ビブラートの出力先 / CC 番号 / CC=127 になる深さ |
| `stats` | | 解析由来の統計（生成には使わない） |

---

## 8. IGF 仕様（schema 0.1）

```
{
  "schema": "IGF", "schema_version": "0.1",
  "analyzer": {"name", "version", "pitch_detector", "hop_ms", "created_at"},
  "source": {"file", "sample_rate", "reference_tuning_hz", "duration_s"},
  "instrument", "style",
  "key": {"tonic": 0-11, "mode": "major|minor", "confidence"},
  "notes": [ {
    "id", "midi_note", "start_sec", "end_sec", "duration_sec",
    "pitch_center_cents",              # イントネーション（基準ピッチ差し引き後）
    "confidence",                      # 音符全体の F0 信頼度
    "context": {"previous_interval", "next_interval", "legato_in", "legato_out", "gap_before_sec", "gap_after_sec"},
    "attack": {"deviation_cents", "settlement_ms", "confidence"} | null,
    "transition_in": {"portamento", "duration_ms", "interval", "overshoot_cents", "start_sec", "end_sec"} | null,
    "sustain": {"drift_cents", "jitter_cents"},
    "vibrato": {"onset_ms", "mean_rate_hz", "mean_depth_cents", "center_offset", "ramp_ms"} | null,
    "release": {"cents"} | null,
    "dynamics": {"attack_ms", "attack_from", "sustain_slope", "release_to"} | null,
    "curve": {"time_sec": [...], "cents": [...], "confidence": [...], "raw_f0_hz": [...]}
  } ]
}
```

`curve.cents` は目標音（`midi_note`）からの偏差。`raw_f0_hz` は補正前の生 F0。
解析器が改良されたら、元の録音から作り直せるように `analyzer.version` を記録しています。

---

## 9. トラブルシューティング

まず `pitchtrace doctor` を実行してください。環境側の問題はここでほぼ切り分きます。

| 症状 | 原因と対処 |
|---|---|
| 音程が全体にずれる | ベンドレンジ不一致。`pitchtrace bendcheck` で確かめ、音源側を `--bend-range` の値に |
| インストールしたのに `pitchtrace` が見つからない | `source .venv/bin/activate` を忘れている。`doctor` が場所を教えます |
| ビブラートが二重 | 音源のビブラートを切る、または `--vibrato-lane cc` |
| 音が途切れる・重なる | 単旋律前提。和音があるなら `--mode mpe` か、トラックを分ける |
| `analyze` で音符が見つからない | 無音・ノイズ・伴奏入り。無伴奏の単旋律に。`--fmin` `--fmax` を楽器に合わせる |
| 解析の音高が 1 オクターブ違う | 既定の補正で直らなければ `plot` で確認。`--fmin` が高すぎないか |
| `ports` でポートが出ない | `pip install python-rtmidi`。Mac はターミナルの権限も確認 |
| `plot` が失敗 | `pip install matplotlib` |
| 同じ音の連打が 1 音になる | 音量の落ち込みで分割している。落ち込みが浅い演奏では分かれないことがある |
| 転写で「循環します」と出る | 参照とターゲットの音数が違う。`--mapping context` か `--map` で対応を指定 |

---

## 10. 既知の制限

- 対象は単旋律のみ。和音楽器は対象外
- 20 ms 未満のポルタメントは F0 抽出の時間分解能で段差と区別できない
- 発音直後 15〜20 ms は F0 が信頼できない。アタックの値は指数減衰で外挿している
- 基準ピッチの推定は短いフレーズでは ±10 セント程度ぶれる（30 秒以上で安定）
- ビブラートの開始が遅い奏法では 0.5 秒未満の音で検出しにくい
- リアルタイムでは次の音を知らないので、フレーズ末の表情とマイクロタイミングは付かない

---

## 11. 開発者向け

- テスト: `python -m pytest -q`（`tests/`）。往復評価の回帰ガードは `tests/test_evaluate.py`
- CI: `.github/workflows/pitch-trace.yml`（Ubuntu / macOS × Python 3.11 / 3.12）
- 改良時のルール（リポジトリ直下 `CLAUDE.md`）: 機能を変えたら必ず本マニュアル、
  `GUIDE_FOR_EVERYONE.md`、`BACKGROUND.md` を更新し、`pytest` と `pitchtrace eval --all` を通す
- 設計上の判断は `../../notes/pitch-trace/CONCEPT.md` に記録する
