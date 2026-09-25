#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.1 後端模組的純函式與本機流程（不連網、不碰任何雲端；模擬器那一層在 scripts/test_functions.py）：

  · lib/notify.py：class.json 的 notifications 欄位、config/notify 的身分欄位、Functions 產生檔的值
  · notify_config.py：階段切換的規矩（live 一定先 dryrun＋排程有心跳、從 off 打開才寫起始線、開關、同步寄件人）
  · notify_setup.py：雲端檢查的判斷（假的回應）
  · docs_index.py：掃「班級文件」、保留人工類別、表格跳脫、學年學期（學期名稱照設定）、--check／--apply
  · publish_site.py：roster/links 兩個網址的檢查
  · publish_courses.py：課程頁與課表的寫法
  · parent_note.py：草稿、收件人、mailto（**螢幕輸出沒有姓名與信箱**）
"""
import io
import sys
import json
import shutil
import datetime
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock
from contextlib import redirect_stdout

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from lib import notify, paths, drivetree as dt  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
import notify_config as nc  # noqa: E402
import notify_setup as ns  # noqa: E402
import docs_index as di  # noqa: E402
import publish_site as ps  # noqa: E402
import publish_courses as pc  # noqa: E402
import parent_note as pn  # noqa: E402

AT = "@"
# Windows 的檔名不能有 |：那裡用別的名字，只在 Mac／Linux 驗「檔名裡的 | 要跳脫」
PIPE_NAME = "座位 草圖" if sys.platform.startswith("win") else "座位|草圖"


def quiet(fn, *a, **kw):
    buf = io.StringIO()
    with redirect_stdout(buf):
        r = fn(*a, **kw)
    return r, buf.getvalue()


def class_cfg(**notif):
    return {
        "class_name": "測試班", "teacher": {"email": "Wang.Teacher" + AT + "example.com", "display_name": "王老師"},
        "notifications": dict({"enabled": True}, **notif),
    }


class TestNotifyLib(unittest.TestCase):
    def test_identity_defaults_and_overrides(self):
        ident = notify.identity(class_cfg())
        self.assertEqual(ident["teacherEmail"], "Wang.Teacher" + AT + "example.com")
        self.assertEqual(ident["teacherKey"], "wang.teacher" + AT + "example.com")
        self.assertEqual(ident["fromEmail"], ident["teacherEmail"], "沒填 gmail_address＝用導師信箱寄")
        self.assertEqual(ident["senderName"], "王老師（測試班）")
        self.assertEqual(ident["signature"], "測試班 王老師")
        ident = notify.identity(class_cfg(sender_name="三年二班", signature="三年二班 王老師\n敬上",
                                          gmail_address="class.mail" + AT + "example.com"))
        self.assertEqual(ident["fromEmail"], "class.mail" + AT + "example.com")
        self.assertEqual(ident["senderName"], "三年二班")
        self.assertIn("\n", ident["signature"], "署名可以換行")

    def test_validate(self):
        self.assertEqual(notify.validate(class_cfg()), [])
        self.assertEqual(notify.validate({"notifications": {"enabled": False}}), [])
        self.assertEqual(notify.validate({}), [])
        for bad in ({"enabled": 1}, {"digest_hour": -1}, {"digest_hour": "7"}, {"time_zone": "Asia/Taipei x"},
                    {"gmail_address": "nope"}, {"sender_name": "a\rb"}, {"sender_name": "x" * 41}):
            self.assertTrue(notify.validate({"notifications": bad}), bad)

    def test_functions_values_have_no_email_and_follow_status(self):
        from lib import thresholds
        v = notify.functions_values(class_cfg(time_zone="Asia/Tokyo", digest_hour=6))
        self.assertEqual(v, {"NOTIFY_TIME_ZONE": "Asia/Tokyo", "NOTIFY_DIGEST_HOUR": 6,
                             "BACKUP_REMIND_DAYS": thresholds.BACKUP_REMIND_DAYS,
                             "BACKUP_URGENT_DAYS": thresholds.BACKUP_URGENT_DAYS})
        self.assertEqual(notify.functions_values({})["NOTIFY_TIME_ZONE"], notify.DEFAULT_TZ)
        self.assertNotIn(AT, json.dumps(v))

    def test_deploy_hints(self):
        self.assertIn("functions:secrets:set", notify.deploy_hint(["Error: secret CMW_GMAIL_APP_PASSWORD not found"]))
        self.assertIn("5 分鐘", notify.deploy_hint(["Permission denied while using the Eventarc Service Agent"]))
        self.assertIn("不要加 --force", notify.deploy_hint(["found in your project but do not exist in your local source"]))
        self.assertIsNone(notify.deploy_hint(["something else"]))


class TestNotifyConfigRules(unittest.TestCase):
    ident = notify.identity(class_cfg())

    def plan(self, current, sweep=5, **args):
        base = {"phase": None, "sync": False, "teacher-mail": None, "parent-mail": None, "digest": None}
        base.update(args)
        return nc.plan_changes(current, base, self.ident, sweep)

    def test_first_time_on_writes_floor_and_identity(self):
        f, p = self.plan(None, phase="dryrun")
        self.assertEqual(p, [])
        self.assertEqual(f["phase"], "dryrun")
        self.assertIs(f["notifyFloor"], fr.SERVER_TIME, "從 off 打開要寫起始線")
        self.assertTrue(f["teacherMail"] and f["parentMail"] and f["digest"])
        for k in nc.IDENTITY_FIELDS:
            self.assertEqual(f[k], self.ident[k])
        merged = {k: ("t" if v is fr.SERVER_TIME else v) for k, v in f.items()}
        self.assertEqual(nc.validate_doc(merged), [])

    def test_live_requires_dryrun_first(self):
        _, p = self.plan(None, phase="live")
        self.assertTrue(p and "dryrun" in p[0])
        _, p = self.plan({"phase": "off"}, phase="live")
        self.assertTrue(p)

    def test_live_requires_fresh_sweep_heartbeat(self):
        cur = dict(self.ident, phase="dryrun", notifyFloor="2026-01-01T00:00:00Z", teacherMail=True, parentMail=True, digest=True)
        _, p = self.plan(cur, sweep=None, phase="live")
        self.assertTrue(p and "排程" in p[0])
        _, p = self.plan(cur, sweep=notify.SWEEP_STALE_MINUTES + 1, phase="live")
        self.assertTrue(p)
        f, p = self.plan(cur, sweep=3, phase="live")
        self.assertEqual(p, [])
        self.assertEqual(f["phase"], "live")
        self.assertNotIn("notifyFloor", f, "dryrun → live 不重設起始線")

    def test_off_is_always_allowed_and_keeps_floor(self):
        cur = dict(self.ident, phase="live", notifyFloor="2026-01-01T00:00:00Z")
        f, p = self.plan(cur, sweep=None, phase="off")
        self.assertEqual((p, f["phase"]), ([], "off"))
        self.assertNotIn("notifyFloor", f)
        f, _ = self.plan(dict(cur, phase="off"), phase="dryrun")
        self.assertIs(f["notifyFloor"], fr.SERVER_TIME, "關掉再打開：起始線重設到現在")

    def test_toggles_and_noop(self):
        cur = dict(self.ident, phase="dryrun", notifyFloor="x", teacherMail=True, parentMail=True, digest=True)
        f, _ = self.plan(cur, **{"parent-mail": "off"})
        self.assertEqual(f["parentMail"], False)
        self.assertEqual(set(f) - {"updatedAt"}, {"parentMail"})
        f, _ = self.plan(cur, **{"digest": "on"})
        self.assertEqual(f, {}, "已經是這樣就不寫")
        f, _ = self.plan(cur, phase="dryrun")
        self.assertEqual(f, {})

    def test_sync_updates_identity(self):
        cur = dict(self.ident, phase="dryrun", notifyFloor="x", senderName="舊名字")
        f, _ = self.plan(cur, sync=True)
        self.assertEqual(f["senderName"], self.ident["senderName"])
        self.assertIn("updatedAt", f)

    def test_validate_doc_catches_bad_shapes(self):
        good = dict(self.ident, phase="dryrun", notifyFloor="t", teacherMail=True, parentMail=True, digest=True)
        self.assertEqual(nc.validate_doc(good), [])
        self.assertTrue(nc.validate_doc(dict(good, phase="maybe")))
        self.assertTrue(nc.validate_doc(dict(good, teacherEmail="nope")))
        self.assertTrue(nc.validate_doc(dict(good, extra=1)))
        self.assertTrue(nc.validate_doc(dict(good, notifyFloor=None)))

    def test_describe_masks_emails(self):
        lines = nc.describe({"teacherEmail": self.ident["teacherEmail"], "phase": "live", "notifyFloor": fr.SERVER_TIME})
        text = "\n".join(lines)
        self.assertNotIn(self.ident["teacherEmail"], text)
        self.assertIn("W***" + AT + "example.com", text)


class TestNotifySetupEval(unittest.TestCase):
    def test_secret(self):
        self.assertFalse(ns.eval_secret(404, None)["ok"])
        self.assertFalse(ns.eval_secret(200, {"versions": [{"state": "DESTROYED"}]})["ok"])
        self.assertTrue(ns.eval_secret(200, {"versions": [{"state": "ENABLED"}]})["ok"])
        self.assertIsNone(ns.eval_secret(403, None)["ok"])
        self.assertIn("不要貼給 AI 代理", ns.eval_secret(404, None)["todo"])

    def test_functions_listing(self):
        allf = {"functions": [{"name": "projects/p/locations/asia-east1/functions/%s" % n} for n in notify.FUNCTION_IDS]}
        self.assertTrue(ns.eval_functions(200, allf, "asia-east1")["ok"])
        some = {"functions": allf["functions"][:3]}
        it = ns.eval_functions(200, some, "asia-east1")
        self.assertFalse(it["ok"])
        self.assertIn("cmwNotifySweep", it["todo"])
        lower = {"functions": [{"name": "x/" + n.lower()} for n in notify.FUNCTION_IDS]}
        self.assertTrue(ns.eval_functions(200, lower, "asia-east1")["ok"], "大小寫不影響")

    def test_cleanup_and_heartbeats(self):
        self.assertTrue(ns.eval_cleanup(200, {"cleanupPolicies": {"firebase-functions-cleanup": {}}})["ok"])
        self.assertFalse(ns.eval_cleanup(200, {})["ok"])
        self.assertFalse(ns.eval_cleanup(404, None)["ok"])
        now = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.timezone.utc)
        items = ns.eval_heartbeats(None, {}, {}, now)
        self.assertFalse(items[0]["ok"])
        items = ns.eval_heartbeats({"phase": "dryrun"}, {"lastRunAt": "2026-10-01T11:55:00Z"}, {"lastRunAt": "2026-10-01T07:00:00Z"}, now)
        self.assertTrue(all(i["ok"] for i in items), items)
        items = ns.eval_heartbeats({"phase": "live"}, {"lastRunAt": "2026-10-01T09:00:00Z"}, {}, now)
        self.assertFalse(items[1]["ok"], "排程 3 小時沒跑＝沒在動")


class TempRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cmw-notify-"))
        self.root = self.tmp / "root"
        (self.root / "config").mkdir(parents=True)
        (self.root / "data").mkdir()

    def tearDown(self):
        paths.reset_root()
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def write_cfg(self, extra=None):
        cfg = json.loads((REPO / "config" / "class.example.json").read_text(encoding="utf-8"))
        cfg["teacher"]["email"] = "t" + AT + "example.com"
        cfg["firebase"].update({"project_id": "my-class-2026", "api_key": "k", "app_id": "a"})
        cfg.update(extra or {})
        (self.root / "config" / "class.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        return cfg


class TestDocsIndex(TempRoot):
    def make_tree(self, extra_cfg=None):
        sync = self.tmp / "drive" / "My Drive"
        sync.mkdir(parents=True)
        cf = "測試班 班級網站"
        for t in dt.tree_folders("2030-2031"):
            (sync / cf).joinpath(*t).mkdir(parents=True, exist_ok=True)
        (sync / cf / dt.MARKER_NAME).write_text(dt.marker_text(cf), encoding="utf-8")
        cfg = {"drive": {"sync_root": str(sync), "class_folder": cf}}
        cfg.update(extra_cfg or {})
        self.write_cfg(cfg)
        base = sync / cf / dt.CONF / dt.CLASS_DOCS
        files = {
            "通用文件/班級公約.pdf": b"x", "2030-2031/上學期/座談簡報.pptx": b"x", "2030-2031/上學期/%s.png" % PIPE_NAME: b"x",
            "會議紀錄/119學年 下學期/會議.docx": b"x", "會議紀錄/期初.gdoc": b"{}", "課程/.DS_Store": b"x",
            "課程/~$暫存.docx": b"x", "課程/範例單元/列印/講義.pdf": b"x",
        }
        for rel, data in files.items():
            p = base / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        return base

    def run_main(self, *args):
        return quiet(di.main, list(args) + ["--root", str(self.root)])

    def test_scan_classify_and_skip(self):
        base = self.make_tree()
        docs = {d["pos"]: d for d in di.scan(base)}
        self.assertEqual(len(docs), 6, sorted(docs))
        self.assertNotIn("課程/.DS_Store", docs)
        self.assertNotIn("課程/~$暫存.docx", docs)
        self.assertEqual((docs["通用文件/班級公約.pdf"]["term"], docs["通用文件/班級公約.pdf"]["cat"]), ("通用", "PDF"))
        d = docs["2030-2031/上學期/座談簡報.pptx"]
        self.assertEqual((d["year"], d["term"], d["cat"]), ("2030-2031", "上學期", "簡報"))
        d = docs["會議紀錄/119學年 下學期/會議.docx"]
        self.assertEqual((d["year"], d["term"], d["cat"]), ("119學年", "下學期", "文件"))
        self.assertEqual(docs["會議紀錄/期初.gdoc"]["cat"], "文件", "雲端硬碟的 Google 文件捷徑")

    def test_terms_come_from_config(self):
        three = ("第一學期", "第二學期", "第三學期")
        self.assertEqual(di.classify(("會議紀錄", "119學年 第二學期"), three), ("119學年", "第二學期"))
        self.assertEqual(di.classify(("2030-2031", "第三學期"), three), ("2030-2031", "第三學期"))
        self.assertEqual(di.classify(("會議紀錄", "119學年 第二學期")), ("119學年", ""), "預設的學期名稱裡沒有「第二學期」")
        self.assertEqual(di.classify(("第二學期活動",), three), ("", ""), "整段不等於學期名稱就不算")
        self.assertEqual(di.classify(("2031", "上學期"), start_month=1), ("2031", "上學期"))
        self.assertEqual(di.classify(("2031",)), ("", ""), "學年不是從一月開始時，四位數字不當學年")
        base = self.make_tree({"school_year": {"start_month": 9, "terms": list(three)}})
        (base / "2030-2031" / "第二學期").mkdir(parents=True)
        (base / "2030-2031" / "第二學期" / "期末成果發表.pdf").write_bytes(b"x")
        rc, out = self.run_main("--apply")
        self.assertEqual(rc, 0, out)
        text = (base / "index.md").read_text(encoding="utf-8")
        self.assertIn("| 期末成果發表.pdf | PDF | 2030-2031 | 第二學期 | 2030-2031/第二學期/期末成果發表.pdf |", text)
        self.assertIn("| 名稱 | 類別 | 學年 | 學期 | 位置 |", text)

    def test_term_aliases(self):
        aliases = {"第一學期": "上學期", "寒假後": "下學期"}
        self.assertEqual(di.classify(("119學年 第一學期",)), ("119學年", ""), "沒登記別名就不認")
        self.assertEqual(di.classify(("119學年 第一學期",), aliases=aliases), ("119學年", "上學期"))
        self.assertEqual(di.classify(("會議紀錄", "寒假後"), aliases=aliases), ("", "下學期"))
        self.assertEqual(di.classify(("第一學期活動",), aliases=aliases), ("", ""), "整段不等於別名就不算")
        self.assertEqual(di.term_of("下學期", dt.DEFAULT_TERMS, {"下學期": "上學期"}), "下學期", "學期名稱本身優先")
        self.assertEqual(di.term_of("第三學期", dt.DEFAULT_TERMS, {"第三學期": "不存在的學期"}), "",
                         "別名對到的學期不在 terms 裡就不算")
        base = self.make_tree({"school_year": {"term_aliases": {"上學期": ["第一學期"]}}})
        (base / "舊資料" / "第一學期").mkdir(parents=True)
        (base / "舊資料" / "第一學期" / "期初說明.pdf").write_bytes(b"x")
        rc, out = self.run_main("--apply")
        self.assertEqual(rc, 0, out)
        text = (base / "index.md").read_text(encoding="utf-8")
        self.assertIn("| 期初說明.pdf | PDF | — | 上學期 | 舊資料/第一學期/期初說明.pdf |", text)

    def test_apply_keeps_manual_category_and_check(self):
        base = self.make_tree()
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assertFalse((base / "index.md").exists(), "預覽不寫檔")
        for name in ("班級公約", "座談簡報", "座位", "會議", "講義"):
            self.assertNotIn(name, out, "螢幕上不印檔名")
        rc, out = self.run_main("--apply")
        text = (base / "index.md").read_text(encoding="utf-8")
        if "|" in PIPE_NAME:
            self.assertIn("座位\\|草圖.png", text, "檔名裡的 | 要跳脫，表格才不會壞")
        rc, out = self.run_main("--check")
        self.assertEqual(rc, 0, out)
        # 老師把一列的類別改掉，再把檔案搬到下學期：類別要跟著保留
        text = text.replace("| 座談簡報.pptx | 簡報 |", "| 座談簡報.pptx | 座談資料 |")
        (base / "index.md").write_text(text, encoding="utf-8")
        shutil.move(str(base / "2030-2031" / "上學期" / "座談簡報.pptx"), str(base / "2030-2031" / "下學期" / "座談簡報.pptx"))
        (base / "通用文件" / "新的.xlsx").write_bytes(b"x")
        rc, out = self.run_main("--check")
        self.assertEqual(rc, 1)
        rc, out = self.run_main("--apply")
        self.assertIn("新增 1 列", out)
        self.assertIn("移除 1 列", out)
        new = (base / "index.md").read_text(encoding="utf-8")
        self.assertIn("| 座談簡報.pptx | 座談資料 | 2030-2031 | 下學期 | 2030-2031/下學期/座談簡報.pptx |", new)
        self.assertIn("| 新的.xlsx | 表格 |", new)
        by_pos, _ = di.read_manual(new)
        self.assertEqual(by_pos["2030-2031/上學期/%s.png" % PIPE_NAME], "圖片")

    def test_missing_tree_stops(self):
        self.write_cfg()
        rc, out = self.run_main("--apply")
        self.assertEqual(rc, 2)
        self.assertIn("同步夾", out)


class TestPublishSite(unittest.TestCase):
    def test_plan(self):
        f, p = ps.plan(None, {"records_kit": None, "class_docs": "https://drive.google.com/file/d/abc/view"})
        self.assertEqual(p, [])
        self.assertEqual(f["classDocsIndexUrl"], "https://drive.google.com/file/d/abc/view")
        self.assertEqual(f["recordsKitUrl"], "", "第一次寫要補另一欄的空字串（規則與前端都認得）")
        f, p = ps.plan({"recordsKitUrl": "https://example.com/r", "classDocsIndexUrl": ""},
                       {"records_kit": "", "class_docs": None})
        self.assertEqual(set(f), {"recordsKitUrl", "updatedAt"})
        for bad in ("http://example.com", "javascript:alert(1)", "https://exa mple.com", "https://" + "x" * 600):
            _, p = ps.plan(None, {"records_kit": bad, "class_docs": None})
            self.assertTrue(p, bad)
        f, p = ps.plan({"recordsKitUrl": "https://example.com/r"}, {"records_kit": "https://example.com/r", "class_docs": None})
        self.assertEqual(f, {})


class TestPublishCourses(TempRoot):
    def md(self, name, text):
        p = self.root / "data" / "courses" / (name + ".md")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def build(self, name):
        self.write_cfg()
        paths.set_root(str(self.root))
        return pc.build(name, None)

    def test_course_page(self):
        self.md("courses-term", "---\ntitle: 本學期課程\norder: 1\n---\n這學期的課程單元是範例單元。\n\n## 課程說明影片\n"
                "[[video:https://www.youtube.com/watch?v=abcdefghijk|第一週導覽]]\n\n## 各科課程大綱\n### 英文（王老師）\n"
                "讀三本繪本、唱英文歌。\n網址：https://drive.google.com/file/d/abc/view\n\n### 美術\n做一本小書。\n\n## 其他標題\n算正文。\n")
        d = self.build("courses-term")
        path, doc, kind = d.docs[0]
        self.assertEqual((path, kind, doc["kind"], doc["order"]), ("pages/courses-term", "page", "course", 1))
        self.assertEqual(doc["data"]["videos"], [{"url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "第一週導覽"}])
        self.assertEqual(doc["data"]["cards"], [
            {"title": "英文（王老師）", "text": "讀三本繪本、唱英文歌。", "url": "https://drive.google.com/file/d/abc/view"},
            {"title": "美術", "text": "做一本小書。"}])
        text = json.dumps(doc["blocks"], ensure_ascii=False)
        self.assertIn("範例單元", text)
        self.assertIn("其他標題", text)
        self.assertNotIn("繪本", text, "大綱卡不會重複出現在正文")
        d.validate()

    def test_schedule(self):
        self.md("schedule", "---\ntitle: 課表\n---\n| 節次 | 一 | 二 |\n|---|---|---|\n| 第一節 | 國語 | 數學 |\n| 第二節 | 英文 | 音樂 |\n")
        d = self.build("schedule")
        doc = d.docs[0][1]
        self.assertEqual(doc["kind"], "schedule")
        self.assertEqual(doc["data"]["rows"], [{"cells": ["節次", "一", "二"]}, {"cells": ["第一節", "國語", "數學"]},
                                               {"cells": ["第二節", "英文", "音樂"]}])
        d.validate()

    def test_errors(self):
        self.md("schedule-x", "---\ntitle: 課表\n---\n這不是表格\n")
        with self.assertRaises(pc.pub.PublishError):
            self.build("schedule-x")
        self.md("courses-a", "---\ntitle: 課\n---\n## 各科課程大綱\n沒有科目標題\n")
        with self.assertRaises(pc.pub.PublishError):
            self.build("courses-a")
        self.md("courses-b", "---\ntitle: 課\n---\n## 各科課程大綱\n### 英文\n" + "字" * 301 + "\n")
        with self.assertRaises(pc.pub.PublishError):
            self.build("courses-b")
        with self.assertRaises(pc.pub.PublishError):
            self.build("about")


class TestParentNote(TempRoot):
    def setUp(self):
        super().setUp()
        self.write_cfg()
        d = self.root / "data"
        (d / "roster.csv").write_text("座號,姓名,稱呼,備註\n3,測試全名甲,小甲,\n4,測試全名乙,小乙,\n", encoding="utf-8")
        (d / "contacts.csv").write_text(
            "座號,關係,姓名,Email,私密讀者,暫停,備註\n"
            "3,母,家長甲母,mom.three" + AT + "example.com,,,\n"
            "3,父,家長甲父,dad.three" + AT + "example.com,,,\n"
            "3,祖母,家長甲祖母,grandma.three" + AT + "example.com,,是,\n"
            "4,母,家長乙母,mom.four" + AT + "example.com,,,\n"
            ",同仁,同事,staff.one" + AT + "example.com,,,\n", encoding="utf-8")
        self.draft = d / "exports" / "parent-notes" / "03-2026-10-01.md"
        self.draft.parent.mkdir(parents=True)
        self.draft.write_text("---\nsubject: 〔孩子〕最近在學校的情形\n---\n〔孩子〕的家長您好：\n\n這陣子在學校看到〔孩子〕：\n"
                              "他這週在課堂上畫了一張很仔細的圖。\n", encoding="utf-8")

    def run_main(self, *args):
        return quiet(pn.main, list(args) + ["--root", str(self.root)])

    def test_preview_has_no_names_or_full_emails(self):
        with mock.patch.object(pn, "open_with_system", side_effect=AssertionError("預覽不准打開")):
            rc, out = self.run_main("--seat", "3", "--draft", str(self.draft))
        self.assertEqual(rc, 0, out)
        for secret in ("小甲", "測試全名甲", "家長甲母", "mom.three" + AT, "dad.three" + AT, "grandma"):
            self.assertNotIn(secret, out)
        self.assertIn("收件 2 位", out, "暫停的祖母不算、同仁不算")
        self.assertIn("m***" + AT + "example.com", out)

    def test_open_fills_name_and_recipients(self):
        opened = []
        with mock.patch.object(pn, "open_with_system", side_effect=opened.append):
            rc, out = self.run_main("--seat", "03", "--draft", str(self.draft), "--to", "母", "--open")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(opened), 1)
        url = opened[0]
        self.assertTrue(url.startswith("mailto:mom.three" + AT + "example.com?"), url[:60])
        q = urllib.parse.parse_qs(url.split("?", 1)[1])
        self.assertEqual(q["subject"], ["小甲最近在學校的情形"])
        self.assertIn("小甲的家長您好：\r\n", q["body"][0])
        self.assertNotIn("〔孩子〕", q["body"][0])
        self.assertNotIn("小甲", out, "名字只進郵件程式，不進螢幕輸出")

    def test_long_body_falls_back_to_text_file(self):
        self.draft.write_text("---\nsubject: 分享\n---\n〔孩子〕的家長您好：\n" + "很長的內容。" * 500 + "\n", encoding="utf-8")
        opened = []
        with mock.patch.object(pn, "open_with_system", side_effect=opened.append), \
                mock.patch.dict(pn.URL_LIMIT, {pn.hostos.OS: 2000}):
            rc, out = self.run_main("--seat", "3", "--draft", str(self.draft), "--open")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(opened), 2)
        self.assertNotIn("body=", opened[0])
        txt = Path(opened[1]).read_text(encoding="utf-8")
        self.assertTrue(txt.startswith("小甲的家長您好："))

    def test_errors(self):
        rc, out = self.run_main("--seat", "5", "--draft", str(self.draft))
        self.assertEqual(rc, 2)
        rc, out = self.run_main("--seat", "3", "--draft", str(self.draft), "--to", "姑姑")
        self.assertEqual(rc, 2)
        self.draft.write_text("沒有檔頭\n", encoding="utf-8")
        rc, out = self.run_main("--seat", "3", "--draft", str(self.draft))
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
