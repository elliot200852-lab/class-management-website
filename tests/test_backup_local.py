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
