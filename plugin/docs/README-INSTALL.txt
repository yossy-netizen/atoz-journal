CV Rider（子音 / 母音ライダー）— Mac へのインストール
=====================================================

1. このフォルダの中の「Install CV Rider.command」をダブルクリックします。
   → ターミナルが開き、自動でインストールが進みます。
   → 「"Install CV Rider.command" は開発元を確認できないため開けません」と出た場合:
      ファイルを「右クリック（または control + クリック）→ 開く → 開く」でもう一度実行してください。
      それでも開けない場合: システム設定 → プライバシーとセキュリティ → 一番下の
      「"Install CV Rider.command" は開発元を確認できないため…」の横の「このまま開く」を押してください。

2. 「=== インストール完了 ===」と出たら Enter で閉じます。
   入る場所:
     ~/Library/Audio/Plug-Ins/Components/CV Rider.component   （AU: Logic Pro 用）
     ~/Library/Audio/Plug-Ins/VST3/CV Rider.vst3              （VST3: Cubase / Studio One など）

3. Logic Pro を起動（起動中なら一度終了して起動）。
   ボーカルトラックの Audio FX スロット → Audio Units → AtoZ Studio → CV Rider

Logic に出てこないとき:
   Logic Pro → 設定 → プラグインマネージャー → 「AtoZ Studio」で絞り込み → CV Rider を選択 →
   「選択項目をリセットして再スキャン」。

詳しい手順とツマミの説明: リポジトリの plugin/docs/logic-setup.md、guide-for-everyone.md
