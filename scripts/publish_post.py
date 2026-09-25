#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_post.py — 發班級紀事：data/class-posts/<slug>.md（＋同名資料夾裡的照片）→ 網站。

  寫到（docs/DATA-MODEL.md §2.6、§2.12）：
    posts/<slug>/images/<pid>、posts/<slug>/thumbs/<pid>   照片（顯示圖、縮圖）
    posts/<slug>/content/main                              正文區塊
    posts/<slug>                                           摘要（列表用；最後寫）

  md 檔頭（--- 包起來）：
    title:    標題（必填，1–120 字）
    date:     日期 YYYY-MM-DD（必填）
    category: 分類（必填，要是 config/class.json 的 categories 之一）
    cover:    封面照片的檔名（選填；不寫就用正文第一張）
    excerpt:  列表卡片的摘要（選填，≤ 200 字；不寫就取正文開頭）
    visible:  true／false（選填，預設 true；false＝下架，家長看不到）
  正文寫法見 data-template/class-posts/README.md（段落、## 標題、- 清單、> 引言、![圖說](檔名)、[[video:https://…]]）。

用法：
  python3 scripts/publish_post.py <slug>                    # 預覽（不上線）
  python3 scripts/publish_post.py <slug> --open             # 預覽並打開瀏覽器
  python3 scripts/publish_post.py <slug> --publish          # 上線
  python3 scripts/publish_post.py <slug> --publish --update # 已上線的再發一次（改內容、下架）
  （Windows：py -3 scripts/publish_post.py …）
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, schema  # noqa: E402
from lib import blocks as blk  # noqa: E402
from lib import frontmatter as fm  # noqa: E402
from lib import preview as pv  # noqa: E402
from lib import publishing as pub  # noqa: E402
from lib.firestore_rest import SERVER_TIME  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

ALLOWED = ("title", "date", "category", "cover", "excerpt", "visible")
REQUIRED = ("title", "date", "category")


def slug_arg(s):
    s = s.strip()
    if s.endswith(".md"):
        s = s[:-3]
    return Path(s).name


def build(slug, cfg):
    """讀本機檔 → Draft。任何問題丟 PublishError。"""
    if not schema.valid_slug(slug):
        raise pub.PublishError("檔名（slug）格式不對：要是「日期-英文小寫與數字」，例如 2026-10-01-autumn-walk（最長 80 字）")
    base = paths.data_dir() / "class-posts"
    md = base / (slug + ".md")
    folder = base / slug
    meta, body, first = pub.read_md(md, ALLOWED, REQUIRED)
    problems = []
    title = str(meta["title"]).strip()
    date = str(meta["date"]).strip()
    category = str(meta["category"]).strip()
    if not (1 <= len(title) <= 120):
        problems.append("title 要 1–120 字")
    if not schema.valid_date(date):
        problems.append("date 要寫成 YYYY-MM-DD（例如 2026-10-01）")
    if cfg.categories and category not in cfg.categories:
        problems.append("category「%s」不在 config/class.json 的分類裡（可以用：%s）" % (category, "、".join(cfg.categories)))
    try:
        visible = fm.as_bool(meta.get("visible"), True, "visible")
    except fm.FrontmatterError as e:
        problems += e.problems
        visible = True
    if problems:
        raise pub.PublishError(["%s：%s" % (pub.rel(md), x) for x in problems])
    cover_name = str(meta.get("cover") or "").strip()
    final, photos, cover, srcs, unused = pub.body_with_photos(md, folder, body, first, cover_name)
    if not final:
        raise pub.PublishError("%s：正文是空的" % pub.rel(md))
    excerpt = str(meta.get("excerpt") or "").strip() or blk.excerpt(final)
    if len(excerpt) > 200:
        raise pub.PublishError("%s：excerpt 超過 200 字" % pub.rel(md))
    owner = "posts/" + slug
    content = {"blocks": final, "updatedAt": SERVER_TIME}
    summary_doc = {
        "title": title, "date": date, "category": category, "excerpt": excerpt,
        "coverPid": cover.pid if cover else None, "coverThumb": cover.inline() if cover else None,
        "photoCount": len(photos), "visible": visible,
        "publishedAt": SERVER_TIME, "updatedAt": SERVER_TIME,
    }
    summary = [
        "班級紀事：%s" % slug,
        "標題：%s｜日期：%s｜分類：%s" % (title, date, category),
        "上線後誰看得到：%s" % ("名單上的家長與同仁（登入後）" if visible else "只有導師（visible: false＝下架）"),
        "正文：" + pub.block_counts(final),
        pub.photo_summary(photos) + ("，封面：%s" % (cover_name or srcs[0]) if photos else ""),
        "列表摘要：%s" % excerpt,
    ]
    if unused:
        summary.append("提醒：資料夾裡有 %d 張照片沒被正文用到，不會上傳（%s）"
                       % (len(unused), "、".join(unused[:5]) + ("…" if len(unused) > 5 else "")))
    body_html = pv.blocks_html(final, pub.pid_src(photos))
    if cover:
        body_html = ('<figure><img src="%s" alt="封面"><figcaption>列表上的封面</figcaption></figure>'
                     % pv.esc(pv.data_uri(cover.small.data))) + body_html
    html = pv.page("預覽：" + title, title, [date, category, "" if visible else "已下架"], summary, body_html)
    docs = [(owner + "/content/main", content, "post_content"), (owner, summary_doc, "post")]
    return pub.Draft("post", slug, owner, photos, docs, summary, html)


def main(argv=None):
    ap = argparse.ArgumentParser(description="發班級紀事（預設只預覽；--publish 才上線）")
    ap.add_argument("slug", help="data/class-posts/ 裡的檔名（不含 .md），例如 2026-10-01-autumn-walk")
    pub.add_common_args(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        cfg = classcfg.load()
    except classcfg.ConfigError as e:
        return pub.fail([str(e)])
    slug = slug_arg(a.slug)
    try:
        draft = build(slug, cfg)
    except pub.PublishError as e:
        return pub.fail(e.lines)
    return pub.run(draft, a, cfg, "publish_post.py", "posts/" + slug, after=pub.refresh_post_index)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
