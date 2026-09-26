#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""開工狀態檢查（scripts/status.py）與「我的資料在哪」（scripts/where.py）：每一項判斷的純函式、整體不連網、不寫檔。"""
import io
import sys
import json
import shutil
import tempfile
import datetime
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
import status  # noqa: E402
import where  # noqa: E402
import admin_support as fx  # noqa: E402
from lib import paths, ledgers  # noqa: E402
from lib import drivetree as dt  # noqa: E402

NOW = datetime.datetime(2026, 10, 20, 12, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))


def ago(days):
    return (NOW - datetime.timedelta(days=days)).isoformat()


class TestPure(unittest.TestCase):
    def test_backup_thresholds(self):
        self.assertEqual(status.backup_item("firestore", None, NOW)["level"], status.WARN)
        self.assertEqual(status.backup_item("firestore", {"last_ok": ago(3)}, NOW)["level"], status.OK)
        self.assertEqual(status.backup_item("records", {"last_ok": ago(7)}, NOW)["level"], status.WARN)
        u = status.backup_item("blogs", {"last_ok": ago(14.5)}, NOW)
        self.assertEqual(u["level"], status.URGENT)
        self.assertIn("14 天", u["title"])
        self.assertEqual(u["playbook"], "playbooks/backup.md")
        f = status.backup_item("firestore", {"last_ok": ago(2), "last_fail": ago(1), "last_error": "網路斷了"}, NOW)
        self.assertEqual(f["level"], status.WARN)
        self.assertIn("網路斷了", f["title"])
        ok = status.backup_item("firestore", {"last_ok": ago(1), "last_fail": ago(2)}, NOW)
        self.assertEqual(ok["level"], status.OK, "失敗之後又成功就不算")

    def test_names(self):
        t = NOW - datetime.timedelta(days=1)
        self.assertEqual(status.names_item({}, None)["level"], status.INFO)
        self.assertEqual(status.names_item({"roster.csv": t}, None)["level"], status.WARN)
        self.assertEqual(status.names_item({"roster.csv": t}, NOW)["level"], status.OK)
        w = status.names_item({"roster.csv": t, "contacts.csv": NOW}, t + datetime.timedelta(hours=1))
        self.assertEqual(w["level"], status.WARN)
        self.assertIn("contacts.csv", w["title"])
        self.assertNotIn("roster.csv", w["title"])

    def test_inbox(self):
        self.assertEqual([i["level"] for i in status.inbox_item(0, 0)], [status.OK])
        items = status.inbox_item(3, 2)
        self.assertEqual([i["level"] for i in items], [status.WARN, status.INFO])
        self.assertEqual(items[0]["playbook"], "playbooks/archive-media.md")

    def test_capacity(self):
        gib = 1024 ** 3
        self.assertEqual(status.capacity_item(None)["level"], status.INFO)
        self.assertEqual(status.capacity_item(int(gib * 0.69))["level"], status.OK)
        self.assertEqual(status.capacity_item(int(gib * 0.70) + 1)["level"], status.WARN)
        self.assertEqual(status.capacity_item(int(gib * 0.95))["level"], status.URGENT)

    def test_orphans(self):
        self.assertIsNone(status.orphan_item(None))
        self.assertIsNone(status.orphan_item({"count": 0, "bytes": 0, "seats": {}}))
        it = status.orphan_item({"count": 3, "bytes": 3 * 1024 * 1024,
                                 "seats": {"05": {"count": 2, "bytes": 1, "posts": ["2026-10-05-a***"]},
                                           "07": {"count": 1, "bytes": 1, "posts": []}}}, "20261001-120000")
        self.assertEqual(it["level"], status.WARN)
        self.assertIn("座號 05 2 份", it["title"])
        self.assertIn("座號 07 1 份", it["title"])
        self.assertEqual(it["playbook"], "playbooks/data-exit.md")

    def test_orphans_shown_from_last_backup(self):
        tmp = Path(tempfile.mkdtemp(prefix="cmw-st-o-"))
        try:
            root = fx.make_root(tmp / "root", photos=False, n=3)
            paths.set_root(root)
            ledgers.mark_ok("firestore", snapshot="20261001-120000",
                            orphans={"count": 4, "bytes": 2048, "seats": {"05": {"count": 4, "bytes": 2048, "posts": []}}})
            with mock.patch.object(status.hostos, "find_exe_all", return_value=[("/x", True)]):
                items = status.collect(NOW)
            self.assertTrue(any("孤兒照片 4 份" in i["title"] for i in items))
        finally:
            paths.reset_root()
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_tools(self):
        self.assertEqual([i["level"] for i in status.tools_items(True, True, True)], [status.OK])
        miss = status.tools_items(False, True, False)
        self.assertEqual(len(miss), 2)
        self.assertTrue(all("doctor.py" in i["todo"] for i in miss))


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cmw-st-"))
        self.root = self.tmp / "root"

    def tearDown(self):
        paths.reset_root()
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def out(self, mod, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = mod.main(list(args) + ["--root", str(self.root)])
        return rc, buf.getvalue()


class TestCollect(Env):
    def test_empty_folder(self):
        self.root.mkdir()
        paths.set_root(self.root)
        items = status.collect(NOW)
        self.assertEqual(items[0]["level"], status.URGENT)
        rc, out = self.out(status)
        self.assertEqual(rc, 0)
        self.assertIn("AGENTS.md", out)

    def test_installed_class(self):
        fx.make_root(self.root, photos=False, n=3)
        sync = self.tmp / "My Drive"
        sync.mkdir()
        dt.build_tree(sync, "示範班級 班級網站")
        cfg = fx.config()
        cfg["drive"] = {"sync_root": str(sync), "class_folder": "示範班級 班級網站"}
        fx.write(self.root / "config" / "class.json", json.dumps(cfg, ensure_ascii=False))
        (self.root / "data" / "inbox").mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "inbox" / "a.jpg").write_bytes(b"1")
        (self.root / "data" / "inbox" / "README.md").write_text("說明", encoding="utf-8")
        paths.set_root(self.root)
        ledgers.mark_access_sync()
        before = sorted(p.as_posix() for p in self.root.rglob("*"))
        with mock.patch.object(status.hostos, "find_exe_all", return_value=[("/x", True)]):
            rc, out = self.out(status)
        self.assertEqual(rc, 0)
        self.assertIn("雲端硬碟同步夾與資料夾樹都在", out)
        self.assertIn("data/inbox/ 有 1 個檔", out)
        self.assertIn("網站資料庫備份：還沒有成功過", out)
        self.assertNotIn("學生 A", out)
        self.assertEqual(sorted(p.as_posix() for p in self.root.rglob("*")), before, "status.py 不寫任何檔")
        shutil.rmtree(str(sync / "示範班級 班級網站" / dt.SITE))
        rc, out = self.out(status)
        self.assertIn("drive_init.py --apply", out)

    def test_estimate_bytes(self):
        from lib import fsbackup as fsb
        base = self.tmp / "fs"
        ex = fsb.Export()
        ex.docs = [{"path": "posts/p", "fields": {}, "createTime": "", "updateTime": ""}]
        pool = fsb.Pool(base / "photos")
        key = fsb.pool_key("posts/p/images/a", "t")
        pool.save({"path": "posts/p/images/a", "fields": {"data": {"stringValue": "x" * 1000}}}, key)
        d, _ = fsb.write_snapshot(base, "20261001-000000", "demo-x", ex,
                                  [{"path": "posts/p/images/a", "updateTime": "t", "key": key, "md5": "m"},
                                   {"path": "posts/p/images/b", "updateTime": "t", "key": "0" * 32 + "-" + "0" * 8, "md5": "m"}])
        est = status.estimate_bytes(d)
        one = (base / "photos" / (key + ".json")).stat().st_size
        self.assertEqual(est, (d / "documents.jsonl").stat().st_size + 2 * one + 1280 * 3, "缺的照片用平均補")
        self.assertIsNone(status.estimate_bytes(self.tmp / "none"))


class TestWhere(Env):
    def test_prints_everything_and_open_names(self):
        fx.make_root(self.root, photos=False, n=2)
        sync = self.tmp / "My Drive"
        sync.mkdir()
        dt.build_tree(sync, "示範班級 班級網站")
        cfg = fx.config(project="my-class-2026")
        cfg["drive"] = {"sync_root": str(sync), "class_folder": "示範班級 班級網站"}
        fx.write(self.root / "config" / "class.json", json.dumps(cfg, ensure_ascii=False))
        rc, out = self.out(where)
        self.assertEqual(rc, 0)
        self.assertIn("https://my-class-2026.firebaseapp.com", out)
        self.assertIn("console.firebase.google.com/project/my-class-2026", out)
        self.assertIn("課堂檔案", out)
        self.assertIn("（media）", out)
        rc, out = self.out(where, "--list-names")
        self.assertIn("blog_archive", out)
        self.assertIn("inbox", out)
        rc, out = self.out(where, "--open", "沒有這個")
        self.assertEqual(rc, 2)
        with mock.patch.object(where, "open_target") as op:
            rc, out = self.out(where, "--open", "media")
        self.assertEqual(rc, 0)
        op.assert_called_once()
        self.assertEqual(Path(op.call_args[0][0]), sync / "示範班級 班級網站" / dt.CONF / dt.MEDIA)

    def test_not_configured(self):
        self.root.mkdir()
        rc, out = self.out(where)
        self.assertEqual(rc, 0)
        self.assertIn("drive_init.py", out)


if __name__ == "__main__":
    unittest.main()
