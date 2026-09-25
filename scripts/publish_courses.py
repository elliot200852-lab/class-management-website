#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_courses.py — 發課程頁：課程介紹、課程說明影片、各科課程大綱卡、課表（docs/DATA-MODEL.md §2.11 的 course／schedule）。

  來源：data/courses/<頁面代號>.md（＋同名資料夾 data/courses/<頁面代號>/ 裡的照片）
        · 頁面代號 courses 或 courses-<英數>（例如 courses-term）→ 課程（kind: course）
        · 頁面代號 schedule 或 schedule-<英數>                  → 課表（kind: schedule）
        · data/courses/ 底下的**子資料夾**（每個課程單元的 records.md 課程紀錄）一律不讀、不上網
  寫到：pages/<頁面代號>（＋照片 pages/<頁面代號>/images|thumbs/<pid>）；網站的「課程」頁全部列出來。

  課程頁的寫法：
    ---
    title: 本學期課程            （必填，1–80 字）
    order: 1                  （選填，同種類裡的排序，小的在前）
    visible: true             （選填；false＝下架，只有導師看得到）
    ---
    課程介紹正文（寫法同班級紀事，可以放照片）

    ## 課程說明影片
    [[video:https://www.youtube.com/watch?v=…|第一週導覽]]

    ## 各科課程大綱
    ### 英文（王老師）
    這學期讀三本繪本、唱英文歌。（≤ 300 字，家長看得懂的白話）
    網址：https://drive.google.com/file/d/…/view   （選填：大綱 PDF 的分享連結）
  「## 課程說明影片」「## 各科課程大綱」這兩個標題名稱是固定的；其他 ## 標題都算正文。

  課表的寫法：正文只放一個 Markdown 表格（第一列、第一欄是表頭；最多 20 列 × 10 欄，每格 ≤ 40 字）。

用法（Windows 把 python3 換成 py -3）：
  python3 scripts/publish_courses.py <頁面代號>                    # 預覽
  python3 scripts/publish_courses.py <頁面代號> --publish          # 上線
  python3 scripts/publish_courses.py <頁面代號> --publish --update # 已上線的再發一次（改內容、下架）
"""
import re
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, schema, mdlite  # noqa: E402
from lib import blocks as blk  # noqa: E402
from lib import frontmatter as fm  # noqa: E402
from lib import preview as pv  # noqa: E402
from lib import publishing as pub  # noqa: E402
from lib.firestore_rest import SERVER_TIME  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

ALLOWED = ("title", "order", "visible")
REQUIRED = ("title",)
PAGE_RE = re.compile(r"^(courses|schedule)(-[a-z0-9]+)*$")
VIDEOS_HEAD = "課程說明影片"
CARDS_HEAD = "各科課程大綱"
URL_LINE_RE = re.compile(r"^(?:網址|連結)\s*[：:]\s*(\S+)\s*$")
MAX_CARDS, MAX_VIDEOS = 30, 20
MAX_ROWS, MAX_COLS, MAX_CELL = 20, 10, 40


def kind_of(page_id):
    return "schedule" if page_id.startswith("schedule") else "course"


def split_sections(body):
    """正文 → (正文行, 影片行, 卡片行)；各自帶原本的行號（從 0 起算，給錯誤訊息用）。"""
    main, videos, cards = [], [], []
    cur = main
    for i, line in enumerate(body.split("\n")):
        s = line.strip()
        if s.startswith("## ") and not s.startswith("### "):
            head = s[3:].strip()
            if head == VIDEOS_HEAD:
                cur = videos
                continue
            if head == CARDS_HEAD:
                cur = cards
                continue
            cur = main
        cur.append((i, line))
    return main, videos, cards


def parse_videos(lines, first):
    out, problems = [], []
    for i, line in lines:
        s = line.strip()
        if not s:
            continue
        m = mdlite.VIDEO_RE.match(s)
        if not m:
            problems.append("第 %d 行：「## %s」底下只放 [[video:https://…|標題]] 這種行" % (first + i, VIDEOS_HEAD))
            continue
        url, title = m.group(1), (m.group(2) or "").strip()
        if not blk.is_https(url, 500):
            problems.append("第 %d 行：影片網址要是 https:// 開頭" % (first + i))
            continue
        if len(title) > blk.LIMITS["video_title"]:
            problems.append("第 %d 行：影片標題超過 %d 字" % (first + i, blk.LIMITS["video_title"]))
            continue
        v = {"url": url}
        if title:
            v["title"] = title
        out.append(v)
    if len(out) > MAX_VIDEOS:
        problems.append("影片最多 %d 支" % MAX_VIDEOS)
    return out, problems


def parse_cards(lines, first):
    cards, problems, cur = [], [], None
    for i, line in lines:
        s = line.strip()
        if s.startswith("### "):
            cur = {"title": s[4:].strip(), "text": [], "url": "", "line": first + i}
            cards.append(cur)
            continue
        if not s:
            continue
        if cur is None:
            problems.append("第 %d 行：「## %s」底下每一科用「### 科目名稱」開始" % (first + i, CARDS_HEAD))
            continue
        m = URL_LINE_RE.match(s)
        if m:
            cur["url"] = m.group(1)
            continue
        cur["text"].append(s)
    out = []
    for c in cards:
        text = "\n".join(c["text"]).strip()
        if not (1 <= len(c["title"]) <= 40):
            problems.append("第 %d 行：科目名稱要 1–40 字" % c["line"])
        if len(text) > 300:
            problems.append("第 %d 行起：「%s」的說明超過 300 字（大綱全文放 PDF，這裡寫兩三句就好）" % (c["line"], c["title"][:20]))
        if c["url"] and not blk.is_https(c["url"], 500):
            problems.append("第 %d 行起：「%s」的網址要是 https:// 開頭" % (c["line"], c["title"][:20]))
        card = {"title": c["title"], "text": text}
        if c["url"]:
            card["url"] = c["url"]
        out.append(card)
    if len(out) > MAX_CARDS:
        problems.append("各科課程大綱最多 %d 張卡片" % MAX_CARDS)
    return out, problems


def parse_table(body, first):
    rows, problems, outside = [], [], []
    for i, line in enumerate(body.split("\n")):
        s = line.strip()
        if not s:
            continue
        if not (s.startswith("|") and s.endswith("|")):
            outside.append(first + i)
            continue
        cells = [c.strip() for c in s[1:-1].split("|")]
        if all(re.match(r"^:?-{3,}:?$", c) for c in cells if c) and any(cells):
            continue
        rows.append(cells)
    if outside:
        problems.append("第 %s 行：課表檔只放一個 Markdown 表格（表格以外的文字請刪掉或改放課程頁）"
                        % "、".join(str(x) for x in outside[:5]))
    if not rows:
        problems.append("沒有找到表格：每一列寫成 | 節次 | 一 | 二 | … |")
    if len(rows) > MAX_ROWS:
        problems.append("課表最多 %d 列" % MAX_ROWS)
    for n, r in enumerate(rows, 1):
        if len(r) > MAX_COLS:
            problems.append("課表第 %d 列超過 %d 欄" % (n, MAX_COLS))
        if any(len(c) > MAX_CELL for c in r):
            problems.append("課表第 %d 列有一格超過 %d 字" % (n, MAX_CELL))
    return [{"cells": r} for r in rows], problems


def check_data(kind, data):
    """course／schedule 的 data 形狀（DATA-MODEL §2.11）；lib/schema.py 的 page 檢查不細看這兩種，這裡補上。"""
    p = []
    if kind == "course":
        if set(data) - {"videos", "cards"}:
            p.append("course 的 data 只能有 videos、cards")
        for v in data.get("videos", []):
            if set(v) - {"url", "title"} or not blk.is_https(v.get("url"), 500):
                p.append("影片格式不對")
        for c in data.get("cards", []):
            if set(c) - {"title", "text", "url"} or not (1 <= len(c.get("title", "")) <= 40) or len(c.get("text", "")) > 300:
                p.append("大綱卡格式不對")
    else:
        if set(data) != {"rows"}:
            p.append("schedule 的 data 只能有 rows")
    return p


def build(page_id, cfg):
    if not PAGE_RE.match(page_id) or not schema.PAGE_ID_RE.match(page_id):
        raise pub.PublishError("頁面代號要是 courses、courses-<英數>（例如 courses-term）、schedule 或 schedule-<英數>")
    kind = kind_of(page_id)
    base = paths.data_dir() / "courses"
    md = base / (page_id + ".md")
    folder = base / page_id
    meta, body, first = pub.read_md(md, ALLOWED, REQUIRED)
    problems = []
    title = str(meta["title"]).strip()
    if not (1 <= len(title) <= 80):
        problems.append("title 要 1–80 字")
    try:
        visible = fm.as_bool(meta.get("visible"), True, "visible")
        order = fm.as_int(meta.get("order"), 0, "order", -999999, 999999)
    except fm.FrontmatterError as e:
        problems += e.problems
        visible, order = True, 0
    if problems:
        raise pub.PublishError(["%s：%s" % (pub.rel(md), x) for x in problems])
    doc = {"title": title, "kind": kind, "order": order, "visible": visible, "updatedAt": SERVER_TIME}
    photos, notes, preview_body = [], [], ""
    if kind == "schedule":
        rows, problems = parse_table(body, first)
        if problems:
            raise pub.PublishError(["%s：%s" % (pub.rel(md), x) for x in problems])
        doc["data"] = {"rows": rows}
        notes.append("課表：%d 列" % len(rows))
        preview_body = "<table>" + "".join(
            "<tr>%s</tr>" % "".join(("<th>%s</th>" if (i == 0 or j == 0) else "<td>%s</td>") % pv.esc(c)
                                    for j, c in enumerate(r["cells"])) for i, r in enumerate(rows)) + "</table>"
    else:
        main_lines, video_lines, card_lines = split_sections(body)
        videos, p1 = parse_videos(video_lines, first)
        cards, p2 = parse_cards(card_lines, first)
        if p1 or p2:
            raise pub.PublishError(["%s：%s" % (pub.rel(md), x) for x in p1 + p2])
        keep = {i for i, _ in main_lines}
        main_text = "\n".join(line if n in keep else "" for n, line in enumerate(body.split("\n")))
        final, photos, _cover, _srcs, unused = pub.body_with_photos(md, folder, main_text, first)
        if final:
            doc["blocks"] = final
        data = {}
        if videos:
            data["videos"] = videos
        if cards:
            data["cards"] = cards
        if not final and not data:
            raise pub.PublishError("%s：這一頁是空的（至少要有正文、影片或一張大綱卡）" % pub.rel(md))
        if data:
            doc["data"] = data
        srcmap = pub.pid_src(photos)
        preview_body = pv.blocks_html(final, srcmap)
        for v in videos:
            preview_body += '<p>影片：%s（%s）</p>' % (pv.esc(v.get("title", "")), pv.esc(v["url"]))
        for c in cards:
            preview_body += '<div class="card"><h3>%s</h3><p class="body-pre">%s</p>%s</div>' % (
                pv.esc(c["title"]), pv.esc(c["text"]), ('<p>%s</p>' % pv.esc(c["url"])) if c.get("url") else "")
        if final:
            notes.append("正文：" + pub.block_counts(final))
        notes.append("課程說明影片：%d 支｜各科課程大綱卡：%d 張" % (len(videos), len(cards)))
        if unused:
            notes.append("提醒：資料夾裡有 %d 張照片沒被用到，不會上傳" % len(unused))
    bad = check_data(kind, doc.get("data", {}))
    if bad:
        raise pub.PublishError(["%s：%s" % (pub.rel(md), x) for x in bad])
    owner = "pages/" + page_id
    label = "課表" if kind == "schedule" else "課程"
    summary = ["課程頁：%s（%s）" % (page_id, label), "標題：%s" % title,
               "上線後誰看得到：%s" % ("名單上的家長與同仁（登入後，網站的「課程」頁）" if visible else "只有導師（visible: false＝下架）"),
               pub.photo_summary(photos)] + notes
    html = pv.page("預覽：" + title, title, [label, "" if visible else "已下架"], summary, preview_body)
    return pub.Draft("page", page_id, owner, photos, [(owner, doc, "page")], summary, html)


def main(argv=None):
    ap = argparse.ArgumentParser(description="發課程頁（課程介紹、影片、各科課程大綱卡）與課表（預設只預覽）")
    ap.add_argument("page_id", help="data/courses/ 裡的檔名（不含 .md），例如 courses-term、schedule")
    pub.add_common_args(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        cfg = classcfg.load()
    except classcfg.ConfigError as e:
        return pub.fail([str(e)])
    page_id = re.sub(r"\.md$", "", Path(a.page_id).name)
    try:
        draft = build(page_id, cfg)
    except pub.PublishError as e:
        return pub.fail(e.lines)
    return pub.run(draft, a, cfg, "publish_courses.py", "pages/" + page_id, keep_published=False)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
