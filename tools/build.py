#!/usr/bin/env python3
"""
AtoZ Sound Journal — 静的サイトジェネレータ（暫定版）
src/articles/*.md → docs/ を生成する。

対応する記事フォーマット（2WAY）:
  A) YAMLフロントマター形式（新規記事の標準）
     ---
     title: 記事タイトル
     date: 2026-07-20
     tags: [ハーモニー, 音楽理論]
     series: ハーモニーの正体シリーズ
     series_no: 1
     description: メタ説明文
     ---
     本文（Markdown）

  B) AtoZ既存形式（01-4の既存完成稿）
     # タイトル
     **AtoZ Sound Journal ｜ ○○シリーズ 第N回**
     著：AZ / AtoZ Studio
     ...本文...
     <!-- ===== 本文ここまで。以下は公開設定用メモ ===== -->
     - **meta description...** : 説明文
     - **フォーカスキーワード:** タグ1, タグ2

使い方: python3 tools/build.py
"""
import json
import re
import unicodedata
from datetime import date
from pathlib import Path

import markdown
import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "articles"
DOCS = ROOT / "docs"
ARTICLES_OUT = DOCS / "articles"

SITE_TITLE = "AtoZ Sound Journal"
SITE_TAGLINE = "音楽の営みに、敬意を。― プロの現場から届ける読み物"
SITE_FOOTER = "AtoZ Studio / AtoZ DTM School（高田馬場・荻窪・芦花公園）"
BASE_PATH = "/atoz-journal"  # GitHub Pages のプロジェクトパス

MD = markdown.Markdown(extensions=["extra", "toc", "nl2br"])


def parse_frontmatter(text: str):
    """YAMLフロントマター形式をパース。なければ None を返す。"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    return meta, m.group(2)


def parse_atoz_legacy(text: str):
    """AtoZ既存形式（本文 + 末尾コメント区切りメタ）をパース。"""
    meta = {}
    # タイトル: 最初の h1
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if m:
        meta["title"] = m.group(1).strip()
    # シリーズ表記: **AtoZ Sound Journal ｜ ○○シリーズ 第N回**
    m = re.search(r"\*\*AtoZ Sound Journal\s*[｜|]\s*(.+?)\s+第(\d+)回\*\*", text)
    if m:
        meta["series"] = m.group(1).strip()
        meta["series_no"] = int(m.group(2))
    else:
        m2 = re.search(r"\*\*AtoZ Sound Journal\s*[｜|]\s*(.+?)\*\*", text)
        if m2:
            meta["series"] = m2.group(1).strip()
    # 本文とメタ部の分離
    body = text
    m = re.search(r"<!--\s*=+\s*本文ここまで.*?-->", text, re.DOTALL)
    tail = ""
    if m:
        body = text[: m.start()]
        tail = text[m.end():]
    # meta description
    m = re.search(r"\*\*meta description[^:：]*[:：]?\*\*\s*[:：]?\s*(.+)", tail)
    if m:
        meta["description"] = m.group(1).strip()
    # フォーカスキーワード → tags
    m = re.search(r"\*\*フォーカスキーワード[:：]?\*\*\s*[:：]?\s*(.+)", tail)
    if m:
        tags = [t.strip() for t in re.split(r"[,、，]", m.group(1)) if t.strip()]
        meta["tags"] = tags
    return meta, body


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKC", name)
    s = re.sub(r"\.md$", "", s)
    s = re.sub(r"_v\d+$", "", s)  # 版サフィックス(_v2/_v4等)は公開URL・slugに残さない
    s = re.sub(r"[^A-Za-z0-9぀-ヿ一-鿿-]+", "-", s)
    return s.strip("-").lower() or "article"


def load_articles():
    articles = []
    for p in sorted(SRC.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        parsed = parse_frontmatter(text)
        if parsed:
            meta, body = parsed
        else:
            meta, body = parse_atoz_legacy(text)
        title = str(meta.get("title") or p.stem)
        # 本文先頭の重複h1を除去（タイトルはテンプレートで出す）
        body = re.sub(r"^#\s+.+\n", "", body.lstrip(), count=1)
        # 既存形式のシリーズ行・著者行も本文冒頭から除去
        body = re.sub(r"^\*\*AtoZ Sound Journal[^\n]*\*\*\s*\n", "", body.lstrip(), count=1)
        body = re.sub(r"^著[:：][^\n]*\n", "", body.lstrip(), count=1)
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in re.split(r"[,、，]", tags) if t.strip()]
        d = meta.get("date")
        if isinstance(d, date):
            d = d.isoformat()
        articles.append({
            "slug": slugify(p.stem),
            "title": title,
            "date": str(d) if d else "",
            "tags": [str(t) for t in tags],
            "series": meta.get("series", ""),
            "series_no": meta.get("series_no", ""),
            "description": str(meta.get("description", "")).strip(),
            "body_md": body,
            "source_file": p.name,
        })
    # 新着順（日付降順・日付なしは最後）
    articles.sort(key=lambda a: a["date"] or "0000-00-00", reverse=True)
    return articles


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def page_shell(title: str, description: str, content: str, depth: int = 0) -> str:
    rel = "../" * depth
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="stylesheet" href="{rel}assets/style.css">
</head>
<body>
<header class="site-header">
  <a class="site-title" href="{rel}index.html">AtoZ<span>Sound Journal</span></a>
  <p class="site-tagline">{esc(SITE_TAGLINE)}</p>
</header>
<main class="container">
{content}
</main>
<footer class="site-footer">
  <p>{esc(SITE_FOOTER)}</p>
  <p class="footer-note">プロの制作現場の知識を根幹に、音楽の歴史と文化への敬意を込めてお届けします。</p>
</footer>
</body>
</html>
"""


def tag_chips(tags, rel=""):
    return "".join(
        f'<a class="tag" href="{rel}index.html?tag={esc(t)}">{esc(t)}</a>' for t in tags
    )


def build_article_page(a):
    MD.reset()
    body_html = MD.convert(a["body_md"])
    series_line = ""
    if a["series"]:
        no = f" 第{a['series_no']}回" if a["series_no"] else ""
        series_line = f'<p class="article-series">{esc(a["series"])}{no}</p>'
    date_line = f'<time datetime="{esc(a["date"])}">{esc(a["date"])}</time>' if a["date"] else ""
    content = f"""
<article class="article">
  <header class="article-header">
    {series_line}
    <h1>{esc(a["title"])}</h1>
    <div class="article-meta">{date_line}<div class="tags">{tag_chips(a["tags"], rel="../")}</div></div>
  </header>
  <div class="article-body">
{body_html}
  </div>
  <div class="article-back"><a href="../index.html">← 記事一覧へ戻る</a></div>
</article>
"""
    desc = a["description"] or f"{a['title']} — {SITE_TITLE}"
    return page_shell(f"{a['title']} | {SITE_TITLE}", desc, content, depth=1)


def build_index(articles):
    all_tags = sorted({t for a in articles for t in a["tags"]})
    tag_buttons = '<button class="tag-filter active" data-tag="">すべて</button>' + "".join(
        f'<button class="tag-filter" data-tag="{esc(t)}">{esc(t)}</button>' for t in all_tags
    )
    cards = []
    for a in articles:
        tags_attr = esc(json.dumps(a["tags"], ensure_ascii=False))
        series_line = f'<p class="card-series">{esc(a["series"])}</p>' if a["series"] else ""
        desc = a["description"][:90] + ("…" if len(a["description"]) > 90 else "")
        date_html = f'<time>{esc(a["date"])}</time>' if a["date"] else ""
        cards.append(f"""
  <article class="card" data-tags='{tags_attr}'>
    {series_line}
    <h2><a href="articles/{a['slug']}.html">{esc(a["title"])}</a></h2>
    <p class="card-desc">{esc(desc)}</p>
    <div class="card-meta">{date_html}<div class="tags">{tag_chips(a["tags"])}</div></div>
  </article>""")
    cards_html = "\n".join(cards) if cards else '<p class="empty">記事は準備中です。</p>'
    content = f"""
<div class="tag-filters" id="tagFilters">{tag_buttons}</div>
<div class="cards" id="cards">
{cards_html}
</div>
<script>
(function() {{
  var buttons = document.querySelectorAll('.tag-filter');
  var cards = document.querySelectorAll('.card');
  function apply(tag) {{
    buttons.forEach(function(b) {{ b.classList.toggle('active', b.dataset.tag === tag); }});
    cards.forEach(function(c) {{
      var tags = JSON.parse(c.dataset.tags || '[]');
      c.style.display = (!tag || tags.indexOf(tag) !== -1) ? '' : 'none';
    }});
  }}
  buttons.forEach(function(b) {{
    b.addEventListener('click', function() {{ apply(b.dataset.tag); }});
  }});
  var params = new URLSearchParams(location.search);
  var t = params.get('tag');
  if (t) apply(t);
}})();
</script>
"""
    return page_shell(SITE_TITLE, f"{SITE_TITLE} — {SITE_TAGLINE}", content, depth=0)


def main():
    ARTICLES_OUT.mkdir(parents=True, exist_ok=True)
    articles = load_articles()
    # 古い記事HTMLを一掃してから再生成（削除された記事を残さない）
    for old in ARTICLES_OUT.glob("*.html"):
        old.unlink()
    for a in articles:
        out = ARTICLES_OUT / f"{a['slug']}.html"
        out.write_text(build_article_page(a), encoding="utf-8")
    (DOCS / "index.html").write_text(build_index(articles), encoding="utf-8")
    manifest = [{k: a[k] for k in ("slug", "title", "date", "tags", "series", "source_file")}
                for a in articles]
    (DOCS / "articles.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"built {len(articles)} article(s)")
    for a in articles:
        print(f"  - {a['date'] or '(no date)'} {a['title']} [{', '.join(a['tags'])}]")


if __name__ == "__main__":
    main()
