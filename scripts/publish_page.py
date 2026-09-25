#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_page.py — 發單頁：關於我們、專題活動、首頁橫幅、獨立單頁（docs/DATA-MODEL.md §2.11）。

  來源：data/pages/<pageId>.md（＋同名資料夾 data/pages/<pageId>/ 裡的照片）
  寫到：pages/<pageId>/images|thumbs/<pid>、pages/<pageId>

  pageId：小寫英數與連字號、英文字母開頭（例如 about、fun、home、field-trip-guide）。
  種類（檔頭 kind；沒寫就照 pageId 猜）：
    about        關於我們（pageId 用 about）：正文寫法同班級紀事
    fun          專題活動（pageId 用 fun）：每個「## 標題」開一張卡片，下面的文字是卡片內容（≤ 300 字），
                 卡片裡第一張 ![](照片) 是卡片的照片；第一個 ## 之前的文字是這一頁的開場白
    home         首頁橫幅（pageId 用 home）：檔頭 banner 是橫幅那句話（≤ 200 字），banner_image 是橫幅照片
    standalone   獨立單頁（其他 pageId）：正文寫法同班級紀事
  其他檔頭：title（必填，1–80 字）、order（整數，預設 0）、visible（預設 true）。

用法：
  python3 scripts/publish_page.py <pageId>                    # 預覽
  python3 scripts/publish_page.py <pageId> --publish          # 上線
  python3 scripts/publish_page.py <pageId> --publish --update # 已上線的再發一次
"""
import re
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, schema, mdlite  # noqa: E402
from lib import frontmatter as fm  # noqa: E402
from lib import preview as pv  # noqa: E402
from lib import publishing as pub  # noqa: E402
from lib.firestore_rest import SERVER_TIME  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

ALLOWED = ("title", "kind", "order", "visible", "banner", "banner_image")
REQUIRED = ("title",)
KINDS = ("about", "fun", "home", "standalone")
DEFAULT_KIND = {"about": "about", "fun": "fun", "home": "home"}


def _fun_cards(md, blocks_raw):
    """fun 頁：## 標題 → 一張卡片。回 (開場白區塊, [(title, text, 照片檔名或 None)])。"""
    intro, cards, cur = [], [], None
    for b in blocks_raw:
        if b["t"] == "h" and b["level"] == 2:
            cur = {"title": b["text"], "text": [], "src": None}
            cards.append(cur)
            continue
        if cur is None:
            intro.append(b)
            continue
        if b["t"] == "img":
            if cur["src"] is None:
                cur["src"] = b["src"]
        elif b["t"] in ("p", "quote"):
            cur["text"].append("".join(s["text"] for s in b["spans"]))
        elif b["t"] == "list":
            cur["text"] += ["・" + "".join(s["text"] for s in it["spans"]) for it in b["items"]]
    out, problems = [], []
    for c in cards:
        text = "\n".join(c["text"]).strip()
        if not (1 <= len(c["title"]) <= 40):
            problems.append("卡片標題「%s」要 1–40 字" % c["title"][:20])
        if len(text) > 300:
            problems.append("卡片「%s」的內容超過 300 字" % c["title"][:20])
        out.append((c["title"], text, c["src"]))
    if not out:
        problems.append("專題活動這一頁至少要有一張卡片（用「## 標題」開始一張）")
    if problems:
        raise pub.PublishError(["%s：%s" % (pub.rel(md), x) for x in problems])
    return intro, out


def build(page_id, cfg):
    if not schema.PAGE_ID_RE.match(page_id):
        raise pub.PublishError("頁面代號格式不對：小寫英數與連字號、英文字母開頭，最多 40 字（例如 about、fun、trip-guide）")
    if page_id.startswith("poems-"):
        raise pub.PublishError("poems- 開頭的頁面代號保留給每日一詩（scripts/publish_poems.py），換一個名字")
    base = paths.data_dir() / "pages"
    md = base / (page_id + ".md")
    folder = base / page_id
    meta, body, first = pub.read_md(md, ALLOWED, REQUIRED)
    problems = []
    title = str(meta["title"]).strip()
    kind = str(meta.get("kind") or DEFAULT_KIND.get(page_id, "standalone")).strip()
    if kind not in KINDS:
        problems.append("kind 只能是 %s（課程頁、課表用 scripts/publish_courses.py）" % "、".join(KINDS))
    if kind in ("about", "fun", "home") and page_id != kind:
        problems.append("%s 頁的檔名要叫 %s.md（網站固定從 pages/%s 讀）" % (kind, kind, kind))
    if not (1 <= len(title) <= 80):
        problems.append("title 要 1–80 字")
    try:
        visible = fm.as_bool(meta.get("visible"), True, "visible")
        order = fm.as_int(meta.get("order"), 0, "order", -999999, 999999)
    except fm.FrontmatterError as e:
        problems += e.problems
        visible, order = True, 0
    banner = str(meta.get("banner") or "").strip()
    banner_image = str(meta.get("banner_image") or "").strip()
    if (banner or banner_image) and kind != "home":
        problems.append("banner、banner_image 只有首頁（home）用得到")
    if len(banner) > 200:
        problems.append("banner 超過 200 字")
    if problems:
        raise pub.PublishError(["%s：%s" % (pub.rel(md), x) for x in problems])

    doc = {"title": title, "kind": kind, "order": order, "visible": visible, "updatedAt": SERVER_TIME}
    photos, preview_body, notes = [], "", []
    if kind == "fun":
        try:
            raw = mdlite.parse(body, first)
        except mdlite.MdError as e:
            raise pub.PublishError(["%s：%s" % (pub.rel(md), x) for x in e.problems])
        intro, cards = _fun_cards(md, raw)
        srcs = [s for s in mdlite.image_sources(intro)] + [c[2] for c in cards if c[2]]
        srcs = list(dict.fromkeys(srcs))
        files = [pub.photo_path(folder, n) for n in srcs]
        photos, pids = pub.process_photos([(p, "") for p in files])
        by_src = dict(zip(srcs, pids))
        intro_final = mdlite.fill_pids(intro, by_src)
        card_docs = []
        for t, text, src in cards:
            c = {"title": t, "text": text}
            if src:
                c["pid"] = by_src[src]
            card_docs.append(c)
        if intro_final:
            doc["blocks"] = intro_final
        doc["data"] = {"cards": card_docs}
        srcmap = pub.pid_src(photos)
        preview_body = pv.blocks_html(intro_final, srcmap)
        for c in card_docs:
            img = ('<img src="%s" alt="">' % pv.esc(srcmap[c["pid"]])) if c.get("pid") else ""
            preview_body += '<div class="card"><h3>%s</h3>%s<p class="body-pre">%s</p></div>' % (
                pv.esc(c["title"]), img, pv.esc(c["text"]))
        notes.append("卡片：%d 張" % len(card_docs))
    else:
        final, photos, cover, srcs, unused = pub.body_with_photos(md, folder, body, first,
                                                                  banner_image if kind == "home" else "")
        if final:
            doc["blocks"] = final
        elif kind in ("about", "standalone"):
            raise pub.PublishError("%s：正文是空的" % pub.rel(md))
        if kind == "home":
            data = {"bannerText": banner}
            if banner_image:
                data["bannerPid"] = cover.pid      # 封面參數傳的就是 banner_image
            doc["data"] = data
            notes.append("橫幅：%s%s" % (banner or "（沒有文字）", "＋照片" if banner_image else ""))
        srcmap = pub.pid_src(photos)
        preview_body = pv.blocks_html(final, srcmap)
        if kind == "home" and banner_image:
            preview_body = '<figure><img src="%s" alt=""><figcaption>%s</figcaption></figure>' % (
                pv.esc(srcmap[doc["data"]["bannerPid"]]), pv.esc(banner)) + preview_body
        if final:
            notes.append("正文：" + pub.block_counts(final))
        if unused:
            notes.append("提醒：資料夾裡有 %d 張照片沒被用到，不會上傳" % len(unused))
    owner = "pages/" + page_id
    label = {"about": "關於我們", "fun": "專題活動", "home": "首頁橫幅", "standalone": "獨立單頁"}[kind]
    summary = ["單頁：%s（%s）" % (page_id, label), "標題：%s" % title,
               "上線後誰看得到：%s" % ("名單上的家長與同仁（登入後）" if visible else "只有導師（visible: false＝下架）"),
               pub.photo_summary(photos)] + notes
    if kind == "standalone":
        summary.append("網址：<網站>/page.html?id=%s" % page_id)
    html = pv.page("預覽：" + title, title, [label, "" if visible else "已下架"], summary, preview_body)
    return pub.Draft("page", page_id, owner, photos, [(owner, doc, "page")], summary, html)


def main(argv=None):
    ap = argparse.ArgumentParser(description="發單頁：關於我們、專題活動、首頁橫幅、獨立單頁（預設只預覽）")
    ap.add_argument("page_id", help="data/pages/ 裡的檔名（不含 .md），例如 about、fun、home")
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
    return pub.run(draft, a, cfg, "publish_page.py", "pages/" + page_id, keep_published=False)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
