# CV Rider を Logic Pro で使う — Mac Studio M2（macOS Sequoia）向け詳細手順

> 対象: Mac Studio M2 / macOS Sequoia / Logic Pro。Mac mini M4（Tahoe）でも手順は同じです。
> 所要時間: 約 5 分。ターミナルの操作は「ダブルクリック」だけで済むようにしてあります。

## 0. 用意するもの

- ダウンロード用のリンク（下記）
- Logic Pro（起動していたら、インストールの前に一度終了しておく）

## 1. ダウンロードする

**最新ビルドの直接リンク（クリックすると `cvrider-macos.zip` が落ちてきます）:**

https://github.com/yossy-netizen/atoz-journal/releases/download/cvrider-latest/cvrider-macos.zip

- Safari で開くと、通常は「ダウンロード」フォルダ（Finder の左側「ダウンロード」、Dock 右端のスタック）に保存されます。
- 一覧ページ（更新日やメモを見たいとき）: https://github.com/yossy-netizen/atoz-journal/releases/tag/cvrider-latest

## 2. 展開する

1. Finder で「ダウンロード」を開く。
2. `cvrider-macos.zip` を **ダブルクリック** → 同じ場所に `cvrider-macos` フォルダができる。
   Safari の設定によっては、ダウンロード時に自動で展開されて最初からフォルダになっていることもあります。
3. フォルダの中身:

| ファイル | 役割 |
|---|---|
| `Install CV Rider.command` | **これをダブルクリックするだけでインストール完了** |
| `CV Rider.component` | AU 版（Logic Pro が使う本体） |
| `CV Rider.vst3` | VST3 版（Cubase / Studio One / Live 用。Logic では使わない） |
| `CV Rider.app` | 単体アプリ（DAW なしでマイクを通して試せる） |
| `install-mac.sh` | インストーラ本体（.command から呼ばれる） |
| `README-INSTALL.txt` | この手順の短縮版 |

## 3. インストールする（ダブルクリック 1 回）

1. `Install CV Rider.command` を **ダブルクリック**。ターミナルが開いて処理が進みます。
2. 次のように出れば成功です。

```
installed ~/Library/Audio/Plug-Ins/Components/CV Rider.component
installed ~/Library/Audio/Plug-Ins/VST3/CV Rider.vst3
--- auval ---
...
* * PASS
=== インストール完了 ===
```

3. Enter キーでウィンドウを閉じます。

### 「開発元を確認できないため開けません」と出たとき

インターネットから落としたファイルには macOS が「隔離」マークを付けるので、初回だけ止められることがあります。
どちらかの方法で通してください。

- **方法 A（おすすめ）**: `Install CV Rider.command` を **右クリック（または control キーを押しながらクリック）→「開く」→ 表示されるダイアログでもう一度「開く」**。
- **方法 B**: システム設定 → **プライバシーとセキュリティ** → 下のほうにある「"Install CV Rider.command" は開発元を確認できないため…」の横の **「このまま開く」** → Touch ID / パスワード。

インストーラは、プラグイン本体の隔離マークも自動で外し、この Mac 用の簡易署名（アドホック署名）を付けます。
これは自分の Mac で使う分には十分で、Apple の Developer ID 署名は不要です。

### ターミナルを使いたい場合（同じことを手で行う）

```bash
cd ~/Downloads/cvrider-macos
chmod +x install-mac.sh && ./install-mac.sh .
```

## 4. Logic Pro で開く

1. Logic Pro を起動する（インストール前から起動していた場合は、いったん終了して起動し直す）。
   起動時に新しい AU をスキャンし、「CV Rider」が検証されます。
2. ボーカルのオーディオトラックを選び、チャンネルストリップの **Audio FX** スロットをクリック。
3. **Audio Units → AtoZ Studio → CV Rider** を選ぶ（モノラルトラックなら「モノラル」、ステレオなら「ステレオ」）。
4. プラグイン画面が開きます。上段の青↔橙のバーが「母音 / 子音」の判定、下段がツマミです。

### 出てこないとき

1. Logic Pro → **設定 → プラグインマネージャー**（メニューバー「Logic Pro」→「設定」）。
2. 検索欄に `CV Rider` または `AtoZ` と入力。
3. 行を選び、右下の **「選択項目をリセットして再スキャン」**。
4. 「使用」列にチェックが付けば OK。「検証失敗」なら、その行をダブルクリックして出るログを添えてご連絡ください。
5. それでも一覧に無い場合は、Finder で `~/Library/Audio/Plug-Ins/Components/` に `CV Rider.component` があるか確認します
   （Finder で「移動」メニューを option キーを押しながら開くと「ライブラリ」が出ます）。

## 5. 最初の音出し（おすすめ手順）

1. **プリセット**（画面上部の「Preset:」）で **Lead Vocal** を選ぶ。
2. **Monitor: Consonants** に切り替えて再生。サ行・タ行・ハ行だけが聞こえる状態を作る。
   - 母音まで聞こえる → **Sensitivity** を左（−2〜−6）
   - サ行が聞こえない → **Sensitivity** を右（+2〜+4）
   - ブレス（息）が混ざる → Sensitivity を左、または **Breathy** プリセット
3. **Monitor: Off** に戻す（戻し忘れ注意）。
4. 母音の **Target** を狙いのレベル（目安 −18 dB）、子音の **Target** をその 4〜8 dB 下に。
5. サ行が刺さる → 子音の **Trim** を −2〜−4 dB。歌詞が聞き取りにくい → +2 dB。
6. **Bypass** で ON/OFF を聞き比べて、かけすぎていないか確認。

### Logic 側の設定で気をつけること

- **プラグインディレイ補正**: 既定 3 ms のルックアヘッド分の遅れを Logic に報告しています。
  Logic Pro → 設定 → オーディオ → 一般 → 「プラグインディレイ補正」が **すべて** になっていることを確認（既定でなっています）。
- **録音しながらのモニター**（歌いながら CV Rider を通す）で遅れが気になるときは、**Lookahead** を 0 にします。
- **バウンス**: リアルタイム再生と同じ結果になります。書き出す前に Monitor が Off であることを確認してください。
- **プロジェクト保存**: パラメータとプリセット番号は Logic のプロジェクトに保存されます。

## 6. 別の Mac（Mac mini など）へも入れるとき

同じ zip を持っていき、同じ手順で `Install CV Rider.command` をダブルクリックするだけです
（AirDrop や USB で `cvrider-macos` フォルダを丸ごとコピーしても構いません）。

## 7. アンインストール

Finder で次の 2 つをゴミ箱へ入れ、Logic を再起動します。

```
~/Library/Audio/Plug-Ins/Components/CV Rider.component
~/Library/Audio/Plug-Ins/VST3/CV Rider.vst3
```

## 8. 新しいビルドに更新するとき

1 の直接リンクからもう一度ダウンロードし、3 の手順を繰り返すだけです（古いものは自動で置き換えます）。
更新内容は [CHANGELOG.md](CHANGELOG.md) に書いてあります。
