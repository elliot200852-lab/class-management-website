#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""雲端硬碟同步夾（scripts/lib/drivetree.py、scripts/drive_init.py）：找同步夾（假目錄、Windows 用 PureWindowsPath）、
資料夾樹、名字檢查、學年、找不到就停（不自己建）。**不碰真的雲端硬碟同步夾**，全部在暫存目錄。"""
import io
import sys
import json
import shutil
import tempfile
import datetime
import unittest
from pathlib import Path, PureWindowsPath
from contextlib import redirect_stdout
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
from lib import drivetree as dt, paths  # noqa: E402
import admin_support as fx  # noqa: E402
import drive_init  # noqa: E402


class FakeFS(object):
    """假的檔案系統：isdir 看字串在不在集合裡；listdir 回某個資料夾底下的名字。"""

    def __init__(self, dirs, listing=None):
        self.dirs = set(dirs)
        self.listing = listing or {}

    def isdir(self, p):
        return str(p) in self.dirs

    def listdir(self, p):
        if str(p) not in self.listing:
            raise OSError("no such dir")
        return self.listing[str(p)]


class TestDetect(unittest.TestCase):
    def test_mac_cloudstorage_both_languages(self):
        home = "/Users/t"
        cs = home + "/Library/CloudStorage"
        fs = FakeFS([cs + "/GoogleDrive-a@example.com/我的雲端硬碟", cs + "/GoogleDrive-b@example.com/My Drive",
                     cs + "/OneDrive-x/Documents"],
                    {cs: ["OneDrive-x", "GoogleDrive-b@example.com", "GoogleDrive-a@example.com"]})
        got = dt.detect_candidates("mac", home, environ={}, isdir=fs.isdir, listdir=fs.listdir)
        self.assertEqual(got, [cs + "/GoogleDrive-a@example.com/我的雲端硬碟", cs + "/GoogleDrive-b@example.com/My Drive"])

    def test_mac_old_locations_and_nothing(self):
        fs = FakeFS(["/Volumes/GoogleDrive/My Drive"])
        self.assertEqual(dt.detect_candidates("mac", "/Users/t", environ={}, isdir=fs.isdir, listdir=fs.listdir),
                         ["/Volumes/GoogleDrive/My Drive"])
        empty = FakeFS([])
        self.assertEqual(dt.detect_candidates("mac", "/Users/t", environ={}, isdir=empty.isdir, listdir=empty.listdir), [])

    def test_windows_drive_letters_with_purewindowspath(self):
        g = str(PureWindowsPath("G:\\") / "My Drive")
        h = str(PureWindowsPath("H:\\") / "我的雲端硬碟")
        mirror = str(PureWindowsPath("C:\\Users\\t") / "Google Drive" / "我的雲端硬碟")
        fs = FakeFS([h, g, mirror])
        got = dt.detect_candidates("win", "C:\\Users\\t", environ={"USERPROFILE": "C:\\Users\\t"}, isdir=fs.isdir,
                                   listdir=fs.listdir)
        self.assertEqual(got, ["G:\\My Drive", "H:\\我的雲端硬碟", "C:\\Users\\t\\Google Drive\\我的雲端硬碟"])
        self.assertTrue(all("\\" in x and "/" not in x for x in got))

    def test_windows_isdir_errors_are_swallowed(self):
        def boom(p):
            raise OSError("裝置沒有就緒")
        self.assertEqual(dt.detect_candidates("win", "C:\\Users\\t", environ={}, isdir=boom), [])

    def test_linux(self):
        fs = FakeFS(["/home/t/Google Drive/My Drive"])
        self.assertEqual(dt.detect_candidates("linux", "/home/t", environ={}, isdir=fs.isdir, listdir=fs.listdir),
                         ["/home/t/Google Drive/My Drive"])

    def test_looks_like_drive(self):
        self.assertTrue(dt.looks_like_drive("G:\\My Drive"))
        self.assertTrue(dt.looks_like_drive("/x/GoogleDrive-a/我的雲端硬碟"))
        self.assertFalse(dt.looks_like_drive("/Users/t/Desktop"))


class TestNames(unittest.TestCase):
    def test_name_problem(self):
        self.assertIsNone(dt.name_problem("範例單元"))
        self.assertIsNone(dt.name_problem("單元一-範例課"))
        for bad in ("", " x", "a/b", "a\\b", "a:b", "a*b", "a?b", '"x"', "<x>", "a|b", ".hidden", "..", "x.", "CON",
                    "nul.txt", "COM1", "lpt9", "x\ny"):
            self.assertIsNotNone(dt.name_problem(bad), bad)
        self.assertIsNotNone(dt.name_problem("字" * 61))

    def test_class_folder_name(self):
        self.assertEqual(dt.class_folder_name("三年甲班"), "三年甲班 班級網站")
        self.assertEqual(dt.class_folder_name("A/B: 班"), "A_B_ 班 班級網站")
        self.assertEqual(dt.class_folder_name(""), "我的班級 班級網站")
        self.assertEqual(dt.class_folder_name("CON"), "我的班級 班級網站")
        self.assertIsNone(dt.name_problem(dt.class_folder_name('我的:"班"*')))

    def test_school_year(self):
        self.assertEqual(dt.school_year(datetime.date(2030, 7, 31)), "2029-2030")
        self.assertEqual(dt.school_year(datetime.date(2030, 8, 1)), "2030-2031")
        self.assertEqual(dt.school_year("20310301"), "2030-2031")
        self.assertEqual(dt.school_year("2030-09-25"), "2030-2031")
        with self.assertRaises(ValueError):
            dt.school_year("2030/09/25")

    def test_school_year_start_month_is_configurable(self):
        self.assertEqual(dt.school_year("2031-03-31", 4), "2030-2031")
        self.assertEqual(dt.school_year("2031-04-01", 4), "2031-2032")
        self.assertEqual(dt.school_year("2031-03-03", 1), "2031", "學年就是日曆年：只寫年份")
        self.assertEqual(dt.school_year("2031-03-03", 99), "2030-2031", "不合法的月份退回預設值")

    def test_year_settings(self):
        self.assertEqual(dt.year_settings({}), (8, ("上學期", "下學期")))
        self.assertEqual(dt.year_settings({"school_year": {"start_month": 9, "terms": ["第一學期", "第二學期", "第三學期"]}}),
                         (9, ("第一學期", "第二學期", "第三學期")))
        self.assertEqual(dt.year_settings({"school_year": {"start_month": "8", "terms": ["a/b"]}}),
                         (8, ("上學期", "下學期")), "寫錯的欄位用預設值")
        self.assertEqual(dt.school_year_problems(None), [])
        self.assertEqual(dt.school_year_problems({"start_month": 2, "terms": ["第一學期", "第二學期", "第三學期"]}), [])
        for bad in ([], {"start_month": 0}, {"start_month": True}, {"terms": []}, {"terms": ["上", "上"]},
                    {"terms": ["a/b"]}, {"terms": "上學期"}, {"terms": ["x"] * 7}):
            self.assertTrue(dt.school_year_problems(bad), bad)

    def test_term_aliases(self):
        self.assertEqual(dt.term_aliases({}), {}, "沒寫＝沒有別名")
        self.assertEqual(dt.term_aliases({"school_year": {"term_aliases": {}}}), {})
        ok = {"term_aliases": {"上學期": ["第一學期", "上學期班"], "下學期": ["第二學期"]}}
        self.assertEqual(dt.school_year_problems(ok), [])
        self.assertEqual(dt.term_aliases({"school_year": ok}),
                         {"第一學期": "上學期", "上學期班": "上學期", "第二學期": "下學期"})
        three = {"terms": ["學段一", "學段二", "學段三"], "term_aliases": {"學段二": ["期中段"]}}
        self.assertEqual(dt.school_year_problems(three), [])
        self.assertEqual(dt.term_aliases({"school_year": three}), {"期中段": "學段二"})
        for bad in ({"term_aliases": ["第一學期"]},                                  # 不是物件
                    {"term_aliases": {"第一學期": ["學段一"]}},                       # 鍵不是 terms 裡的學期
                    {"term_aliases": {"上學期": "第一學期"}},                         # 值不是清單
                    {"term_aliases": {"上學期": []}},
                    {"term_aliases": {"上學期": ["x%d" % i for i in range(dt.MAX_ALIASES + 1)]}},
                    {"term_aliases": {"上學期": ["a/b"]}},                            # 不能當資料夾名稱
                    {"term_aliases": {"上學期": ["下學期"]}},                         # 跟學期名稱撞名
                    {"term_aliases": {"上學期": ["第一"], "下學期": ["第一"]}},        # 一個別名對到兩個學期
                    {"term_aliases": {"上學期": ["第一", "第一"]}}):
            with self.subTest(bad=bad):
                self.assertTrue(dt.school_year_problems(bad), bad)
                self.assertEqual(dt.term_aliases({"school_year": bad}), {}, "寫錯就當沒有別名")
        self.assertEqual(dt.year_settings({"school_year": {"terms": ["學段一", "學段二"], "term_aliases": {"x": 1}}}),
                         (8, ("學段一", "學段二")), "別名寫錯不影響學期本身")

    def test_tree_folders_parents_first_and_share_folder_present(self):
        tf = dt.tree_folders("2030-2031")
        for i, t in enumerate(tf):
            self.assertTrue(all(t[:k] in tf[:i] for k in range(1, len(t))), t)
        self.assertIn((dt.SHARE, "科任課程大綱"), tf)
        self.assertIn((dt.CONF, dt.MEDIA, "2030-2031"), tf)
        self.assertIn((dt.CONF, dt.CLASS_DOCS, "2030-2031", "上學期"), tf)
        self.assertIn((dt.CONF, dt.CLASS_DOCS, dt.GENERAL_DOCS), tf)
        self.assertTrue(all(dt.name_problem(seg) is None for t in tf for seg in t))
        three = dt.tree_folders("2030-2031", ("第一學期", "第二學期", "第三學期"))
        self.assertIn((dt.CONF, dt.CLASS_DOCS, "2030-2031", "第三學期"), three)
        self.assertNotIn((dt.CONF, dt.CLASS_DOCS, "2030-2031", "上學期"), three)


class TreeBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cmw-drive-"))
        self.sync = self.tmp / "My Drive"
        self.sync.mkdir()

    def tearDown(self):
        paths.reset_root()
        shutil.rmtree(str(self.tmp), ignore_errors=True)


class TestTree(TreeBase):
    def test_require_stops_without_creating(self):
        t = dt.DriveTree(None, "")
        with self.assertRaises(dt.DriveTreeError) as e:
            t.require()
        self.assertIn("drive_init", e.exception.plain())
        gone = dt.DriveTree(self.tmp / "不在", "班 班級網站")
        with self.assertRaises(dt.DriveTreeError) as e:
            gone.require("media")
        self.assertIn("雲端硬碟桌面程式", e.exception.plain())
        self.assertFalse((self.tmp / "不在").exists())
        t = dt.DriveTree(self.sync, "班 班級網站")
        with self.assertRaises(dt.DriveTreeError):
            t.require("media")
        self.assertEqual(list(self.sync.iterdir()), [], "找不到樹時不准自己建")

    def test_build_then_require_everything(self):
        created = dt.build_tree(self.sync, "班 班級網站", year="2030-2031")
        self.assertIn("班 班級網站/" + dt.MARKER_NAME, created)
        t = dt.DriveTree(self.sync, "班 班級網站")
        got = t.require(*dt.LOCATIONS)
        self.assertEqual(got["media"], self.sync / "班 班級網站" / dt.CONF / "課堂檔案")
        self.assertIn("只是建好，還沒有分享", (t.root / dt.MARKER_NAME).read_text(encoding="utf-8"))
        self.assertEqual(dt.build_tree(self.sync, "班 班級網站", year="2030-2031"), [], "第二次跑什麼都不用建")

    def test_marker_and_subfolder_missing(self):
        dt.build_tree(self.sync, "班 班級網站")
        t = dt.DriveTree(self.sync, "班 班級網站")
        shutil.rmtree(str(t.path("fs_photos")))
        with self.assertRaises(dt.DriveTreeError) as e:
            t.require("fs_photos")
        self.assertIn("drive_init.py --apply", e.exception.plain())
        self.assertFalse(t.path("fs_photos").exists())
        (t.root / dt.MARKER_NAME).unlink()
        with self.assertRaises(dt.DriveTreeError) as e:
            t.require()
        self.assertIn("說明檔", e.exception.plain())

    def test_ensure_below(self):
        dt.build_tree(self.sync, "班 班級網站")
        t = dt.DriveTree(self.sync, "班 班級網站")
        p = dt.ensure_below(t.path("media"), "2030-2031", "範例單元")
        self.assertTrue(p.is_dir())
        for bad in ("../x", "a/b", "..", ""):
            with self.assertRaises(dt.DriveTreeError):
                dt.ensure_below(t.path("media"), bad)
        with self.assertRaises(dt.DriveTreeError):
            dt.ensure_below(self.tmp / "沒驗證過", "x")

    def test_from_config(self):
        t = dt.DriveTree.from_config({"class_name": "三甲", "drive": {"sync_root": str(self.sync)}})
        self.assertEqual(t.class_folder, "三甲 班級網站")
        t = dt.DriveTree.from_config({"class_name": "三甲", "drive": {"sync_root": str(self.sync), "class_folder": "舊名 班級網站"}})
        self.assertEqual(t.class_folder, "舊名 班級網站", "改班名不會讓程式找不到原來那棵樹")
        self.assertIsNone(dt.DriveTree.from_config({}).root)
        t = dt.DriveTree.from_config({"drive": {"sync_root": str(self.sync)}, "school_year": {"start_month": 4}})
        self.assertEqual((t.start_month, t.school_year("2031-03-31")), (4, "2030-2031"))
        self.assertEqual(t.term_aliases, {})
        t = dt.DriveTree.from_config({"drive": {"sync_root": str(self.sync)},
                                      "school_year": {"term_aliases": {"下學期": ["第二學期"]}}})
        self.assertEqual(t.term_aliases, {"第二學期": "下學期"})


class TestDriveInit(TreeBase):
    def setUp(self):
        super().setUp()
        self.root = self.tmp / "root"
        fx.write(self.root / "config" / "class.json", json.dumps(fx.config(), ensure_ascii=False, indent=2))

    def run_main(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = drive_init.main(list(args) + ["--root", str(self.root)])
        return rc, buf.getvalue()

    def test_list_candidates_and_pick(self):
        with mock.patch.object(dt, "detect_candidates", return_value=[str(self.sync)]):
            rc, out = self.run_main()
            self.assertEqual(rc, 0)
            self.assertIn("1. %s" % self.sync, out)
            self.assertEqual(list(self.sync.iterdir()), [], "只列清單不建")
            rc, out = self.run_main("--pick", "2", "--apply")
            self.assertEqual(rc, 2)
            rc, out = self.run_main("--pick", "1")
            self.assertEqual(rc, 0)
            self.assertIn("只是預覽", out)
            self.assertEqual(list(self.sync.iterdir()), [])
            rc, out = self.run_main("--pick", "1", "--apply")
        self.assertEqual(rc, 0, out)
        cfg = json.loads((self.root / "config" / "class.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["drive"], {"sync_root": str(self.sync), "class_folder": "示範班級 班級網站"})
        self.assertEqual(cfg["teacher"]["email"], fx.TEACHER, "其他欄位原樣保留")
        self.assertEqual(self.run_main("--check")[0], 0)
        shutil.rmtree(str(self.sync / "示範班級 班級網站" / dt.SITE))
        self.assertEqual(self.run_main("--check")[0], 2)
        rc, out = self.run_main("--apply")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.run_main("--check")[0], 0, "已經設定過：--apply 把缺的補回來")

    def test_no_candidates_explains_official_download(self):
        with mock.patch.object(dt, "detect_candidates", return_value=[]):
            rc, out = self.run_main()
        self.assertEqual(rc, 2)
        self.assertIn("https://www.google.com/drive/download/", out)

    def test_path_must_exist(self):
        rc, out = self.run_main("--path", str(self.tmp / "nope"), "--apply")
        self.assertEqual(rc, 2)
        other = self.tmp / "Desktop"
        other.mkdir()
        rc, out = self.run_main("--path", str(other))
        self.assertEqual(rc, 0)
        self.assertIn("看起來不像", out)


if __name__ == "__main__":
    unittest.main()
