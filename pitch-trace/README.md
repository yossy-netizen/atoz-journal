# PitchTrace（v0.2 プロトタイプ）

生楽器（バイオリン・チェロ・オーボエ・サックス等、単旋律）の**ピッチの揺らぎ・繋ぎ・外し方**を
プロファイル化し、MIDI 打ち込みにピッチベンド / MPE / CC として付与するツール。
構想は [`../notes/pitch-trace/CONCEPT.md`](../notes/pitch-trace/CONCEPT.md)。

この v0.2 は構想のフェーズ 0〜1（L0: ルール + 統計エンジン、スタンドアロン CLI）に、中間表現 IGF と
参照演奏の転写（Reference Performance Transfer）、リアルタイム処理を加えたもの。

## できること

| コマンド | 内容 |
|---|---|
| `pitchtrace info song.mid` | トラック一覧（番号・音符数・音域・テンポチェンジ） |
| `pitchtrace render in.mid out.mid --profile violin_classical` | MIDI に表情（ピッチベンド + CC11）を付ける。`--track N` で曲全体の MIDI の 1 トラックだけ差し替え（他トラックとテンポマップは保持）。`--mode mpe` で MPE、`--vibrato-lane cc` でビブラートを CC1 に分離 |
| `pitchtrace analyze solo.wav -o my_violin.json --base violin_classical` | ソロ録音（無伴奏・単旋律）からプロファイル（統計）を推定。出力はそのまま `--profile` に渡せる |
| `pitchtrace analyze solo.wav --igf solo.igf.json` | 音符ごとのジェスチャー + 生カーブを IGF（中間表現）として保存。`--detector pyin`、`--tuning 442` |
| `pitchtrace transfer cello_ref.wav melody.mid out.mid` | **参照演奏のジェスチャーを別の MIDI へ転写**。`--adapt param|raw`、`--mapping positional|context`、`--map 0,1,3,-`、`--wav` で試聴用 WAV |
| `pitchtrace plot out.png --igf solo.igf.json --midi melody.mid --profile cello_classical` | 可視化（生 F0・正規化カーブ・信頼度・境界・生成カーブ・ダイナミクス）。要 matplotlib |
| `pitchtrace demo out_dir --profile cello_classical --blind` | 静止 / ランダム・ヒューマナイズ / ジェスチャーをシャッフルした X/Y/Z WAV（答えは別ファイル） |
| `pitchtrace demo out_dir --profile alto_sax_jazz` | 静止ピッチ版とトレース版の WAV / MIDI を出力（A/B 試聴用） |
| `pitchtrace dump in.mid out.csv` | 生成したカーブを成分ごとに CSV へ（可視化・検証用） |
| `pitchtrace live --profile violin_classical` | 仮想 MIDI ポート `PitchTrace In/Out` を作り、DAW からリアルタイムに受けてピッチベンド付きで返す（要 `pip install python-rtmidi`） |
| `pitchtrace ports` | MIDI ポート一覧 |
| `pitchtrace profiles` | 組み込みプロファイル一覧 |

組み込みプロファイル: `violin_classical` `cello_classical` `oboe_classical` `alto_sax_classical` `alto_sax_jazz`（比較用 `random_humanize`）
（v0 は文献値と経験則による**手調整の目安**。実測で更新する前提）

## セットアップ

```bash
cd pitch-trace
pip install -e ".[dev,live,viz]" # live はリアルタイム用（python-rtmidi）、viz は plot 用（matplotlib）、analysis は pYIN 用（librosa）
python -m pytest -q
pitchtrace demo /tmp/pt_demo --profile violin_classical   # demo_static.wav と demo_violin_classical.wav を聴き比べ
```

Mac（Apple Silicon）でのセットアップ、DAW とのルーティング、テスト運用のチェックリストは
[`docs/MAC_SETUP.md`](docs/MAC_SETUP.md)。`bash scripts/setup_mac.sh --live` で venv 作成からデモ生成まで行う。

依存は numpy と mido のみ。F0 抽出は YIN の自前実装（精度が要る段階で CREPE / PESTO に差し替える）。

## 仕組み

ピッチを「目標音からのセント偏差 c(t)」として、次の成分の和で生成する（`generate.py`）。

```
c(t) = intonation + transition(t) + attack(t) + vibrato(t) + drift(t) + release(t) + jitter(t)
```

各成分のパラメータは `profile.py` の分布（mean / std / min / max）から音符ごとにサンプルされ、
音程差・音長・レガートかどうか・フレーズ内の位置（先頭 / 末尾 / 最高音）で条件付けされる。

イントネーションは「ランダム成分（前の音との連続性あり）+ 調に対する度数バイアス」で、
調は音符列から自動判定する（Krumhansl 法、`--key Am` で上書き、`--no-key-bias` で無効）。
弦のクラシック系プロファイルは導音を高め・長 3 度をやや高めにする旋律的イントネーション、
ジャズ系はバイアスなし。解析側は度数ごとの中央値からバイアス表を推定する。

ピッチに加えて、同じ枠組みで次も生成する:

- **ダイナミクス**（`profile.dynamics`、既定 CC11）: 発音時のふくらみ、サステインの傾き、
  音末の減衰、フレーズの山に向かうクレッシェンド、ゆっくりした揺らぎ。`--no-dynamics` で無効、
  `--dyn-cc 1` で CC 番号を変更（音源が CC1 = ダイナミクスの場合）
- **マイクロタイミング**（`profile.timing`、オフライン専用）: ランダムな前後ずれ、レガート音の
  先行、フレーズ先頭の遅れ、非レガート音の短縮。`--no-timing` で無効。順序が入れ替わらないよう
  前の音の開始より前には動かさない

解析（`analyze.py`）はこの逆問題をルールベースで解く:
音声 → YIN で F0 → ノート分割 → 音符ごとに各成分を推定 → 分布に集計 → プロファイル JSON。
`tests/test_analyze.py` に「生成 → 合成 → 解析」の往復で主要パラメータが戻ることの検証がある。

## 音源側の設定

- **ベンドレンジ**を `--bend-range`（既定 12 半音）と音源で揃える。RPN 0 で MIDI にも書き込む
- ビブラート・レガートが録音に焼き込まれた音源では二重にかかる。物理モデル系（SWAM 等）や
  ビブラートを CC で制御できる音源（`--vibrato-lane cc`）が相性が良い
- レガート検出に重なりが要る音源は `--legato-overlap-ms 20` などで重なりを残す

## IGF（Instrument Gesture Format）と転写

`analyze --igf` は解析結果を IGF（JSON）として保存する。音符ごとに、目標音からのセント偏差の
生カーブ（時間・セント・信頼度・補正前の生 F0）、意味パラメータ（アタック・遷移・ビブラート・
ドリフト・リリース・ダイナミクス）、前後関係（音程差・レガート・隙間）を持ち、解析器のバージョン、
基準ピッチ（A=442 などを推定）、調を記録する。生成モデルや MIDI 規格に依存しない中間表現で、
将来の再解析や学習データの単位になる。

`transfer` は参照演奏（WAV か IGF）のジェスチャーをターゲット MIDI へ転写する。

- 対応付け: `positional`（i 番目 → i 番目、循環）、`context`（音長・前後の音程差・レガート・音域が近い
  上位 K からランダム）、`--map` で手動
- 適応 `param`: 参照音符の意味パラメータを固定値として生成器に渡し、ターゲットの音長で再生成する。
  ビブラートのレートは保たれ、音長が大きく違っても破綻しにくい（既定）
- 適応 `raw`: 参照の生カーブをそのまま使う。遷移区間はターゲットの音程差でスケールし、アタックと末尾は
  元の時間を保ち、サステインだけ切り詰め／クロスフェードで継ぎ足す。参照のビブラートの形が残る
- `--amount` と `--amount-vibrato` などで成分ごとに量を変えられる（1.5 で誇張）

## リアルタイム動作

`realtime.py` の `RealtimeTracer` はノートオン時に前の音との関係（ピッチ・隙間・終端偏差）から
その音のカーブを生成し、ベンドをノートオンより先に送ってから hop ごとに流す。
次の音と音長が分からないため、フレーズ末のリリースとクライマックスの強調は付かない。
ノートオン時の処理コストは 1 音あたり約 2 ms。

## 既知の制限（v0.1）

- 対象は単旋律のみ。同音連打はピッチだけでは分割できない（オンセット検出は未実装）
- 20 ms 未満のポルタメントは F0 抽出の時間分解能により「段差」と区別できない
- ビブラートの立ち上がりが遅い奏法では、0.5 秒未満の音でビブラートを検出しにくい
- 解析は「安定区間の中央値」を目標音とみなすため、ビブラートの中心ずれとイントネーションの
  分離は近似（ビブラート開始前の区間が取れるときのみ分離）
- ダイナミクスの解析は RMS 包絡からの近似（アタック時間・傾き・減衰のみ）。タイミングは楽譜がないと解析できないため手調整値のみ

## 次のステップ

構想メモ §7 のフェーズ 0: バイオリンとアルトサックスの実録音を `analyze` にかけ、
組み込みプロファイルの数値を実測で置き換える。次に MIDI FX プラグイン（JUCE）へ移植する。
