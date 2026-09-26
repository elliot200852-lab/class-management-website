#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""照文件實走安裝時抓到的小地方（不連網）：「再跑」提示帶回 --root／--emulator、安裝做到一半時的提示、
學年封存旗標、家長信草稿的座號、資料退場的登入帳號清單、where.py 用路徑打開、備份心跳的說法、三處禁讀清單一致。"""
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
import admin_support as fx  # noqa: E402
import access_sync  # noqa: E402
import status  # noqa: E402
import parent_note  # noqa: E402
import data_exit as de  # noqa: E402
import where  # noqa: E402
import drive_init  # noqa: E402
import backup  # noqa: E402
from lib import paths, progress, ledgers  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib.emailkey import email_key  # noqa: E402


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cmw-walk-"))
        self.root = fx.make_root(self.tmp / "root", photos=False, n=5)
        paths.set_root(self.root)

    def tearDown(self):
        paths.reset_root()
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def run_main(self, fn, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = fn(list(args) + ["--root", str(self.root)])
        return rc, buf.getvalue()

    def progress_file(self, steps):
        fx.write(self.root / "setup" / "progress.json",
                 json.dumps({"format": 1, "version": "x", "steps": steps}, ensure_ascii=False))


class TestRerunFlags(unittest.TestCase):
    def test_carries_root_and_emulator(self):
        class A(object):
            root = None
            emulator = False
        a = A()
        self.assertEqual(paths.rerun_flags(a), "")
        a.emulator = True
        self.assertEqual(paths.rerun_flags(a), " --emulator")
        a.root = "try"
        self.assertEqual(paths.rerun_flags(a), ' --root "try" --emulator')
        a.root = "C:\\Users\\x\\try"
        self.assertIn('--root "C:/Users/x/try"', paths.rerun_flags(a), "路徑一律正斜線")

    def test_publish_preview_hint_keeps_flags(self):
        tmp = Path(tempfile.mkdtemp(prefix="cmw-walk-"))
        try:
            root = fx.make_root(tmp / "root", photos=False, n=3)
            import publish_post
            buf = io.StringIO()
            with mock.patch.object(fr, "make_client", side_effect=AssertionError("預覽不該連資料庫")), redirect_stdout(buf):
                rc = publish_post.main(["2026-10-01-autumn-walk", "--root", str(root), "--emulator"])
            self.assertEqual(rc, 0, buf.getvalue())
            self.assertIn('--publish --root "%s" --emulator' % str(root).replace("\\", "/"), buf.getvalue())
        finally:
            paths.reset_root()
            shutil.rmtree(str(tmp), ignore_errors=True)


class TestInstallProgress(Env):
    def test_first_open_step(self):
        self.assertIsNone(progress.first_open_step(None))
        self.assertEqual(progress.first_open_step({"steps": {"0": {"done": True}}}), 1)
        self.assertEqual(progress.first_open_step({"steps": {str(n): {"done": True} for n in range(11)}}), None)
        self.assertEqual(progress.first_open_step({"steps": {"0": {"done": True}, "1": {"done": "yes"}}}), 1)

    def test_status_only_says_which_step_during_install(self):
        self.progress_file({"0": {"done": True}, "1": {"done": True}, "2": {"done": True}, "3": {"done": False, "note": "問到第 4 題"}})
        rc, out = self.run_main(status.main)
        self.assertEqual(rc, 0)
        self.assertIn("安裝做到第 3 步，照 AGENTS.md 接著做", out)
        self.assertIn("問到第 4 題", out)
        self.assertNotIn("備份", out.replace("日常提醒（備份", ""), "安裝中不印日常建議")
        self.assertNotIn("access_sync", out)

    def test_status_normal_when_installed_or_unknown(self):
        rc, out = self.run_main(status.main)
        self.assertIn("網站資料庫備份", out, "沒有進度檔：照平常印")
        self.progress_file({str(n): {"done": True} for n in range(11)})
        rc, out = self.run_main(status.main)
        self.assertNotIn("安裝做到第", out)
        (self.root / "setup" / "progress.json").write_text("{壞掉", encoding="utf-8")
        rc, out = self.run_main(status.main)
        self.assertNotIn("安裝做到第", out)

    def test_drive_init_next_step_follows_progress(self):
        sync = self.tmp / "My Drive"
        sync.mkdir()
        self.progress_file({"0": {"done": True}, "5": {"done": False}})
        rc, out = self.run_main(drive_init.main, "--path", str(sync), "--apply")
        self.assertEqual(rc, 0, out)
        self.assertIn("回 AGENTS.md 接著做", out)
        self.assertNotIn("backup.py all", out)
        self.progress_file({str(n): {"done": True} for n in range(11)})
        rc, out = self.run_main(drive_init.main, "--apply")
        self.assertEqual(rc, 0, out)
        self.assertIn("backup.py all", out)


class TestYearEndFlag(Env):
    def test_ledger_roundtrip(self):
        self.assertIsNone(ledgers.year_end_pending())
        ledgers.mark_year_end("archive")
        self.assertEqual(ledgers.year_end_pending()["mode"], "archive")
        ledgers.clear_year_end()
        self.assertIsNone(ledgers.year_end_pending())

    def test_status_warns_first(self):
        ledgers.mark_year_end("photos")
        items = status.collect()
        self.assertEqual(items[0]["level"], status.URGENT)
        self.assertIn("學年已封存", items[0]["title"])
        self.assertIn("--new-roster", items[0]["todo"])

    def test_access_sync_apply_needs_new_roster(self):
        ledgers.mark_year_end("archive")
        with mock.patch.object(fr, "make_client", side_effect=AssertionError("安全閘要在連資料庫之前")):
            rc, out = self.run_main(access_sync.main, "--apply", "--emulator")
        self.assertEqual(rc, 2)
        self.assertIn("學年已封存", out)
        self.assertIn("--new-roster", out)
        self.assertIsNotNone(ledgers.year_end_pending(), "擋下來不收旗標")


class TestParentNoteSeat(Env):
    def test_draft_seat(self):
        self.assertEqual(parent_note.draft_seat("03-2026-10-01.md"), "03")
        self.assertEqual(parent_note.draft_seat("3-2026-10-01.md"), "03")
        self.assertIsNone(parent_note.draft_seat("2026-10-01-note.md"))
        self.assertIsNone(parent_note.draft_seat("note.md"))

    def test_mismatch_stops(self):
        d = fx.write(self.root / "data" / "exports" / "parent-notes" / "03-2026-10-01.md",
                     "---\nsubject: 〔孩子〕最近\n---\n〔孩子〕的家長您好：\n內容。\n")
        rc, out = self.run_main(parent_note.main, "--seat", "4", "--draft", str(d))
        self.assertEqual(rc, 2)
        self.assertIn("座號 03", out)
        rc, out = self.run_main(parent_note.main, "--seat", "3", "--draft", str(d))
        self.assertEqual(rc, 0, out)


class TestAuthCleanupFile(Env):
    def test_full_emails_only_in_file_and_merged(self):
        p = de.Plan("學生轉出（座號 03）")
        k1, k2 = email_key(fx.parent_mail(2)), email_key(fx.mail("parent2-c"))
        p.auth_keys = [k1, k2]
        f, missing = de.write_auth_file(p, "seat-03", {k1: fx.parent_mail(2), k2: fx.mail("parent2-c")})
        self.assertEqual(missing, 0)
        self.assertEqual(f.resolve(), (self.root / "data" / "exports" / "data-exit" / "seat-03-auth-cleanup.txt").resolve())
        text = f.read_text(encoding="utf-8")
        self.assertIn(fx.parent_mail(2), text)
        self.assertIn(fx.mail("parent2-c"), text)
        # 老師刪掉 contacts.csv 那幾列以後再預覽：已經抄下的信箱留著
        f, missing = de.write_auth_file(p, "seat-03", {})
        self.assertEqual(missing, 0)
        self.assertIn(fx.parent_mail(2), f.read_text(encoding="utf-8"))
        # 從來沒抄到的：只留遮住的
        q = de.Plan("x")
        q.auth_keys = [email_key(fx.mail("someone"))]
        f2, missing = de.write_auth_file(q, "seat-09", {})
        self.assertEqual(missing, 1)
        self.assertNotIn(fx.mail("someone"), f2.read_text(encoding="utf-8"))
        self.assertIsNone(de.write_auth_file(de.Plan("y"), "seat-10", {})[0], "沒有要刪的帳號就不寫檔")

    def test_contact_emails_keeps_typed_form(self):
        from lib.sources import contact_emails
        got = contact_emails(self.root / "data" / "contacts.csv")
        self.assertEqual(got[email_key(fx.parent_mail(0))], fx.parent_mail(0))
        self.assertEqual(contact_emails(self.root / "data" / "none.csv"), {})


class TestWhereOpenPath(Env):
    def test_opens_paths_inside_root_only(self):
        (self.root / "data" / "personal-photos").mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "inbox").mkdir(parents=True, exist_ok=True)
        fx.write(self.root / "exports" / "preview" / "post-x.html", "<p>x</p>")
        fx.write(self.root / "data" / "run.command", "echo x")
        opened = []
        with mock.patch.object(where, "open_target", side_effect=opened.append):
            rc, out = self.run_main(where.main, "--open", "data/personal-photos")
            self.assertEqual(rc, 0, out)
            rc, out = self.run_main(where.main, "--open", "exports/preview/post-x.html")
            self.assertEqual(rc, 0, out)
            rc, out = self.run_main(where.main, "--open", "data/run.command")
            self.assertEqual(rc, 2, "程式、指令檔不開")
            rc, out = self.run_main(where.main, "--open", "../outside")
            self.assertEqual(rc, 2)
            rc, out = self.run_main(where.main, "--open", "inbox")
            self.assertEqual(rc, 0, "名稱照舊可以用")
        self.assertEqual([Path(x).name for x in opened], ["personal-photos", "post-x.html", "inbox"])


class TestBackupHeartbeatWording(unittest.TestCase):
    def test_failed_backup_never_says_unaffected(self):
        class Ctx(object):
            def client(self):
                raise fr.FirestoreError(401, "UNAUTHENTICATED", "", "", "還沒登入", [])
        for ok, want in ((False, False), (True, True)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                backup.heartbeat(Ctx(), "weekly", ok)
            self.assertNotIn("不受影響", buf.getvalue())
            self.assertEqual("已經做好了" in buf.getvalue(), want)


class TestDenyLists(unittest.TestCase):
    def test_three_lists_block_the_same_paths(self):
        claude = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["deny"]
        from_claude = {x[len("Read("):-1] for x in claude if x.startswith("Read(")}

        def lines(name):
            return {x.strip() for x in (REPO / name).read_text(encoding="utf-8").splitlines()
                    if x.strip() and not x.strip().startswith("#")}
        self.assertEqual(from_claude, lines(".geminiignore"))
        self.assertEqual(from_claude, lines(".aiexclude"))
        for must in ("data/roster.csv", "data/contacts.csv", "exports/**", "data/exports/**", "data/records/**",
                     "data/ledgers/alias-history.jsonl"):
            self.assertIn(must, from_claude)
        # Read 的每一條都要有對應的終端機讀檔 deny（盡力而為的防呆：擋不住 python、type 之類，AGENTS.md 鐵則 5 照樣要守）
        bash = {x for x in claude if x.startswith("Bash(")}
        for p in from_claude:
            stem = p[:-2] if p.endswith("/**") else p
            for cmd in ("cat", "head", "tail", "sed", "grep"):
                self.assertIn("Bash(%s *%s*)" % (cmd, stem), bash)


if __name__ == "__main__":
    unittest.main()
