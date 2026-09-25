#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""資料退場（scripts/data_exit.py）不連網的部分：本機名單檔沒改好就停、計畫檔與輸出遮信箱。
刪資料的完整流程（轉出、家長刪除、學年結束）在模擬器整合測試（tests/emulator_backup.py）。"""
import io
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

    def test_needs_subcommand(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(de.main([]), 2)


if __name__ == "__main__":
    unittest.main()
