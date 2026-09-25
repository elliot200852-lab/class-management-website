#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_album.py — 上傳相簿：data/albums/<slug>.md（相簿資訊）＋ data/albums/<slug>/ 裡的全部照片 → 網站。

  寫到（docs/DATA-MODEL.md §2.9、§2.12）：
    albums/<slug>/images/<pid>、albums/<slug>/thumbs/<pid>   照片（格子依檔名順序排）
    albums/<slug>                                            相簿資訊（最後寫）

  md 檔頭：
    title:    相簿名稱（必填，1–80 字）
    date:     日期 YYYY-MM-DD（必填）
    order:    排序用的整數（選填，預設 0；小的排前面）
    cover:    封面照片的檔名（選填；預設第一張）
    link:     整本相簿另外的外部連結（選填，https://，例如老師自己分享的雲端硬碟資料夾）
    videos:   影片連結清單（選填，最多 20 支；影片不上傳，只放老師自選分享範圍的連結）
      - 影片標題 | https://www.youtube.com/watch?v=...
    captions: 照片圖說（選填；沒寫的照片就沒有圖說，不要替老師編）
      - 檔名.jpg | 圖說
    visible:  true／false（選填，預設 true）
  正文（檔頭下面的文字）＝相簿說明，純文字，最多 1000 字。

  照片檔名只用來排順序，**不會上傳**（原始檔名可能含姓名或時間）。原圖留在老師自己的電腦。

用法：
  python3 scripts/publish_album.py <slug>                    # 預覽（不上線）
  python3 scripts/publish_album.py <slug> --publish          # 上線
  python3 scripts/publish_album.py <slug> --publish --update # 加照片、改說明、換封面、下架
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

ALLOWED = ("title", "date", "order", "cover", "link", "videos", "captions", "visible")
REQUIRED = ("title", "date")
MAX_PHOTOS = 300


def build(slug, cfg):
    if not schema.valid_slug(slug):
        raise pub.PublishError("相簿代號（slug）格式不對：要是「日期-英文小寫與數字」，例如 2026-10-01-sports-day")
    base = paths.data_dir() / "albums"
    md = base / (slug + ".md")
    folder = base / slug
    meta, body, _ = pub.read_md(md, ALLOWED, REQUIRED)
    problems = []
    title = str(meta["title"]).strip()
    date = str(meta["date"]).strip()
    if not (1 <= len(title) <= 80):
        problems.append("title 要 1–80 字")
    if not schema.valid_date(date):
        problems.append("date 要寫成 YYYY-MM-DD")
    try:
        visible = fm.as_bool(meta.get("visible"), True, "visible")
        order = fm.as_int(meta.get("order"), 0, "order", -999999999, 999999999)
    except fm.FrontmatterError as e:
        problems += e.problems
        visible, order = True, 0
    description = body.strip("\n").strip()
    if len(description) > 1000:
        problems.append("相簿說明（檔頭下面的文字）超過 1000 字")
    link = str(meta.get("link") or "").strip()
    if link and not blk.is_https(link):
        problems.append("link 要是 https:// 開頭的網址")
    videos = []
    for item in fm.as_list(meta.get("videos")):
        t, u = fm.pair(item)
        if not u and blk.is_https(t):
            t, u = "", t
        if not blk.is_https(u):
            problems.append("videos 的「%s」網址不是 https://（寫法：- 標題 | https://…）" % item[:40])
        elif len(t) > 80:
            problems.append("videos 的標題超過 80 字")
        else:
            videos.append({"title": t, "url": u})
    if len(videos) > 20:
        problems.append("videos 最多 20 支")
    captions = {}
    for item in fm.as_list(meta.get("captions")):
        n, c = fm.pair(item)
        if not n or not c:
            problems.append("captions 的寫法是「- 檔名 | 圖說」：%s" % item[:40])
        elif len(c) > 300:
            problems.append("captions 的圖說超過 300 字：%s" % n)
        else:
            captions[n] = c
    files = pub.folder_photos(folder)
    if not files and not videos and not link:
        problems.append("%s/ 裡沒有照片，也沒有影片或連結" % pub.rel(folder))
    if len(files) > MAX_PHOTOS:
        problems.append("一本相簿最多 %d 張（現在 %d 張）：請拆成兩本" % (MAX_PHOTOS, len(files)))
    names = [p.name for p in files]
    for n in captions:
        if n not in names:
            problems.append("captions 寫了 %s，但資料夾裡沒有這張" % n)
    cover_name = str(meta.get("cover") or "").strip()
    if cover_name and cover_name not in names:
        problems.append("cover 的 %s 不在資料夾裡" % cover_name)
    if problems:
        raise pub.PublishError(["%s：%s" % (pub.rel(md), x) for x in problems])
    photos, pids = pub.process_photos([(p, captions.get(p.name, "")) for p in files])
    by_name = dict(zip(names, pids))
    cover = None
    if photos:
        cp = by_name[cover_name] if cover_name else photos[0].pid
        cover = next(ph for ph in photos if ph.pid == cp)
    owner = "albums/" + slug
    doc = {"title": title, "date": date, "order": order,
           "coverPid": cover.pid if cover else None, "coverThumb": cover.inline() if cover else None,
           "photoCount": len(photos), "videos": videos, "visible": visible, "updatedAt": SERVER_TIME}
    if description:
        doc["description"] = description
    if link:
        doc["linkUrl"] = link
    summary = [
        "相簿：%s" % slug,
        "名稱：%s｜日期：%s" % (title, date),
        "上線後誰看得到：%s" % ("名單上的家長與同仁（登入後）" if visible else "只有導師（visible: false＝下架）"),
        pub.photo_summary(photos) + ("，封面：%s" % (cover_name or names[0]) if photos else ""),
        "有圖說的照片：%d 張｜影片連結：%d 支%s" % (sum(1 for p in photos if p.caption), len(videos),
                                                "｜外部連結：有" if link else ""),
    ]
    body_html = ""
    if description:
        body_html += '<p class="body-pre">%s</p>' % pv.esc(description)
    for v in videos:
        body_html += pv.blocks_html([{"t": "video", "url": v["url"], "title": v["title"] or "影片"}], {})
    if link:
        body_html += '<p>相簿連結：<a href="%s" rel="noopener noreferrer" target="_blank">%s</a></p>' % (pv.esc(link), pv.esc(link))
    body_html += pv.grid_html([(pv.data_uri(p.thumb.data), p.caption) for p in photos])
    html = pv.page("預覽：" + title, title, [date, "" if visible else "已下架"], summary, body_html)
    return pub.Draft("album", slug, owner, photos, [(owner, doc, "album")], summary, html)


def main(argv=None):
    ap = argparse.ArgumentParser(description="上傳相簿（預設只預覽；--publish 才上線）")
    ap.add_argument("slug", help="data/albums/ 裡的相簿代號（.md 檔名，不含 .md）")
    pub.add_common_args(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        cfg = classcfg.load()
    except classcfg.ConfigError as e:
        return pub.fail([str(e)])
    slug = Path(a.slug[:-3] if a.slug.endswith(".md") else a.slug).name
    try:
        draft = build(slug, cfg)
    except pub.PublishError as e:
        return pub.fail(e.lines)
    return pub.run(draft, a, cfg, "publish_album.py", "albums/" + slug, keep_published=False)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
