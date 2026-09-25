#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_site.py 的測試：示範站不含任何 Firebase 設定、單一 HTML 零外部相依（字型除外）、
正式網站拒收範本值、每一頁都有 noindex、不亂清別的資料夾。"""
import sys
import json
import tempfile
import unittest
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import build_site  # noqa: E402

AT = "@"


def run(*args, root=None):
    cmd = [sys.executable, str(REPO / "scripts" / "build_site.py")] + list(args)
    if root:
        cmd += ["--root", str(root)]
    return subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)


class TestBuildSite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_demo_build(self):
        out = self.dir / "demo"
        r = run("--demo", "--out", str(out))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((out / "js" / "core" / "store-firestore.js").exists(), "示範站不放 store-firestore.js")
        self.assertEqual((out / "robots.txt").read_text(encoding="utf-8"), "User-agent: *\nDisallow: /\n")
        self.assertTrue((out / ".nojekyll").exists())
        cfg_text = (out / "js" / "site-config.js").read_text(encoding="utf-8")
        cfg = json.loads(cfg_text.split("window.SITE_CONFIG = ", 1)[1].rstrip().rstrip(";"))
        self.assertIs(cfg["demo"], True)
        self.assertEqual(cfg["firebase"], {})
        for p in out.rglob("*"):
            if p.is_file() and p.suffix in (".html", ".js", ".css"):
                text = p.read_text(encoding="utf-8")
                for marker in build_site.SDK_MARKERS:
                    self.assertNotIn(marker, text, p.name)
                if p.suffix == ".html":
                    self.assertIn('name="robots" content="noindex', text, p.name)

    def test_single_file(self):
        out = self.dir / "one.html"
        r = run("--demo-single-file", str(out))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        html = out.read_text(encoding="utf-8")
        self.assertNotIn("<script src=", html)
        self.assertNotIn('rel="stylesheet"', html)
        self.assertIn('"singleFile": true', html)
        self.assertIn("CMW.app.start();", html)
        self.assertIn("noindex", html)
        # 唯一的外部網址是 Google Fonts；加 --no-webfonts 連它也沒有
        self.assertIn("fonts.googleapis.com", html)
        out2 = self.dir / "offline.html"
        r2 = run("--demo-single-file", str(out2), "--no-webfonts")
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertNotIn("fonts.googleapis.com", out2.read_text(encoding="utf-8"))
        for marker in build_site.SDK_MARKERS:
            self.assertNotIn(marker, html)

    def test_single_file_order_follows_boot(self):
        files = build_site.load_file_lists()
        order = build_site.ordered_scripts(files, demo=True)
        self.assertEqual(order[0], "js/core/ns.js")
        self.assertLess(order.index("js/core/store.js"), order.index("js/core/store-demo.js"))
        self.assertNotIn("js/core/store-firestore.js", order)
        self.assertEqual(len(order), len(set(order)))
        for f in order:
            self.assertTrue((REPO / "site" / f).is_file(), f)

    def test_live_build_refuses_placeholders(self):
        r = run("--out", str(self.dir / "site"), root=self.dir)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("範本值", r.stdout)
        self.assertFalse((self.dir / "site").exists())

    def test_live_build_with_config(self):
        cfg = json.loads((REPO / "config" / "class.example.json").read_text(encoding="utf-8"))
        cfg["teacher"]["email"] = "someone" + AT + "example.org"
        cfg["firebase"].update({"project_id": "demo-class-2026", "api_key": "test-api-key-not-real",
                                "app_id": "test-app-id"})
        (self.dir / "config").mkdir()
        (self.dir / "config" / "class.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        out = self.dir / "site"
        r = run("--out", str(out), root=self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (out / "js" / "site-config.js").read_text(encoding="utf-8")
        self.assertIn('"demo-class-2026"', text)
        self.assertIn("https://demo-class-2026.firebaseapp.com", text)
        self.assertNotIn("someone", text, "導師信箱不准出現在公開設定檔")
        self.assertTrue((out / "js" / "core" / "store-firestore.js").exists())
        self.assertTrue((out / "robots.txt").exists())

    def test_refuses_to_clear_unrelated_folder(self):
        victim = self.dir / "precious"
        victim.mkdir()
        (victim / "notes.txt").write_text("不要刪我", encoding="utf-8")
        r = run("--demo", "--out", str(victim))
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((victim / "notes.txt").exists())

    def test_noindex_injection(self):
        html = "<!doctype html><html><head><title>x</title></head><body></body></html>"
        self.assertIn("noindex", build_site.ensure_noindex(html))


if __name__ == "__main__":
    unittest.main()
