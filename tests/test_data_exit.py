#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""資料退場（scripts/data_exit.py）不連網的部分：本機名單檔沒改好就停、計畫檔與輸出遮信箱。
刪資料的完整流程（轉出、家長刪除、學年結束）在模擬器整合測試（tests/emulator_backup.py）。"""
import io
import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
import data_exit as de  # noqa: E402
import admin_support as fx  # noqa: E402
from lib import paths  # noqa: E402
from lib.emailkey import email_key  # noqa: E402


class TestGates(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cmw-de-"))
        self.root = fx.make_root(self.tmp / "root", photos=False, n=5)
        self.data = self.root / "data"
        paths.set_root(self.root)

    def tearDown(self):
        paths.reset_root()
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def test_seat_gate_until_all_three_files_edited(self):
        probs = de.local_gate_seat(self.data, "03")
        self.assertEqual(len(probs), 3)
        self.assertFalse(any("學生 C" in p or "example.com" in p for p in probs), "只說座號與檔名")
        fx.write(self.data / "roster.csv", "\n".join(l for l in fx.roster_csv(5).splitlines() if not l.startswith("03,")) + "\n")
        fx.write(self.data / "contacts.csv", fx.contacts_csv(5, drop=(2,)))
        fx.write(self.data / "parent-roles.yaml",
                 "\n".join(l for l in fx.roles_yaml(5).splitlines() if not l.startswith('"03"')) + "\n")
        probs = de.local_gate_seat(self.data, "03")
        self.assertEqual(len(probs), 1, "同仁那一列（座號 03）也要改掉")
        fx.write(self.data / "contacts.csv", "\n".join(l for l in fx.contacts_csv(5, drop=(2,)).splitlines()
                                                     if not l.startswith("03,")) + "\n")
        self.assertEqual(de.local_gate_seat(self.data, "03"), [])

    def test_parent_gate(self):
        k = email_key(fx.parent_mail(1))
        self.assertEqual(len(de.local_gate_parent(self.data, k)), 1)
        fx.write(self.data / "contacts.csv", fx.contacts_csv(5, drop=(1,)))
        self.assertEqual(de.local_gate_parent(self.data, k), [])

    def test_plan_file_masks_emails(self):
        p = de.Plan("測試")
        p.revoke = ["allowlist/" + email_key(fx.parent_mail(0))]
        p.deletes = ["posts/x/reads/" + email_key(fx.parent_mail(0))]
        f = de.write_plan_file(p, "t")
        text = f.read_text(encoding="utf-8")
        self.assertNotIn(fx.parent_mail(0), text)
        self.assertIn("p***@example.com", text)
        buf = io.StringIO()
        with redirect_stdout(buf):
            de.show(p)
        self.assertNotIn(fx.parent_mail(0), buf.getvalue())

    def test_remove_path_reads_back(self):
        d = self.tmp / "sync" / "04_部落格歸檔" / "05"
        (d / "2026").mkdir(parents=True)
        (d / "2026" / "a.md").write_text("x", encoding="utf-8")
        (d / "b.jpg").write_bytes(b"1")
        self.assertEqual(de.remove_path(d), [])
        self.assertFalse(d.exists())
        self.assertEqual(de.remove_path(d), [], "已經不在＝刪好了")
        f = self.tmp / "one.jpg"
        f.write_bytes(b"1")
        self.assertEqual(de.remove_path(f), [])
        self.assertFalse(f.exists())

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "用唯讀資料夾模擬「檔案被鎖住」：Windows 與 root 做不出來")
    def test_locked_folder_is_reported_not_swallowed(self):
        d = self.tmp / "sync" / "學生個別資料" / "05"
        locked = d / "照片"
        locked.mkdir(parents=True)
        (locked / "a.jpg").write_bytes(b"1")
        (d / "b.md").write_text("x", encoding="utf-8")
        os.chmod(str(locked), 0o500)
        try:
            p = de.Plan("測試")
            p.sync = [d]
            gone, failed = de.execute(None, p, [])
            self.assertTrue(d.exists())
            self.assertFalse((d / "b.md").exists(), "刪得掉的照樣刪")
            self.assertEqual(failed, [str(locked / "a.jpg")], "刪不掉的列出來，不假裝刪好了")
        finally:
            os.chmod(str(locked), 0o700)

    def test_orphan_photos_of_seat(self):
        from lib import fsbackup as fsb
        from lib import firestore_rest as fr
        e = "student_blogs/05/entries/2026-10-05-abcdefgh"

        class C(object):
            def list_docs(self, coll, mask=None):
                assert coll == "student_blogs/05/entries" and mask == ["photos"]
                return [fr.Doc(e, {"photos": [{"pid": "0", "w": 2, "h": 2}]})]

        class W(object):
            def walk(self, roots=None, names_only=False):
                assert roots == ["student_blogs/05/entries"] and names_only
                ex = fsb.Export()
                ex.photos = [{"path": e + "/images/0"}, {"path": e + "/thumbs/2"},
                             {"path": "student_blogs/05/entries/2026-10-09-nopostxx/images/0"}]
                return ex
        self.assertEqual(de.orphan_photos_of_seat(C(), W(), "05"),
                         [e + "/thumbs/2", "student_blogs/05/entries/2026-10-09-nopostxx/images/0"])

    def test_needs_subcommand(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(de.main([]), 2)


if __name__ == "__main__":
    unittest.main()
