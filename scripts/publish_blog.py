#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_blog.py — 導師替某個座號發一篇部落格文章（「我的孩子」；docs/DATA-MODEL.md §2.14）。

  來源：data/blog-drafts/<座號>/<草稿名>.md（＋同名資料夾裡最多 3 張照片）
  寫到：student_blogs/<座號>/entries/<postId>（author: 'teacher'，作者代號＝導師在 allowlist 的 alias）
        以及它的 thumbs/0–2、images/0–2——**一次送出**（全部成功或全部失敗）。

  md 檔頭：
    title:  標題（必填，1–200 字）
    date:   日期 YYYY-MM-DD（選填，預設今天）
    photos: 照片（選填，最多 3 張；照這個順序；沒給圖說就留空，不要替老師編）
      - 檔名.jpg | 圖說
  正文：**逐字保留**（空白、換行照原樣；不轉 Markdown），1–10,000 字。

  · postId 每次上線都重新產生（日期＋8 碼隨機）；發過的草稿記在 data/ledgers/blog-posts.jsonl，
    同一份草稿再發一次會被擋下（避免同一篇出現兩次）；台帳不見了也會先查網站上有沒有同標題、同日期的導師文。
  · --update：只改已發那篇的標題與正文（照片發了就不能換；要換照片請到網站上把舊文下架，再發一篇新的）。
  · 部落格要先開好（open_blogs.py）、名單要先同步（access_sync.py：導師的作者代號在那裡產生）。

用法：
  python3 scripts/publish_blog.py --seat 3 <草稿名>                    # 預覽
  python3 scripts/publish_blog.py --seat 3 <草稿名> --publish          # 發文
  python3 scripts/publish_blog.py --seat 3 <草稿名> --publish --update # 改已發那篇的標題／正文
"""
import sys
import time
import secrets
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, schema, gauth  # noqa: E402
from lib import frontmatter as fm  # noqa: E402
from lib import preview as pv  # noqa: E402
from lib import publishing as pub  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib.seats import parse_seat  # noqa: E402
from lib.console import setup_utf8  # noqa: E402
from lib.hostos import PY  # noqa: E402

setup_utf8()

ALLOWED = ("title", "date", "photos")
REQUIRED = ("title",)
LEDGER = "blog-posts.jsonl"
_ALNUM = "abcdefghijklmnopqrstuvwxyz0123456789"


def new_post_id(date):
    return "%s-%s" % (date, "".join(secrets.choice(_ALNUM) for _ in range(8)))


def published_record(seat, draft_name):
    rec = None
    for r in pub.ledger_read(LEDGER):
        if r.get("seat") == seat and r.get("draft") == draft_name:
            rec = r
    return rec


def build(seat, draft_name, today=None):
    base = paths.data_dir() / "blog-drafts" / seat
    md = base / (draft_name + ".md")
    folder = base / draft_name
    meta, body, _ = pub.read_md(md, ALLOWED, REQUIRED)
    problems = []
    title = str(meta["title"]).strip()
    date = str(meta.get("date") or today or time.strftime("%Y-%m-%d")).strip()
    text = body.strip("\n")
    if not (1 <= len(title) <= 200):
        problems.append("title 要 1–200 字")
    if not schema.valid_date(date):
        problems.append("date 要寫成 YYYY-MM-DD")
    if not text.strip():
        problems.append("正文是空的")
    elif len(text) > 10000:
        problems.append("正文超過 10,000 字（現在 %d 字）" % len(text))
    items = []
    for item in fm.as_list(meta.get("photos")):
        n, cap = fm.pair(item)
        if len(cap) > 300:
            problems.append("照片 %s 的圖說超過 300 字" % n)
        items.append((n, cap))
    if len(items) > 3:
        problems.append("一篇最多 3 張照片（現在 %d 張）：請老師自己挑，不要替他選" % len(items))
    if len({n for n, _ in items}) != len(items):
        problems.append("同一張照片寫了兩次")
    if problems:
        raise pub.PublishError(["%s：%s" % (pub.rel(md), x) for x in problems])
    files = [(pub.photo_path(folder, n), cap) for n, cap in items]
    photos, pids = pub.process_photos(files)
    if len(photos) != len(files):
        raise pub.PublishError("%s：有兩張照片其實是同一張" % pub.rel(md))
    for i, ph in enumerate(photos):
        ph.pid = str(i)          # 部落格照片的 pid 固定是 0、1、2（DATA-MODEL §0.4）
        ph.order = i
    return {"title": title, "date": date, "body": text, "photos": photos, "md": md}


def make_draft(seat, draft_name, b, post_id, alias):
    owner = "student_blogs/%s/entries/%s" % (seat, post_id)
    entry = {
        "title": b["title"], "body": b["body"], "date": b["date"], "author": "teacher",
        "authorAlias": alias or "aaaaaaaaaaaa",
        "photos": [dict({"pid": p.pid, "w": p.image.w, "h": p.image.h}, **({"caption": p.caption} if p.caption else {}))
                   for p in b["photos"]],
        "visible": True, "createdAt": fr.SERVER_TIME,
    }
    summary = [
        "部落格文章：座號 %s（草稿 %s）" % (seat, draft_name),
        "標題：%s｜日期：%s｜作者：導師" % (b["title"], b["date"]),
        "上線後誰看得到：座號 %s 的家長、被授權這個座號的同仁、導師（登入後）" % seat,
        "正文：%d 字（逐字保留）" % len(b["body"]),
        pub.photo_summary(b["photos"]),
    ]
    body_html = '<p class="body-pre">%s</p>' % pv.esc(b["body"])
    for p in b["photos"]:
        body_html += '<figure><img src="%s" alt="%s">%s</figure>' % (
            pv.esc(pv.data_uri(p.image.data)), pv.esc(p.caption),
            ("<figcaption>%s</figcaption>" % pv.esc(p.caption)) if p.caption else "")
    html = pv.page("預覽：" + b["title"], b["title"], [b["date"], "座號 " + seat, "導師發文"], summary, body_html)
    ident = "%s-%s" % (seat, draft_name)
    return pub.Draft("blog", ident, owner, b["photos"], [(owner, entry, "entry")], summary, html, blog=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="導師替某個座號發部落格文章（預設只預覽；--publish 才發）")
    ap.add_argument("draft", help="data/blog-drafts/<座號>/ 裡的草稿檔名（不含 .md）")
    ap.add_argument("--seat", required=True, help="座號（1–40）")
    pub.add_common_args(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        seat = parse_seat(a.seat)
    except ValueError:
        return pub.fail(["--seat 要是 1–40 的數字"])
    draft_name = Path(a.draft[:-3] if a.draft.endswith(".md") else a.draft).name
    try:
        cfg = classcfg.load()
        b = build(seat, draft_name)
    except classcfg.ConfigError as e:
        return pub.fail([str(e)])
    except pub.PublishError as e:
        return pub.fail(e.lines)
    rec = published_record(seat, draft_name)
    preview_draft = make_draft(seat, draft_name, b, new_post_id(b["date"]), None)
    try:
        preview_draft.validate()
    except pub.PublishError as e:
        return pub.fail(e.lines)
    for line in preview_draft.summary:
        print("  " + line)
    if rec:
        print("  提醒：這份草稿 %s 已經發過了（postId %s）。" % (rec.get("at", "")[:10], rec.get("postId")))
    p = pub.write_preview(preview_draft, a.open)
    print("  預覽檔：%s" % p)
    if not a.publish:
        print("\n這只是預覽，還沒發。老師看過、說好之後再跑：")
        print("  %s scripts/publish_blog.py --seat %s %s --publish%s%s" % (PY, seat, draft_name, " --update" if rec else "",
                                                                  paths.rerun_flags(a)))
        return 0
    if rec and not a.update:
        return pub.fail(["這份草稿已經發過了（postId %s），再發會變成兩篇一樣的文章。" % rec.get("postId"),
                         "要改那篇的標題或正文：加 --update；真的要另外再發一篇，請另存一份新的草稿檔名。"],
                        "沒有重複發文：")
    try:
        client = fr.make_client(cfg.project_id, emulator_flag=a.emulator)
    except ValueError as e:
        return pub.fail([str(e)])
    print("上線目標：%s" % client.describe_target())
    try:
        blog = client.get("student_blogs/" + seat, mask=["seat"])
        if blog is None:
            return pub.fail(["座號 %s 的部落格還沒開：先跑 %s scripts/open_blogs.py --seat %s%s（先預覽，再 --apply）"
                             % (seat, PY, seat, paths.rerun_flags(a))])
        me = client.get("allowlist/" + cfg.teacher_key)
        alias = (me.data.get("alias") if me else None) or ""
        if not me or me.data.get("kind") != "teacher" or not schema.ALIAS_RE.match(alias):
            return pub.fail(["名單裡還沒有導師的作者代號：先跑 %s scripts/access_sync.py%s（先預覽，再 --apply）"
                             % (PY, paths.rerun_flags(a))])
        if rec is None:
            # 本機台帳不見了（換電腦、刪掉 data/ledgers）也要擋重複：雲端有同標題、同日期的導師文就當作發過了
            same = [e for e in client.list_docs("student_blogs/%s/entries" % seat, mask=["title", "date", "author", "photos"])
                    if e.data.get("author") == "teacher" and e.data.get("title") == b["title"]
                    and e.data.get("date") == b["date"]]
            if same and not a.update:
                return pub.fail(["座號 %s 已經有一篇同標題、同日期的導師文（postId %s），再發會變成兩篇。" % (seat, same[0].id),
                                 "要改那篇的正文：加 --update；真的要另外發一篇，請改標題。"], "沒有重複發文：")
            if same:
                if len(same[0].data.get("photos") or []) != len(b["photos"]):
                    return pub.fail(["照片張數跟網站上那篇不一樣。照片發了就不能換：請到網站上把舊文下架，再改標題發一篇新的。"])
                rec = {"postId": same[0].id, "photoMd5": [p.src_md5 for p in b["photos"]], "from": "cloud"}
        if rec:
            return update_existing(client, seat, draft_name, b, rec)
        post_id = new_post_id(b["date"])
        draft = make_draft(seat, draft_name, b, post_id, alias)
        draft.validate()
        writes = [client.set_write(draft.owner, draft.docs[0][1], must_not_exist=True)]
        for ph in draft.photos:
            image, thumb = pub.photo_docs(ph, blog=True)
            writes.append(client.set_write("%s/images/%s" % (draft.owner, ph.pid), image, must_not_exist=True))
            writes.append(client.set_write("%s/thumbs/%s" % (draft.owner, ph.pid), thumb, must_not_exist=True))
        try:
            client.commit(writes, what="發部落格文章（一次送出 %d 個寫入）" % len(writes))
        except fr.FirestoreError as e:
            if e.status not in ("FAILED_PRECONDITION", "ALREADY_EXISTS"):
                raise
            # 重試時上一次其實已經寫進去了：讀回來確認是不是同一篇
        probs = pub.verify(client, draft)
        if probs:
            return pub.fail(["寫完讀回來比對不一致："] + probs, "發文後檢查沒過：")
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        print("  → 一篇文章是一次送出的：失敗就是整篇都沒發，修好後再跑同一個指令就好（會換一個新的 postId）。")
        return 1
    except pub.PublishError as e:
        return pub.fail(e.lines)
    pub.ledger_append(LEDGER, [{"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seat": seat, "draft": draft_name,
                                "postId": post_id, "title": b["title"],
                                "photoMd5": [p.src_md5 for p in b["photos"]]}])
    pub.record_publish(draft, "publish", {"title": b["title"], "date": b["date"]})
    print("✓ 已發到座號 %s 的部落格（postId %s），讀回比對一致。家長重新整理「我的孩子」就看得到。" % (seat, post_id))
    return 0


def update_existing(client, seat, draft_name, b, rec):
    post_id = rec.get("postId", "")
    if not schema.POST_ID_RE.match(post_id or ""):
        return pub.fail(["台帳裡這份草稿的 postId 看不懂：%r" % post_id])
    path = "student_blogs/%s/entries/%s" % (seat, post_id)
    if [p.src_md5 for p in b["photos"]] != rec.get("photoMd5", []):
        return pub.fail(["照片跟發文時不一樣。照片發了就不能換：請到網站上把舊文下架，再用新的草稿檔名發一篇。"])
    cur = client.get(path)
    if cur is None:
        return pub.fail(["網站上找不到這篇（postId %s），可能已經被刪了。" % post_id])
    patch = {"title": b["title"], "body": b["body"], "updatedAt": fr.SERVER_TIME}
    merged = dict(cur.data, title=b["title"], body=b["body"], updatedAt=fr.SERVER_TIME)
    probs = schema.problems("entry", dict(merged, visible=True))
    if probs:
        return pub.fail(probs)
    client.commit([client.set_write(path, patch, mask_fields=["title", "body", "updatedAt"])], what="改部落格文章")
    after = client.get(path)
    if not after or after.data.get("title") != b["title"] or after.data.get("body") != b["body"]:
        return pub.fail(["改完讀回來比對不一致"], "改文後檢查沒過：")
    pub.ledger_append(LEDGER, [{"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seat": seat, "draft": draft_name,
                                "postId": post_id, "title": b["title"], "photoMd5": rec.get("photoMd5", []),
                                "action": "update"}])
    print("✓ 已更新座號 %s 那篇（postId %s）的標題與正文，讀回比對一致。" % (seat, post_id))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
