#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publishing.py — 所有「把本機內容送上網站」的腳本共用的流程（docs/ARCHITECTURE.md §5.1）。

兩段式：
  1. 預設只預覽：讀本機 md → 驗證 → 處理照片 → 印摘要 → 產生 exports/preview/<種類>-<id>.html。
     這一步**不連網、不需要 gcloud**，也不會改任何雲端資料。
  2. 老師看過、說「上傳」，才加 --publish。已經上線的內容再發一次要多加 --update（明示「我要改已上線的」）。

上線時的順序（摘要出現在列表上時，正文與照片一定都在）：
  顯示圖 → 縮圖 → 正文 → 摘要 → 最後才刪「舊版本用過、新版本沒用到」的照片（兩份都刪）。
  照片 pid＝顯示圖 JPEG 的 SHA-256 前 16 碼：顯示圖已經在的不重寫（照片文件不可變）；
  同一張照片只有順序或圖說改了，只重寫那份縮圖文件（data 一個位元組都不變）。
寫完讀回來逐欄比對，對不上就 exit 1。
"""
import re
import sys
import json
import time
import webbrowser
from pathlib import Path

from . import paths, schema, images, frontmatter, gauth
from . import firestore_rest as fr
from . import preview as pv
from .hostos import PY

EXIT_STOPPED = 2


class PublishError(Exception):
    def __init__(self, lines):
        if isinstance(lines, str):
            lines = [lines]
        super().__init__("\n".join(lines))
        self.lines = list(lines)


def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def rel(p):
    try:
        return Path(p).resolve().relative_to(paths.root()).as_posix()
    except ValueError:
        return str(p)


def read_md(path, allowed, required):
    """讀本機 md：回 (檔頭, 正文, 正文第一行的行號)。任何問題 → PublishError。"""
    if not path.exists():
        raise PublishError("找不到 %s" % rel(path))
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise PublishError("%s 不是 UTF-8 文字檔：請用文字編輯器另存成 UTF-8" % rel(path))
    try:
        meta, body, first = frontmatter.split(text)
    except frontmatter.FrontmatterError as e:
        raise PublishError(["%s：%s" % (rel(path), p) for p in e.problems])
    probs = frontmatter.check_keys(meta, allowed, required)
    if probs:
        raise PublishError(["%s：%s" % (rel(path), p) for p in probs])
    return meta, body, first


def photo_path(folder, name):
    """同名資料夾裡的一張照片（只准檔名，不准路徑）。"""
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise PublishError("照片只寫檔名就好：%r" % name)
    p = folder / name
    if not p.is_file():
        raise PublishError("找不到照片 %s（照片要放在 %s/ 裡）" % (name, rel(folder)))
    if not images.is_photo_file(p):
        raise PublishError("%s 不是支援的照片格式（jpg、png、webp、heic…）" % name)
    return p


def folder_photos(folder):
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir() if p.is_file() and images.is_photo_file(p)),
                  key=lambda p: natural_key(p.name))


def process_photos(items):
    """items：[(本機檔, 圖說)] → (照片清單, 每一項對到的 pid)。同一張照片出現兩次只上傳一次。
    沒裝 Pillow → PublishError（印官方安裝說明，不代裝）。"""
    if not items:
        return [], []
    if not images.have_pillow():
        raise PublishError(images.pillow_help().splitlines())
    out, pids, seen = [], [], {}
    for i, (p, cap) in enumerate(items):
        print("  處理照片 %d／%d：%s" % (i + 1, len(items), p.name))
        sys.stdout.flush()
        try:
            ph = images.process(p)
        except images.ImageError as e:
            raise PublishError(str(e).splitlines())
        pids.append(ph.pid)
        if ph.pid in seen:
            print("  提醒：%s 跟 %s 是同一張照片，只上傳一次" % (p.name, seen[ph.pid]))
            continue
        seen[ph.pid] = p.name
        ph.caption = cap or ""
        ph.order = len(out)
        out.append(ph)
    return out, pids


def body_with_photos(md, folder, body, first_line, cover_name=""):
    """正文 md → (區塊（pid 已填）, 照片, 封面照片或 None, 用到的檔名, 資料夾裡沒用到的檔名)。
    照片＝正文裡的 ![圖說](檔名)，加上檔頭的 cover（沒出現在正文也會上傳，當封面）。"""
    from . import mdlite
    try:
        blocks = mdlite.parse(body, first_line)
    except mdlite.MdError as e:
        raise PublishError(["%s：%s" % (rel(md), x) for x in e.problems])
    srcs = mdlite.image_sources(blocks)
    if cover_name and cover_name not in srcs:
        srcs.append(cover_name)
    files = [photo_path(folder, n) for n in srcs]
    unused = [p.name for p in folder_photos(folder) if p.name not in srcs]
    photos, pids = process_photos([(p, "") for p in files])
    by_src = dict(zip(srcs, pids))
    final = mdlite.fill_pids(blocks, by_src)
    cover = None
    if photos:
        cover_pid = by_src[cover_name] if cover_name else by_src[srcs[0]]
        cover = next(ph for ph in photos if ph.pid == cover_pid)
    return final, photos, cover, srcs, unused


def block_counts(final):
    names = {"p": "段落", "h": "標題", "list": "清單", "quote": "引言", "img": "圖片", "video": "影片", "hr": "分隔線"}
    counts = {}
    for b in final:
        counts[b["t"]] = counts.get(b["t"], 0) + 1
    return "%d 個區塊（%s）" % (len(final), "、".join("%s %d" % (names[k], v) for k, v in counts.items()))


def photo_docs(ph, blog=False):
    """一張照片的 (顯示圖文件, 縮圖文件)。"""
    image = {"data": ph.image.data, "w": ph.image.w, "h": ph.image.h}
    thumb = {"data": ph.thumb.data, "w": ph.thumb.w, "h": ph.thumb.h, "order": ph.order}
    if ph.caption and not blog:
        thumb["caption"] = ph.caption
    return image, thumb


def kb(chars):
    return "%d KB" % max(1, round(chars / 1024.0))


def photo_summary(photos):
    if not photos:
        return "照片：沒有"
    return "照片：%d 張（顯示圖共 %s、縮圖共 %s；已清掉 EXIF 與定位資訊）" % (
        len(photos), kb(sum(len(p.image.data) for p in photos)), kb(sum(len(p.thumb.data) for p in photos)))


class Draft(object):
    """準備上線的一份內容。docs：[(路徑, 資料, schema 種類)]，照寫入順序（摘要放最後）。"""

    def __init__(self, kind, ident, owner, photos, docs, summary, preview_html, blog=False):
        self.kind = kind
        self.ident = ident
        self.owner = owner
        self.photos = photos
        self.docs = docs
        self.summary = summary
        self.preview_html = preview_html
        self.blog = blog

    def validate(self):
        probs = []
        for path, data, kind in self.docs:
            for x in schema.problems(kind, data):
                probs.append("%s：%s" % (path, x))
            sp = schema.size_problem(path, data, schema.BLOCKS_DOC_MAX if "blocks" in data else schema.DOC_MAX)
            if sp:
                probs.append(sp)
        for ph in self.photos:
            image, thumb = photo_docs(ph, self.blog)
            if self.blog:
                probs += ["照片 %s：%s" % (ph.pid, x) for x in schema.problems("blog_thumb", thumb, pid=ph.pid)]
            else:
                probs += ["照片 %s：%s" % (ph.pid, x) for x in schema.problems("thumb", thumb)]
            probs += ["照片 %s：%s" % (ph.pid, x) for x in schema.problems("image", image)]
        if probs:
            raise PublishError(["資料格式檢查沒過（多半是程式問題，請回報）："] + probs)


def preview_path(kind, ident):
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", ident)
    return paths.rpath("exports", "preview", "%s-%s.html" % (kind, safe))


def write_preview(draft, open_it=False):
    p = preview_path(draft.kind, draft.ident)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(draft.preview_html)
    if open_it:
        try:
            webbrowser.open(p.resolve().as_uri())
        except (OSError, webbrowser.Error):
            print("  提醒：沒辦法自動打開瀏覽器，請手動打開上面那個檔。")
    return p


def pid_src(photos):
    return {p.pid: pv.data_uri(p.image.data) for p in photos}


# ── 上線 ─────────────────────────────────────────────────────────────────

def existing_photos(client, owner):
    thumbs = {d.id: d.data for d in client.list_docs(owner + "/thumbs", mask=["order", "caption", "w", "h"])}
    imgs = {d.id: d.data for d in client.list_docs(owner + "/images", mask=["w", "h"])}
    return thumbs, imgs


def photo_writes(client, owner, photos, thumbs, imgs, blog=False):
    """回 (照片寫入清單, 要刪的舊 pid 清單)。"""
    img_w, thumb_w = [], []
    for ph in photos:
        image, thumb = photo_docs(ph, blog)
        if ph.pid not in imgs:
            img_w.append(client.set_write("%s/images/%s" % (owner, ph.pid), image))
        cur = thumbs.get(ph.pid)
        meta = {k: v for k, v in thumb.items() if k != "data"}
        if cur is None or cur != meta:
            thumb_w.append(client.set_write("%s/thumbs/%s" % (owner, ph.pid), thumb))
    keep = {p.pid for p in photos}
    stale = sorted((set(thumbs) | set(imgs)) - keep)
    return img_w + thumb_w, stale


def verify(client, draft):
    """讀回比對：文件逐欄（時間欄只驗有值）；照片驗存在與 w、h、order、caption。"""
    problems = []
    got = client.batch_get([p for p, _, _ in draft.docs])
    for path, data, _ in draft.docs:
        d = got.get(path)
        if d is None:
            problems.append("%s 讀不到" % path)
            continue
        if fr.strip_times(d.data) != fr.strip_times(data):
            problems.append("%s 內容跟送出的不一樣" % path)
        for k, v in data.items():
            if v is fr.SERVER_TIME and not isinstance(d.data.get(k), fr.Timestamp):
                problems.append("%s 的 %s 沒有時間" % (path, k))
    if draft.owner:
        thumbs, imgs = existing_photos(client, draft.owner)
        want = {p.pid for p in draft.photos}
        if set(thumbs) != want or set(imgs) != want:
            problems.append("照片數量對不上（應該 %d 張，縮圖 %d、顯示圖 %d）" % (len(want), len(thumbs), len(imgs)))
        for ph in draft.photos:
            image, thumb = photo_docs(ph, draft.blog)
            meta = {k: v for k, v in thumb.items() if k != "data"}
            if thumbs.get(ph.pid) != meta:
                problems.append("照片 %s 的縮圖資訊對不上" % ph.pid)
            if imgs.get(ph.pid) != {"w": image["w"], "h": image["h"]}:
                problems.append("照片 %s 的顯示圖資訊對不上" % ph.pid)
    return problems


def publish(client, draft, progress=True):
    """照固定順序寫進資料庫、刪掉舊照片、讀回比對。回 (寫入數, 刪除數)。"""
    thumbs, imgs = existing_photos(client, draft.owner) if draft.owner else ({}, {})
    writes, stale = photo_writes(client, draft.owner, draft.photos, thumbs, imgs, draft.blog)
    for path, data, _ in draft.docs:
        writes.append(client.set_write(path, data))
    deletes = []
    for pid in stale:
        deletes.append(client.delete_write("%s/thumbs/%s" % (draft.owner, pid)))
        deletes.append(client.delete_write("%s/images/%s" % (draft.owner, pid)))

    def prog(i, n, k):
        if progress and n > 1:
            print("  已送出第 %d／%d 批（%d 個寫入）" % (i, n, k))
            sys.stdout.flush()

    client.commit_all(writes + deletes, what="上線 %s" % draft.ident, progress=prog)
    probs = verify(client, draft)
    if probs:
        raise PublishError(["寫完讀回來比對不一致："] + probs)
    return len(writes), len(stale)


# ── 台帳 ─────────────────────────────────────────────────────────────────

def ledger_append(name, records):
    p = paths.rpath("data", "ledgers", name)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def ledger_read(name):
    p = paths.rpath("data", "ledgers", name)
    out = []
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def record_publish(draft, action, extra=None):
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    rec = {"at": now, "kind": draft.kind, "id": draft.ident, "action": action}
    rec.update(extra or {})
    ledger_append("published.jsonl", [rec])
    ledger_append("uploads.jsonl", [{"at": now, "owner": draft.owner, "pid": p.pid, "imageChars": len(p.image.data),
                                     "thumbChars": len(p.thumb.data), "srcMd5": p.src_md5} for p in draft.photos])


def refresh_post_index():
    """data/class-posts/index.md：發過哪些紀事（自動產生）。"""
    latest = {}
    for r in ledger_read("published.jsonl"):
        if r.get("kind") == "post":
            latest[r.get("id")] = r
    lines = ["# 班級紀事索引", "", "由 scripts/publish_post.py 自動產生，不要手改。網址：<網站>/post.html?s=<檔名>", "",
             "| 日期 | 標題 | 檔名 | 最後上線 |", "|---|---|---|---|"]
    for slug, r in sorted(latest.items(), key=lambda kv: (kv[1].get("date", ""), kv[0]), reverse=True):
        title = str(r.get("title", "")).replace("|", "｜")
        lines.append("| %s | %s | %s | %s |" % (r.get("date", ""), title, slug, r.get("at", "")[:16].replace("T", " ")))
    p = paths.rpath("data", "class-posts", "index.md")
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


# ── 共同的命令列與流程 ───────────────────────────────────────────────────

def add_common_args(ap):
    ap.add_argument("--publish", action="store_true", help="真的上線（先不加，看過預覽、老師說好了再加）")
    ap.add_argument("--update", action="store_true", help="已經上線的內容要再發一次（改內容、下架）時才加")
    ap.add_argument("--open", action="store_true", help="產生預覽後用瀏覽器打開")
    ap.add_argument("--emulator", action="store_true", help="寫到本機模擬器（測試用）")
    paths.add_root_arg(ap)
    return ap


def fail(lines, header="停下來了，什麼都沒有上線："):
    print("✗ " + header)
    for ln in (lines if isinstance(lines, list) else [lines]):
        print("  " + ln)
    return EXIT_STOPPED


def run(draft, a, cfg, script, summary_path, keep_published=True, after=None):
    """預覽／上線的共同流程。summary_path＝判斷「是否已上線」與保留 publishedAt 的那份文件。"""
    try:
        draft.validate()
    except PublishError as e:
        return fail(e.lines)
    for line in draft.summary:
        print("  " + line)
    p = write_preview(draft, a.open)
    print("  預覽檔：%s" % p)
    again = paths.rerun_flags(a)
    if not a.publish:
        print("\n這只是預覽，還沒上線。請老師先看預覽檔；確認沒問題、說「上傳」之後再跑：")
        print("  %s scripts/%s %s --publish%s" % (PY, script, draft.ident, again))
        return 0
    try:
        client = fr.make_client(cfg.project_id, emulator_flag=a.emulator)
    except ValueError as e:
        return fail([str(e)])
    print("上線目標：%s" % client.describe_target())
    try:
        existing = client.get(summary_path)
        for note in getattr(client.tokens, "notes", []):
            print("  提醒：" + note)
        if existing is not None and not a.update:
            return fail(["這份內容已經上線了（%s）。要改內容或下架，確認過後加 --update：" % summary_path,
                         "%s scripts/%s %s --publish --update%s" % (PY, script, draft.ident, again)],
                        "沒有覆蓋已上線的內容：")
        if existing is not None and keep_published:
            for path, data, _ in draft.docs:
                if path == summary_path and "publishedAt" in data and isinstance(existing.data.get("publishedAt"), fr.Timestamp):
                    data["publishedAt"] = existing.data["publishedAt"]
        n_writes, n_stale = publish(client, draft)
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        print("  → 修好後再跑同一個指令就好：已經寫進去的照片不會重複寫。")
        return 1
    except PublishError as e:
        return fail(e.lines, "上線後檢查沒過：")
    action = "update" if existing is not None else "publish"
    extra = {}
    for path, data, _ in draft.docs:
        if path == summary_path:
            extra = {"title": data.get("title", ""), "date": data.get("date", "")}
    record_publish(draft, action, extra)
    if after:
        after()
    print("✓ 已上線（%s）：寫入 %d 份文件%s，讀回比對一致。網站下一次重新整理就看得到，不用重新部署。"
          % ("更新" if action == "update" else "新發布", n_writes, ("、刪掉舊照片 %d 張" % n_stale) if n_stale else ""))
    return 0
