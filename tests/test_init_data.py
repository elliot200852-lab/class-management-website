#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""init_data.py 的測試：把 data-template/ 複製成 data/，已存在的檔不覆蓋。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import paths
import init_data


class TestInitData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        paths.set_root(self.tmp.name)

    def tearDown(self):
        paths.reset_root()
        self.tmp.cleanup()

    def test_copies_template_into_data(self):
        copied, skipped = init_data.copy_tree_no_overwrite(
            paths.pkg_path("data-template"), paths.rpath("data"))
        self.assertTrue(copied, "應該至少複製了一些檔案")
        self.assertEqual(skipped, [])
        self.assertTrue((paths.rpath("data") / "class-posts").is_dir())
        self.assertTrue((paths.rpath("data") / "roster.csv").exists())

    def test_does_not_overwrite_existing_file(self):
        dest = paths.rpath("data")
        (dest / "class-posts").mkdir(parents=True, exist_ok=True)
        marker = dest / "class-posts" / "README.md"
        marker.write_text("我改過的內容，不准被蓋掉", encoding="utf-8")

        init_data.copy_tree_no_overwrite(paths.pkg_path("data-template"), dest)

        self.assertEqual(marker.read_text(encoding="utf-8"), "我改過的內容，不准被蓋掉")

    def test_main_runs_and_reports_counts(self):
        rc = init_data.main([])
        self.assertEqual(rc, 0)
        self.assertTrue((paths.rpath("data") / "roster.csv").exists())

        # 重跑一次：第二次應該全部是「已存在」，不會出錯也不會覆蓋
        rc2 = init_data.main([])
        self.assertEqual(rc2, 0)

    def test_sync_warnings_returns_list_without_raising(self):
        # 不管在哪台 CI runner 上跑，這支都不該丟例外
        warnings = init_data.sync_warnings(paths.root())
        self.assertIsInstance(warnings, list)


if __name__ == "__main__":
    unittest.main()
