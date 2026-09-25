#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驗過才算數的複製、原子寫檔、執行鎖、垃圾桶、增量鏡像（scripts/lib/filesafe.py）與台帳（scripts/lib/ledgers.py）。
全部在暫存目錄；垃圾桶用假的 HOME，不碰這台電腦真的垃圾桶。"""
import os
import sys
import json
import time
import shutil
import tempfile
import datetime
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from lib import filesafe as fs, ledgers, paths  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cmw-fs-"))

    def tearDown(self):
        paths.reset_root()
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def f(self, name, data=b"hello"):
        p = self.tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p


class TestCopy(Base):
    def test_copy_then_idempotent(self):
        src = self.f("a.jpg", b"123")
        dst = self.tmp / "sync" / "a.jpg"
        m, did = fs.copy_verified(src, dst)
        self.assertTrue(did)
        self.assertEqual(m, fs.md5_bytes(b"123"))
        self.assertEqual(dst.read_bytes(), b"123")
        self.assertEqual(fs.copy_verified(src, dst), (m, False))
        self.assertFalse([p for p in dst.parent.iterdir() if p.name.startswith(fs.TMP_PREFIX)])

    def test_refuses_to_overwrite_different_file(self):
        src = self.f("a.txt", b"new")
        dst = self.f("sync/a.txt", b"old")
        with self.assertRaises(fs.CopyError):
            fs.copy_verified(src, dst)
        self.assertEqual(dst.read_bytes(), b"old")
        fs.copy_verified(src, dst, overwrite=True)
        self.assertEqual(dst.read_bytes(), b"new")

    def test_expected_md5_mismatch(self):
        src = self.f("a.txt", b"x")
        with self.assertRaises(fs.CopyError):
            fs.copy_verified(src, self.tmp / "b.txt", expected_md5="0" * 32)
        self.assertFalse((self.tmp / "b.txt").exists())

    def test_corrupted_copy_is_detected_and_removed(self):
        src = self.f("a.txt", b"good")

        def bad_copy(s, d):
            Path(d).write_bytes(b"bad")
        with mock.patch.object(fs.shutil, "copyfile", side_effect=bad_copy):
            with self.assertRaises(fs.CopyError):
                fs.copy_verified(src, self.tmp / "out" / "a.txt")
        self.assertFalse((self.tmp / "out" / "a.txt").exists())

    def test_replace_retries_while_file_is_busy(self):
        real = fs.os.replace
        calls = []

        def flaky(a, b):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("檔案正被雲端硬碟程式開著")
            return real(a, b)
        slept = []
        a, b = self.f("a.tmp", b"1"), self.tmp / "b.txt"
        with mock.patch.object(fs.os, "replace", side_effect=flaky):
            fs._replace(a, b, sleep=slept.append)
        self.assertEqual((b.read_bytes(), len(calls), len(slept)), (b"1", 3, 2))
        with mock.patch.object(fs.os, "replace", side_effect=PermissionError("一直被開著")):
            with self.assertRaises(PermissionError):
                fs._replace(self.f("c.tmp"), self.tmp / "d.txt", tries=2, sleep=slept.append)

    def test_atomic_json_and_corrupt_read(self):
        p = self.tmp / "l" / "x.json"
        fs.write_json_atomic(p, {"中": 1})
        self.assertEqual(fs.read_json(p), {"中": 1})
        p.write_text("{壞掉", encoding="utf-8")
        self.assertEqual(fs.read_json(p, default={}), {})
        self.assertFalse(p.exists())
        self.assertTrue(any(x.name.startswith("x.json.corrupt-") for x in p.parent.iterdir()))

    def test_media_kind(self):
        self.assertEqual(fs.media_kind("A.JPG"), "photo")
        self.assertEqual(fs.media_kind("x.mov"), "video")
        self.assertEqual(fs.media_kind("x.m4a"), "audio")
        self.assertEqual(fs.media_kind("x.pdf"), "doc")
        self.assertIsNone(fs.media_kind("x.exe"))

    def test_human_size(self):
        self.assertEqual(fs.human_size(10), "10 B")
        self.assertEqual(fs.human_size(1536), "1.5 KB")
        self.assertEqual(fs.human_size(3 * 1024 ** 3), "3.0 GB")


class TestLockAndTrash(Base):
    def test_lock_busy_and_stale(self):
        lp = self.tmp / "b" / ".lock"
        with fs.RunLock(lp):
            with self.assertRaises(fs.LockBusy):
                with fs.RunLock(lp):
                    pass
        self.assertFalse(lp.exists())
        lp.write_text("1 old", encoding="ascii")
        old = time.time() - 7 * 3600
        os.utime(str(lp), (old, old))
        with fs.RunLock(lp):
            pass

    def test_mac_trash_with_fake_home(self):
        home = self.tmp / "home"
        (home / ".Trash").mkdir(parents=True)
        (home / ".Trash" / "a.jpg").write_bytes(b"older")
        src = self.f("inbox/a.jpg", b"x")
        where, _ = fs.move_to_trash(src, self.tmp / "fallback", os_name="mac", home=str(home), environ={})
        self.assertEqual(where, "trash")
        self.assertFalse(src.exists())
        self.assertEqual(len(list((home / ".Trash").iterdir())), 2, "同名不蓋掉垃圾桶裡原本的檔")

    def test_fallback_when_no_trash(self):
        src = self.f("inbox/b.jpg", b"x")
        where, dst = fs.move_to_trash(src, self.tmp / "inbox" / ".archived", os_name="mac", home=str(self.tmp / "nohome"),
                                      environ={})
        self.assertEqual(where, "fallback")
        self.assertTrue(Path(dst).exists() and not src.exists())
        src2 = self.f("inbox/c.jpg", b"x")
        with self.assertRaises(OSError):
            fs.move_to_trash(src2, None, os_name="unknown-os", environ={})
        self.assertTrue(src2.exists())

    def test_linux_freedesktop_trash_with_fake_home(self):
        home = self.tmp / "home"
        src = self.f("data/student-blogs/03/a.md", b"x")
        where, _ = fs.move_to_trash(src.parent, None, os_name="linux", home=str(home), environ={})
        self.assertEqual(where, "trash")
        trash = home / ".local" / "share" / "Trash"
        self.assertFalse(src.parent.exists())
        self.assertTrue((trash / "files" / "03" / "a.md").exists(), "整個資料夾進垃圾桶")
        info = (trash / "info" / "03.trashinfo").read_text(encoding="utf-8")
        self.assertTrue(info.startswith("[Trash Info]\nPath=/") or info.startswith("[Trash Info]\nPath="))
        self.assertIn("DeletionDate=", info)
        self.assertEqual(fs.trash_files_dir("linux", str(home), environ={}), trash / "files")
        # 同名第二次：不蓋掉，換一個名字，info 一對一
        src2 = self.f("data/student-blogs/03/b.md", b"y")
        fs.move_to_trash(src2.parent, None, os_name="linux", home=str(home), environ={})
        self.assertEqual(sorted(p.name for p in (trash / "files").iterdir()), ["03", "03.1"])
        self.assertEqual(sorted(p.name for p in (trash / "info").iterdir()), ["03.1.trashinfo", "03.trashinfo"])

    def test_linux_trash_follows_xdg_data_home(self):
        xdg = self.tmp / "xdg"
        env = {"XDG_DATA_HOME": str(xdg)}
        self.assertEqual(fs.freedesktop_trash(None, env), xdg / "Trash")
        self.assertEqual(fs.freedesktop_trash(None, {"XDG_DATA_HOME": "relative/not-allowed"}).name, "Trash")
        self.assertNotIn("relative", str(fs.freedesktop_trash(None, {"XDG_DATA_HOME": "relative/not-allowed"})))
        src = self.f("c.jpg", b"x")
        fs.move_to_trash(src, None, os_name="linux", environ=env)
        self.assertTrue((xdg / "Trash" / "files" / "c.jpg").exists())

    def test_trashinfo_escapes_path(self):
        txt = fs.trashinfo_text("/tmp/課程 影像/a b.jpg", when=0)
        self.assertIn("Path=/tmp/%E8%AA%B2%E7%A8%8B%20%E5%BD%B1%E5%83%8F/a%20b.jpg", txt)

    def test_windows_branch_calls_recycle_bin(self):
        src = self.f("d.jpg", b"x")
        calls = []

        def fake_recycle(p):
            calls.append(str(p))
            Path(p).unlink()
        with mock.patch.object(fs, "_trash_windows", side_effect=fake_recycle), \
                mock.patch.object(fs.sys, "platform", "win32"):
            where, info = fs.move_to_trash(src, None, os_name="win", environ={})
        self.assertEqual((where, info), ("trash", "資源回收筒"))
        self.assertEqual(calls, [str(src)])
        self.assertIsNone(fs.trash_files_dir("win", environ={}))

    def test_windows_branch_falls_back_when_recycle_fails(self):
        src = self.f("e.jpg", b"x")
        with mock.patch.object(fs, "_trash_windows", side_effect=OSError("SHFileOperationW 回 2")), \
                mock.patch.object(fs.sys, "platform", "win32"):
            where, dst = fs.move_to_trash(src, self.tmp / "fb", os_name="win", environ={})
        self.assertEqual(where, "fallback")
        self.assertTrue(Path(dst).exists())

    def test_test_hook_env_used_on_every_platform(self):
        box = self.tmp / "fake-trash"
        for osn in ("mac", "linux", "win"):
            src = self.f("g-%s.jpg" % osn, b"x")
            with mock.patch.object(fs, "_trash_windows", side_effect=AssertionError("不准碰真的資源回收筒")):
                where, _ = fs.move_to_trash(src, None, os_name=osn, environ={fs.TRASH_DIR_ENV: str(box)})
            self.assertEqual(where, "trash")
            self.assertTrue((box / src.name).exists())
        self.assertEqual(fs.trash_files_dir("win", environ={fs.TRASH_DIR_ENV: str(box)}), box)

    def test_windows_flags(self):
        flags = fs.windows_trash_flags()
        self.assertTrue(flags & fs.FOF_ALLOWUNDO, "一定要可復原（進資源回收筒，不是永久刪除）")
        self.assertTrue(flags & fs.FOF_NOCONFIRMATION)
        self.assertEqual(fs.windows_from_field("C:\\x\\a.jpg"), "C:\\x\\a.jpg\0")


class TestMirror(Base):
    def test_only_new_or_changed(self):
        src = self.f("data/albums/s/p.jpg", b"1")
        dst = self.tmp / "sync" / "s" / "p.jpg"
        m = fs.Mirror(self.tmp / "led.json")
        self.assertTrue(m.sync(src, dst, "albums/s/p.jpg"))
        self.assertFalse(m.sync(src, dst, "albums/s/p.jpg"))
        m.save()
        m2 = fs.Mirror(self.tmp / "led.json")
        self.assertFalse(m2.sync(src, dst, "albums/s/p.jpg"), "台帳記得就不重算")
        dst.unlink()
        self.assertTrue(m2.sync(src, dst, "albums/s/p.jpg"), "同步夾那份不見了就補回")
        src.write_bytes(b"22")
        t = time.time() + 5
        os.utime(str(src), (t, t))
        self.assertTrue(m2.sync(src, dst, "albums/s/p.jpg"))
        self.assertEqual(dst.read_bytes(), b"22")


class TestLedgers(Base):
    def setUp(self):
        super().setUp()
        paths.set_root(self.tmp)

    def test_fail_does_not_touch_last_ok(self):
        ledgers.mark_ok("firestore", snapshot="x")
        ok = ledgers.read_state()["firestore"]["last_ok"]
        ledgers.mark_fail("firestore", "網路斷了")
        st = ledgers.read_state()["firestore"]
        self.assertEqual(st["last_ok"], ok)
        self.assertEqual(st["last_error"], "網路斷了")
        ledgers.mark_ok("firestore")
        self.assertNotIn("last_error", ledgers.read_state()["firestore"])

    def test_media_fold_tombstone_and_restore(self):
        evs = [{"event": "archived", "md5": "a", "name": "n1", "block": "b", "year": "y", "at": "t1"},
               {"event": "archived", "md5": "a", "name": "dup", "at": "t2"},
               {"event": "removed", "md5": "a", "at": "t3"},
               {"event": "restored", "md5": "a", "at": "t4"},
               {"event": "archived", "md5": "b", "name": "n2", "at": "t1"},
               {"event": "removed", "md5": "b", "at": "t5"},
               {"event": "removed", "md5": "zz", "at": "t5"}]
        ledgers.append_media_events(evs)
        with open(str(ledgers.media_ledger_path()), "a", encoding="utf-8") as f:
            f.write("{壞掉\n" + json.dumps({"event": "?", "md5": "c"}) + "\n")
        got, bad = ledgers.read_media_events()
        self.assertEqual(bad, 2)
        st = ledgers.fold_media(got)
        self.assertEqual(st["a"]["status"], "active")
        self.assertEqual(st["a"]["name"], "n1", "同一個 md5 第二次 archived 不算")
        self.assertEqual(st["b"]["status"], "removed")
        self.assertNotIn("zz", st)

    def test_access_sync_marker(self):
        self.assertIsNone(ledgers.last_access_sync())
        ledgers.mark_access_sync()
        self.assertLess(abs((datetime.datetime.now().astimezone() - ledgers.last_access_sync()).total_seconds()), 5)


if __name__ == "__main__":
    unittest.main()
