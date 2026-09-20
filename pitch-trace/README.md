# PitchTrace（v0.1 プロトタイプ）

生楽器（バイオリン・チェロ・オーボエ・サックス等、単旋律）の**ピッチの揺らぎ・繋ぎ・外し方**を
プロファイル化し、MIDI 打ち込みにピッチベンド / MPE / CC として付与するツール。
構想は [`../notes/pitch-trace/CONCEPT.md`](../notes/pitch-trace/CONCEPT.md)。

この v0.1 は構想のフェーズ 0〜1（L0: ルール + 統計エンジン、スタンドアロン CLI）に相当する。

## できること

| コマンド | 内容 |
|---|---|
| `pitchtrace render in.mid out.mid --profile violin_classical` | MIDI に表情（ピッチベンド）を付ける。`--mode mpe` で MPE、`--vibrato-lane cc` でビブラートを CC1 に分離 |
| `pitchtrace analyze solo.wav -o my_violin.json --base violin_classical` | ソロ録音（無伴奏・単旋律）からプロファイルを推定。出力はそのまま `--profile` に渡せる |
| `pitchtrace demo out_dir --profile alto_sax_jazz` | 静止ピッチ版とトレース版の WAV / MIDI を出力（A/B 試聴用） |
| `pitchtrace dump in.mid out.csv` | 生成したカーブを成分ごとに CSV へ（可視化・検証用） |
| `pitchtrace live --profile violin_classical` | 仮想 MIDI ポート `PitchTrace In/Out` を作り、DAW からリアルタイムに受けてピッチベンド付きで返す（要 `pip install python-rtmidi`） |
| `pitchtrace ports` | MIDI ポート一覧 |
| `pitchtrace profiles` | 組み込みプロファイル一覧 |

組み込みプロファイル: `violin_classical` `cello_classical` `oboe_classical` `alto_sax_classical` `alto_sax_jazz`
（v0 は文献値と経験則による**手調整の目安**。実測で更新する前提）

## セットアップ

```bash
cd pitch-trace
pip install -e ".[dev,live]"     # live はリアルタイム用（python-rtmidi）。不要なら ".[dev]"
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

解析（`analyze.py`）はこの逆問題をルールベースで解く:
音声 → YIN で F0 → ノート分割 → 音符ごとに各成分を推定 → 分布に集計 → プロファイル JSON。
`tests/test_analyze.py` に「生成 → 合成 → 解析」の往復で主要パラメータが戻ることの検証がある。

## 音源側の設定

- **ベンドレンジ**を `--bend-range`（既定 12 半音）と音源で揃える。RPN 0 で MIDI にも書き込む
- ビブラート・レガートが録音に焼き込まれた音源では二重にかかる。物理モデル系（SWAM 等）や
  ビブラートを CC で制御できる音源（`--vibrato-lane cc`）が相性が良い
- レガート検出に重なりが要る音源は `--legato-overlap-ms 20` などで重なりを残す

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
- ダイナミクス（CC1/CC11）と微小タイミングは未対応（同じ枠組みで拡張予定）

## 次のステップ

構想メモ §7 のフェーズ 0: バイオリンとアルトサックスの実録音を `analyze` にかけ、
組み込みプロファイルの数値を実測で置き換える。次に MIDI FX プラグイン（JUCE）へ移植する。
