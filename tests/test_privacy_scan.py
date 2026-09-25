#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""privacy_scan.py 的測試。

注意：這份 repo 的 privacy_scan 會對整棵樹（含 tests/）跑一次自我掃描
（scripts/check.py、CI 都會跑 `privacy_scan.py .`）。下面所有「假樣本」都刻意用
字串組合（`"a" + "b"`）拼出來，不讓完整的樣板文字連續出現在這份原始碼裡——
不然這個測試檔本身就會被 privacy_scan 抓到「命中」，變成自己絆自己。
"""
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import privacy_scan as ps

FAKE_EMAIL = "someone" + "@" + "gmail" + "." + "com"
FAKE_EXAMPLE_EMAIL = "someone" + "@" + "example" + "." + "com"
FAKE_APIKEY = "AIza" + "SyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"
FAKE_GOOGLE_ID = "1" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AB"
FAKE_SERVICE_ACCOUNT = ("my-app@my-project-123456" + "." + "iam" + "." +
                         "gserviceaccount" + "." + "com")
FAKE_TW_ID = "A" + "123456789"
FAKE_TW_PHONE = "09" + "12345678"
FAKE_BASE64_IMG = "data:image/png;base64," + ("A" * 210)
FAKE_DRIVE_FOLDER_URL = "https://drive.google.com/drive/" + "folders/" + "abcdefghijklmnop"


class TestClassifyLine(unittest.TestCase):
    def test_email(self):
        self.assertIn("email", ps.classify_line("聯絡我：%s" % FAKE_EMAIL))

    def test_example_domain_not_flagged(self):
        self.assertEqual(ps.classify_line("聯絡我：%s" % FAKE_EXAMPLE_EMAIL), set())

    def test_google_id(self):
        self.assertIn("google_id", ps.classify_line("夾在 %s 裡" % FAKE_GOOGLE_ID))

    def test_google_url_id(self):
        self.assertIn("google_id", ps.classify_line(FAKE_DRIVE_FOLDER_URL))

    def test_api_key(self):
        self.assertIn("api_key", ps.classify_line("key=%s" % FAKE_APIKEY))

    def test_service_account(self):
        self.assertIn("service_account", ps.classify_line(FAKE_SERVICE_ACCOUNT))

    def test_tw_id(self):
        self.assertIn("tw_id", ps.classify_line("身分證 %s" % FAKE_TW_ID))

    def test_tw_phone(self):
        self.assertIn("tw_phone", ps.classify_line("電話 %s" % FAKE_TW_PHONE))

    def test_base64_image(self):
        self.assertIn("base64_image", ps.classify_line(FAKE_BASE64_IMG))

    def test_clean_line_no_hits(self):
        self.assertEqual(ps.classify_line("這是一段完全乾淨的中文說明文字。"), set())


class TestScanTree(unittest.TestCase):
    def test_hits_reported_without_leaking_string(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "leak.txt").write_text("email: %s\n" % FAKE_EMAIL, encoding="utf-8")
            buf = StringIO()
            with redirect_stdout(buf):
                rc = ps.main([str(root)])
            out = buf.getvalue()
            self.assertEqual(rc, 1)
            self.assertIn("leak.txt:1｜email", out)
            self.assertNotIn(FAKE_EMAIL, out)

    def test_clean_tree_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ok.txt").write_text("聯絡我：%s\n" % FAKE_EXAMPLE_EMAIL, encoding="utf-8")
            buf = StringIO()
            with redirect_stdout(buf):
                rc = ps.main([str(root)])
            self.assertEqual(rc, 0)

    def test_skip_git_and_node_modules(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text(FAKE_EMAIL, encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "x.js").write_text(FAKE_EMAIL, encoding="utf-8")
            buf = StringIO()
            with redirect_stdout(buf):
                rc = ps.main([str(root)])
            self.assertEqual(rc, 0)

    def test_binary_file_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "img.bin").write_bytes(bytes(range(256)))
            buf = StringIO()
            with redirect_stdout(buf):
                rc = ps.main([str(root)])
            out = buf.getvalue()
            self.assertEqual(rc, 1)
            self.assertIn("binary_file", out)

    def test_allowlist_suppresses(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "leak.txt").write_text("email: %s\n" % FAKE_EMAIL, encoding="utf-8")
            (root / "privacy-allow.txt").write_text("leak.txt:1\n", encoding="utf-8")
            buf = StringIO()
            with redirect_stdout(buf):
                rc = ps.main([str(root)])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
