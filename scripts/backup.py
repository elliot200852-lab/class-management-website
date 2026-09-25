#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backup.py — 備份與還原：網站資料庫、本機 data/、學生部落格 → Google 雲端硬碟同步夾。

只寫進這台電腦上的「Google 雲端硬碟桌面版」同步夾，由雲端硬碟程式自己上傳；不用 Drive API、不申請任何憑證。
同步夾的資料夾樹由 scripts/drive_init.py 建；這支**找不到就停下來**，不會自己另外建一個。
每個複製的檔都讀回來比 md5，對得上才算成功。**成功**才更新 data/ledgers/backup-state.json 的時間
（失敗不更新，status.py 的提醒就會一直叫）。

子指令：
  firestore   整個網站資料庫匯出成 JSON（保留型別）→ data/backups/firestore/<日期時間>/
              → 同步夾 05_全站備份/firestore/snapshots/YYYY-MM/<日期時間>/ 與 latest/；照片只下載新的
              （05_全站備份/firestore/photos/）。保留最近 --keep 份（預設 30），只刪這個工具自己建的快照。
              讀取次數大約等於資料庫的文件數（一學年後約一兩萬次；免費方案每天 50,000 次）：
              建議傍晚以後跑，別跟「大家都在看新相簿」的那天撞在一起。
  records     data/ 裡的名冊、母本、課程單元、課程紀錄、台帳（backups/、inbox/、exports/ 以外的全部）
              打包成 zip → 同步夾 01_機密（只有導師）/紀錄備份/records-<日期時間>.zip ＋ records-latest.zip，
              保留 --keep 份。照片、影片、音檔與 20 MB 以上的大檔不進 zip，改成增量鏡像：
              相簿原圖 → 03_相簿原圖/<slug>/；其他 → 紀錄備份/照片與附件/<原路徑>（只增不刪）。
  blogs       學生部落格 → data/student-blogs/<座號>/（每篇一個 md、照片存 jpg）
              → 同步夾 04_部落格歸檔/<座號>/<學年>/（資料夾只用座號）。
  all         firestore → blogs（直接用剛匯出的資料，不多讀一次資料庫）→ records（包進最新的部落格鏡像）。
  restore firestore  從快照把資料庫寫回去。**預設只預覽**（列出會新建、會覆蓋哪些文件）；加 --apply 才寫，
              寫之前自動先做一份「還原前」的本機快照。只寫「現在沒有」或「內容不同」的文件，**不刪任何文件**
              （快照之後才有的留言、文章都保留）。--only <路徑> 只還原某一篇、某一本（例如 posts/2026-10-01-walk）。
  restore records    從紀錄備份 zip 還原 data/（以及鏡像裡的照片與附件）。預設只預覽；--apply 才寫；
              已經存在的檔**不覆蓋**，除非加 --overwrite。
  list        列出本機與同步夾有哪些快照、紀錄備份（唯讀、不連網）。

用法（Windows 把 python3 換成 py -3）：
  python3 scripts/backup.py all
  python3 scripts/backup.py firestore --keep 30
  python3 scripts/backup.py restore firestore --snapshot latest --only posts/2026-10-01-walk
  python3 scripts/backup.py restore firestore --snapshot 20261001-183000 --apply
  python3 scripts/backup.py restore records --zip latest
  python3 scripts/backup.py list

exit code：0 成功；2 停下來了（設定、同步夾、鎖、輸入的問題，什麼都沒寫）；1 做到一半失敗（照印出來的「→」處理後重跑，重跑是安全的）。
"""
import os
import re
import sys
import base64
import zipfile
import argparse
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, gauth, schema  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib import fsbackup as fsb  # noqa: E402
from lib import ledgers  # noqa: E402
from lib.drivetree import DriveTree, DriveTreeError, ensure_below  # noqa: E402
from lib.filesafe import (copy_verified, CopyError, RunLock, LockBusy, Mirror, media_kind, write_bytes_atomic,  # noqa: E402
                          md5_file, md5_bytes, human_size, TMP_PREFIX)
from lib.hostos import PY  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

EXIT_STOPPED = 2
KEEP_DEFAULT = 30
PRE_RESTORE_KEEP = 5
SKIP_TOP = ("backups", "inbox", "exports")
BIG_FILE = 20 * 1024 * 1024
RECORDS_RE = re.compile(r"^records-\d{8}-\d{6}\.zip$")
RECORDS_LATEST = "records-latest.zip"
SEAT_RE = re.compile(r"^(0[1-9]|[1-3][0-9]|40)$")
BLOG_PID_RE = re.compile(r"^[0-2]$")


class Ctx(object):
    def __init__(self, a):
        paths.apply_root(a)
        self.a = a
        self.cfg = classcfg.load()
        self.tree = DriveTree.from_config(self.cfg.raw)
        self.data = paths.data_dir()
        self.fs_base = self.data / "backups" / "firestore"
        self._client = None

    def client(self):
        if self._client is None:
            self._client = fr.make_client(self.cfg.project_id, emulator_flag=getattr(self.a, "emulator", False))
        return self._client

    def lock(self):
        return RunLock(self.data / "backups" / ".lock")


def _say(msg):
    print(msg)
    sys.stdout.flush()


def _utc_now():
    return fr.Timestamp(datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"))


def heartbeat(ctx, line, ok):
    """網站導師專用頁的「備份狀態」讀 ops/backup_status（DATA-MODEL §2.17）。寫不進去不影響備份本身。
    weekly＝整個資料庫的快照；nightly＝學生部落格（家長寫的內容）的匯出。"""
    try:
        c = ctx.client()
        c.commit([c.set_write("ops/backup_status", {line: {"lastRunAt": _utc_now(), "ok": bool(ok)}}, mask_fields=[line])],
                 what="寫備份心跳")
    except (fr.FirestoreError, gauth.AuthError, ValueError) as e:
        if ok:
            _say("  提醒：網站上的「備份狀態」沒更新（%s）；這一份備份本身已經做好了。" % getattr(e, "title", type(e).__name__))
        # ok=False：備份本身已經失敗、原因上面印過了；心跳寫不進去多半是同一個原因（例如還沒登入），不再多說，
        # 更不能說「備份本身不受影響」。


def _latest_regular(base):
    snaps = [(i, p) for i, p in fsb.list_snapshots(base) if (fsb.read_manifest(p) or {}).get("kind") == "regular"]
    return snaps[-1][1] if snaps else None


def _known_md5(base):
    last = _latest_regular(base)
    if not last:
        return {}
    try:
        _, _, rows = fsb.load_snapshot(last)
    except fsb.SnapshotError:
        return {}
    return {r["key"]: r["md5"] for r in rows}


def _progress_docs(n):
    _say("  … 已經列了 %d 份文件" % n)


def _progress_photos(done, total):
    if done == total or done % 80 == 0:
        _say("  … 下載新照片 %d／%d" % (done, total))


# ════════════════════════════════════════════════════════════════════════
# firestore
# ════════════════════════════════════════════════════════════════════════

def export_all(ctx, roots=None, photo_filter=None):
    """走遍資料庫＋照片增量。回 (Export, 照片列, 這次下載幾張, 照片池)。"""
    c = ctx.client()
    sync_photos = ctx.tree.path("fs_photos")
    pool = fsb.Pool(ctx.fs_base / "photos", sync_photos if (sync_photos and sync_photos.is_dir()) else None)
    ex = fsb.Walker(c, progress=_progress_docs).walk(roots=roots)
    refs = ex.photos if photo_filter is None else [r for r in ex.photos if photo_filter(r["path"])]
    rows, fetched = fsb.fetch_photos(c, refs, pool, known_md5=_known_md5(ctx.fs_base), progress=_progress_photos)
    return ex, rows, fetched, pool


def do_firestore(ctx, keep):
    need = ctx.tree.require("fs_backup", "fs_latest", "fs_snapshots", "fs_photos")
    ctx.fs_base.mkdir(parents=True, exist_ok=True)
    fsb.clean_partials(ctx.fs_base)
    c = ctx.client()
    _say("網站資料庫備份：%s" % c.describe_target())
    last = _latest_regular(ctx.fs_base)
    if last:
        cnt = (fsb.read_manifest(last) or {}).get("counts") or {}
        _say("  上一份快照有 %d 份文件、%d 份照片文件；這次大約要讀 %d 次（免費方案每天 50,000 次）"
             % (cnt.get("documents", 0), cnt.get("photos", 0), cnt.get("documents", 0) + cnt.get("photos", 0)))
    ex, rows, fetched, pool = export_all(ctx)
    sid = fsb.free_snapshot_id(lambda i: (ctx.fs_base / i).exists())
    snap_dir, man = fsb.write_snapshot(ctx.fs_base, sid, ctx.cfg.project_id, ex, rows, created=ledgers.now_iso())
    _say("  本機快照：data/backups/firestore/%s（%d 份文件、%d 份照片文件，其中新下載 %d 份）"
         % (sid, len(ex.docs), len(rows), fetched))
    pushed = 0
    for r in rows:
        if pool.push(r["key"], r["md5"]):
            pushed += 1
    fsb.push_snapshot(snap_dir, need["fs_snapshots"], need["fs_latest"])
    _say("  已複製到同步夾並逐檔比對 md5：快照 3 個檔、新照片 %d 份" % pushed)
    regular = [(i, p) for i, p in fsb.list_snapshots(ctx.fs_base) if (fsb.read_manifest(p) or {}).get("kind") == "regular"]
    gone_local = fsb.prune(regular, keep)
    gone_sync = fsb.prune(fsb.list_sync_snapshots(need["fs_snapshots"]), keep)
    if gone_local or gone_sync:
        _say("  保留最近 %d 份：刪掉較舊的快照 本機 %d 份、同步夾 %d 份（照片不刪）" % (keep, len(gone_local), len(gone_sync)))
    if ex.phantoms:
        _say("  提醒：有 %d 個「本身已刪、底下還有資料」的空殼路徑（例如 %s），已照樣備份底下的資料。"
             % (len(ex.phantoms), fsb.mask_path(ex.phantoms[0])))
    ledgers.mark_ok("firestore", snapshot=sid, documents=len(ex.docs), photos=len(rows), downloaded=fetched)
    heartbeat(ctx, "weekly", True)
    _say("✓ 資料庫備份完成（%s）。雲端硬碟程式會自己上傳；右上角（Windows 右下角）的雲端硬碟圖示顯示「已是最新狀態」才算傳完。" % sid)
    return ex, rows, pool


# ════════════════════════════════════════════════════════════════════════
# blogs
# ════════════════════════════════════════════════════════════════════════

def _local_time(ts):
    if not ts:
        return ""
    try:
        d = datetime.datetime.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        return d.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(ts)


def blog_markdown(seat, post_id, entry, comments, photo_files):
    """一篇部落格 → md（給人看的備份；正文逐字保留）。"""
    who = {"parent": "家長", "teacher": "導師"}
    lines = ["# %s" % (entry.get("title") or "（沒有標題）"), "",
             "- 座號：%s" % seat,
             "- 日期：%s" % (entry.get("date") or ""),
             "- 作者：%s" % who.get(entry.get("author"), entry.get("author") or ""),
             "- 網站上：%s" % ("顯示中" if entry.get("visible") is not False else "已下架"),
             "- 文章代號：%s" % post_id,
             "- 發文時間：%s" % _local_time(entry.get("createdAt"))]
    if entry.get("updatedAt"):
        lines.append("- 最後修改：%s" % _local_time(entry.get("updatedAt")))
    for name, cap in photo_files:
        lines.append("- 照片：%s%s" % (name, ("（%s）" % cap) if cap else ""))
    lines += ["", "---", "", entry.get("body") or "", "", "---", "", "## 對話（%d 則）" % len(comments), ""]
    for c in comments:
        tag = "（已收起）" if c.get("status") == "hidden" else ""
        lines += ["**%s**（%s）%s：" % (who.get(c.get("role"), c.get("role") or ""), _local_time(c.get("createdAt")), tag),
                  c.get("body") or "", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def do_blogs(ctx, ex=None, rows=None, pool=None):
    need = ctx.tree.require("blog_archive")
    if ex is None:
        c = ctx.client()
        _say("學生部落格匯出：%s" % c.describe_target())
        ex, rows, _, pool = export_all(ctx, roots=["student_blogs"],
                                       photo_filter=lambda p: p.split("/")[-2] == "images")
    photo_key = {r["path"]: r["key"] for r in rows}
    entries, comments = {}, {}
    for d in ex.docs:
        segs = d["path"].split("/")
        if segs[0] != "student_blogs" or len(segs) < 4 or segs[2] != "entries":
            continue
        if not SEAT_RE.match(segs[1]) or not schema.POST_ID_RE.match(segs[3]):
            _say("  略過一份格式不對的部落格文件：%s" % fsb.mask_path(d["path"]))
            continue
        if len(segs) == 4:
            entries[d["path"]] = fr.decode_fields(d["fields"])
        elif len(segs) == 6 and segs[4] == "blog_comments":
            comments.setdefault("/".join(segs[:4]), []).append(fr.decode_fields(d["fields"]))
    local_root = ctx.data / "student-blogs"
    mirror = Mirror(ctx.data / "ledgers" / "blog-mirror.json")
    written = 0
    seats = set()
    for path in sorted(entries):
        e = entries[path]
        _, seat, _, post_id = path.split("/")
        seats.add(seat)
        try:
            year = ctx.tree.school_year(e.get("date") or post_id[:10])
        except ValueError:
            year = ctx.tree.school_year(post_id[:10])
        folder = local_root / seat
        files = []
        photo_files = []
        for ph in e.get("photos") or []:
            pid = str((ph or {}).get("pid", ""))
            if not BLOG_PID_RE.match(pid):
                continue
            key = photo_key.get("%s/images/%s" % (path, pid))
            if not key:
                continue
            doc = pool.load(key)
            b64 = ((doc.get("fields") or {}).get("data") or {}).get("stringValue") or ""
            try:
                jpeg = base64.b64decode(b64)
            except (ValueError, TypeError):
                continue
            if not jpeg.startswith(b"\xff\xd8"):
                continue
            name = "%s-%s.jpg" % (post_id, pid)
            files.append((folder / name, jpeg))
            photo_files.append((name, (ph or {}).get("caption") or ""))
        cs = sorted(comments.get(path, []), key=lambda x: str(x.get("createdAt") or ""))
        md = blog_markdown(seat, post_id, e, cs, photo_files).encode("utf-8")
        files.append((folder / ("%s.md" % post_id), md))
        dst_dir = ensure_below(need["blog_archive"], seat, year)
        for p, data in files:
            if not p.exists() or md5_file(p) != md5_bytes(data):
                write_bytes_atomic(p, data)
                written += 1
            mirror.sync(p, dst_dir / p.name, "%s/%s" % (seat, p.name))
    mirror.save()
    ledgers.mark_ok("blogs", entries=len(entries), seats=len(seats), copied=mirror.copied)
    heartbeat(ctx, "nightly", True)
    _say("✓ 學生部落格：%d 個座號、%d 篇；本機更新 %d 個檔，同步夾 04_部落格歸檔 新增或更新 %d 個檔（逐檔比對 md5）。"
         % (len(seats), len(entries), written, mirror.copied))


# ════════════════════════════════════════════════════════════════════════
# records
# ════════════════════════════════════════════════════════════════════════

def collect_records(data):
    """data/ 底下要備份的檔：回 (進 zip 的相對路徑, 要鏡像的相對路徑, 略過的捷徑數)。
    backups/、inbox/、exports/ 不備份；student-blogs/ 裡的照片由 blogs 那一條負責（04_部落格歸檔）。"""
    data = Path(data)
    to_zip, to_mirror, links = [], [], 0
    for dirpath, dirnames, filenames in os.walk(str(data), followlinks=False):
        rel_dir = Path(dirpath).relative_to(data).as_posix()
        if rel_dir == ".":
            rel_dir = ""
            dirnames[:] = [d for d in dirnames if d not in SKIP_TOP]
        keep_dirs = []
        for d in dirnames:
            if d.startswith("."):
                continue
            if os.path.islink(os.path.join(dirpath, d)):
                links += 1
                continue
            keep_dirs.append(d)
        dirnames[:] = sorted(keep_dirs)
        for f in sorted(filenames):
            if f.startswith(".") or f.startswith(TMP_PREFIX) or f in ("Thumbs.db", "desktop.ini"):
                continue
            full = os.path.join(dirpath, f)
            if os.path.islink(full):
                links += 1
                continue
            rel = (rel_dir + "/" + f) if rel_dir else f
            kind = media_kind(f)
            try:
                big = os.path.getsize(full) >= BIG_FILE
            except OSError:
                continue
            if kind in ("photo", "video", "audio") or big:
                if rel.startswith("student-blogs/"):
                    continue
                to_mirror.append(rel)
            else:
                to_zip.append(rel)
    return to_zip, to_mirror, links


def mirror_dest(rel, need):
    parts = rel.split("/")
    if parts[0] == "albums" and len(parts) >= 3:
        return need["album_originals"].joinpath(*parts[1:])
    return need["records_media"].joinpath(*parts)


def list_record_zips(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and RECORDS_RE.match(p.name))


def do_records(ctx, keep):
    need = ctx.tree.require("records_backup", "records_media", "album_originals")
    if not ctx.data.is_dir():
        raise DriveTreeError(["找不到 data/ 資料夾。", "→ 先跑 %s scripts/init_data.py" % PY])
    to_zip, to_mirror, links = collect_records(ctx.data)
    _say("紀錄備份：%d 個檔進壓縮檔、%d 個照片／影音／大檔做增量鏡像%s"
         % (len(to_zip), len(to_mirror), ("（略過 %d 個捷徑，例如指向 teacher-records-kit 的 records/）" % links) if links else ""))
    sid = fsb.free_snapshot_id(lambda i: (need["records_backup"] / ("records-%s.zip" % i)).exists())
    tmpdir = ctx.data / "backups" / ".tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    name = "records-%s.zip" % sid
    zpath = tmpdir / name
    try:
        with zipfile.ZipFile(str(zpath), "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as z:
            for rel in to_zip:
                z.write(str(ctx.data.joinpath(*rel.split("/"))), arcname=rel)
        with zipfile.ZipFile(str(zpath)) as z:
            bad = z.testzip()
        if bad is not None:
            raise CopyError("壓縮檔自我檢查失敗（%s）" % bad)
        md5, _ = copy_verified(zpath, need["records_backup"] / name)
        copy_verified(zpath, need["records_backup"] / RECORDS_LATEST, overwrite=True)
        size = zpath.stat().st_size
    finally:
        if zpath.exists():
            zpath.unlink()
    zips = list_record_zips(need["records_backup"])
    doomed = zips[:-keep] if len(zips) > keep else []
    for p in doomed:
        p.unlink()
    _say("  壓縮檔：01_機密（只有導師）/紀錄備份/%s（%s，md5 已比對）＋ %s%s"
         % (name, human_size(size), RECORDS_LATEST, ("；刪掉較舊的 %d 份" % len(doomed)) if doomed else ""))
    mirror = Mirror(ctx.data / "ledgers" / "media-mirror.json")
    try:
        for rel in to_mirror:
            mirror.sync(ctx.data.joinpath(*rel.split("/")), mirror_dest(rel, need), rel)
    finally:
        mirror.save()
    ledgers.mark_ok("records", zip=name, files=len(to_zip), media=len(to_mirror), media_copied=mirror.copied)
    _say("✓ 紀錄備份完成：照片與附件新增或更新 %d 個（相簿原圖在 03_相簿原圖/，其他在 紀錄備份/照片與附件/）。" % mirror.copied)


# ════════════════════════════════════════════════════════════════════════
# restore
# ════════════════════════════════════════════════════════════════════════

def _print_paths(label, items, limit=20):
    if not items:
        return
    _say("  %s %d 份：" % (label, len(items)))
    for p in items[:limit]:
        _say("    %s" % fsb.mask_path(p))
    if len(items) > limit:
        _say("    …還有 %d 份（完整清單在上面寫出的計畫檔）" % (len(items) - limit))


def do_restore_firestore(ctx, a):
    tree = ctx.tree
    snap_root = tree.path("fs_snapshots")
    latest = tree.path("fs_latest")
    sync_photos = tree.path("fs_photos")
    snap = fsb.find_snapshot(a.snapshot, ctx.fs_base,
                             snap_root if (snap_root and snap_root.is_dir()) else None,
                             latest if (latest and latest.is_dir()) else None)
    if snap is None:
        raise fsb.SnapshotError("找不到快照「%s」。跑 %s scripts/backup.py list%s 看有哪些。"
                                % (a.snapshot, PY, paths.rerun_flags(a)))
    man, docs, photos = fsb.load_snapshot(snap)
    if man.get("project") != ctx.cfg.project_id and not a.to_other_project:
        _say("✗ 這份快照是專案 %s 的，現在的設定是 %s。" % (man.get("project"), ctx.cfg.project_id))
        _say("  → 真的要搬到另一個專案（例如換了新專案），加 --to-other-project。")
        return EXIT_STOPPED
    pool = fsb.Pool(ctx.fs_base / "photos", sync_photos if (sync_photos and sync_photos.is_dir()) else None)
    chosen = set(fsb.select_paths([d["path"] for d in docs] + [r["path"] for r in photos], a.only or ()))
    if not chosen:
        _say("✗ 快照 %s 裡沒有符合 --only 的文件。" % man.get("id"))
        return EXIT_STOPPED
    missing = [r["key"] for r in photos if r["path"] in chosen and pool.find(r["key"]) is None]
    if missing:
        _say("✗ 照片池少了 %d 份照片（本機與同步夾都沒有），還原不完整，先停下來。" % len(missing))
        return EXIT_STOPPED
    c = ctx.client()
    _say("還原資料庫%s：快照 %s（%s）→ %s" % ("" if a.apply else "（預覽，不會寫任何東西）", man.get("id"),
                                         man.get("created") or "", c.describe_target()))
    if not a.apply:
        now = {}
        lst = sorted(chosen)
        for i in range(0, len(lst), 100):
            now.update(c.batch_get(lst[i:i + 100], mask=["__name__"]))
        create = sorted(p for p in lst if now.get(p) is None)
        exist = sorted(p for p in lst if now.get(p) is not None)
        plan = ctx.data / "exports" / ("restore-plan-%s.txt" % fsb.snapshot_id())
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text("".join("新建 %s\n" % p for p in create) + "".join("可能覆蓋 %s\n" % p for p in exist),
                        encoding="utf-8")
        _say("  快照裡選中的文件 %d 份：現在不在（會新建）%d 份、現在還在（內容不同才會覆蓋）%d 份。"
             % (len(lst), len(create), len(exist)))
        _print_paths("會新建", create)
        _print_paths("可能覆蓋", exist, limit=10)
        _say("  完整清單：%s" % plan.relative_to(paths.root()).as_posix())
        _say("  快照之後才新增的文件**不會被刪**。真的要寫的時候會先自動做一份「還原前」快照。")
        _say("\n這只是預覽。老師說好之後再跑同一個指令加 --apply。")
        return 0
    with ctx.lock():
        _say("  先做一份「還原前」快照（出事可以再還原回來）……")
        ex, rows, _, pool = export_all(ctx)
        pre_id = fsb.free_snapshot_id(lambda i: (ctx.fs_base / i).exists())
        fsb.write_snapshot(ctx.fs_base, pre_id, ctx.cfg.project_id, ex, rows, kind="pre-restore",
                           created=ledgers.now_iso())
        pres = [(i, p) for i, p in fsb.list_snapshots(ctx.fs_base)
                if (fsb.read_manifest(p) or {}).get("kind") == "pre-restore"]
        fsb.prune(pres, PRE_RESTORE_KEEP)
        _say("  還原前快照：data/backups/firestore/%s" % pre_id)
        writes, summary = fsb.restore_writes(c, docs, photos, pool, ex.docs, rows, only=a.only or ())
        if not writes:
            _say("✓ 選中的 %d 份文件跟現在一模一樣，不用寫。" % summary["same"])
            return 0
        n = c.commit_all(writes, what="還原資料庫")
        written = [w["update"]["name"].split("/documents/", 1)[1] for w in writes]
        back = {}
        for i in range(0, len(written), 8):
            back.update(fsb.batch_get_raw(c, written[i:i + 8]))
        want = {w["update"]["name"].split("/documents/", 1)[1]: w["update"]["fields"] for w in writes}
        bad = [p for p in written if back.get(p) is None or (back[p].get("fields") or {}) != want[p]]
        if bad:
            _say("✗ 寫完讀回來有 %d 份對不上（例如 %s）。還原前快照在 %s，可以再還原回去。"
                 % (len(bad), fsb.mask_path(bad[0]), pre_id))
            return 1
        _say("✓ 已還原：新建 %d 份、覆蓋 %d 份（%d 次寫入批次），內容相同略過 %d 份；讀回逐欄比對一致。"
             % (len(summary["create"]), len(summary["overwrite"]), n, summary["same"]))
        _say("  要反悔：先預覽 %s scripts/backup.py restore firestore --snapshot %s%s（看過再照它說的加 --apply）。"
             % (PY, pre_id, paths.rerun_flags(a)))
        if summary["create"]:
            _say("    注意：還原前快照裡沒有這次新建的 %d 份文件，反悔也不會把它們拿掉（還原從來不刪文件）；"
                 "要收回，照那一種內容的劇本另外下架（visible: false）或刪除。" % len(summary["create"]))
    return 0


def _safe_member(name):
    if not name or name.startswith("/") or "\\" in name or ":" in name:
        return False
    parts = name.split("/")
    return all(p and p not in (".", "..") for p in parts)


def _mirror_back(need):
    """鏡像裡的照片與附件 → 對應回 data/ 的相對路徑：[(同步夾檔, 相對路徑)]。"""
    out = []
    for base, prefix in ((need.get("records_media"), ""), (need.get("album_originals"), "albums/")):
        if base is None or not Path(base).is_dir():
            continue
        for dirpath, _, files in os.walk(str(base)):
            for f in files:
                if f.startswith(".") or f.startswith(TMP_PREFIX):
                    continue
                full = Path(dirpath) / f
                rel = prefix + full.relative_to(base).as_posix()
                out.append((full, rel))
    return out


def do_restore_records(ctx, a):
    need = ctx.tree.require("records_backup", "records_media", "album_originals")
    if a.zip == "latest":
        zpath = need["records_backup"] / RECORDS_LATEST
    elif "/" in a.zip or "\\" in a.zip:
        zpath = Path(a.zip)
    else:
        zpath = need["records_backup"] / a.zip
    if not zpath.is_file():
        _say("✗ 找不到紀錄備份：%s（跑 %s scripts/backup.py list%s 看有哪些）" % (zpath.name, PY, paths.rerun_flags(a)))
        return EXIT_STOPPED
    plan = {"new": [], "same": 0, "differ": [], "bad": []}
    with zipfile.ZipFile(str(zpath)) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        for info in infos:
            if not _safe_member(info.filename):
                plan["bad"].append(info.filename)
                continue
            target = ctx.data.joinpath(*info.filename.split("/"))
            if not target.exists():
                plan["new"].append(info)
            elif md5_file(target) == md5_bytes(z.read(info)):
                plan["same"] += 1
            else:
                plan["differ"].append(info)
        media = [(src, rel) for src, rel in _mirror_back(need) if not ctx.data.joinpath(*rel.split("/")).exists()]
        _say("還原 data/%s：%s" % ("" if a.apply else "（預覽，不會寫任何東西）", zpath.name))
        _say("  壓縮檔裡 %d 個檔：data/ 沒有的 %d 個（會補回）、一樣的 %d 個、內容不同的 %d 個（%s）"
             % (len(infos), len(plan["new"]), plan["same"], len(plan["differ"]),
                "加了 --overwrite，會用備份蓋掉" if a.overwrite else "不會動；要用備份蓋掉加 --overwrite"))
        _say("  照片與附件鏡像：data/ 沒有的 %d 個（會補回；已經有的不動）" % len(media))
        if plan["bad"]:
            _say("  ！ 有 %d 個檔名不安全（絕對路徑或 ..），一律略過" % len(plan["bad"]))
        for info in (plan["new"] + plan["differ"])[:15]:
            _say("    %s" % info.filename)
        if not a.apply:
            _say("\n這只是預覽。老師說好之後再跑同一個指令加 --apply。")
            return 0
        todo = plan["new"] + (plan["differ"] if a.overwrite else [])
        for info in todo:
            write_bytes_atomic(ctx.data.joinpath(*info.filename.split("/")), z.read(info))
    for src, rel in media:
        copy_verified(src, ctx.data.joinpath(*rel.split("/")))
    _say("✓ 已還原 %d 個檔、照片與附件 %d 個（照片逐檔比對 md5）。" % (len(todo), len(media)))
    return 0


# ════════════════════════════════════════════════════════════════════════
# list
# ════════════════════════════════════════════════════════════════════════

def do_list(ctx):
    _say("本機快照（data/backups/firestore/）：")
    local = fsb.list_snapshots(ctx.fs_base)
    if not local:
        _say("  （沒有）")
    for i, p in local:
        m = fsb.read_manifest(p) or {}
        cnt = m.get("counts") or {}
        _say("  %s  %s  文件 %d、照片 %d" % (i, "還原前" if m.get("kind") == "pre-restore" else "一般",
                                           cnt.get("documents", 0), cnt.get("photos", 0)))
    probs = ctx.tree.problems(("fs_snapshots", "records_backup"))
    if probs:
        _say("同步夾：看不到（%s）" % probs[0].lines[0])
        return 0
    _say("同步夾快照（05_全站備份/firestore/snapshots/）：")
    sync = fsb.list_sync_snapshots(ctx.tree.path("fs_snapshots"))
    _say("  " + ("、".join(i for i, _ in sync) if sync else "（沒有）"))
    _say("紀錄備份（01_機密（只有導師）/紀錄備份/）：")
    zips = list_record_zips(ctx.tree.path("records_backup"))
    _say("  " + ("、".join(p.name for p in zips) if zips else "（沒有）"))
    return 0


# ════════════════════════════════════════════════════════════════════════

def guarded(ctx, kind, fn):
    """跑一條備份線：成功回 0；停下來回 2；失敗回 1（並記 last_fail，不動 last_ok）。"""
    try:
        with ctx.lock():
            fn()
        return 0
    except LockBusy as e:
        _say("✗ %s" % e)
        return EXIT_STOPPED
    except DriveTreeError as e:
        _say(e.plain())
        ledgers.mark_fail(kind, e.lines[0])
        return EXIT_STOPPED
    except (fr.FirestoreError, gauth.AuthError) as e:
        _say(e.plain())
        ledgers.mark_fail(kind, e.title)
        if kind == "firestore":
            heartbeat(ctx, "weekly", False)
        return 1
    except (CopyError, fsb.SnapshotError, OSError, zipfile.BadZipFile, ValueError) as e:
        _say("✗ %s備份失敗：%s" % ({"firestore": "資料庫", "records": "紀錄", "blogs": "部落格"}[kind], e))
        _say("  → 修好後再跑同一個指令（重跑是安全的：已經複製好的檔會跳過）。")
        ledgers.mark_fail(kind, e)
        return 1


def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    paths.add_root_arg(common)
    common.add_argument("--emulator", action="store_true", help="連本機模擬器（測試用）")
    ap = argparse.ArgumentParser(description="備份與還原（網站資料庫、本機 data/、學生部落格 → 雲端硬碟同步夾）")
    sub = ap.add_subparsers(dest="cmd")
    for name, text in (("firestore", "網站資料庫 → 快照"), ("records", "本機 data/ → 紀錄備份 zip"),
                       ("blogs", "學生部落格 → 本機鏡像與 04_部落格歸檔"), ("all", "依序跑 firestore、blogs、records")):
        p = sub.add_parser(name, parents=[common], help=text)
        if name in ("firestore", "records", "all"):
            p.add_argument("--keep", type=int, default=KEEP_DEFAULT, help="保留最近幾份（預設 %d）" % KEEP_DEFAULT)
    sub.add_parser("list", parents=[common], help="列出有哪些快照與紀錄備份（唯讀）")
    rp = sub.add_parser("restore", help="還原（預設只預覽）")
    rsub = rp.add_subparsers(dest="what")
    rf = rsub.add_parser("firestore", parents=[common], help="從快照寫回資料庫")
    rf.add_argument("--snapshot", default="latest", help="快照代號（日期時間，例如 20261001-183000）或 latest")
    rf.add_argument("--only", action="append", metavar="路徑", help="只還原這個路徑（含底下全部）；可以給好幾次")
    rf.add_argument("--apply", action="store_true", help="真的寫（先自動做還原前快照）")
    rf.add_argument("--to-other-project", action="store_true", help="快照是別的專案的，也照樣寫（換專案時用）")
    rr = rsub.add_parser("records", parents=[common], help="從紀錄備份 zip 還原 data/")
    rr.add_argument("--zip", default="latest", help="紀錄備份的檔名（records-日期時間.zip）或 latest")
    rr.add_argument("--overwrite", action="store_true", help="data/ 已經有、內容不同的檔也用備份蓋掉")
    rr.add_argument("--apply", action="store_true", help="真的寫")
    a = ap.parse_args(argv)
    if not a.cmd or (a.cmd == "restore" and not getattr(a, "what", None)):
        ap.print_help()
        return EXIT_STOPPED
    if hasattr(a, "keep") and not (1 <= a.keep <= 365):
        _say("✗ --keep 要是 1–365")
        return EXIT_STOPPED
    try:
        ctx = Ctx(a)
    except classcfg.ConfigError as e:
        _say("✗ %s" % e)
        return EXIT_STOPPED
    except ValueError as e:
        _say("✗ %s" % e)
        return EXIT_STOPPED

    if a.cmd == "list":
        return do_list(ctx)
    if a.cmd == "restore":
        try:
            if a.what == "firestore":
                return do_restore_firestore(ctx, a)
            with ctx.lock():
                return do_restore_records(ctx, a)
        except LockBusy as e:
            _say("✗ %s" % e)
            return EXIT_STOPPED
        except DriveTreeError as e:
            _say(e.plain())
            return EXIT_STOPPED
        except fsb.SnapshotError as e:
            _say("✗ %s" % e)
            return EXIT_STOPPED
        except (fr.FirestoreError, gauth.AuthError) as e:
            _say(e.plain())
            return 1
        except (CopyError, OSError, zipfile.BadZipFile, ValueError) as e:
            _say("✗ 還原失敗：%s" % e)
            return 1

    if a.cmd == "firestore":
        return guarded(ctx, "firestore", lambda: do_firestore(ctx, a.keep))
    if a.cmd == "records":
        return guarded(ctx, "records", lambda: do_records(ctx, a.keep))
    if a.cmd == "blogs":
        return guarded(ctx, "blogs", lambda: do_blogs(ctx))
    # all
    got = {}

    def fs():
        got["fs"] = do_firestore(ctx, a.keep)

    rcs = [guarded(ctx, "firestore", fs)]
    if "fs" in got:
        ex, rows, pool = got["fs"]
        rcs.append(guarded(ctx, "blogs", lambda: do_blogs(ctx, ex, rows, pool)))
    else:
        rcs.append(guarded(ctx, "blogs", lambda: do_blogs(ctx)))
    rcs.append(guarded(ctx, "records", lambda: do_records(ctx, a.keep)))
    if any(rcs):
        _say("\n✗ 三條備份沒有全部成功（資料庫 %d、部落格 %d、紀錄 %d；0＝成功）。照上面的「→」處理後再跑一次。" % tuple(rcs))
        return 1 if 1 in rcs else EXIT_STOPPED
    _say("\n✓ 三條備份都完成了。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
