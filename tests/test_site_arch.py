#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""前台的架構檢查（docs/ARCHITECTURE.md §8.1）：讀原始碼比對，不開瀏覽器。

  1. site/js 裡除了 core/store-firestore.js，沒有任何檔提到 Firebase SDK 的網址。
  2. 整個 site/ 沒有會解析 HTML 字串的 API、沒有 setAttribute('on…')、沒有 firebase/storage。
  3. views/ 裡沒有集合路徑字串（路徑一律經 CMW.paths）。
  4. 每個 site/*.html 都是同一個「殼」，只有 data-page 不同，沒有內容文字與 inline 程式。
  5. boot.js 的載入清單跟實際檔案一致（沒有漏載、沒有孤兒檔）。
  6. 兩個 Store 都實作了 §2.3 的 20 個方法。
  7. 前端用到的查詢名都有登記（templates/queries.json）。
  8. 整個 repo 沒有任何圖片檔。
"""
import os
import re
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
JS = SITE / "js"


def js_files():
    return sorted(p for p in JS.rglob("*.js"))


def rel(p):
    return p.relative_to(REPO).as_posix()


SHELL = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>班級網站</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="css/site.css">
</head>
<body data-page="{PAGE}">
<header id="site-header"></header>
<main id="app"></main>
<footer id="site-footer"></footer>
<script src="js/site-config.js"></script>
<script src="js/boot.js"></script>
</body>
</html>
"""

BANNED = [
    (re.compile(r"\binnerHTML\b"), "innerHTML"),
    (re.compile(r"\bouterHTML\b"), "outerHTML"),
    (re.compile(r"insertAdjacentHTML"), "insertAdjacentHTML"),
    (re.compile(r"document\s*\.\s*write"), "document.write"),
    (re.compile(r"\bDOMParser\b"), "DOMParser"),
    (re.compile(r"\beval\s*\("), "eval("),
    (re.compile(r"\bnew\s+Function\b"), "new Function"),
    (re.compile(r"setAttribute\(\s*['\"]on", re.I), "setAttribute('on…')"),
    (re.compile(r"firebase/storage|firebase-storage"), "Cloud Storage SDK"),
    (re.compile(r"\.style\s*\.\s*cssText|\.style\s*="), "從程式設定 style"),
]

SDK_URL_RE = re.compile(r"gstatic\.com/firebasejs|firebasejs/")
COLLECTION_STR_RE = re.compile(
    r"['\"](posts|albums|private_posts|pages|student_blogs|allowlist|private_allowlist|parent_child_map|"
    r"config|roster|ops|site_access|seating|personal_photos|parent_photo_display)/")
QUERY_NAME_RE = re.compile(
    r"['\"]((?:posts|comments|reads|albums|photos|private|pages|blogs|entries|blogComments|allowlist|"
    r"privateAllowlist|parentMap|seating|personalPhotos|parentPhotos|notifyQueue)\.[A-Za-z.]+)['\"]")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp", ".avif", ".heic", ".tif", ".tiff"}
# 產生的輸出與本機資料（都被 .gitignore 擋住）不算 repo 內容
SKIP_DIRS = {".git", "build", "exports", "data", "node_modules", "__pycache__", ".venv", "venv"}


class TestSiteArchitecture(unittest.TestCase):
    def test_sdk_url_only_in_store_firestore(self):
        hits = [rel(p) for p in js_files() if SDK_URL_RE.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(hits, ["site/js/core/store-firestore.js"])

    def test_no_banned_apis_in_site(self):
        bad = []
        for p in sorted(SITE.rglob("*")):
            if p.is_file() and p.suffix in (".js", ".html", ".css"):
                text = p.read_text(encoding="utf-8")
                for pat, name in BANNED:
                    if pat.search(text):
                        bad.append("%s：%s" % (rel(p), name))
        self.assertEqual(bad, [])

    def test_views_have_no_collection_paths(self):
        bad = []
        for p in sorted((JS / "views").glob("*.js")):
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if COLLECTION_STR_RE.search(line):
                    bad.append("%s:%d" % (rel(p), i))
        self.assertEqual(bad, [], "views 裡的路徑一律經 CMW.paths")

    def test_html_shells_identical_except_page(self):
        pages = set()
        for p in sorted(SITE.glob("*.html")):
            text = p.read_text(encoding="utf-8")
            m = re.search(r'<body data-page="([a-z-]+)">', text)
            self.assertIsNotNone(m, p.name)
            pages.add(m.group(1))
            self.assertEqual(text, SHELL.replace("{PAGE}", m.group(1)), "%s 不是標準的頁面殼" % p.name)
        self.assertGreaterEqual(len(pages), 16)
        route = (JS / "core" / "route.js").read_text(encoding="utf-8")
        for page in pages:
            self.assertRegex(route, r"['\"]?%s['\"]?\s*:\s*'" % re.escape(page), "route.js 的 FILES 沒有 %s" % page)

    def test_robots_disallow_all(self):
        self.assertEqual((SITE / "robots.txt").read_text(encoding="utf-8"), "User-agent: *\nDisallow: /\n")

    def test_boot_file_list_matches_disk(self):
        text = (JS / "boot.js").read_text(encoding="utf-8")
        m = re.search(r"/\* files:begin \*/(.*?)/\* files:end \*/", text, re.S)
        self.assertIsNotNone(m)
        files = json.loads(m.group(1))
        listed = set(files["first"] + files["core"] + files["live"] + files["demo"] + files["always"])
        for lst in files["views"].values():
            listed.update(lst)
        for f in listed:
            self.assertTrue((SITE / f).is_file(), "boot.js 列了不存在的檔：%s" % f)
        on_disk = {p.relative_to(SITE).as_posix() for p in js_files()}
        orphans = on_disk - listed - {"js/boot.js", "js/site-config.js"}
        self.assertEqual(sorted(orphans), [], "有檔案沒被 boot.js 載入")
        # 示範模式不載 store-firestore.js；真站不載示範資料
        self.assertNotIn("js/core/store-firestore.js", files["demo"] + files["core"])
        self.assertNotIn("js/core/demo-data.js", files["live"] + files["core"])

    def test_both_stores_implement_all_methods(self):
        store = (JS / "core" / "store.js").read_text(encoding="utf-8")
        m = re.search(r"C\.STORE_METHODS = \[(.*?)\];", store, re.S)
        names = re.findall(r"'([A-Za-z]+)'", m.group(1))
        self.assertEqual(len(names), 20)
        for cls, fname in (("FirestoreStore", "store-firestore.js"), ("DemoStore", "store-demo.js")):
            src = (JS / "core" / fname).read_text(encoding="utf-8")
            for n in names:
                if n == "isDemo":
                    self.assertIn("this.isDemo =", src, fname)
                else:
                    self.assertRegex(src, r"%s\.prototype\.%s = function" % (cls, n), "%s 少了 %s" % (cls, n))

    def test_query_names_are_registered(self):
        reg = json.loads((REPO / "templates" / "queries.json").read_text(encoding="utf-8"))["queries"]
        used = set()
        for p in js_files():
            if p.name == "queries.js":
                continue
            used.update(n for n in QUERY_NAME_RE.findall(p.read_text(encoding="utf-8"))
                        if not n.endswith((".html", ".js", ".css")))
        self.assertTrue(used, "應該找得到前端用到的查詢名")
        self.assertEqual(sorted(n for n in used if n not in reg), [])

    def test_no_image_files_in_repo(self):
        found = []
        # os.walk 邊走邊剪掉略過的資料夾（不要走進 node_modules 這種大樹）
        for dirpath, dirnames, filenames in os.walk(str(REPO)):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if Path(fn).suffix.lower() in IMAGE_EXT:
                    found.append(rel(Path(dirpath) / fn))
        self.assertEqual(found, [], "公開 repo 不放任何圖檔（示範照片由程式當場畫）")

    def test_every_js_file_is_iife(self):
        for p in js_files():
            if p.name == "site-config.js":
                continue
            text = p.read_text(encoding="utf-8")
            self.assertIn("(function (g) {", text, "%s 要用 IIFE 包起來" % rel(p))
            self.assertNotRegex(text, r"^\s*(import|export)\s", "%s 不能用 ES module 語法" % rel(p))


if __name__ == "__main__":
    unittest.main()
