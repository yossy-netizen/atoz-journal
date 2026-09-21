CV Rider（子音 / 母音ライダー）— Mac へのインストール
=====================================================

■ 方法 A: ターミナルに 1 行貼るだけ（おすすめ・警告が出ません）

  ターミナル（⌘ + スペース → 「ターミナル」）を開いて、次の 1 行を貼り付けて Enter:

cd ~/Downloads && curl -fL -o cvrider-macos.zip https://github.com/yossy-netizen/atoz-journal/releases/download/cvrider-latest/cvrider-macos.zip && rm -rf cvrider-macos && ditto -x -k cvrider-macos.zip . && cd cvrider-macos && chmod +x install-mac.sh && ./install-mac.sh .

  「* * PASS」と出れば成功です。


■ 方法 B: このフォルダの「Install CV Rider.command」をダブルクリック

  → ターミナルが開き、自動でインストールが進みます。
  → 「"Install CV Rider.command" は開発元を確認できないため開けません」と出た場合:
     ファイルを「右クリック（または control + クリック）→ 開く → 開く」でもう一度実行してください。
     それでも開けない場合: システム設定 → プライバシーとセキュリティ → 一番下の
     「"Install CV Rider.command" は開発元を確認できないため…」の横の「このまま開く」を押してください。


■ インストール先

     ~/Library/Audio/Plug-Ins/Components/CV Rider.component   （AU: Logic Pro 用）
     ~/Library/Audio/Plug-Ins/VST3/CV Rider.vst3              （VST3: Cubase / Studio One など）


■ Logic Pro で開く

  Logic Pro を起動（起動中なら一度終了して起動）。
  ボーカルトラックの Audio FX スロット → Audio Units → AtoZ Studio → CV Rider

  出てこないとき:
  Logic Pro → 設定 → プラグインマネージャー → 「AtoZ Studio」で絞り込み → CV Rider を選択 →
  「選択項目をリセットして再スキャン」。


詳しい手順とツマミの説明: リポジトリの plugin/docs/logic-setup.md、guide-for-everyone.md
