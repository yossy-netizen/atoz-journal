# AtoZ Sound Journal（暫定サイト）

AtoZ DTM School / AtoZ Studio の読み物サイト「AtoZ Sound Journal」の暫定リポジトリ。
公開URL: **https://journal.atoz-studio.com/**（独自ドメイン・docs/CNAMEで管理）
正式サイト（Claude Codeで構築予定）への移行までの間、公開ワークフローの確立と運用を担う。

## 仕組み

- `src/articles/*.md` … 記事ソース（正本は Google Drive `AtoZ_Sound_Journal/02_記事Library/`）
- `tools/build.py` … 静的サイトジェネレータ（`src` → `docs`）
- `docs/` … GitHub Pages 公開ルート（main ブランチ / docs フォルダ）
- `state.json` … 公開履歴（二重投稿防止の正本）

## 記事フォーマット

新規記事は YAML フロントマター形式:

```markdown
---
title: 記事タイトル
date: 2026-07-20
tags: [ハーモニー, 音楽理論]
series: ハーモニーの正体シリーズ
series_no: 1
description: 検索結果に表示される説明文
---
本文（Markdown）
```

既存の完成稿（本文末尾に `<!-- ===== 本文ここまで ===== -->` コメントでメタ情報を持つ
AtoZ形式）もそのままビルド可能（2WAYパーサ）。

## ビルド

```bash
pip install markdown pyyaml --quiet
python3 tools/build.py
```

## 運用（Cowork スケジュールタスク）

1. **Journal article writer**（週1）… 承認前記事を Google Drive `01-4_完成稿_精査前` に自動作成
2. **Journal review reminder**（週1・金）… 精査待ち一覧を阿藤さんに通知。承認 = Drive で `02-1_完成_公開待ち` へ移動
3. **Journal auto poster**（週2・月木）… `02-1` の最古記事を取得 → ここに commit & push → サイト反映 → `02-2_公開済み` へコピー

運用ドキュメント: Google Drive `AtoZ_Master/Operations_Manual/Journal/`
