# Mac でのセットアップと DAW 連携（テスト運用 → 本番）

対象: Mac mini M4（macOS Tahoe）でのテスト運用、Mac Studio M2（macOS Sequoia）での本番使用。
どちらも Apple Silicon なので手順は同じ。

## 1. インストール

```bash
git clone <このリポジトリ>
cd atoz-journal/pitch-trace
bash scripts/setup_mac.sh --logic
```

- Python 3.10 以上が必要。macOS 付属の `python3`（Xcode Command Line Tools）が 3.9 の場合は
  `brew install python@3.12` を先に実行する
- `--live` を付けると `python-rtmidi`（CoreMIDI 接続用）も入る。Apple Silicon 用の wheel が
  配布されているのでコンパイルは不要
- `--logic` は `--live` を含み、さらに `logic_start/` に Logic へ読み込む確認ファイル 3 つを作る
- `python-rtmidi` のインストールに失敗しても、セットアップは止まらず続行する。オフライン
  （`render` / `bendcheck` / `analyze`）はそのまま使え、リアルタイム（`live` / `ports`）だけが
  使えない状態になる。Logic で使う分にはオフラインで足りる
- 完了すると `demo_out/` に静止ピッチ版とトレース版の WAV / MIDI ができる。まずこれを聴き比べる
- 最後に環境診断（`pitchtrace doctor`）が走る。`失敗` が出たら画面の対処に従ってもう一度

以後は `source .venv/bin/activate` してから `pitchtrace ...` を使う。

### 1.1 うまくいかないときは `doctor`

```bash
source .venv/bin/activate
pitchtrace doctor                      # 画面で読む
pitchtrace doctor --json doctor.json   # 相談用に保存
```

Python が古い、仮想環境に入っていない、`python-rtmidi` が無い、CoreMIDI に仮想ポートを作れない、
といった原因を 1 画面で切り分ける。各行の `注意` `失敗` には対処方法が付く。
離れた場所に相談するときは `doctor.json` の中身を貼れば、環境を再現しなくても原因が絞り込める。

---

## 2. Logic Pro で使う（最短手順）

Logic で最初に鳴らすところまでを、つまずきやすい順に並べる。所要 15 分ほど。

### 2.1 まずベンドレンジを合わせる（ここを飛ばすと全部ずれる）

PitchTrace は音程の動きを**ピッチベンド**で書く。ベンドの最大値が何半音に相当するかの設定が
**ベンドレンジ**で、PitchTrace の既定は 12 半音（1 オクターブ）。多くの音源の初期値は 2 半音なので、
合わせないと表情の量がそのまま音痴になる。MIDI 規格の RPN という仕組みで通知はしているが、
無視する音源が多いため、耳で確かめるのが確実。

1. Logic で空のプロジェクトを作り、**ソフトウェア音源トラック**を 1 本作る
2. `logic_start/01_bendcheck.mid` をそのトラックにドラッグして再生する
3. 4 つの区間が順に鳴る。聴きどころは区間 2 と 3

| 区間 | 鳴るもの | 正しいときの聞こえ方 |
|---|---|---|
| 1 | C4 と C5 | この 2 つの高さを覚える区間 |
| 2 | ベンドで上げ切った音 → C5 | **2 音が同じ高さ**。低ければ音源のベンドレンジが小さい |
| 3 | ベンドで下げ切った音 → C4 | **2 音が同じ高さ** |
| 4 | 2 拍かけて上がる音 | 段差やざらつきがなく滑らか |

4. ずれていたら音源側のベンドレンジを 12 半音にする。Logic では**グローバルな設定は無く、音源ごと**に持つ
   - ES2: 画面左上の `Bend Range`（Up / Down）を 12 に
   - Retro Synth: `Bend Range`
   - Sampler（旧 EXS24）: `Pitch` の項目にあるベンド幅
   - Alchemy: パフォーマンス設定のピッチベンド幅
   - サードパーティ音源: 設定画面で `Bend` または `Pitch Bend Range` を探す
   - 12 に設定できない音源では、逆に PitchTrace 側を合わせる。例えば音源が 2 半音固定なら
     `pitchtrace bendcheck check2.mid --bend-range 2` で確かめ、以後 `render --bend-range 2` を付ける
     （ただし 2 半音では分解能が粗くなり、細かいビブラートが階段状になりやすい）
5. 合うまで 1〜4 を繰り返す。合ったら**その音源設定を保存**しておく

区間 4 で段差が聞こえる場合は、音源のベンド解像度が粗い。その音源では `--mode mpe` か、
ベンドレンジを小さめにして分解能を稼ぐ。

### 2.2 表情の有無を聴き比べる

同じ音源のまま、次の 2 つを読み込んで交互に鳴らす。

- `logic_start/02_static.mid` … 表情なし（打ち込みそのまま）
- `logic_start/03_traced.mid` … 表情あり（バイオリンのプロファイル）

差が分からないときは、音源側の内蔵ビブラートが強すぎて PitchTrace の動きが埋もれている可能性が高い。
音源のビブラートを切ってからもう一度。

### 2.3 自分の曲に適用する

```bash
source .venv/bin/activate
pitchtrace info song.mid                         # トラック番号を調べる
pitchtrace render song.mid song_traced.mid --track 2 --profile violin_classical
```

1. Logic でメロディのトラックを選び、**ファイル > 書き出す > 選択部分を MIDI ファイルとして**
2. 上のコマンドで変換する。`--track` を指定すると、そのトラックだけ差し替えて他は保持する
3. できた `song_traced.mid` を Logic にドラッグする
4. 音量表情は **CC11（エクスプレッション）** に書かれる。音源側で CC11 を音量に割り当てる。
   CC1 で受ける音源なら `--dyn-cc 1`、要らなければ `--no-dynamics`
5. 強すぎると感じたら `--amount 0.6`、やり直したいだけなら `--seed 1` のように振り直す

**書かれたデータを目で確かめる**には、リージョンをダブルクリックしてピアノロールを開き、
下部の **MIDI ドロー** で `ピッチベンド` を選ぶ。音符ごとに曲線が描かれていれば成功。
`エクスプレッション` に切り替えると CC11 も見える。

### 2.4 Logic の音源選び

| 音源 | 相性 | 理由 |
|---|---|---|
| SWAM 等の物理モデル | 最良 | ベンドと CC への追従が自然。`--mode mpe` も効く |
| ES2 / Retro Synth / Sampler | 良い | ベンドに素直に追従する。検証に向く |
| Studio Strings / Studio Horns | 注意 | 内蔵の表情と二重になりやすい。ビブラートを絞る |
| Kontakt 系のサンプル音源 | 注意 | ビブラートが録音に焼き込まれていると二重にかかる。`--vibrato-lane cc` を検討 |

### 2.5 リアルタイムで使う（任意）

オフライン（2.3）で足りるなら不要。その場で反応させたいときだけ。

```bash
pitchtrace doctor        # 「仮想 MIDI ポートの作成」が OK であること
pitchtrace live --profile violin_classical --bend-range 12
```

1. `PitchTrace In` と `PitchTrace Out` という MIDI ポートが現れる
2. Logic で**外部 MIDI トラック**を作り、出力ポートを `PitchTrace In` にする。メロディはここに置く
3. 音源トラックは `PitchTrace Out` から受ける。Logic は既定で全入力を受けるので、
   **Logic Pro > 設定 > MIDI > 入力**（バージョンにより「環境設定」）で `PitchTrace Out` 以外を切ると確実
4. 音源のベンドレンジを `--bend-range` と揃える（2.1 と同じ）

リアルタイムでは次の音と音長が分からないため、フレーズ末のリリース、クライマックスの強調、
マイクロタイミングは付かない。最終書き出しはオフラインで行うのが良い。

---

## 3. 使い方は 2 通り（Logic 以外の DAW も含めた全体像）

Logic だけを使うなら §2 で足りる。ここは Cubase / Studio One / Ableton Live を含めた一般の手順。

### A. オフライン: MIDI ファイルに表情を付けて DAW に読み込む（まずはこちらから）

1. DAW でメロディトラックを MIDI ファイルに書き出す（単旋律）。曲全体のマルチトラック MIDI でもよい
2. 変換する

   ```bash
   pitchtrace info song.mid                       # トラック番号と音符数を確認
   pitchtrace render song.mid song_traced.mid --track 2 --profile violin_classical
   #   → トラック 2 だけ表情付きに差し替え、他トラックとテンポチェンジはそのまま保持
   pitchtrace render melody.mid melody_traced.mid --profile violin_classical --bend-range 12
   # MPE 対応音源なら
   pitchtrace render melody.mid melody_traced.mid --profile violin_classical --mode mpe
   # ビブラートを CC1 で制御する音源なら
   pitchtrace render melody.mid melody_traced.mid --profile violin_classical --vibrato-lane cc
   ```

3. `melody_traced.mid` を DAW に読み込み、音源の**ベンドレンジを 12 半音**に合わせる
   （`--bend-range` で変更可。RPN でも書き込んでいるが、音源が無視することがある）
4. 気に入らなければ `--seed` を変えて振り直す。`--amount 0.6` で控えめにできる。
   調は自動判定される（出力に `key C` のように表示）。転調が多い曲や判定が違うときは
   `--key Am` で指定、`--no-key-bias` で度数バイアスを切る
5. 音量表情は **CC11** に書かれる。音源側でエクスプレッションを CC11 に割り当てる。
   CC1 で受ける音源なら `--dyn-cc 1`。不要なら `--no-dynamics`。
   音の前後ずれ（マイクロタイミング）が不要なら `--no-timing`

### A2. 参照演奏の転写（Reference Performance Transfer）

手元にチェロ（やバイオリン）のソロ録音があれば、その奏者のジェスチャーを打ち込みへ転写できる。

```bash
pitchtrace analyze cello_ref.wav --igf cello_ref.igf.json --instrument cello   # 解析（1 回だけ）
pitchtrace plot check.png --igf cello_ref.igf.json                              # 解析結果を目で確認
pitchtrace transfer cello_ref.igf.json melody.mid melody_traced.mid --mapping context --wav preview.wav
pitchtrace transfer cello_ref.igf.json melody.mid melody_raw.mid --adapt raw    # 生カーブをそのまま使う版
```

録音は無伴奏・単旋律・モノラル推奨。`--tuning 442` で基準ピッチを固定できる（省略時は推定）。
評価は `pitchtrace demo out --profile cello_classical --blind` の X/Y/Z を聴いてから答えを見る。

### B. リアルタイム: DAW → PitchTrace → DAW（仮想 MIDI ポート）

演奏やピアノロールの再生に対して、その場でピッチベンドを付ける。

1. **仮想ポートを立ち上げる**

   ```bash
   pitchtrace live --profile alto_sax_jazz --bend-range 12
   ```

   `PitchTrace In` と `PitchTrace Out` という CoreMIDI ポートが現れる（`pitchtrace ports` で確認）。

2. **DAW 側のルーティング**
   - メロディの MIDI トラックの出力先を **External MIDI / 外部 MIDI → `PitchTrace In`** にする
   - 音源トラックの MIDI 入力を **`PitchTrace Out`** にする（DAW が入力ポートを選べない場合は、
     環境設定で `PitchTrace Out` 以外の MIDI 入力を無効にする）
   - 音源のベンドレンジを `--bend-range` と揃える

   | DAW | 出力先の設定 | 入力側の設定 |
   |---|---|---|
   | Logic Pro | 外部 MIDI トラックを作り、出力ポートに `PitchTrace In` | 音源トラックは全入力を受けるので、環境設定 > MIDI > 入力 で `PitchTrace Out` 以外をオフ |
   | Cubase | MIDI トラックの出力に `PitchTrace In` | 音源トラックの入力に `PitchTrace Out` |
   | Studio One | 外部デバイスとして `PitchTrace In` を登録し、インストゥルメントトラックの出力に指定 | 外部デバイス（キーボード）として `PitchTrace Out` を登録 |
   | Ableton Live | MIDI トラックの MIDI To に `PitchTrace In` | 音源トラックの MIDI From に `PitchTrace Out` |

   IAC Driver（Audio MIDI 設定 > MIDI スタジオ > IAC ドライバ > 「装置はオンライン」）を使う場合は
   `--in "IAC" --out "IAC Bus 2"` のように部分一致で指定できる。

3. **オプション**
   - `--mode mpe` … MPE 対応音源（SWAM、Sample Modeling 等）向け。重なった音も正しく扱える
   - `--vibrato-lane cc` … ビブラートを CC1 に分離（音源側でビブラートを CC1 に割り当てる）
   - `--legato-overlap-ms 20` … レガート検出に重なりが要る音源向け
   - `--in-channel 0` … 特定チャンネルだけ処理（0 始まり）
   - `--no-dynamics` … CC11 のダイナミクスを出さない（`--dyn-cc 1` で CC 番号変更）
   - `--key C` … 調を指定して度数バイアス（導音高めなど）を付ける。リアルタイムでは自動判定しない
   - `-v` … 受信メッセージを表示（トラブル時）

4. **リアルタイム動作の制約**
   - 「次の音」と「音長」を知らないので、フレーズ末のリリース、クライマックスの強調、
     マイクロタイミングは付かない（ポルタメント・しゃくり・ビブラート・ドリフト・ダイナミクスは付く）
   - 追加レイテンシは 1 音あたり数 ms（30 秒分のカーブをノートオン時に生成）。
     気になる場合はオフライン（A）で最終書き出しする

## 4. 音源側の注意

- ビブラート・レガート遷移が録音に焼き込まれた音源（Kontakt 系の多く）では二重にかかる。
  音源のビブラートを切るか、`--vibrato-lane cc` で音源側のビブラート量を CC で動かす
- 物理モデル系（SWAM 等）はピッチベンド / MPE への追従が自然で、最も相性が良い
- ベンドレンジが合っていないと音程がずれる。`pitchtrace bendcheck check.mid` で作った MIDI を
  読み込み、区間 2 と 3 の 2 音が同じ高さに聞こえるかで判定する（§2.1）

## 5. テスト運用のチェックリスト（Mac mini M4）

1. `bash scripts/setup_mac.sh --logic` がテスト込みで通る
2. `pitchtrace doctor` に `失敗` が無い（`注意` は可。内容を控えておく）
3. `demo_out/` の WAV で、静止版との差が聴き取れる
4. `logic_start/01_bendcheck.mid` の区間 2 と 3 が同じ高さに聞こえる（ベンドレンジ確認）
5. `02_static.mid` と `03_traced.mid` の差が聴き取れる
6. 実曲のメロディを `render` して、音源で再生。プロファイルと `--amount` を調整
7. `pitchtrace live` で DAW 往復が動き、音切れやハングがない（30 分程度連続再生）
8. 実録音があれば `pitchtrace analyze` でプロファイルを作り、組み込みと聴き比べ

問題なければ Mac Studio M2 で同じ手順を実行し、本番のプロジェクトに使う。
本番では、最終書き出しは再現性のあるオフライン（`render --seed N`）を推奨する。

## 6. トラブルシューティング

原因の切り分けは `pitchtrace doctor` から始める。環境側の問題はここでほぼ出る。

| 症状 | 確認すること |
|---|---|
| インストールしたのに `pitchtrace` が見つからない | `source .venv/bin/activate` を忘れている。`doctor` が場所を教える |
| Logic から `PitchTrace In/Out` が見えない | `doctor` の「仮想 MIDI ポートの作成」を確認。`live` を起動したままにする必要がある |
| `pitchtrace ports` でポートが出ない | `pip install python-rtmidi`。macOS の「プライバシーとセキュリティ」で Terminal に MIDI 関連の許可が要る場合がある |
| 音程が全体にずれる | ベンドレンジ不一致。音源側を 12（または `--bend-range` の値）に |
| ビブラートが二重にかかる | 音源のビブラートを切るか `--vibrato-lane cc` |
| 音が途切れる・重なる | single モードは単旋律前提。和音や重なりが多いなら `--mode mpe` |
| リアルタイムで反応が遅い | `-v` でメッセージが届いているか確認。DAW 側のバッファ設定も確認 |
