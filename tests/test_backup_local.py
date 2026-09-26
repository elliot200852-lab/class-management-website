#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""備份腳本不連網的部分（scripts/backup.py）：紀錄備份 zip＋照片鏡像、保留份數輪替、latest、還原 data/（不覆蓋、
zip 檔名安全）、部落格 md 的格式、找不到同步夾就停且記失敗。同步夾是暫存目錄裡的假「My Drive」。"""
import io
import os
import sys
import json
import shutil
import zipfile
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
import backup  # noqa: E402
import admin_support as fx  # noqa: E402
from lib import paths, ledgers  # noqa: E402
from lib import drivetree as dt  # noqa: E402

TREE = "示範班級 班級網站"


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cmw-bk-"))
        self.root = fx.make_root(self.tmp / "root", photos=False, n=3)
        self.data = self.root / "data"
        self.sync = self.tmp / "My Drive"
        self.sync.mkdir()

    def tearDown(self):
        paths.reset_root()
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def configure(self):
        cfg = fx.config()
        cfg["drive"] = {"sync_root": str(self.sync), "class_folder": TREE}
        fx.write(self.root / "config" / "class.json", json.dumps(cfg, ensure_ascii=False))
        dt.build_tree(self.sync, TREE)
        self.tree = dt.DriveTree(self.sync, TREE)

    def run_main(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = backup.main(list(args) + ["--root", str(self.root)])
        return rc, buf.getvalue()


class TestCollect(Env):
    def test_classification(self):
        d = self.data
        fx.write(d / "units" / "範例單元" / "大綱.md", "大綱")
        (d / "albums" / "2026-10-02-sports-day").mkdir(parents=True, exist_ok=True)
        (d / "albums" / "2026-10-02-sports-day" / "p1.jpg").write_bytes(b"jpg")
        (d / "class-posts" / "2026-10-01-autumn-walk").mkdir(parents=True, exist_ok=True)
        (d / "class-posts" / "2026-10-01-autumn-walk" / "v.mp4").write_bytes(b"mp4")
        (d / "student-blogs" / "01").mkdir(parents=True)
        (d / "student-blogs" / "01" / "x.jpg").write_bytes(b"1")
        (d / "student-blogs" / "01" / "x.md").write_text("文", encoding="utf-8")
        for skip in ("backups", "inbox", "exports"):
            fx.write(d / skip / "s.txt", "x")
        fx.write(d / ".DS_Store", "x")
        (d / "units" / "範例單元" / "big.pdf").write_bytes(b"0" * 5000)
        with mock.patch.object(backup, "BIG_FILE", 4000):
            z, m, links = backup.collect_records(d)
        self.assertIn("roster.csv", z)
        self.assertIn("units/範例單元/大綱.md", z)
        self.assertIn("student-blogs/01/x.md", z)
        self.assertNotIn("student-blogs/01/x.jpg", z + m, "部落格照片由 blogs 那一條負責")
        self.assertIn("albums/2026-10-02-sports-day/p1.jpg", m)
        self.assertIn("class-posts/2026-10-01-autumn-walk/v.mp4", m)
        self.assertIn("units/範例單元/big.pdf", m, "20 MB 以上的大檔不進 zip")
        self.assertFalse(any(x.split("/")[0] in ("backups", "inbox", "exports") for x in z + m))
        self.assertNotIn(".DS_Store", z)

    @unittest.skipIf(not hasattr(os, "symlink") or sys.platform.startswith("win"), "Windows 建捷徑要特權")
    def test_symlinks_skipped(self):
        target = self.tmp / "kit-data"
        fx.write(target / "obs.md", "觀察")
        os.symlink(str(target), str(self.data / "records-link"))
        z, m, links = backup.collect_records(self.data)
        self.assertEqual(links, 1)
        self.assertFalse(any(x.startswith("records-link/") for x in z))

    def test_mirror_dest(self):
        need = {"album_originals": Path("/s/03"), "records_media": Path("/s/01/m")}
        self.assertEqual(backup.mirror_dest("albums/2026-10-02-x/p1.jpg", need), Path("/s/03/2026-10-02-x/p1.jpg"))
        self.assertEqual(backup.mirror_dest("albums/loose.jpg", need), Path("/s/01/m/albums/loose.jpg"))
        self.assertEqual(backup.mirror_dest("class-posts/a/b.jpg", need), Path("/s/01/m/class-posts/a/b.jpg"))


class TestRecords(Env):
    def test_stops_without_tree_and_records_failure(self):
        rc, out = self.run_main("records")
        self.assertEqual(rc, 2)
        self.assertIn("drive_init", out)
        self.assertEqual(list(self.sync.iterdir()), [], "找不到就停，不自己建")
        paths.set_root(self.root)
        st = ledgers.read_state()["records"]
        self.assertIn("last_fail", st)
        self.assertNotIn("last_ok", st)

    def test_backup_rotate_and_restore(self):
        self.configure()
        (self.data / "albums" / "2026-10-02-sports-day").mkdir(parents=True, exist_ok=True)
        (self.data / "albums" / "2026-10-02-sports-day" / "p1.jpg").write_bytes(b"jpg")
        for i in range(3):
            rc, out = self.run_main("records", "--keep", "2")
            self.assertEqual(rc, 0, out)
        rb = self.tree.path("records_backup")
        zips = sorted(p.name for p in rb.iterdir() if p.name.endswith(".zip"))
        self.assertEqual(len(zips), 3, "保留 2 份＋records-latest.zip")
        self.assertIn("records-latest.zip", zips)
        with zipfile.ZipFile(str(rb / "records-latest.zip")) as z:
            names = z.namelist()
        self.assertIn("roster.csv", names)
        self.assertIn("class-posts/2026-10-01-autumn-walk.md", names)
        self.assertNotIn("albums/2026-10-02-sports-day/p1.jpg", names)
        self.assertEqual((self.tree.path("album_originals") / "2026-10-02-sports-day" / "p1.jpg").read_bytes(), b"jpg")
        paths.set_root(self.root)
        self.assertTrue(ledgers.read_state()["records"]["last_ok"])
        self.assertFalse((self.data / "backups" / ".tmp" / zips[0]).exists(), "暫存 zip 用完就刪")
        # 還原：不見的補回、改過的不蓋（除非 --overwrite）、照片從鏡像補回
        md = self.data / "class-posts" / "2026-10-01-autumn-walk.md"
        orig = md.read_bytes()
        md.unlink()
        about = self.data / "pages" / "about.md"
        about.write_text("新的", encoding="utf-8")
        (self.data / "albums" / "2026-10-02-sports-day" / "p1.jpg").unlink()
        rc, out = self.run_main("restore", "records")
        self.assertEqual(rc, 0)
        self.assertFalse(md.exists(), "預覽不寫")
        rc, out = self.run_main("restore", "records", "--apply")
        self.assertEqual(rc, 0, out)
        self.assertEqual(md.read_bytes(), orig)
        self.assertEqual(about.read_text(encoding="utf-8"), "新的")
        self.assertEqual((self.data / "albums" / "2026-10-02-sports-day" / "p1.jpg").read_bytes(), b"jpg")
        rc, out = self.run_main("restore", "records", "--apply", "--overwrite")
        self.assertEqual(rc, 0)
        self.assertNotEqual(about.read_text(encoding="utf-8"), "新的")
        rc, out = self.run_main("restore", "records", "--zip", "records-19990101-000000.zip")
        self.assertEqual(rc, 2)

    def test_unsafe_zip_members(self):
        for bad in ("/etc/x", "../x", "a/../../x", "C:/x", "a\\b", "", "a//b"):
            self.assertFalse(backup._safe_member(bad), bad)
        self.assertTrue(backup._safe_member("class-posts/a.md"))

    def test_list_offline(self):
        self.configure()
        rc, out = self.run_main("list")
        self.assertEqual(rc, 0)
        self.assertIn("（沒有）", out)

    def test_keep_range(self):
        self.assertEqual(self.run_main("records", "--keep", "0")[0], 2)


class FakeRestoreClient(object):
    """還原預覽用得到的兩個方法。now＝{路徑: 解碼後的欄位}（現在資料庫裡有的）。"""

    def __init__(self, now):
        self.now = now
        self.gets = 0

    def describe_target(self):
        return "假的資料庫"

    def batch_get(self, paths_, mask=None):
        from lib import firestore_rest as fr
        self.gets += 1
        return {p: (fr.Doc(p, dict(self.now[p])) if p in self.now else None) for p in paths_}


class TestRestoreGates(Env):
    """整庫還原（backup.py restore firestore）的三道閘：名單不寫、退場的人不復活、下架的不自動上架。"""
    KEY = "p@example.com"

    def snapshot(self, created):
        from lib import fsbackup as fsb
        ex = fsb.Export()
        ex.docs = [{"path": p, "fields": f, "createTime": "", "updateTime": ""} for p, f in (
            ("allowlist/" + self.KEY, {"alias": {"stringValue": "a" * 12}}),
            ("parent_child_map/" + self.KEY, {"kind": {"stringValue": "parent"}}),
            ("posts/p", {"title": {"stringValue": "紀事"}, "visible": {"booleanValue": True}}),
            ("posts/p/comments/c", {"body": {"stringValue": "好"}, "status": {"stringValue": "visible"}}),
            ("student_blogs/03", {"seat": {"stringValue": "03"}}),
            ("student_blogs/05/entries/2026-10-05-parentxx", {"authorAlias": {"stringValue": "b" * 12}}),
        )]
        base = self.data / "backups" / "firestore"
        fsb.write_snapshot(base, "20261001-120000", fx.config()["firebase"]["project_id"], ex, [], created=created)

    def preview(self, *extra, now=None):
        client = FakeRestoreClient(now or {})
        with mock.patch.object(backup.Ctx, "client", lambda self_: client):
            rc, out = self.run_main("restore", "firestore", *extra)
        return rc, out, client

    def test_lists_excluded_and_hidden_kept_in_preview(self):
        self.configure()
        self.snapshot("2026-01-01T12:00:00+08:00")
        rc, out, _ = self.preview(now={"posts/p": {"visible": False}, "posts/p/comments/c": {"status": "hidden"}})
        self.assertEqual(rc, 0, out)
        self.assertIn("名單類", out)
        self.assertIn("access_sync.py", out)
        self.assertIn("保留下架", out)
        self.assertNotIn(self.KEY, out)
        paths.set_root(self.root)
        plan = sorted((self.data / "exports").glob("restore-plan-*.txt"))[-1].read_text(encoding="utf-8")
        self.assertIn("不還原（名單類） allowlist/", plan)
        self.assertIn("保留下架 posts/p", plan)
        self.assertNotIn("新建 allowlist/", plan)
        rc, out, _ = self.preview("--restore-visibility", now={"posts/p": {"visible": False}})
        self.assertIn("還原後會重新變可見", out)
        rc, out, _ = self.preview("--only", "allowlist")
        self.assertEqual(rc, 2, "只挑名單 → 沒東西可還原")

    def test_stops_on_exit_after_snapshot(self):
        self.configure()
        self.snapshot("2026-01-01T12:00:00+08:00")
        paths.set_root(self.root)
        ledgers.record_exit("seat", seats=["03"], keys=[self.KEY], aliases=["a" * 12])
        rc, out, client = self.preview()
        self.assertEqual(rc, 2, out)
        self.assertIn("已經退場", out)
        self.assertIn("student_blogs/03", out)
        self.assertIn("--include-exited", out)
        self.assertEqual(client.gets, 0, "停下來之前一次都沒讀資料庫")
        rc, out, _ = self.preview("--only", "posts/p")
        self.assertEqual(rc, 0, "避開退場的資料就照常")
        rc, out, _ = self.preview("--include-exited")
        self.assertEqual(rc, 0, out)
        self.assertIn("--include-exited", out)

    def test_exit_before_snapshot_does_not_block(self):
        self.configure()
        paths.set_root(self.root)
        ledgers.record_exit("seat", seats=["03"])
        self.snapshot("2099-01-01T00:00:00+08:00")
        rc, out, _ = self.preview()
        self.assertEqual(rc, 0, "快照比退場晚（例如新學年同一個座號換了人）→ 不擋")

    def test_year_end_pending_blocks(self):
        self.configure()
        self.snapshot("2026-01-01T12:00:00+08:00")
        paths.set_root(self.root)
        ledgers.mark_year_end("archive")
        rc, out, _ = self.preview("--only", "posts/p")
        self.assertEqual(rc, 2, out)
        self.assertIn("學年封存", out)

    def test_parent_exit_blocks_photo_only_restore(self):
        from lib import fsbackup as fsb
        self.configure()
        self.snapshot("2026-01-01T12:00:00+08:00")
        e = "student_blogs/05/entries/2026-10-05-parentxx"
        base = self.data / "backups" / "firestore"
        # 快照裡加一張他那篇文章的縮圖（照片列）
        man, docs, _ = fsb.load_snapshot(base / "20261001-120000")
        pool = fsb.Pool(base / "photos")
        key = fsb.pool_key(e + "/thumbs/0", "t")
        pool.save({"path": e + "/thumbs/0", "fields": {"data": {"stringValue": "AAAA"}}}, key)
        import shutil as _sh
        _sh.rmtree(str(base / "20261001-120000"))
        ex = fsb.Export()
        ex.docs = docs
        fsb.write_snapshot(base, "20261001-120000", man["project"], ex,
                           [{"path": e + "/thumbs/0", "updateTime": "t", "key": key, "md5": "m"}], created=man["created"])
        paths.set_root(self.root)
        ledgers.record_exit("parent", keys=["q@example.com"], aliases=["b" * 12])
        rc, out, client = self.preview("--only", e + "/thumbs")
        self.assertEqual(rc, 2, out)
        self.assertIn("已經退場", out)
        self.assertEqual(client.gets, 0)

    def test_exit_ledger_has_no_email(self):
        paths.set_root(self.root)
        ledgers.record_exit("parent", keys=[self.KEY], aliases=["a" * 12])
        text = ledgers.exit_ledger_path().read_text(encoding="utf-8")
        self.assertNotIn(self.KEY, text)
        self.assertNotIn("a" * 12, text)
        (rec,) = ledgers.read_exits()
        self.assertEqual(rec["keyHashes"], [ledgers.exit_hash(self.KEY)])


class TestOrphanReport(Env):
    def test_prints_seat_count_size_only(self):
        from lib import fsbackup as fsb
        pool = fsb.Pool(self.tmp / "pool")
        e = "student_blogs/05/entries/2026-10-05-secretid"
        ex = fsb.Export()
        ex.docs = [{"path": e, "fields": {"photos": {"arrayValue": {}}, "body": {"stringValue": "不該印出來的內文"}}}]
        ex.photos = [{"path": e + "/images/0"}, {"path": "student_blogs/07/entries/2026-10-06-ghostxyz/thumbs/1"}]
        key = fsb.pool_key(e + "/images/0", "t")
        pool.save({"path": e + "/images/0", "fields": {"data": {"stringValue": "Z" * 5000}}}, key)
        buf = io.StringIO()
        with redirect_stdout(buf):
            s = backup.orphan_report(ex, [{"path": e + "/images/0", "key": key}], pool)
        out = buf.getvalue()
        self.assertEqual(s["count"], 2)
        self.assertGreater(s["seats"]["05"]["bytes"], 5000)
        self.assertIn("座號 05", out)
        self.assertIn("座號 07", out)
        self.assertNotIn("secretid", out)
        self.assertNotIn("不該印出來", out)
        self.assertNotIn("ZZZZ", out)
        with redirect_stdout(io.StringIO()) as quiet:
            self.assertEqual(backup.orphan_report(fsb.Export(), [], pool)["count"], 0)
        self.assertEqual(quiet.getvalue(), "", "沒有孤兒就不吵")


class TestBlogMarkdown(unittest.TestCase):
    def test_verbatim_body_comments_and_hidden(self):
        md = backup.blog_markdown("03", "2026-10-03-abcdefgh",
                                  {"title": "今天", "body": "第一行\n  縮排\n\n空行後", "date": "2026-10-03", "author": "parent",
                                   "visible": False, "createdAt": "2026-10-03T12:00:00Z"},
                                  [{"role": "teacher", "body": "謝謝", "status": "visible", "createdAt": "2026-10-03T13:00:00Z"},
                                   {"role": "parent", "body": "收起的", "status": "hidden", "createdAt": "2026-10-03T14:00:00Z"}],
                                  [("2026-10-03-abcdefgh-0.jpg", "作品")])
        self.assertIn("第一行\n  縮排\n\n空行後", md)
        self.assertIn("- 座號：03", md)
        self.assertIn("- 作者：家長", md)
        self.assertIn("已下架", md)
        self.assertIn("## 對話（2 則）", md)
        self.assertIn("**家長**", md)
        self.assertIn("（已收起）", md)
        self.assertIn("2026-10-03-abcdefgh-0.jpg（作品）", md)


if __name__ == "__main__":
    unittest.main()
