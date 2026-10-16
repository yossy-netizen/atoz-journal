# 引き継ぎ指示書（Mac 側で作業する Claude Code / Codex 向け）

このファイルは、**Mac mini M4 または Mac Studio M2 上で動くエージェント**に向けた作業指示です。
クラウド側のエージェント（PitchTrace を開発している側）が、実機での確認を依頼するために置いています。

読んだら、まず「## 1. あなたの役割」と「## 5. やらないこと」を確認してから着手してください。

---

## 1. あなたの役割

PitchTrace を実機にセットアップし、**機械で判定できることをすべて判定し**、
**人にしか判定できないことを人に提示し**、結果を報告する。開発（コードの改良）は担当しません。

| 判定の種類 | 誰がやるか | 例 |
|---|---|---|
| 入るか、落ちないか、数値が合うか | あなた（自動） | インストール、テスト、`doctor`、`eval` |
| Logic の設定が合っているか | 人が耳で判定（あなたは手順を提示して結果を聞く） | ベンドレンジ |
| 音楽として良いか | 人が耳で判定 | 表情の量、プロファイルの妥当性 |

**音の良し悪しをあなたが推測して書かないでください。** 聴いていない判断は報告として無価値であり、
こちらの改良を誤った方向に進めます。聴けていない項目は「未実施」と書いてください。

---

## 2. セットアップ

```bash
git clone https://github.com/yossy-netizen/atoz-journal.git
cd atoz-journal
git checkout claude/instrument-pitch-trace-plugin-z00rsk
cd pitch-trace
bash scripts/setup_mac.sh --logic
```

すでに clone 済みなら `git pull origin claude/instrument-pitch-trace-plugin-z00rsk` で更新してから
`bash scripts/setup_mac.sh --logic` を実行してください。

- Python 3.10 以上が必要。無ければ `brew install python@3.12`
- `--logic` は `--live`（`python-rtmidi`）を含み、`logic_start/` に Logic 用の確認ファイルを作る
- `python-rtmidi` のインストールに失敗しても中断しません。オフライン利用には不要です
- 途中で止まったら `source .venv/bin/activate && pitchtrace doctor` の出力を報告に載せてください

以降のコマンドはすべて `source .venv/bin/activate` の後、`pitch-trace/` で実行します。

---

## 3. あなたが自動で行う確認

次を順に実行し、出力をすべて控えてください。

```bash
source .venv/bin/activate
python -m pytest -q                       # 全件通ること
pitchtrace doctor --json /tmp/doctor.json # 「失敗」が 0 であること
pitchtrace eval --all                     # docs/EVAL_LOG.md の v0.3.0 の表と一致すること
pitchtrace profiles
ls -1 logic_start/                        # 01_bendcheck.mid / 02_static.mid / 03_traced.mid
```

判定基準:

| 項目 | 合格 |
|---|---|
| pytest | 全件通過。1 件でも落ちたら、その出力全文を報告 |
| doctor | `失敗` が 0 件。`注意` は許容するが、内容を報告に転記 |
| eval | 音符の検出数と誤差が `docs/EVAL_LOG.md` の v0.3.0 の表と一致。ずれたら数値を報告 |
| logic_start | 3 ファイルが存在 |

`eval` の数値が表と食い違った場合、それは**環境依存の差**であり重要な発見です。
勝手に直さず、数値をそのまま報告してください（numpy のバージョン差などが疑われます）。

---

## 4. 人に依頼する確認（Logic Pro）

以下を**人に提示して、結果を聞き取って**ください。あなたが代わりに判定してはいけません。
詳しい手順は [`MAC_SETUP.md`](MAC_SETUP.md) の「2. Logic Pro で使う（最短手順）」にあります。

### 4.1 ベンドレンジ合わせ（最優先。ここが合わないと他が無意味）

人への説明文（そのまま伝えて構いません）:

> Logic で空のプロジェクトを作り、ソフトウェア音源トラックを 1 本用意してください。
> `logic_start/01_bendcheck.mid` をそのトラックにドラッグして再生します。
> 8 秒ほどの間に 4 つの区間が鳴ります。聴きどころは 2 番目と 3 番目で、
> **それぞれ 2 つの音が同じ高さに聞こえれば正解**です。
> ずれて聞こえたら、音源の設定で `Bend Range`（または `Pitch Bend Range`）を **12** にしてください。

聞き取る項目:

- 使った音源の名前
- 区間 2 の 2 音は同じ高さに聞こえたか。違うなら、ベンドで上げた音は高かったか低かったか
- 区間 3 も同様
- 区間 4 は滑らかだったか、段差が聞こえたか
- 音源のベンドレンジ設定をどの値にしたか

12 半音に設定できない音源だった場合は、その値を控えて
`pitchtrace bendcheck check.mid --bend-range <その値>` で作り直して再確認してもらってください。
以後の `render` にも同じ `--bend-range` を付ける必要があります。

### 4.2 表情の有無の聴き比べ

> 同じ音源のまま `logic_start/02_static.mid`（表情なし）と `logic_start/03_traced.mid`（表情あり）を
> 交互に鳴らしてください。違いが分かりますか。

差が分からない場合、音源の内蔵ビブラートが強すぎて埋もれている可能性が高いので、
音源のビブラートを切って再確認してもらってください。

### 4.3 実曲での確認（時間があれば）

人にメロディの MIDI を書き出してもらい、次を実行して Logic に戻します。

```bash
pitchtrace info song.mid
pitchtrace render song.mid song_traced.mid --track <番号> --profile violin_classical
```

感想が出てきたら、次の表で**こちらが動かせるつまみ**に翻訳して報告してください。

| 人の言葉 | 疑う成分 | その場で試すこと |
|---|---|---|
| 音程が全体にずれる | 設定（成分ではない） | 音源のベンドレンジを確認（4.1 に戻る） |
| ビブラートが機械的、一定すぎる | vibrato の揺らぎ | `--amount-vibrato 0.7` |
| ビブラートが深い、速い | vibrato | `--amount-vibrato 0.5` |
| ビブラートが二重にかかる | 音源の内蔵ビブラート | 音源側を切る、または `--vibrato-lane cc` |
| 音の入りがしゃくりすぎる | attack | `--amount-attack 0.5` |
| 音のつながりがずり上がりすぎる | transition | `--amount-transition 0.5` |
| 全体がふらついて酔う | drift と jitter | `--amount-drift 0.5 --amount-jitter 0.5` |
| 音量が不自然に波打つ | dynamics | `--no-dynamics` で切り分け |
| リズムが甘い、走る | timing | `--no-timing` で切り分け |
| 音程感が曲に合わない | intonation の度数バイアス | `--key Am` で調を指定、または `--no-key-bias` |

成分は `--amount-<成分名>` で個別に効きます。使えるのは intonation、transition、attack、vibrato、
drift、release、jitter、dynamics、timing の 9 つ。全体を薄くするだけなら `--amount 0.6`。

試した結果まで報告に含めてもらえると、こちらでの往復が 1 回減ります。

---

## 5. やらないこと

- **`pitchtrace/` 以下のコードを変更しない。** 不具合を見つけたら報告してください。直すのは開発側です
- **`profiles/*.json` を書き換えない。** 聴感に合わせた調整は、根拠（実測か試聴の記録）とセットで
  開発側が行います
- **`docs/` の既存文書を書き換えない。** 記述の誤りを見つけたら報告に書いてください
- **`docs/feedback/` 以外のファイルをコミットしない。** ここだけは開発側が触らないと決めてあるので、
  衝突しません
- **生成物（`.venv/`、`demo_out/`、`logic_start/`、`*.mid`、`*.wav`）をコミットしない。**
  `.gitignore` 済みですが念のため

例外は、人から明示的に「直して」と指示された場合です。その場合も、何をなぜ変えたかを報告に残してください。

---

## 6. 報告の出し方

`docs/feedback/YYYY-MM-DD-<マシン名>.md` を新規作成し、下のテンプレートを埋めてください。
マシン名は `mac-mini-m4` または `mac-studio-m2`。

```markdown
# 実機確認 YYYY-MM-DD（mac-studio-m2）

## 環境
- macOS: （バージョン）
- 機種: Mac Studio M2 / Mac mini M4
- Python: （`python -V`）
- コミット: （`git rev-parse --short HEAD`）
- DAW: Logic Pro （バージョン）
- 音源: （名前とバージョン）

## 自動確認
- pytest: 通過 / 失敗（失敗なら出力全文）
- doctor: 失敗 0 件 / N 件。注意の内容: （転記）
- eval --all: EVAL_LOG v0.3.0 と一致 / 相違（相違なら数値）

## ベンドレンジ（人が試聴）
- 区間 2: 一致した / ベンドした音が高い / 低い / 未実施
- 区間 3: 一致した / ずれた / 未実施
- 区間 4: 滑らか / 段差あり / 未実施
- 音源側の設定値: （半音）

## 表情の聴き比べ（人が試聴）
- 差が分かったか:
- 感想:

## 実曲（人が試聴）
- 使ったコマンド:
- 感想と、§4.3 の表での翻訳:
- 試した調整とその結果:

## 気づいたこと・不具合
-
```

コミットとプッシュ:

```bash
cd /path/to/atoz-journal
git add pitch-trace/docs/feedback/
git commit -m "実機確認の記録: <マシン名> YYYY-MM-DD"
git pull --rebase origin claude/instrument-pitch-trace-plugin-z00rsk
git push origin claude/instrument-pitch-trace-plugin-z00rsk
```

`git pull --rebase` を先に行ってください。開発側が同じブランチに push しているため、
省くと拒否されます。`docs/feedback/` は開発側が触らないので、内容の衝突は起きません。

プッシュが通らない、または git を使わない運用の場合は、書いた Markdown の中身をそのまま
人に渡してください。人がクラウド側の会話に貼ります。

---

## 7. 判断に迷ったら

- 音に関する判断 → 人に聞く。推測で書かない
- コードの不具合らしきもの → 直さず報告。再現手順とコマンドの出力を添える
- 指示書に書かれていない作業を頼まれた → 人の指示が優先。ただし §5 の「やらないこと」に
  触れる場合は、その旨を伝えてから実施し、報告に明記する
