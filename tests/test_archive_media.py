#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""課堂檔案歸檔（scripts/archive_media.py、scripts/lib/namecheck.py）與開新課程單元（scripts/new_block.py）：
命名規則、姓名檢查、台帳與墓碑、影片一次一支、驗過才移走原檔。全部在暫存目錄；同步夾是假的、垃圾桶是假的。"""
import io
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
import archive_media as am  # noqa: E402
import new_block  # noqa: E402
import admin_support as fx  # noqa: E402
from lib import namecheck, ledgers, paths, filesafe  # noqa: E402
from lib import drivetree as dt  # noqa: E402
from lib.sources import Student  # noqa: E402


def nb(*args):
    with redirect_stdout(io.StringIO()):
        return new_block.main(list(args))


class TestNaming(unittest.TestCase):
    def test_build_name(self):
        self.assertEqual(am.build_name("20310303", "範例單元", "板書", "單元重點", ".JPG"),
                         "20310303-範例單元-板書-單元重點.jpg")
        for typ in ("照片", "作品", "", "板書 "):
            with self.assertRaises(am.Stop):
                am.build_name("20310303", "範例單元", typ, "x", ".jpg")
        for desc in ("", "  ", "a/b", "字" * 41, "x:y"):
            with self.assertRaises(am.Stop):
                am.build_name("20310303", "範例單元", "板書", desc, ".jpg")
        for d in ("2031033", "20311303", "2031-03-03"):
            with self.assertRaises(am.Stop):
                am.build_name(d, "範例單元", "板書", "重點", ".jpg")

    def test_types_are_exactly_five(self):
        self.assertEqual(am.TYPES, ("板書", "作業本", "課堂活動", "教材", "其他"))


class TestNameCheck(unittest.TestCase):
    def setUp(self):
        self.n = namecheck.needles([Student("01", "王小明", "小明", 2), Student("02", "Anna Lee", "Anna", 3),
                                    Student("03", "林", "林", 4), Student("04", "歐陽大文", "大文", 5)])

    def test_hits_return_seats_only(self):
        self.assertEqual(namecheck.find("王小明的作業本", self.n), ["01"])
        self.assertEqual(namecheck.find("小明寫的", self.n), ["01"], "只寫名不寫姓也要擋")
        self.assertEqual(namecheck.find("anna 的畫", self.n), ["02"], "英文不分大小寫")
        self.assertEqual(namecheck.find("大文的作品", self.n), ["04"])
        self.assertEqual(namecheck.find("樹林裡的葉子", self.n), [], "1 個字的名字不擋（太容易誤判）")
        self.assertEqual(namecheck.find("習寫練習", self.n), [])

    def test_load_without_roster(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            self.assertIsNone(namecheck.load(tmp))
            fx.write(tmp / "roster.csv", fx.roster_csv(3))
            self.assertEqual(namecheck.find("學生 B 的作業", namecheck.load(tmp)), ["02"])
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cmw-am-"))
        self.root = fx.make_root(self.tmp / "root", photos=False, n=5)
        self.data = self.root / "data"
        self.sync = self.tmp / "My Drive"
        self.sync.mkdir()
        cfg = fx.config()
        cfg["drive"] = {"sync_root": str(self.sync), "class_folder": "示範班級 班級網站"}
        fx.write(self.root / "config" / "class.json", json.dumps(cfg, ensure_ascii=False))
        dt.build_tree(self.sync, "示範班級 班級網站", year="2030-2031")
        self.media = dt.DriveTree(self.sync, "示範班級 班級網站").path("media")
        self.home = self.tmp / "home"
        (self.home / ".Trash").mkdir(parents=True)
        paths.set_root(self.root)
        self.real_trash = filesafe.move_to_trash
        home = str(self.home)
        self.patch = mock.patch.object(am, "move_to_trash",
                                       lambda p, fb: self.real_trash(p, fb, os_name="mac", home=home))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        paths.reset_root()
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def inbox(self, name, data):
        p = self.data / "inbox" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def run_main(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = am.main(list(args) + ["--root", str(self.root)])
        return rc, buf.getvalue()


class TestArchive(Env):
    def test_block_must_exist(self):
        self.inbox("a.jpg", b"1")
        rc, out = self.run_main("--block", "範例單元", "--file", "a.jpg", "--type", "板書", "--desc", "重點")
        self.assertEqual(rc, 2)
        self.assertIn("new_block.py", out)

    def test_full_flow_ledger_tombstone(self):
        self.assertEqual(nb("範例單元", "--root", str(self.root)), 0)
        self.inbox("IMG_1.jpg", b"photo-1")
        self.inbox("講義.pdf", b"pdf")
        man = self.tmp / "m.json"
        man.write_text(json.dumps([{"file": "IMG_1.jpg", "type": "板書", "desc": "單元重點", "date": "20310303"},
                                   {"file": "講義.pdf", "type": "教材", "desc": "單元講義", "date": "20310304"}],
                                  ensure_ascii=False), encoding="utf-8")
        rc, out = self.run_main("--block", "範例單元", "--manifest", str(man))
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.data / "inbox" / "IMG_1.jpg").exists(), "預覽不動 inbox")
        self.assertFalse((self.media / "2030-2031" / "範例單元").exists(), "預覽不建夾")
        rc, out = self.run_main("--block", "範例單元", "--manifest", str(man), "--apply")
        self.assertEqual(rc, 0, out)
        dst = self.media / "2030-2031" / "範例單元" / "20310303-範例單元-板書-單元重點.jpg"
        self.assertEqual(dst.read_bytes(), b"photo-1")
        self.assertFalse((self.data / "inbox" / "IMG_1.jpg").exists(), "驗過 md5 才移走原檔")
        self.assertEqual(len(list((self.home / ".Trash").iterdir())), 2, "原檔進（假的）垃圾桶")
        st = ledgers.fold_media(ledgers.read_media_events()[0])
        self.assertEqual(sorted(r["name"] for r in st.values()),
                         ["20310303-範例單元-板書-單元重點.jpg", "20310304-範例單元-教材-單元講義.pdf"])
        # 同一個檔再丟進來：跳過
        self.inbox("copy.jpg", b"photo-1")
        rc, out = self.run_main("--block", "範例單元", "--file", "copy.jpg", "--type", "板書", "--desc", "再一次", "--apply")
        self.assertEqual(rc, 0)
        self.assertIn("已經歸檔過", out)
        self.assertTrue((self.data / "inbox" / "copy.jpg").exists(), "跳過的檔不動")
        # 老師在雲端硬碟刪掉 → 墓碑 → 不重傳
        dst.unlink()
        rc, out = self.run_main("--block", "範例單元", "--file", "copy.jpg", "--type", "板書", "--desc", "再一次", "--apply")
        self.assertIn("刪掉了", out)
        self.assertFalse(dst.exists())
        self.assertEqual(ledgers.fold_media(ledgers.read_media_events()[0])[filesafe.md5_bytes(b"photo-1")]["status"], "removed")
        rc, out = self.run_main("--block", "範例單元", "--file", "copy.jpg", "--type", "板書", "--desc", "再一次", "--apply")
        self.assertIn("刪掉了這個檔", out)
        self.assertFalse(dst.exists(), "墓碑擋住重傳")
        # 老師從垃圾桶救回來 → 對帳撤銷墓碑
        dst.write_bytes(b"photo-1")
        rc, out = self.run_main("--reconcile")
        self.assertEqual(rc, 0)
        self.assertIn("救回來 1 個", out)

    def test_name_and_video_gates(self):
        nb("範例單元", "--root", str(self.root))
        self.inbox("a.jpg", b"1")
        rc, out = self.run_main("--block", "範例單元", "--file", "a.jpg", "--type", "作業本", "--desc", "學生 C 的習寫")
        self.assertEqual(rc, 2)
        self.assertIn("座號 03", out)
        self.assertNotIn("學生 C", out.replace("學生 C 的習寫", ""), "只印座號，不印名字")
        self.inbox("v1.mp4", b"v1")
        self.inbox("v2.mov", b"v2")
        man = self.tmp / "m.json"
        man.write_text(json.dumps([{"file": "v1.mp4", "type": "課堂活動", "desc": "分組討論"},
                                   {"file": "v2.mov", "type": "課堂活動", "desc": "戲劇"}], ensure_ascii=False), encoding="utf-8")
        rc, out = self.run_main("--block", "範例單元", "--manifest", str(man), "--apply")
        self.assertEqual(rc, 2)
        self.assertIn("一次只處理一支影片", out)
        self.inbox("x.exe", b"1")
        rc, out = self.run_main("--block", "範例單元", "--file", "x.exe", "--type", "其他", "--desc", "x")
        self.assertEqual(rc, 2)

    def test_listing_is_read_only(self):
        self.inbox("a.jpg", b"1")
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assertIn("a.jpg", out)
        self.assertTrue((self.data / "inbox" / "a.jpg").exists())

    def test_reconcile_guards(self):
        folder = self.media / "2030-2031" / "範例單元"
        folder.mkdir(parents=True)
        state = {m: {"status": "active", "year": "2030-2031", "block": "範例單元", "name": "f%s.jpg" % m} for m in "abc"}
        evs, notes = am.reconcile(state, self.media)
        self.assertEqual(evs, [], "整夾 3 個以上全部不見＝多半還沒同步下來，不下結論")
        self.assertTrue(notes)
        (folder / "fa.jpg").write_bytes(b"x")
        evs, _ = am.reconcile(state, self.media)
        self.assertEqual(sorted(e["md5"] for e in evs if e["event"] == "removed"), ["b", "c"])
        shutil.rmtree(str(folder))
        evs, notes = am.reconcile(state, self.media)
        self.assertEqual(evs, [])
        self.assertIn("整個不見", notes[0])


class TestNewBlock(Env):
    def test_creates_from_template_without_overwrite(self):
        rc = nb("單元一-範例", "--title", "範例單元（示範）", "--start", "2031-03-03", "--root", str(self.root))
        self.assertEqual(rc, 0)
        b = self.data / "units" / "單元一-範例"
        self.assertTrue((b / "大綱.md").exists() and (b / "session.yaml").exists() and (b / "lessons").is_dir()
                        and (b / "texts").is_dir())
        self.assertIn('block: "單元一-範例"', (b / "session.yaml").read_text(encoding="utf-8"))
        self.assertIn("2030-2031", (b / "session.yaml").read_text(encoding="utf-8"))
        rec = self.data / "courses" / "單元一-範例" / "records.md"
        self.assertIn("範例單元（示範）", rec.read_text(encoding="utf-8"))
        self.assertNotIn("{{", rec.read_text(encoding="utf-8"))
        rec.write_text("老師寫的紀錄", encoding="utf-8")
        self.assertEqual(nb("單元一-範例", "--root", str(self.root)), 0)
        self.assertEqual(rec.read_text(encoding="utf-8"), "老師寫的紀錄", "已經有的檔不覆蓋")

    def test_rejects_bad_names(self):
        for bad in ("a/b", "_範本", "..", "學生 A 的課", "CON"):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(new_block.main([bad, "--root", str(self.root)]), 2, bad)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(new_block.main(["x", "--start", "10/05", "--root", str(self.root)]), 2)


if __name__ == "__main__":
    unittest.main()
