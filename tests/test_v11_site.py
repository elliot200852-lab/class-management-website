#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.1 前台的原始碼檢查（不開瀏覽器）：

  1. 導師專用頁的備份提醒門檻＝scripts/lib/thresholds.py（status.py 也讀它；v1 的備份是手動的，不能用「每夜 36 小時」誤報）。
  2. 四個 v1.1 頁面都有自己的 view、boot.js 有載入，不再落到「建置中」。
  3. 導覽有「每日一詩」、導師浮鈕有座位表；座位表只用程式產生 SVG（createElementNS），不拼 SVG 字串。
  4. 列印樣式：A4、只印列印版（頁首、導覽、面板都藏起來）。
"""
import re
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "site" / "js"


def read(rel):
    return (REPO / rel).read_text(encoding="utf-8")


class TestBackupThresholds(unittest.TestCase):
    def test_teacher_page_matches_status_py(self):
        """門檻的正本是 scripts/lib/thresholds.py（status.py 與通知信模組的每日摘要都讀它）。"""
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        from lib import thresholds
        teacher = read("site/js/views/teacher.js")
        remind = int(re.search(r"var BACKUP_REMIND_DAYS = (\d+);", teacher).group(1))
        urgent = int(re.search(r"var BACKUP_URGENT_DAYS = (\d+);", teacher).group(1))
        self.assertEqual(remind, thresholds.BACKUP_REMIND_DAYS)
        self.assertEqual(urgent, thresholds.BACKUP_URGENT_DAYS)
        self.assertIn("thresholds", read("scripts/status.py"), "status.py 也要讀同一份門檻")
        self.assertNotIn("36", re.sub(r"//.*|/\*.*?\*/", "", teacher, flags=re.S), "不准再有 36 小時門檻")

    def test_heartbeat_lines_are_what_backup_writes(self):
        backup = read("scripts/backup.py")
        teacher = read("site/js/views/teacher.js")
        for key in re.findall(r"key: '(\w+)'", teacher):
            self.assertIn('heartbeat(ctx, "%s"' % key, backup)


class TestV11Pages(unittest.TestCase):
    def files(self):
        text = read("site/js/boot.js")
        return json.loads(re.search(r"/\* files:begin \*/(.*?)/\* files:end \*/", text, re.S).group(1))

    def test_views_are_loaded_and_real(self):
        views = self.files()["views"]
        want = {"poem": "views/poem.js", "family-photos": "views/family-photos.js",
                "blog-print": "views/print.js", "my-child-print": "views/print.js", "teacher": "views/seating.js"}
        for page, f in want.items():
            self.assertIn("js/" + f, views.get(page, []), page)
        self.assertNotRegex(read("site/js/views/placeholder.js"), r"'poem'|'family-photos'|'blog-print'")
        for page, f in (("poem", "poem.js"), ("family-photos", "family-photos.js"), ("blog-print", "print.js"),
                        ("my-child-print", "print.js")):
            self.assertRegex(read("site/js/views/" + f), r"C\.views(\.%s|\['%s'\]) = function" % (page, page))

    def test_nav_and_fab(self):
        layout = read("site/js/core/layout.js")
        self.assertRegex(layout, r"key: 'poem', label: '每日一詩', page: 'poem'")
        self.assertRegex(layout, r"label: '座位表', page: 'teacher', sub: 'seating'")

    def test_teacher_only_pages_check_role_before_any_query(self):
        for f in ("family-photos.js", "print.js"):
            text = read("site/js/views/" + f)
            for m in re.finditer(r"C\.views\[['\w-]+\] = function \(ctx\) \{\n(.*?)\n", text):
                self.assertIn("if (!ctx.session.roles.teacher) return teacherOnly", m.group(1), f)

    def test_seating_svg_is_built_with_dom(self):
        text = read("site/js/views/seating.js")
        self.assertIn("createElementNS", text)
        self.assertNotIn("<svg", text)

    def test_print_css(self):
        css = read("site/css/site.css")
        self.assertRegex(css, r"@page cmwdoc \{\s*size: A4;")
        self.assertRegex(css, r"@page cmwseat \{ size: A4 landscape;")
        self.assertIn("html.cmw-print-doc .no-print", css)
        self.assertIn(".print-doc { page: cmwdoc;", css)


if __name__ == "__main__":
    unittest.main()
