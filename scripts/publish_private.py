#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_private.py — 發私密紀事：只有「私密讀者」看得到（docs/DATA-MODEL.md §2.10）。

  來源：data/private-posts/<slug>.md（＋同名資料夾裡的照片）
  寫到：private_posts/<slug>/images/<pid>、private_posts/<slug>/thumbs/<pid>、private_posts/<slug>（摘要＋正文同一份）

  md 檔頭：title（必填）、date（必填）、cover、excerpt、visible（寫法同班級紀事，但沒有 category）。

  收看名單＝資料庫的 private_allowlist，由 contacts.csv 的「私密讀者」欄決定，改名單走 access_sync.py；
  這支的 --viewers 只唯讀地數一下目前有幾位私密讀者（不含導師），不改名單。

用法：
  python3 scripts/publish_private.py <slug>                    # 預覽（不上線）
  python3 scripts/publish_private.py <slug> --publish          # 上線
  python3 scripts/publish_private.py <slug> --publish --update # 已上線的再發一次（改內容、visible: false 下架）
  python3 scripts/publish_private.py --viewers                 # 目前的收看名單有幾位（唯讀）
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, schema, gauth  # noqa: E402
from lib import blocks as blk  # noqa: E402
from lib import frontmatter as fm  # noqa: E402
from lib import preview as pv  # noqa: E402
from lib import publishing as pub  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

ALLOWED = ("title", "date", "cover", "excerpt", "visible")
REQUIRED = ("title", "date")


def build(slug, cfg):
    if not schema.valid_slug(slug):
        raise pub.PublishError("檔名（slug）格式不對：要是「日期-英文小寫與數字」，例如 2026-10-01-note（最長 80 字）")
    base = paths.data_dir() / "private-posts"
    md = base / (slug + ".md")
    folder = base / slug
    meta, body, first = pub.read_md(md, ALLOWED, REQUIRED)
    title = str(meta["title"]).strip()
    date = str(meta["date"]).strip()
    problems = []
    if not (1 <= len(title) <= 120):
        problems.append("title 要 1–120 字")
    if not schema.valid_date(date):
        problems.append("date 要寫成 YYYY-MM-DD")
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
    owner = "private_posts/" + slug
    doc = {
        "title": title, "date": date, "excerpt": excerpt, "blocks": final,
        "coverPid": cover.pid if cover else None, "coverThumb": cover.inline() if cover else None,
        "photoCount": len(photos), "visible": visible,
        "publishedAt": fr.SERVER_TIME, "updatedAt": fr.SERVER_TIME,
    }
    summary = [
        "私密紀事：%s" % slug,
        "標題：%s｜日期：%s" % (title, date),
        "上線後誰看得到：%s" % ("只有私密讀者名單上的人與導師（登入後）" if visible else "只有導師（visible: false＝下架）"),
        "正文：" + pub.block_counts(final),
        pub.photo_summary(photos),
    ]
    if unused:
        summary.append("提醒：資料夾裡有 %d 張照片沒被正文用到，不會上傳" % len(unused))
    html = pv.page("預覽：" + title, title, [date, "私密", "" if visible else "已下架"], summary,
                   pv.blocks_html(final, pub.pid_src(photos)))
    return pub.Draft("private", slug, owner, photos, [(owner, doc, "private_post")], summary, html)


def viewers(cfg, emulator):
    try:
        client = fr.make_client(cfg.project_id, emulator_flag=emulator)
        keys = [d.id for d in client.list_docs("private_allowlist", mask=["updatedAt"])]
    except ValueError as e:
        return pub.fail([str(e)])
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        return 1
    others = [k for k in keys if k != cfg.teacher_key]
    print("私密紀事的收看名單（%s）：私密讀者 %d 位（不含導師）%s"
          % (client.describe_target(), len(others), "" if cfg.teacher_key in keys else "；✗ 導師不在名單裡"))
    print("  要增減名單：請老師在 data/contacts.csv 的「私密讀者」欄改，再跑 access_sync.py（先預覽，再 --apply）。")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="發私密紀事（預設只預覽；--publish 才上線）")
    ap.add_argument("slug", nargs="?", help="data/private-posts/ 裡的檔名（不含 .md）")
    ap.add_argument("--viewers", action="store_true", help="只數一下目前的收看名單（唯讀）")
    pub.add_common_args(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        cfg = classcfg.load()
    except classcfg.ConfigError as e:
        return pub.fail([str(e)])
    if a.viewers:
        return viewers(cfg, a.emulator)
    if not a.slug:
        ap.error("要給檔名（slug），或加 --viewers")
    slug = Path(a.slug[:-3] if a.slug.endswith(".md") else a.slug).name
    try:
        draft = build(slug, cfg)
    except pub.PublishError as e:
        return pub.fail(e.lines)
    return pub.run(draft, a, cfg, "publish_private.py", "private_posts/" + slug)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
