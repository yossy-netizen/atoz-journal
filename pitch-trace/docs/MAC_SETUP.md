# Mac でのセットアップと DAW 連携（テスト運用 → 本番）

対象: Mac mini M4（macOS Tahoe）でのテスト運用、Mac Studio M2（macOS Sequoia）での本番使用。
どちらも Apple Silicon なので手順は同じ。

## 1. インストール

```bash
git clone <このリポジトリ>
cd atoz-journal/pitch-trace
bash scripts/setup_mac.sh --live
```

- Python 3.10 以上が必要。macOS 付属の `python3`（Xcode Command Line Tools）が 3.9 の場合は
  `brew install python@3.12` を先に実行する
- `--live` を付けると `python-rtmidi`（CoreMIDI 接続用）も入る。Apple Silicon 用の wheel が
  配布されているのでコンパイルは不要
- 完了すると `demo_out/` に静止ピッチ版とトレース版の WAV / MIDI ができる。まずこれを聴き比べる

以後は `source .venv/bin/activate` してから `pitchtrace ...` を使う。

## 2. 使い方は 2 通り

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
4. 気に入らなければ `--seed` を変えて振り直す。`--amount 0.6` で控えめにできる
5. 音量表情は **CC11** に書かれる。音源側でエクスプレッションを CC11 に割り当てる。
   CC1 で受ける音源なら `--dyn-cc 1`。不要なら `--no-dynamics`。
   音の前後ずれ（マイクロタイミング）が不要なら `--no-timing`

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
   - `-v` … 受信メッセージを表示（トラブル時）

4. **リアルタイム動作の制約**
   - 「次の音」と「音長」を知らないので、フレーズ末のリリース、クライマックスの強調、
     マイクロタイミングは付かない（ポルタメント・しゃくり・ビブラート・ドリフト・ダイナミクスは付く）
   - 追加レイテンシは 1 音あたり数 ms（30 秒分のカーブをノートオン時に生成）。
     気になる場合はオフライン（A）で最終書き出しする

## 3. 音源側の注意

- ビブラート・レガート遷移が録音に焼き込まれた音源（Kontakt 系の多く）では二重にかかる。
  音源のビブラートを切るか、`--vibrato-lane cc` で音源側のビブラート量を CC で動かす
- 物理モデル系（SWAM 等）はピッチベンド / MPE への追従が自然で、最も相性が良い
- ベンドレンジが合っていないと音程がずれる。まず `demo_out/demo_violin_classical.mid` を
  読み込んで、静止ピッチ版とほぼ同じ音程で鳴るか確認する

## 4. テスト運用のチェックリスト（Mac mini M4）

1. `bash scripts/setup_mac.sh --live` がテスト込みで通る
2. `demo_out/` の WAV で、静止版との差が聴き取れる
3. `demo_violin_classical.mid` を DAW に読み込み、音程がずれない（ベンドレンジ確認）
4. 実曲のメロディを `render` して、音源で再生。プロファイルと `--amount` を調整
5. `pitchtrace live` で DAW 往復が動き、音切れやハングがない（30 分程度連続再生）
6. 実録音があれば `pitchtrace analyze` でプロファイルを作り、組み込みと聴き比べ

問題なければ Mac Studio M2 で同じ手順を実行し、本番のプロジェクトに使う。
本番では、最終書き出しは再現性のあるオフライン（`render --seed N`）を推奨する。

## 5. トラブルシューティング

| 症状 | 確認すること |
|---|---|
| `pitchtrace ports` でポートが出ない | `pip install python-rtmidi`。macOS の「プライバシーとセキュリティ」で Terminal に MIDI 関連の許可が要る場合がある |
| 音程が全体にずれる | ベンドレンジ不一致。音源側を 12（または `--bend-range` の値）に |
| ビブラートが二重にかかる | 音源のビブラートを切るか `--vibrato-lane cc` |
| 音が途切れる・重なる | single モードは単旋律前提。和音や重なりが多いなら `--mode mpe` |
| リアルタイムで反応が遅い | `-v` でメッセージが届いているか確認。DAW 側のバッファ設定も確認 |
