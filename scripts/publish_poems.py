#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_poems.py — 每日一詩（poem.html；docs/DATA-MODEL.md §2.11 的 kind 'poem'）。

  來源：data/poems/*.md，一首一檔（建議檔名就是日期：2026-10-01.md）。寫法見 data/poems/README.md：
        ---
        date: 2026-10-01
        title: 詩名
        author: 作者
        source: 出處（書名、頁數或網址；可省略）
        rights: 公版            ← 這首詩能不能公開使用，由老師確認後填（公版／老師自己寫的／已取得授權……）
        ---
        詩的正文，每一行照原樣（空行、行首空白都保留）。

        ## 導讀
        （可省略）一小段導讀。
  寫到：pages/poems-YYYY-MM（一個月一份；名單上的家長與同仁登入後看得到）

**版權由老師負責。** 只收老師自己確認可以公開使用的文本：`rights` 空白的詩，預覽照樣看得到，但 --publish 一律擋下。
代理不准替老師填 `rights`，也不准憑記憶打出有著作權的現代作品全文（劇本 playbooks/poem.md）。

用法：
  python3 scripts/publish_poems.py                          # 列出 data/poems/ 裡有哪幾個月
  python3 scripts/publish_poems.py 2026-10                  # 預覽十月
  python3 scripts/publish_poems.py 2026-10 --publish        # 上線（網站上已經有十月、內容改過的要多加 --update）
  python3 scripts/publish_poems.py --remove 2026-10 [--publish]   # 從網站拿掉整個月（本機的 md 不動）
"""
import re
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, schema, gauth  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib import preview as pv  # noqa: E402
from lib import publishing as pub  # noqa: E402
from lib import multipub as mp  # noqa: E402
from lib.firestore_rest import SERVER_TIME  # noqa: E402
from lib.hostos import PY  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

ALLOWED = ("date", "title", "author", "source", "rights")
REQUIRED = ("date", "title", "author")
GUIDE_RE = re.compile(r"^\s*##\s*導讀\s*$")


def folder():
    return paths.data_dir() / "poems"


def page_id(month):
    return "poems-" + month


def poem_files():
    d = folder()
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".md"
                  and p.name.lower() != "readme.md" and not p.name.startswith("."))


def trim_blank(lines):
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return lines


def read_poem(path):
    """→ (項目, rights 字串或 "")。正文逐字保留（只去掉開頭與結尾的空行）。"""
    meta, body, _ = pub.read_md(path, ALLOWED, REQUIRED)
    label = pub.rel(path)
    lines = body.split("\n")
    cut = next((i for i, ln in enumerate(lines) if GUIDE_RE.match(ln)), None)
    text_lines = trim_blank(lines if cut is None else lines[:cut])
    guide_lines = trim_blank([] if cut is None else lines[cut + 1:])
    item = {"date": str(meta["date"]).strip(), "title": str(meta["title"]).strip(),
            "author": str(meta["author"]).strip(), "text": "\n".join(ln.rstrip() for ln in text_lines)}
    source = meta.get("source")
    if isinstance(source, str) and source.strip():
        item["source"] = source.strip()
    guide = "\n".join(ln.rstrip() for ln in guide_lines).strip()
    if guide:
        item["guide"] = guide
    problems = []
    if not schema.valid_date(item["date"]):
        problems.append("date 要是 YYYY-MM-DD")
    for f, lo, hi in (("title", 1, 80), ("author", 1, 40), ("text", 1, schema.POEM_TEXT_MAX), ("source", 0, 200),
                      ("guide", 0, schema.POEM_GUIDE_MAX)):
        if f in item and not (lo <= len(item[f]) <= hi):
            problems.append({"text": "詩的正文", "guide": "導讀"}.get(f, f) + " 要 %d–%d 字（現在 %d）" % (lo, hi, len(item[f])))
    rights = meta.get("rights")
    rights = rights.strip() if isinstance(rights, str) else ""
    if len(rights) > 60:
        problems.append("rights 最多 60 字")
    if problems:
        raise pub.PublishError(["%s：%s" % (label, p) for p in problems])
    return item, rights


def load_all():
    """→ {月份: [(檔案, 項目, rights)]}；任何一首有問題 → PublishError（全部列出來）。"""
    out, problems = {}, []
    for p in poem_files():
        try:
            item, rights = read_poem(p)
        except pub.PublishError as e:
            problems += e.lines
            continue
        out.setdefault(item["date"][:7], []).append((p, item, rights))
    if problems:
        raise pub.PublishError(problems)
    return out


def build(month, entries):
    by_date = {}
    problems = []
    for p, item, rights in entries:
        if item["date"] in by_date:
            problems.append("%s 有兩首詩：%s 與 %s" % (item["date"], by_date[item["date"]][0].name, p.name))
        by_date[item["date"]] = (p, item, rights)
    if len(entries) > schema.POEM_MAX_ITEMS:
        problems.append("一個月最多 %d 首" % schema.POEM_MAX_ITEMS)
    if problems:
        raise pub.PublishError(problems)
    dates = sorted(by_date)
    items = [by_date[d][1] for d in dates]
    no_rights = [by_date[d][0].name for d in dates if not by_date[d][2]]
    y, m = month.split("-")
    doc = {"title": "每日一詩（%s 年 %d 月）" % (y, int(m)), "kind": "poem", "order": 0, "visible": True,
           "updatedAt": SERVER_TIME, "data": {"month": month, "items": items}}
    owner = "pages/" + page_id(month)
    summary = ["每日一詩：%s，共 %d 首（%s 到 %s）" % (month, len(items), items[0]["date"], items[-1]["date"]),
               "上線後誰看得到：名單上的家長與同仁（登入後），一天一首；還沒到的日子只有導師看得到",
               "導讀：%d 首有" % sum(1 for it in items if it.get("guide"))]
    if no_rights:
        summary.append("還不能上線：這幾首的 rights（能不能公開使用）是空白的：%s——請老師確認後自己填，或跟代理說這首是什麼來源"
                       % "、".join(no_rights))
    body = []
    for it in items:
        body.append('<div class="card"><p class="meta">%s</p><h3>%s</h3><p class="meta">%s%s</p>'
                    '<p class="body-pre">%s</p>%s</div>'
                    % (pv.esc(it["date"]), pv.esc(it["title"]), pv.esc(it["author"]),
                       ("・" + pv.esc(it["source"])) if it.get("source") else "", pv.esc(it["text"]),
                       ('<p class="meta">導讀</p><p class="body-pre">%s</p>' % pv.esc(it["guide"])) if it.get("guide") else ""))
    html = pv.page("預覽：每日一詩 " + month, doc["title"], ["讀者看得到"], summary, "".join(body))
    draft = pub.Draft("poems", month, None, [], [(owner, doc, "page")], summary, html)
    return draft, no_rights


def main(argv=None):
    ap = argparse.ArgumentParser(description="每日一詩：data/poems/*.md → 網站（一個月一份；預設只預覽）")
    ap.add_argument("month", nargs="?", help="月份 YYYY-MM；不寫＝列出有哪幾個月")
    ap.add_argument("--remove", metavar="YYYY-MM", help="從網站拿掉這個月（搭 --publish 才真的刪）")
    pub.add_common_args(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        cfg = classcfg.load()
    except classcfg.ConfigError as e:
        return pub.fail([str(e)])
    if a.remove:
        if not schema.MONTH_RE.match(a.remove):
            return pub.fail("月份格式不對：YYYY-MM（例如 2026-10）")
        return mp.remove("pages/" + page_id(a.remove), a, cfg, "%s 的每日一詩" % a.remove,
                         "%s scripts/publish_poems.py --remove %s%s" % (PY, a.remove, paths.rerun_flags(a)))
    try:
        months = load_all()
    except pub.PublishError as e:
        return pub.fail(e.lines)
    if not a.month:
        if not months:
            print("data/poems/ 裡還沒有任何詩。寫法見 data/poems/README.md（一首一檔，檔名用日期）。")
            return 0
        print("data/poems/ 裡有這幾個月：")
        for mth in sorted(months):
            n_ok = sum(1 for _, _, r in months[mth] if r)
            print("  %s：%d 首（rights 已確認 %d 首）" % (mth, len(months[mth]), n_ok))
        print("預覽某一個月：%s scripts/publish_poems.py <YYYY-MM>%s" % (PY, paths.rerun_flags(a)))
        return 0
    month = a.month.strip()
    if not schema.MONTH_RE.match(month):
        return pub.fail("月份格式不對：YYYY-MM（例如 2026-10）")
    if month not in months:
        return pub.fail("data/poems/ 裡沒有 %s 的詩（檔頭 date 是 %s-xx 的才算）" % (month, month))
    try:
        draft, no_rights = build(month, months[month])
        draft.validate()
    except pub.PublishError as e:
        return pub.fail(e.lines)
    for line in draft.summary:
        print("  " + line)
    p = pub.write_preview(draft, a.open)
    print("  預覽檔：%s" % p)
    cmd = "%s scripts/publish_poems.py %s%s" % (PY, month, paths.rerun_flags(a))
    if not a.publish:
        if no_rights:
            # rights 還空著就算老師說「上傳」也上不去（下面 --publish 會擋），所以這裡不給上線指令
            print("\n這只是預覽，還沒上線，而且**現在還不能上線**：上面那幾首的 rights 是空白的。")
            print("請老師逐首看過（文字、作者、能不能公開使用），確認每一首的來源（公版、自己寫的、已取得授權）"
                  "填進檔頭的 rights，再重新預覽一次：")
            print("  %s" % cmd)
            return 0
        print("\n這只是預覽，還沒上線。請老師逐首看過（文字、作者、能不能公開使用）；確認沒問題、說「上傳」之後再跑：")
        print("  %s --publish" % cmd)
        return 0
    if no_rights:
        return pub.fail(["這幾首還沒確認能不能公開使用（rights 空白）：%s" % "、".join(no_rights),
                         "請老師確認每一首的來源（公版、自己寫的、已取得授權），填進檔頭的 rights 再上線。"])
    owner = "pages/" + page_id(month)
    try:
        cur = mp.connect(cfg, a).get(owner)
    except ValueError as e:
        return pub.fail([str(e)])
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        return 1
    if cur is not None and cur.data.get("kind") != "poem":
        return pub.fail("網站上的 %s 不是每日一詩（是別的單頁），不覆蓋；請先檢查 data/pages/ 裡有沒有同名的頁面" % owner)
    return mp.publish_all([(draft, owner)], a, cfg, cmd, noun="個月")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
