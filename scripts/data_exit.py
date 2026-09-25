#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""data_exit.py — 資料退場：學生轉出、學年結束、家長要求刪除自己的資料（docs/DATA-MODEL.md §6）。

**刪了就回不來。** 所以：
  · 預設只預覽：列出會刪、會改的網站資料庫路徑，以及這台電腦、雲端硬碟同步夾裡會刪的資料夾（不寫任何東西）。
  · 加 --apply 才做，而且做之前**自動先備份整個資料庫**（備份失敗就停，一筆都不刪）。
  · 順序固定：備份 → 撤權限 → 刪資料 → 本機與同步夾 → （選）清舊備份。
    要找某位家長寫過的東西，一定**先**讀出他在名單上的作者代號，**再**撤名單（名單一刪就查不到了）。
  · 網站資料庫的 REST 沒有「連底下一起刪」：一律先列出底下的子集合，從最深的刪起。
  · Firebase 登入帳號（Authentication）**不由程式刪**：印出主控台的操作步驟，請老師自己按。主控台要貼完整信箱，
    所以每次預覽都把完整信箱寫進 data/exports/data-exit/<座號或代號>-auth-cleanup.txt（只給老師開；代理的設定擋住了
    data/exports/，螢幕上只印路徑）。contacts.csv 那幾列一刪就查不到了——**先跑一次預覽，再請老師刪列**。
  · year-end 在撤權限之前先立「學年封存」旗標（data/ledgers/year-end.json）：旗標還在時 access_sync.py --apply
    要多加 --new-roster 才寫，免得上一屆的名單檔一同步就把上一屆的家長全部加回去。
  · 本機的三個名單檔（roster.csv、contacts.csv、parent-roles.yaml）由老師自己先改好；還沒改就停下來，
    不然下次名單同步會把人加回去。

三種情況：
  seat 05             學生轉出（座號 05）：撤掉只對應這個座號的家長；刪部落格（文章、照片、對話）、名冊那一筆、
                      回條；那些家長的留言預設**收起並改署名「已退場家長」**（留言串牽涉別的家長），
                      加 --delete-comments 才整則刪；刪 data/student-blogs/05/、同步夾 04_部落格歸檔/05/ 與 學生個別資料/05/。
  parent --email X    家長要求刪除自己的資料：撤名單；刪他的留言、回條、他發的部落格文章（連照片與對話）、他在對話串的留言。
  year-end --mode M   學年結束：先備份資料庫＋匯出部落格，再撤掉所有人的權限（只留導師），然後依 M：
                        archive  封存：資料留著，只有導師看得到
                        photos   只清照片（騰出免費方案的 1 GiB），文字留著
                        wipe     清空所有內容（紀事、相簿、私密紀事、單頁、部落格、名冊、心跳……）
  --purge-backups     （seat、parent 可加）做完後重做一份乾淨的備份，並刪掉**所有**較舊的資料庫快照與紀錄備份
                      （舊備份裡還有這個人的資料）。不加的話，舊備份照 30 份輪替自然淘汰。

用法（Windows 把 python3 換成 py -3）：
  python3 scripts/data_exit.py seat 05
  python3 scripts/data_exit.py seat 05 --apply
  python3 scripts/data_exit.py parent --email someone@example.com --apply --purge-backups
  python3 scripts/data_exit.py year-end --mode photos --apply

exit code：0 成功；2 停下來了（前置條件不符、一筆都沒刪）；1 做到一半失敗（重跑同一個指令會從目前的狀態接著做）。
"""
import sys
import shutil
import hashlib
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, gauth  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib import fsbackup as fsb  # noqa: E402
from lib.drivetree import DriveTree, DriveTreeError  # noqa: E402
from lib.emailkey import email_key  # noqa: E402
from lib.filesafe import move_to_trash, read_json, write_json_atomic, write_text_atomic, RunLock, LockBusy  # noqa: E402
from lib.seats import parse_seat  # noqa: E402
from lib.sources import load_roster, load_contacts, load_roles, contact_emails, SourceError  # noqa: E402
from lib import ledgers  # noqa: E402
from lib.hostos import PY  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

EXIT_STOPPED = 2
COMMENT_OWNERS = ("posts", "albums", "private_posts")
READ_OWNERS = ("posts", "private_posts")
PHOTO_OWNERS = ("posts", "albums", "private_posts", "pages", "parent_photo_display", "personal_photos")
WIPE_COLLECTIONS = ("posts", "albums", "private_posts", "pages", "student_blogs", "roster", "ops", "seating",
                    "parent_photo_display", "personal_photos", "blog_notify_queue")
RETIRED_NAME = "已退場家長"


class Stop(Exception):
    pass


class Plan(object):
    """一次退場要做的事。firestore 路徑一律相對 documents/。"""

    def __init__(self, title):
        self.title = title
        self.revoke = []        # 撤權限：刪這些名單文件
        self.updates = []       # (路徑, 資料, 要改的欄位)
        self.deletes = []       # 刪這些文件（已展開到最深，深的在前）
        self.local = []         # 這台電腦要刪的資料夾
        self.sync = []          # 同步夾要刪的資料夾
        self.manual = []        # 老師要自己做的事
        self.notes = []
        self.ledger_seats = []  # blog-mirror 台帳要清掉的座號
        self.auth_keys = []     # 登入帳號要由老師在主控台刪掉的人（email 鍵）

    def firestore_count(self):
        return len(self.revoke) + len(self.updates) + len(self.deletes)


def mask(p):
    return fsb.mask_path(p)


# ── 讀資料庫 ─────────────────────────────────────────────────────────────

def doc_paths(w, coll):
    """集合底下所有文件路徑（含「本身已刪、底下還有東西」的空殼）。"""
    return [w._rel(r["name"]) for r in w.list_raw(coll, mask=["__name__"], show_missing=True)]


def expand(w, doc_path):
    """一份文件連同底下全部 → 要刪的路徑（深的在前）。空殼文件本身不用刪（它本來就不存在）。"""
    subs = [doc_path + "/" + cid for cid in w.collection_ids(doc_path)]
    ex = w.walk(roots=subs, names_only=True) if subs else fsb.Export()
    out = [d["path"] for d in ex.docs] + [r["path"] for r in ex.photos]
    if w.c.get(doc_path, mask=["__name__"]) is not None:
        out.append(doc_path)
    return sorted(set(out), key=lambda p: (-p.count("/"), p))


def comments_by(w, aliases):
    """三種留言裡作者代號在 aliases 裡的：[(路徑, 資料)]。逐篇掃（DATA-MODEL §6.1：不為此開索引）。"""
    out = []
    if not aliases:
        return out
    for coll in COMMENT_OWNERS:
        for owner in doc_paths(w, coll):
            for d in w.c.list_docs(owner + "/comments"):
                if d.data.get("authorAlias") in aliases:
                    out.append((d.path, d.data))
    return out


def reads_of(w, keys):
    """這些 email 鍵在紀事、私密紀事上的回條（只回真的存在的）。"""
    if not keys:
        return []
    want = []
    for coll in READ_OWNERS:
        for owner in doc_paths(w, coll):
            for k in keys:
                want.append("%s/reads/%s" % (owner, k))
    out = []
    for i in range(0, len(want), 100):
        got = w.c.batch_get(want[i:i + 100], mask=["__name__"])
        out += [p for p in want[i:i + 100] if got.get(p) is not None]
    return out


def alias_of(c, key):
    """名單上的作者代號；名單已經撤了就查本機台帳 alias-history.jsonl（access_sync 移除人時會記）。"""
    d = c.get("allowlist/" + key)
    if d is not None and d.data.get("alias"):
        return d.data["alias"]
    p = paths.data_dir() / "ledgers" / "alias-history.jsonl"
    if p.exists():
        import json
        for line in reversed(p.read_text(encoding="utf-8").splitlines()):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("emailKey") == key and rec.get("alias"):
                return rec["alias"]
    return None


# ── 三種計畫 ─────────────────────────────────────────────────────────────

def plan_seat(c, w, seat, teacher_key, tree, delete_comments):
    p = Plan("學生轉出（座號 %s）" % seat)
    removed_keys, aliases = [], set()
    for d in c.list_docs("parent_child_map"):
        seats = list(d.data.get("seats") or [])
        if seat not in seats:
            continue
        rest = [s for s in seats if s != seat]
        if rest:
            p.updates.append((d.path, {"seats": rest, "updatedAt": fr.SERVER_TIME}, ["seats", "updatedAt"]))
            p.notes.append("%s 還有其他孩子在班上（座號 %s），只拿掉座號 %s" % (mask(d.id), "、".join(rest), seat))
            continue
        p.revoke.append(d.path)
        if d.data.get("kind") == "parent" and d.id != teacher_key:
            a = alias_of(c, d.id)
            if a:
                aliases.add(a)
            removed_keys.append(d.id)
            for coll in ("allowlist", "private_allowlist"):
                if c.get("%s/%s" % (coll, d.id), mask=["__name__"]) is not None:
                    p.revoke.append("%s/%s" % (coll, d.id))
    p.deletes += expand(w, "student_blogs/" + seat)
    for coll in ("parent_photo_display", "personal_photos"):
        p.deletes += expand(w, "%s/%s" % (coll, seat))
    ros = c.get("roster/students")
    if ros is not None and any((s or {}).get("seat") == seat for s in ros.data.get("students") or []):
        keep = [s for s in ros.data.get("students") or [] if (s or {}).get("seat") != seat]
        p.updates.append(("roster/students", {"students": keep, "updatedAt": fr.SERVER_TIME}, ["students", "updatedAt"]))
    for d in c.list_docs("seating"):
        rows = d.data.get("rows") or []
        if any(seat in ((r or {}).get("seats") or []) for r in rows):
            new_rows = [dict(r, seats=["" if s == seat else s for s in (r or {}).get("seats") or []]) for r in rows]
            p.updates.append((d.path, {"rows": new_rows, "updatedAt": fr.SERVER_TIME}, ["rows", "updatedAt"]))
    for q in doc_paths(w, "blog_notify_queue"):
        if q.split("/")[-1].startswith(seat + "__"):
            p.deletes += expand(w, q)
    p.deletes += reads_of(w, removed_keys)
    for path, data in comments_by(w, aliases):
        if delete_comments:
            p.deletes.append(path)
        else:
            p.updates.append((path, {"authorName": RETIRED_NAME, "status": "hidden"}, ["authorName", "status"]))
    local = paths.data_dir() / "student-blogs" / seat
    if local.exists():
        p.local.append(local)
    # v1.1：這台電腦裡這位孩子的個人照、家長合照（檔名只用座號：03.jpg、3.png……）
    for sub in ("personal-photos", "parent-photos"):
        folder = paths.data_dir() / sub
        for f in (sorted(folder.iterdir()) if folder.is_dir() else []):
            stem, dot, ext = f.name.partition(".")
            if f.is_file() and dot and stem.isdigit() and len(stem) <= 2 and ext.isalpha():
                try:
                    if parse_seat(stem) == seat:
                        p.local.append(f)
                except ValueError:
                    pass
    p.ledger_seats.append(seat)
    if tree.root is not None:
        for q in (tree.path("blog_archive", seat), tree.path("cases", seat)):
            if q is not None and q.exists():
                p.sync.append(q)
    if removed_keys:
        p.auth_keys = list(removed_keys)
        p.manual.append("刪掉 %d 位家長的登入帳號：Firebase 主控台 → Authentication → 使用者 → 搜尋信箱 → 那一列右邊「⋮」→ 刪除帳戶"
                        "（%s；完整信箱在上面印的「要刪的登入帳號」清單檔，請老師自己打開）"
                        % (len(removed_keys), "、".join(mask(k) for k in removed_keys)))
    p.manual.append("人工檢查：班級紀事、相簿、私密紀事裡有沒有這位孩子的照片或文字。程式找不出來——"
                    "請老師在網站上看過，要換照片就改母本重發（--publish --update），要下架就 visible: false。")
    return p


def plan_parent(c, w, key, teacher_key):
    if key == teacher_key:
        raise Stop("這是導師自己的信箱，不能用家長退場刪除")
    p = Plan("家長要求刪除自己的資料（%s）" % mask(key))
    alias = alias_of(c, key)
    if not alias:
        p.notes.append("查不到這位家長的作者代號（名單上沒有、本機台帳也沒有）：他的留言與部落格文章找不出來，只能撤名單與回條")
    for coll in ("allowlist", "private_allowlist", "parent_child_map"):
        if c.get("%s/%s" % (coll, key), mask=["__name__"]) is not None:
            p.revoke.append("%s/%s" % (coll, key))
    aliases = {alias} if alias else set()
    for path, _ in comments_by(w, aliases):
        p.deletes.append(path)
    p.deletes += reads_of(w, [key])
    if alias:
        for seat_doc in doc_paths(w, "student_blogs"):
            for e in c.list_docs(seat_doc + "/entries"):
                if e.data.get("author") == "parent" and e.data.get("authorAlias") == alias:
                    p.deletes += expand(w, e.path)
                    continue
                for bc in c.list_docs(e.path + "/blog_comments"):
                    if bc.data.get("authorAlias") == alias:
                        p.deletes.append(bc.path)
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    for q in doc_paths(w, "blog_notify_queue"):
        if c.get("%s/sent/%s" % (q, h), mask=["__name__"]) is not None:
            p.deletes.append("%s/sent/%s" % (q, h))
    p.auth_keys = [key]
    p.manual.append("刪掉這位家長的登入帳號：Firebase 主控台 → Authentication → 使用者 → 搜尋 %s → 右邊「⋮」→ 刪除帳戶"
                    "（完整信箱在上面印的「要刪的登入帳號」清單檔，請老師自己打開）" % mask(key))
    p.manual.append("他的孩子的 data/student-blogs/ 與 04_部落格歸檔/ 裡，還有他發過的文章備份：下次 backup.py blogs 不會再匯出，"
                    "舊的檔請老師看過後自己刪（檔名是文章代號）。")
    return p


def plan_year_end(c, w, mode, teacher_key):
    p = Plan("學年結束（%s）" % {"archive": "封存", "photos": "只清照片", "wipe": "清空"}[mode])
    for coll in ("allowlist", "private_allowlist"):
        for d in doc_paths(w, coll):
            if d.split("/")[-1] != teacher_key:
                p.revoke.append(d)
    p.revoke += doc_paths(w, "parent_child_map")
    if mode == "photos":
        owners = []
        for coll in PHOTO_OWNERS:
            owners += doc_paths(w, coll)
        for s in doc_paths(w, "student_blogs"):
            owners += doc_paths(w, s + "/entries")
        for o in owners:
            for kind in ("thumbs", "images"):
                p.deletes += [w._rel(r["name"]) for r in w.list_raw(o + "/" + kind, mask=["__name__"])]
        for coll in ("posts", "albums", "private_posts"):
            for d in c.list_docs(coll, mask=["coverThumb"]):
                if d.data.get("coverThumb") is not None:
                    p.updates.append((d.path, {"coverPid": None, "coverThumb": None}, ["coverPid", "coverThumb"]))
    elif mode == "wipe":
        for coll in WIPE_COLLECTIONS:
            for d in doc_paths(w, coll):
                p.deletes += expand(w, d)
        p.manual.append("刪掉導師以外的所有登入帳號：Firebase 主控台 → Authentication → 使用者 → 勾選 → 刪除"
                        "（帳號多的話一頁一頁勾）")
    p.deletes = sorted(set(p.deletes), key=lambda x: (-x.count("/"), x))
    p.manual.append("新學年開始前先改好 data/ 的三個名單檔，再跑 access_sync.py；在那之前**不要**跑它（會把舊名單加回去）。"
                    "做完之後名單同步會上鎖：第一次 --apply 要多加 --new-roster（老師確認是新名單）才會寫。")
    p.manual.append("本機 data/ 與雲端硬碟同步夾的備份，依學校規定的保存年限自己決定留或刪。")
    return p


# ── 前置條件（本機名單檔要先改好）─────────────────────────────────────────

def local_gate_seat(data, seat):
    probs = []
    try:
        students, _ = load_roster(data / "roster.csv")
        if any(s.seat == seat for s in students):
            probs.append("data/roster.csv 還有座號 %s 那一列" % seat)
    except SourceError:
        pass
    try:
        contacts, _ = load_contacts(data / "contacts.csv")
        n = sum(1 for x in contacts if x.seat == seat)
        if n:
            probs.append("data/contacts.csv 還有 %d 列是座號 %s（家長或同仁）" % (n, seat))
    except SourceError:
        pass
    try:
        if seat in load_roles(data / "parent-roles.yaml"):
            probs.append("data/parent-roles.yaml 還有座號 %s" % seat)
    except SourceError:
        pass
    return probs


def local_gate_parent(data, key):
    try:
        contacts, _ = load_contacts(data / "contacts.csv")
    except SourceError:
        return []
    n = sum(1 for x in contacts if x.key == key)
    return ["data/contacts.csv 還有 %d 列是這位家長的信箱" % n] if n else []


# ── 顯示與執行 ───────────────────────────────────────────────────────────

def show(p, limit=30):
    print("%s：網站資料庫要撤權限 %d 份、改 %d 份、刪 %d 份；這台電腦刪 %d 個資料夾；同步夾刪 %d 個資料夾"
          % (p.title, len(p.revoke), len(p.updates), len(p.deletes), len(p.local), len(p.sync)))
    for n in p.notes:
        print("  ・%s" % n)
    groups = (("撤權限", p.revoke), ("改", [u[0] for u in p.updates]), ("刪", p.deletes))
    for label, items in groups:
        if items:
            print("  %s（%d）：" % (label, len(items)))
            for x in items[:limit]:
                print("    %s" % mask(x))
            if len(items) > limit:
                print("    …還有 %d 份（完整清單在計畫檔）" % (len(items) - limit))
    root = paths.root()
    for q in p.local:
        print("  這台電腦刪：%s" % Path(q).relative_to(root).as_posix())
    for q in p.sync:
        print("  同步夾刪：%s" % q)


def write_plan_file(p, tag):
    f = paths.data_dir() / "exports" / ("data-exit-%s-%s.txt" % (tag, fsb.snapshot_id()))
    f.parent.mkdir(parents=True, exist_ok=True)
    lines = [p.title, ""] + ["撤權限 " + mask(x) for x in p.revoke] + ["改 " + mask(u[0]) for u in p.updates] \
        + ["刪 " + mask(x) for x in p.deletes] + ["這台電腦刪 %s" % q for q in p.local] + ["同步夾刪 %s" % q for q in p.sync]
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f


AUTH_DIR = ("exports", "data-exit")
AUTH_HEAD = "# 只給老師自己看：這份有完整信箱。AI 代理的設定擋住了這個資料夾，代理不打開、不念。"


def auth_file_path(tag):
    return paths.data_dir().joinpath(*AUTH_DIR) / ("%s-auth-cleanup.txt" % tag)


def _read_auth_file(f):
    """之前寫過的清單：{email 鍵: 完整信箱}（這支自己讀自己寫的檔；讀不懂就當沒有）。"""
    out = {}
    try:
        text = f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for line in text.splitlines():
        if line.startswith("- ") and "@" in line and "（" not in line:
            raw = line[2:].strip()
            try:
                out.setdefault(email_key(raw), raw)
            except ValueError:
                pass
    return out


def write_auth_file(p, tag, known):
    """刪登入帳號要在主控台貼**完整**信箱，但 contacts.csv 的那幾列一刪就查不到了——所以每次預覽都先把完整信箱
    寫進只給老師開的清單檔（data/exports/ 已被代理的設定擋住）。之前寫過的照樣保留（聯集）。
    known：{email 鍵: 完整信箱}。回 (檔案路徑或 None, 找不到完整信箱的人數)。螢幕上一個信箱都不印。"""
    if not p.auth_keys:
        return None, 0
    f = auth_file_path(tag)
    have = _read_auth_file(f)
    have.update({k: v for k, v in known.items() if k in p.auth_keys})
    lines = [AUTH_HEAD, "# %s：要刪掉的 Firebase 登入帳號" % p.title,
             "# 做法：Firebase 主控台 → Authentication → 使用者（scripts/where.py --open console-users 直接打開）→",
             "#       搜尋框貼上下面的信箱 → 那一列右邊「⋮」→ 刪除帳戶。全部刪完，這個檔可以丟垃圾桶。", ""]
    missing = 0
    for k in sorted(set(have) | set(p.auth_keys)):
        if k in have:
            lines.append("- %s" % have[k])
        else:
            missing += 1
            lines.append("- （這台電腦已經找不到完整信箱）%s" % mask(k))
    write_text_atomic(f, "\n".join(lines) + "\n")
    return f, missing


def execute(c, p, pool_dirs):
    writes = [c.delete_write(x) for x in p.revoke]
    if writes:
        c.commit_all(writes, what="撤權限")
    writes = [c.set_write(path, data, mask_fields=fields) for path, data, fields in p.updates]
    if writes:
        c.commit_all(writes, what="改資料")
    seen, order = set(), []
    for x in p.deletes:
        if x not in seen:
            seen.add(x)
            order.append(x)
    writes = [c.delete_write(x) for x in order]
    if writes:
        c.commit_all(writes, what="刪資料")
    gone = fsb.purge_pool_paths(pool_dirs, p.deletes)
    for q in p.local:
        try:
            move_to_trash(q, None)
        except OSError:
            if Path(q).is_dir():
                shutil.rmtree(str(q), ignore_errors=True)
            else:
                Path(q).unlink(missing_ok=True)
    for q in p.sync:
        shutil.rmtree(str(q), ignore_errors=True)
    if p.ledger_seats:
        f = paths.data_dir() / "ledgers" / "blog-mirror.json"
        led = read_json(f, default={})
        if isinstance(led, dict):
            led = {k: v for k, v in led.items() if k.split("/")[0] not in p.ledger_seats}
            write_json_atomic(f, led)
    return gone


def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    paths.add_root_arg(common)
    common.add_argument("--emulator", action="store_true", help="連本機模擬器（測試用）")
    common.add_argument("--apply", action="store_true", help="真的做（會先自動備份）")
    ap = argparse.ArgumentParser(description="資料退場（預設只預覽；--apply 前會自動備份）")
    sub = ap.add_subparsers(dest="cmd")
    ps = sub.add_parser("seat", parents=[common], help="學生轉出")
    ps.add_argument("seat", help="座號")
    ps.add_argument("--delete-comments", action="store_true", help="那些家長的留言整則刪掉（預設是收起並改署名）")
    ps.add_argument("--purge-backups", action="store_true", help="做完後重做備份並刪掉所有較舊的備份")
    pp = sub.add_parser("parent", parents=[common], help="家長要求刪除自己的資料")
    pp.add_argument("--email", required=True, help="那位家長的信箱")
    pp.add_argument("--purge-backups", action="store_true", help="做完後重做備份並刪掉所有較舊的備份")
    py_ = sub.add_parser("year-end", parents=[common], help="學年結束")
    py_.add_argument("--mode", required=True, choices=("archive", "photos", "wipe"), help="封存／只清照片／清空")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return EXIT_STOPPED
    paths.apply_root(a)
    try:
        cfg = classcfg.load()
    except classcfg.ConfigError as e:
        print("✗ %s" % e)
        return EXIT_STOPPED
    data = paths.data_dir()
    tree = DriveTree.from_config(cfg.raw)
    try:
        c = fr.make_client(cfg.project_id, emulator_flag=a.emulator)
    except ValueError as e:
        print("✗ %s" % e)
        return EXIT_STOPPED
    w = fsb.Walker(c)

    try:
        if a.cmd == "seat":
            seat = parse_seat(a.seat)
            gate = local_gate_seat(data, seat)
            build = lambda: plan_seat(c, w, seat, cfg.teacher_key, tree, a.delete_comments)  # noqa: E731
            tag = "seat-" + seat
        elif a.cmd == "parent":
            key = email_key(a.email)
            gate = local_gate_parent(data, key)
            build = lambda: plan_parent(c, w, key, cfg.teacher_key)  # noqa: E731
            tag = "parent"
        else:
            gate = []
            build = lambda: plan_year_end(c, w, a.mode, cfg.teacher_key)  # noqa: E731
            tag = "year-end-" + a.mode
        print("資料退場%s：%s" % ("" if a.apply else "（預覽，不會動任何東西）", c.describe_target()))
        plan = build()
    except (ValueError, Stop) as e:
        print("✗ %s" % e)
        return EXIT_STOPPED
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        return 1

    show(plan)
    f = write_plan_file(plan, tag)
    print("  完整清單：%s" % f.relative_to(paths.root()).as_posix())
    known = contact_emails(data / "contacts.csv")
    if a.cmd == "parent":
        known[key] = a.email.strip()
        auth_tag = "parent-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    else:
        auth_tag = tag
    af, n_missing = write_auth_file(plan, auth_tag, known)
    if af is not None:
        print("  要刪的登入帳號（完整信箱）：%s" % af.relative_to(paths.root()).as_posix())
        root_flag = (' --root "%s"' % str(a.root).replace("\\", "/")) if getattr(a, "root", None) else ""
        print("    ↑ 只給老師自己打開（%s scripts/where.py --open %s%s）；你不要打開、不要念，信箱只給他在主控台貼。"
              % (PY, af.relative_to(paths.root()).as_posix(), root_flag))
        if n_missing:
            print("    ！ 有 %d 位的完整信箱這台電腦已經找不到了（contacts.csv 那幾列刪掉了）：清單上只有遮住的開頭與網域，"
                  "請老師在主控台用它對照。" % n_missing)
    if gate:
        print("\n✗ 還不能做：這台電腦的名單檔要先改好（不然下次名單同步會把人加回去）：")
        for g in gate:
            print("  ・%s" % g)
        print("  → 請老師自己用 Excel／Numbers 打開 roster.csv、contacts.csv 刪掉那幾列；parent-roles.yaml 可以請你幫忙改。改好再跑一次。")
        return EXIT_STOPPED
    print("\n老師要自己做的事：")
    for m in plan.manual:
        print("  ・%s" % m)
    if not a.apply:
        print("\n這只是預覽。刪了就回不來：請老師看過上面的清單，說好之後再跑同一個指令加 --apply"
              "（會先自動備份整個資料庫）。")
        return 0
    if plan.firestore_count() == 0 and not plan.local and not plan.sync:
        print("✓ 沒有要刪的東西。")
        return 0

    import backup as bk
    try:
        bctx = bk.Ctx(a)
        print("\n① 先備份整個資料庫（失敗就停，一筆都不刪）……")
        with bctx.lock():
            bk.do_firestore(bctx, bk.KEEP_DEFAULT)
        if a.cmd == "year-end":
            print("  再匯出學生部落格到 04_部落格歸檔……")
            with bctx.lock():
                bk.do_blogs(bctx)
    except (DriveTreeError, fr.FirestoreError, gauth.AuthError, LockBusy, OSError, fsb.SnapshotError, ValueError) as e:
        print(e.plain() if hasattr(e, "plain") else "✗ %s" % e)
        print("✗ 備份沒有成功，所以一筆都沒刪。修好備份（playbooks/backup.md）再跑一次。")
        return EXIT_STOPPED
    try:
        print("② 重新列一次要刪的東西（備份的這段時間可能有新資料）……")
        plan = build()
        pool_dirs = [data / "backups" / "firestore" / "photos", tree.path("fs_photos")]
        if a.cmd == "year-end":
            # 先立旗標再撤權限：就算下面做到一半停了，名單同步也不會把上一屆的名單加回去（access_sync.py 看這支旗標）
            ledgers.mark_year_end(a.mode)
        with RunLock(data / "backups" / ".lock"):
            gone = execute(c, plan, pool_dirs)
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        print("  → 做到一半停下來也沒關係：修好後再跑同一個指令，會從目前的狀態接著做"
              "（免費方案每天最多刪 20,000 份，超過就明天再跑）。")
        return 1
    except (Stop, LockBusy, OSError) as e:
        print("✗ %s" % e)
        return 1
    print("✓ 完成：撤權限 %d 份、改 %d 份、刪 %d 份；照片備份池刪 %d 個檔；這台電腦刪 %d 個資料夾、同步夾刪 %d 個資料夾"
          "（雲端硬碟的垃圾桶會保留 30 天）。" % (len(plan.revoke), len(plan.updates), len(plan.deletes), gone,
                                         len(plan.local), len(plan.sync)))
    if getattr(a, "purge_backups", False):
        print("\n③ 清舊備份：重做一份乾淨的備份，再刪掉所有較舊的快照與紀錄備份……")
        try:
            with bctx.lock():
                bk.do_firestore(bctx, 1)
                bk.do_records(bctx, 1)
            for _, q in fsb.list_snapshots(bctx.fs_base):
                if (fsb.read_manifest(q) or {}).get("kind") != "regular":
                    shutil.rmtree(str(q))
        except (DriveTreeError, fr.FirestoreError, gauth.AuthError, LockBusy, OSError, fsb.SnapshotError, ValueError) as e:
            print(e.plain() if hasattr(e, "plain") else "✗ %s" % e)
            again = paths.rerun_flags(a)
            print("✗ 清舊備份沒有完成（資料本身已經刪好了）。修好後跑 %s scripts/backup.py firestore --keep 1%s 與 "
                  "%s scripts/backup.py records --keep 1%s。" % (PY, again, PY, again))
            return 1
        print("✓ 舊備份清好了：現在只剩剛剛那一份乾淨的。")
    elif a.cmd in ("seat", "parent"):
        print("\n提醒：舊的備份（資料庫快照、紀錄備份）裡還有這些資料，會照 30 份輪替慢慢淘汰；"
              "要立刻清掉，重跑一次並加 --purge-backups。")
    if a.cmd == "year-end":
        print("\n名單同步上鎖了：新學年的三個名單檔改好之前不要同步；改好後第一次 access_sync.py --apply 要多加 --new-roster。")
    print("\n老師要自己做的事（再提醒一次）：")
    for m in plan.manual:
        print("  ・%s" % m)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
