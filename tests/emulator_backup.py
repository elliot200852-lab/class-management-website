#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""備份、還原、資料退場的模擬器整合測試（scripts/test_admin.py 的內層在最後呼叫 run()）。

不是 unittest 模組（檔名不以 test 開頭，discover 不會撿到）：它需要 test_admin.py 已經用管理腳本
在模擬器裡種好的虛構班級（名單、紀事、相簿、部落格、私密紀事、單頁），再往上加：
  · 一份涵蓋所有 Firestore 型別的文件（字串、整數、小數、null、時間、地理座標、參照、位元組、巢狀、空陣列、空 map）
  · 一個「本身不存在、底下有子集合」的空殼路徑
  · 家長的留言、回條、家長發的部落格文章與對話串
然後照老師的用法跑：drive_init → backup all → 再跑一次（照片不重抓）→ 清空資料庫 → restore 預覽／--apply
→ **逐欄相等** → --only 只還原一篇 → 紀錄備份還原 → 資料退場（轉出、家長刪除、學年結束）。

**只連模擬器**：所有腳本都在 firebase emulators:exec 裡跑（FIRESTORE_EMULATOR_HOST），專案是 demo-cmw。
同步夾是暫存資料夾裡的假「My Drive」；系統垃圾桶用假的 HOME，不碰這台電腦真的垃圾桶。
"""
import os
import sys
import json
import base64
import hashlib
import subprocess
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

TYPES_FIELDS = {
    "s": {"stringValue": "文字"}, "i": {"integerValue": "42"}, "d": {"doubleValue": 1.5}, "whole": {"doubleValue": 2.0},
    "n": {"nullValue": None}, "t": {"timestampValue": "2026-09-25T01:02:03.456789Z"},
    "g": {"geoPointValue": {"latitude": 23.5, "longitude": 121.0}},
    "r": {"referenceValue": "projects/demo-cmw/databases/(default)/documents/posts/x"},
    "b": {"bytesValue": base64.b64encode(b"\x00\x01\xff").decode("ascii")},
    "m": {"mapValue": {"fields": {"list": {"arrayValue": {"values": [{"integerValue": "1"}, {"stringValue": "二"},
                                                                         {"booleanValue": True}]}}}}},
    "ea": {"arrayValue": {}}, "em": {"mapValue": {}}, "yes": {"booleanValue": False},
}


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def run(R, c, root, fx, host, photos=True, verbose=False):
    from lib import firestore_rest as fr
    from lib import fsbackup as fsb
    from lib import drivetree as dt
    from lib.emailkey import email_key

    root = Path(root)
    work = root.parent
    drive = work / "drive" / "My Drive"
    drive.mkdir(parents=True, exist_ok=True)
    from lib import filesafe, hostos
    home = work / "home"
    (home / ".Trash").mkdir(parents=True, exist_ok=True)
    # 垃圾桶一律在假的 HOME 裡：Mac＝~/.Trash、Linux＝freedesktop 的 ~/.local/share/Trash（XDG_DATA_HOME 也指進假 HOME，
    # CI 機器原本設的值不算數）；Windows 的資源回收筒不是資料夾，改用測試專用的 CMW_TRASH_DIR，絕不碰真的。
    env = dict(os.environ, PYTHONIOENCODING="utf-8", HOME=str(home), USERPROFILE=str(home),
               XDG_DATA_HOME=str(home / ".local" / "share"))
    env.pop(filesafe.TRASH_DIR_ENV, None)
    if hostos.OS not in ("mac", "linux"):
        env[filesafe.TRASH_DIR_ENV] = str(home / "test-trash")
    trash_dir = filesafe.trash_files_dir(hostos.OS, str(home), environ=env)

    def sh(script, *args):
        argv = [sys.executable, str(REPO / "scripts" / script)] + list(args) + ["--root", str(root)]
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        out = (r.stdout or "") + (r.stderr or "")
        if verbose:
            print("   $ %s %s" % (script, " ".join(args)))
            for line in out.splitlines()[-6:]:
                print("     | " + line)
        return r.returncode, out

    def raw_state():
        """整個資料庫的原始欄位：{路徑: fields}（照片也整份讀回來）＋空殼路徑。"""
        ex = fsb.Walker(c).walk()
        out = {d["path"]: d["fields"] for d in ex.docs}
        ph = [r["path"] for r in ex.photos]
        for i in range(0, len(ph), 8):
            for p, raw in fsb.batch_get_raw(c, ph[i:i + 8]).items():
                if raw is not None:
                    out[p] = raw.get("fields", {})
        return out, sorted(ex.phantoms)

    def wipe():
        req = urllib.request.Request("http://%s/emulator/v1/projects/demo-cmw/databases/(default)/documents" % host,
                                     method="DELETE")
        urllib.request.urlopen(req, timeout=30).read()

    tk = email_key(fx.TEACHER)
    pa, pc = email_key(fx.parent_mail(0)), email_key(fx.parent_mail(2))
    pa_alias = c.get("allowlist/" + pa).data["alias"]
    pc_alias = c.get("allowlist/" + pc).data["alias"]
    post = "2026-10-01-autumn-walk"

    # ── 種額外的資料 ──────────────────────────────────────────────────
    print("── 備份測試：種額外資料（全型別、空殼、家長留言與部落格）")
    now = fr.SERVER_TIME
    writes = [
        {"update": {"name": c.name("zz_types/t1"), "fields": TYPES_FIELDS}},
        {"update": {"name": c.name("zz_types/ghost/sub/s1"), "fields": {"k": {"stringValue": "v"}}}},
        c.set_write("posts/%s/comments/cA" % post, {"authorName": "A 的家長", "body": "好美", "role": "parent",
                                                   "authorAlias": pa_alias, "status": "visible", "createdAt": now}),
        c.set_write("posts/%s/comments/cC" % post, {"authorName": "C 的家長", "body": "謝謝老師", "role": "parent",
                                                   "authorAlias": pc_alias, "status": "visible", "createdAt": now}),
        c.set_write("posts/%s/reads/%s" % (post, pa), {"kind": "parent", "readAt": now}),
        c.set_write("posts/%s/reads/%s" % (post, pc), {"kind": "parent", "readAt": now}),
        c.set_write("student_blogs/01/entries/2026-10-05-parenta1", {
            "title": "家裡的觀察", "body": "他今天\n  自己煮了飯。", "date": "2026-10-05", "author": "parent",
            "authorAlias": pa_alias, "photos": [], "visible": True, "createdAt": now}),
        c.set_write("student_blogs/03/entries/2026-10-06-parentc1", {
            "title": "C 的週末", "body": "去爬山", "date": "2026-10-06", "author": "parent",
            "authorAlias": pc_alias, "photos": [{"pid": "0", "w": 2, "h": 2}], "visible": True, "createdAt": now}),
        {"update": {"name": c.name("student_blogs/03/entries/2026-10-06-parentc1/images/0"),
                    "fields": {"data": {"stringValue": base64.b64encode(b"\xff\xd8\xff\xe0fakejpeg\xff\xd9").decode("ascii")},
                               "w": {"integerValue": "2"}, "h": {"integerValue": "2"}}}},
        {"update": {"name": c.name("student_blogs/03/entries/2026-10-06-parentc1/thumbs/0"),
                    "fields": {"data": {"stringValue": "AAAA"}, "w": {"integerValue": "2"}, "h": {"integerValue": "2"},
                               "order": {"integerValue": "0"}}}},
    ]
    ents = c.list_docs("student_blogs/01/entries")
    teacher_entry = [e for e in ents if e.data.get("author") == "teacher"][0].path
    writes += [
        c.set_write(teacher_entry + "/blog_comments/b1", {"body": "謝謝分享", "role": "parent", "authorAlias": pa_alias,
                                                         "status": "visible", "createdAt": now}),
        c.set_write(teacher_entry + "/blog_comments/b2", {"body": "不客氣", "role": "teacher", "authorAlias": "t" * 12,
                                                         "status": "hidden", "createdAt": now}),
    ]
    c.commit(writes, what="種測試資料")

    # ── 同步夾 ────────────────────────────────────────────────────────
    print("── drive_init.py")
    rc, out = sh("backup.py", "firestore")
    R.check("還沒設定同步夾就備份 → 停下（exit 2）、不建任何資料夾", rc == 2 and "drive_init" in out
            and not any(drive.iterdir()), out[-300:])
    rc, out = sh("drive_init.py", "--path", str(drive))
    R.check("drive_init 預覽不建", rc == 0 and not any(drive.iterdir()), out[-300:])
    rc, out = sh("drive_init.py", "--path", str(drive), "--apply")
    tree = dt.DriveTree(drive, dt.class_folder_name(fx.config()["class_name"]))
    R.check("drive_init --apply 建好整棵樹＋說明檔", rc == 0 and not tree.problems(tuple(dt.LOCATIONS)), out[-300:])
    cfg = json.loads((root / "config" / "class.json").read_text(encoding="utf-8"))
    R.check("config 寫進 drive.sync_root、class_folder，其他欄位沒動",
            cfg["drive"]["sync_root"] == str(drive) and cfg["firebase"]["project_id"] == "demo-cmw"
            and cfg["teacher"]["email"] == fx.TEACHER)

    # ── backup all ────────────────────────────────────────────────────
    print("── backup.py all")
    before, phantoms_before = raw_state()
    rc, out = sh("backup.py", "all")
    R.check("backup all exit 0", rc == 0, out[-600:])
    R.check("輸出不含任何完整 email", not any(m in out for m in [fx.parent_mail(i) for i in range(25)] + [fx.TEACHER]))
    base = root / "data" / "backups" / "firestore"
    snaps = fsb.list_snapshots(base)
    R.check("本機有 1 份快照", len(snaps) == 1, str(snaps))
    sid, sdir = snaps[0] if snaps else ("", base)
    man, docs, photos = fsb.load_snapshot(sdir)
    R.check("快照的文件＋照片＝資料庫全部（%d）" % len(before), len(docs) + len(photos) == len(before),
            "%d+%d vs %d" % (len(docs), len(photos), len(before)))
    R.check("空殼路徑有記下來（底下的資料有備份）", "zz_types/ghost" in man.get("phantoms", [])
            and any(d["path"] == "zz_types/ghost/sub/s1" for d in docs))
    sync_dir = tree.path("fs_snapshots", sid[:4] + "-" + sid[4:6], sid)
    R.check("同步夾 snapshots/YYYY-MM/<id>/ 三個檔 md5 跟本機一樣",
            all((sync_dir / n).exists() and md5(sync_dir / n) == md5(sdir / n) for n in fsb.SNAP_FILES))
    R.check("同步夾 latest/ 是同一份", all(md5(tree.path("fs_latest") / n) == md5(sdir / n) for n in fsb.SNAP_FILES))
    pool_sync = sorted(p.name for p in tree.path("fs_photos").iterdir())
    R.check("照片池：每一份照片文件一個檔（%d）" % len(photos), len(pool_sync) == len(photos) and
            all((r["key"] + ".json") in pool_sync for r in photos))
    state = json.loads((root / "data" / "ledgers" / "backup-state.json").read_text(encoding="utf-8"))
    R.check("backup-state 三條都有 last_ok", all(state.get(k, {}).get("last_ok") for k in ("firestore", "records", "blogs")))
    hb = c.get("ops/backup_status")
    R.check("網站心跳 weekly、nightly 都 ok", hb is not None and hb.data.get("weekly", {}).get("ok") is True
            and hb.data.get("nightly", {}).get("ok") is True)
    blog_dir = root / "data" / "student-blogs" / "01"
    tmd = blog_dir / (teacher_entry.split("/")[-1] + ".md")
    R.check("部落格匯出：每篇一個 md，正文逐字保留、對話串與「已收起」都在",
            tmd.exists() and "今天他在數學課上\n  很專心。" in tmd.read_text(encoding="utf-8")
            and "（已收起）" in tmd.read_text(encoding="utf-8") and "謝謝分享" in tmd.read_text(encoding="utf-8"))
    t_id = teacher_entry.split("/")[-1]
    try:
        t_year = tree.school_year([e for e in ents if e.path == teacher_entry][0].data.get("date") or t_id[:10])
    except ValueError:
        t_year = tree.school_year(t_id[:10])
    arch = tree.path("blog_archive", "01", t_year)
    R.check("04_部落格歸檔/01/<學年>/ 有同樣的檔（只用座號）",
            arch.is_dir() and sorted(p.name for p in arch.iterdir()) == sorted(p.name for p in blog_dir.iterdir()))
    jpgs = list(blog_dir.glob("*.jpg"))
    if R.check("部落格照片存成 jpg", bool(jpgs) or not any(e.data.get("photos") for e in ents)):
        R.check("jpg 是 JPEG", all(p.read_bytes()[:2] == b"\xff\xd8" for p in jpgs))
    zips = sorted(p.name for p in tree.path("records_backup").iterdir() if p.name.endswith(".zip"))
    R.check("紀錄備份：records-<日期時間>.zip ＋ records-latest.zip", len(zips) == 2 and "records-latest.zip" in zips, str(zips))
    R.check("相簿原圖鏡像到 03_相簿原圖/<slug>/", not photos or
            (tree.path("album_originals", "2026-10-02-sports-day") / "p1.jpg").exists())

    rc, out = sh("backup.py", "firestore")
    R.check("第二次備份：照片一份都不重新下載", rc == 0 and "其中新下載 0 份" in out, out[-300:])
    rc, out = sh("status.py")
    R.check("status.py：三條備份都正常", rc == 0 and "網站資料庫備份：20" in out and "還沒有成功過" not in out, out[-500:])

    # ── 還原：清空 → 預覽 → --apply → 逐欄相等 ─────────────────────────
    print("── backup.py restore firestore（清空資料庫再還原）")
    wipe()
    R.check("模擬器清空了", not c.list_docs("posts"))
    rc, out = sh("backup.py", "restore", "firestore", "--snapshot", sid)
    R.check("還原預覽 exit 0、不寫", rc == 0 and "會新建" in out and not c.list_docs("posts"), out[-400:])
    R.check("還原預覽不印完整 email", fx.parent_mail(0) not in out and "***@" in out)
    rc, out = sh("backup.py", "restore", "firestore", "--snapshot", sid, "--apply")
    R.check("還原 --apply exit 0（讀回逐欄比對一致）", rc == 0 and "讀回逐欄比對一致" in out, out[-500:])
    after, phantoms_after = raw_state()
    diff = sorted(set(before) ^ set(after)) + sorted(p for p in before if p in after and before[p] != after[p])
    R.check("還原後每一份文件、每一個欄位（含型別）都跟備份前一模一樣（%d 份）" % len(before), not diff,
            "、".join(fsb.mask_path(x) for x in diff[:5]))
    R.check("空殼路徑還原後仍是空殼、底下資料在", phantoms_after == phantoms_before)
    R.check("型別保留：地理座標、參照、位元組、小數 2.0", after.get("zz_types/t1") == TYPES_FIELDS)

    rc, out = sh("backup.py", "restore", "firestore", "--snapshot", sid, "--apply")
    R.check("再還原一次：內容相同全部略過", rc == 0 and "一模一樣，不用寫" in out, out[-300:])

    print("── restore --only（只還原一篇）")
    c.delete_recursive("posts/" + post)
    c.commit([c.set_write("pages/about", {"title": "改過的標題"}, mask_fields=["title"])])
    rc, out = sh("backup.py", "restore", "firestore", "--snapshot", sid, "--only", "posts/" + post, "--apply")
    now_state, _ = raw_state()
    sub = [p for p in before if p == "posts/" + post or p.startswith("posts/%s/" % post)]
    R.check("--only 只把那一篇（連照片、留言、回條 %d 份）還原回來" % len(sub),
            rc == 0 and all(now_state.get(p) == before[p] for p in sub), out[-300:])
    R.check("--only 沒動到其他文件（關於我們維持改過的標題）",
            now_state["pages/about"]["title"]["stringValue"] == "改過的標題")
    pres = [p for _, p in fsb.list_snapshots(base) if (fsb.read_manifest(p) or {}).get("kind") == "pre-restore"]
    R.check("每次 --apply 前都先做「還原前」快照", len(pres) >= 2)

    # ── 紀錄備份還原 ─────────────────────────────────────────────────
    print("── backup.py restore records")
    md = root / "data" / "class-posts" / (post + ".md")
    original = md.read_text(encoding="utf-8")
    md.unlink()
    about = root / "data" / "pages" / "about.md"
    about.write_text("老師剛改過\n", encoding="utf-8")
    rc, out = sh("backup.py", "restore", "records")
    R.check("紀錄還原預覽：不寫", rc == 0 and not md.exists() and "會補回" in out, out[-300:])
    rc, out = sh("backup.py", "restore", "records", "--apply")
    R.check("紀錄還原：不見的檔補回來、一字不差", rc == 0 and md.exists() and md.read_text(encoding="utf-8") == original,
            out[-300:])
    R.check("紀錄還原：已經有的檔沒被蓋掉（沒加 --overwrite）", about.read_text(encoding="utf-8") == "老師剛改過\n")

    # ── 資料退場：學生轉出（座號 03）───────────────────────────────────
    print("── data_exit.py seat 03")
    rc, out = sh("data_exit.py", "seat", "3")
    R.check("名單檔還沒改 → 停下（exit 2）、什麼都沒動", rc == 2 and "還不能做" in out
            and c.get("student_blogs/03") is not None, out[-400:])
    R.check("預覽輸出不含完整 email", not any(fx.parent_mail(i) in out for i in range(25)) and fx.mail("staff-1") not in out)
    auth_file = root / "data" / "exports" / "data-exit" / "seat-03-auth-cleanup.txt"
    R.check("名單檔還沒改的預覽：先把要刪的登入帳號完整信箱抄進只給老師開的清單（螢幕上只印路徑）",
            auth_file.is_file() and fx.parent_mail(2) in auth_file.read_text(encoding="utf-8")
            and "seat-03-auth-cleanup.txt" in out, out[-400:])
    d = root / "data"
    fx.write(d / "roster.csv", "\n".join(l for l in fx.roster_csv().splitlines() if not l.startswith("03,")) + "\n")
    fx.write(d / "contacts.csv", "\n".join(l for l in fx.contacts_csv().splitlines() if not l.startswith("03,")) + "\n")
    fx.write(d / "parent-roles.yaml", "\n".join(l for l in fx.roles_yaml().splitlines() if not l.startswith('"03"')) + "\n")
    (d / "student-blogs" / "03").mkdir(parents=True, exist_ok=True)
    (d / "student-blogs" / "03" / "x.md").write_text("x", encoding="utf-8")
    cases03 = tree.path("cases") / "03"
    cases03.mkdir()
    rc, out = sh("data_exit.py", "seat", "3")
    R.check("名單檔改好後預覽 exit 0、列出部落格與名單", rc == 0 and "student_blogs/03" in out and "撤權限" in out, out[-400:])
    n_snap = len(fsb.list_snapshots(base))
    rc, out = sh("data_exit.py", "seat", "3", "--apply")
    R.check("轉出 --apply exit 0", rc == 0, out[-600:])
    R.check("contacts.csv 那幾列刪掉之後，清單檔裡的完整信箱還在（聯集，不會被蓋掉）",
            fx.parent_mail(2) in auth_file.read_text(encoding="utf-8"))
    R.check("做之前自動備份了一份", len(fsb.list_snapshots(base)) > n_snap)
    R.check("部落格連同文章、照片、對話都刪了", c.get("student_blogs/03") is None
            and not c.list_docs("student_blogs/03/entries")
            and c.get("student_blogs/03/entries/2026-10-06-parentc1/images/0") is None)
    R.check("只對應 03 的家長：名單、座號對應都撤了", all(c.get("%s/%s" % (k, pc)) is None
                                                  for k in ("allowlist", "parent_child_map")))
    staff = c.get("parent_child_map/" + email_key(fx.mail("staff-1")))
    R.check("同仁（對應 01、03）只拿掉 03、還留在名單", staff is not None and staff.data["seats"] == ["01"]
            and c.get("allowlist/" + email_key(fx.mail("staff-1"))) is not None)
    R.check("名冊那一筆拿掉了", all(s["seat"] != "03" for s in c.get("roster/students").data["students"]))
    cc = c.get("posts/%s/comments/cC" % post)
    R.check("那位家長的留言：收起、署名改「已退場家長」（預設不刪）", cc is not None and cc.data["status"] == "hidden"
            and cc.data["authorName"] == "已退場家長")
    R.check("那位家長的回條刪了", c.get("posts/%s/reads/%s" % (post, pc)) is None
            and c.get("posts/%s/reads/%s" % (post, pa)) is not None)
    R.check("這台電腦 data/student-blogs/03 刪了（進假的垃圾桶）", not (d / "student-blogs" / "03").exists()
            and trash_dir is not None and trash_dir.is_dir() and any(trash_dir.iterdir()),
            "垃圾桶：%s" % trash_dir)
    R.check("同步夾 學生個別資料/03、04_部落格歸檔/03 刪了", not cases03.exists() and not tree.path("blog_archive", "03").exists())
    R.check("照片池裡座號 03 的照片也刪了", not any(p.name[:32] == fsb.pool_prefix(
        "student_blogs/03/entries/2026-10-06-parentc1/images/0") for p in tree.path("fs_photos").iterdir()))
    R.check("其他座號的部落格沒動", c.get("student_blogs/01") is not None and c.get(teacher_entry) is not None)

    # ── 資料退場：家長要求刪除（座號 01 的母）────────────────────────────
    print("── data_exit.py parent")
    rc, out = sh("data_exit.py", "parent", "--email", fx.parent_mail(0))
    R.check("contacts 還有這位家長 → 停下", rc == 2 and "還不能做" in out, out[-300:])
    R.check("家長退場的輸出不含完整 email", fx.parent_mail(0) not in out)
    fx.write(d / "contacts.csv", "\n".join(l for l in (d / "contacts.csv").read_text(encoding="utf-8").splitlines()
                                            if fx.parent_mail(0) not in l) + "\n")
    rc, out = sh("data_exit.py", "parent", "--email", fx.parent_mail(0), "--apply", "--purge-backups")
    R.check("家長退場 --apply --purge-backups exit 0", rc == 0 and "舊備份清好了" in out, out[-500:])
    left_snaps = fsb.list_snapshots(base)
    R.check("--purge-backups：本機只剩剛做的那一份乾淨快照（還原前、退場前的都清掉）",
            len(left_snaps) == 1 and (fsb.read_manifest(left_snaps[0][1]) or {}).get("kind") == "regular", str(left_snaps))
    R.check("--purge-backups：同步夾快照只剩 1 份、紀錄備份只剩 1 份＋latest",
            len(fsb.list_sync_snapshots(tree.path("fs_snapshots"))) == 1
            and len([p for p in tree.path("records_backup").iterdir() if p.name.endswith(".zip")]) == 2)
    lm, ldocs, _ = fsb.load_snapshot(left_snaps[0][1])
    R.check("留下來的快照裡已經沒有這位家長的名單與留言",
            not any(pa in d["path"] for d in ldocs) and not any(
                (d["fields"].get("authorAlias") or {}).get("stringValue") == pa_alias for d in ldocs))
    R.check("名單三份都撤了", all(c.get("%s/%s" % (k, pa)) is None for k in ("allowlist", "private_allowlist", "parent_child_map")))
    R.check("他的留言、回條刪了", c.get("posts/%s/comments/cA" % post) is None and c.get("posts/%s/reads/%s" % (post, pa)) is None)
    R.check("他發的部落格文章刪了、他在導師文章底下的對話刪了、導師的文章與導師的對話留著",
            c.get("student_blogs/01/entries/2026-10-05-parenta1") is None and c.get(teacher_entry + "/blog_comments/b1") is None
            and c.get(teacher_entry) is not None and c.get(teacher_entry + "/blog_comments/b2") is not None)
    R.check("導師自己的信箱不能走家長退場", sh("data_exit.py", "parent", "--email", fx.TEACHER)[0] == 2)

    # ── 學年結束 ─────────────────────────────────────────────────────
    print("── data_exit.py year-end")
    rc, out = sh("data_exit.py", "year-end", "--mode", "photos", "--apply")
    R.check("學年結束（只清照片）exit 0", rc == 0, out[-500:])
    left = [p for p in raw_state()[0] if fsb.is_photo_path(p)]
    R.check("照片文件全部清掉", not left, "、".join(left[:3]))
    R.check("封面縮圖改成 null", all(x.data.get("coverThumb") is None for x in c.list_docs("posts")))
    R.check("名單只剩導師", [x.id for x in c.list_docs("allowlist")] == [tk]
            and [x.id for x in c.list_docs("private_allowlist")] == [tk] and not c.list_docs("parent_child_map"))
    R.check("文字留著", c.get("posts/" + post) is not None and c.get("pages/fun") is not None)
    R.check("學年封存旗標立起來了（data/ledgers/year-end.json）", (root / "data" / "ledgers" / "year-end.json").is_file())
    rc, out = sh("access_sync.py", "--apply")
    R.check("學年封存之後：access_sync --apply 沒加 --new-roster → 停下、一筆都沒寫（名單還是只有導師）",
            rc == 2 and "學年已封存" in out and [x.id for x in c.list_docs("allowlist")] == [tk], out[-400:])
    rc, out = sh("status.py")
    R.check("學年封存之後：status.py 先警告「學年已封存」", rc == 0 and "學年已封存" in out, out[-400:])
    rc, out = sh("data_exit.py", "year-end", "--mode", "wipe", "--apply")
    R.check("學年結束（清空）exit 0", rc == 0, out[-500:])
    R.check("內容集合全部清空", all(not c.list_docs(x) for x in ("posts", "albums", "private_posts", "pages", "student_blogs",
                                                         "roster", "ops")))
    R.check("導師還在名單（下學年還進得去）", c.get("allowlist/" + tk) is not None)
