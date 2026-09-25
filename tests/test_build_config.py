#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_config.py 的測試：範本值拒跑、email 注入被擋、渲染正確、--check 不寫檔、
公開設定檔只含公開欄位、authDomain 預設、行事曆私人網址被擋。

大部分用 subprocess 直接跑這支 CLI（--root 指到一個暫存資料夾），驗真正的退出碼與輸出訊息——
這樣測的是「老師或代理實際會跑的那條指令」。只有 compute_values() 的 email 鍵正規化用 import 驗。
"""
import os
import sys
import json
import tempfile
import unittest
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AT = "@"


def run_build_config(root, *extra_args):
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "build_config.py"), "--root", str(root), *extra_args]
    return subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)


class TestBuildConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _example(self):
        example_path = REPO_ROOT / "config" / "class.example.json"
        return json.loads(example_path.read_text(encoding="utf-8"))

    def _write_class_json(self, cfg):
        cfg_dir = self.root / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "class.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    def test_no_class_json_fails_with_friendly_error(self):
        r = run_build_config(self.root, "--check")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("class.example.json", r.stdout)
        self.assertFalse((self.root / "site").exists())
        self.assertFalse((self.root / ".firebaserc").exists())

    def test_allow_placeholders_check_passes(self):
        r = run_build_config(self.root, "--check", "--allow-placeholders")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_check_never_writes_files(self):
        run_build_config(self.root, "--check", "--allow-placeholders")
        self.assertFalse((self.root / "site" / "js" / "site-config.js").exists())
        self.assertFalse((self.root / ".firebaserc").exists())

    def test_render_with_allow_placeholders_creates_expected_files(self):
        r = run_build_config(self.root, "--allow-placeholders")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out_js = self.root / "site" / "js" / "site-config.js"
        out_rc = self.root / ".firebaserc"
        self.assertTrue(out_js.exists())
        self.assertTrue(out_rc.exists())

        js_text = out_js.read_text(encoding="utf-8")
        self.assertIn("window.SITE_CONFIG", js_text)
        self.assertNotIn("{{", js_text)
        self.assertIn('"我的班級"', js_text)

        rc_json = json.loads(out_rc.read_text(encoding="utf-8"))
        self.assertIn("projects", rc_json)
        self.assertIn("default", rc_json["projects"])

    def test_email_injection_rejected(self):
        cfg = self._example()
        cfg["teacher"]["email"] = "x'||true||'@gmail.com"
        self._write_class_json(cfg)
        r = run_build_config(self.root, "--check")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("teacher.email", r.stdout)
        self.assertFalse((self.root / "site").exists())

    def test_email_injection_with_pipe_and_quote_rejected_even_with_placeholders(self):
        # 網域故意用 example.com：這是唯一被 privacy_scan 放行的網域，這個測試檔本身
        # 也會被 privacy_scan 掃到（見 tests/test_privacy_scan.py 檔頭的說明），
        # 用 example.com 才不會讓這一行變成「repo 裡的真實 email 洩漏」。
        cfg = self._example()
        cfg["teacher"]["email"] = "a@example.com'||true||'"
        self._write_class_json(cfg)
        r = run_build_config(self.root, "--check", "--allow-placeholders")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_project_id_format_rejected(self):
        cfg = self._example()
        cfg["teacher"]["email"] = "wang@example.com"
        cfg["firebase"]["project_id"] = "My_Project!"
        self._write_class_json(cfg)
        r = run_build_config(self.root, "--check", "--allow-placeholders")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("project_id", r.stdout)

    def test_students_count_out_of_range(self):
        cfg = self._example()
        cfg["students"]["count"] = 0
        self._write_class_json(cfg)
        r = run_build_config(self.root, "--check", "--allow-placeholders")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("students.count", r.stdout)

    def test_valid_full_config_passes_without_allow_placeholders(self):
        # 這裡的假值刻意避開 privacy_scan 會抓的形狀（AIza 開頭、Google 長 ID、非
        # example.com 的 email……）——這個測試檔本身也會被 privacy_scan 掃到。
        cfg = self._example()
        cfg["teacher"]["email"] = "wang@example.com"
        cfg["firebase"]["project_id"] = "my-class-2026"
        cfg["firebase"]["api_key"] = "test-firebase-api-key-value"
        cfg["firebase"]["messaging_sender_id"] = "000000000000"
        cfg["firebase"]["app_id"] = "test-app-id-value"
        self._write_class_json(cfg)
        r = run_build_config(self.root, "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # ── 公開設定檔只放公開欄位 ────────────────────────────────────────────
    def _full_cfg(self):
        cfg = self._example()
        cfg["class_name"] = "測試班"
        cfg["school_name"] = "測試學校名稱"
        cfg["teacher"]["email"] = "Wang.Teacher" + AT + "example.com"
        cfg["teacher"]["display_name"] = "測試稱呼"
        cfg["students"]["count"] = 23
        cfg["region"] = "asia-east1"
        cfg["firebase"]["project_id"] = "my-class-2026"
        cfg["firebase"]["api_key"] = "test-firebase-api-key-value"
        cfg["firebase"]["app_id"] = "test-app-id-value"
        cfg["calendar_ics_url"] = "https://calendar.example.com/ical/abc/public/basic.ics"
        cfg["notifications"]["enabled"] = False
        return cfg

    def test_public_config_has_no_private_values(self):
        self._write_class_json(self._full_cfg())
        r = run_build_config(self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        js = (self.root / "site" / "js" / "site-config.js").read_text(encoding="utf-8")
        body = js.split("window.SITE_CONFIG", 1)[1]   # 檔頭註解可以提到欄位名，內容不行
        for leaked in ("wang.teacher", "Wang.Teacher", "測試學校名稱", "測試稱呼", "23",
                       "calendar.example.com", "asia-east1", "teacherEmail", "schoolName",
                       "studentsCount", "calendarIcsUrl", "notificationsEnabled", "region",
                       "storageBucket"):
            with self.subTest(leaked=leaked):
                self.assertNotIn(leaked, body)
        for kept in ('"測試班"', '"my-class-2026"', '"test-firebase-api-key-value"', "categories", "pages"):
            with self.subTest(kept=kept):
                self.assertIn(kept, body)

    def test_auth_domain_defaults_to_firebaseapp(self):
        self._write_class_json(self._full_cfg())
        r = run_build_config(self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        js = (self.root / "site" / "js" / "site-config.js").read_text(encoding="utf-8")
        self.assertIn('authDomain: "my-class-2026.firebaseapp.com"', js)
        self.assertIn('siteUrl: "https://my-class-2026.firebaseapp.com"', js)
        self.assertNotIn("web.app", js)

    def test_auth_domain_other_than_firebaseapp_rejected(self):
        for bad in ("my-class-2026.web.app", "class.example.com"):
            with self.subTest(bad=bad):
                cfg = self._full_cfg()
                cfg["firebase"]["auth_domain"] = bad
                self._write_class_json(cfg)
                r = run_build_config(self.root, "--check")
                self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("auth_domain", r.stdout)

    def test_auth_domain_explicit_firebaseapp_ok(self):
        cfg = self._full_cfg()
        cfg["firebase"]["auth_domain"] = "my-class-2026.firebaseapp.com"
        self._write_class_json(cfg)
        r = run_build_config(self.root, "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_private_ical_url_rejected(self):
        cfg = self._full_cfg()
        cfg["calendar_ics_url"] = "https://calendar.example.com/calendar/ical/abc/private-0123abcd/basic.ics"
        self._write_class_json(cfg)
        r = run_build_config(self.root, "--check")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("calendar_ics_url", r.stdout)
        self.assertNotIn("0123abcd", r.stdout)   # 不把私人網址的金鑰印出來

    def test_non_https_calendar_rejected(self):
        for bad in ("http://calendar.example.com/public/basic.ics", "webcal://calendar.example.com/public/basic.ics"):
            with self.subTest(bad=bad):
                cfg = self._full_cfg()
                cfg["calendar_ics_url"] = bad
                self._write_class_json(cfg)
                r = run_build_config(self.root, "--check")
                self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_school_year_validated(self):
        for sy in ({"start_month": 9, "terms": ["第一學期", "第二學期", "第三學期"]}, {"start_month": 2}, None,
                   {"terms": ["學段一", "學段二"], "term_aliases": {"學段一": ["第一學期"]}}, {"term_aliases": {}}):
            with self.subTest(ok=sy):
                cfg = self._full_cfg()
                cfg.pop("school_year", None)
                if sy is not None:
                    cfg["school_year"] = sy
                self._write_class_json(cfg)
                r = run_build_config(self.root, "--check")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for sy in ({"start_month": 13}, {"terms": []}, {"terms": ["上/下"]}, {"terms": ["上學期", "上學期"]}, "8月",
                   {"term_aliases": {"第三學期": ["學段三"]}}, {"term_aliases": {"上學期": ["下學期"]}}):
            with self.subTest(bad=sy):
                cfg = self._full_cfg()
                cfg["school_year"] = sy
                self._write_class_json(cfg)
                r = run_build_config(self.root, "--check")
                self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("school_year", r.stdout)

    def test_leftover_storage_bucket_is_only_a_note(self):
        cfg = self._full_cfg()
        cfg["firebase"]["storage_bucket"] = "my-class-2026-bucket"
        self._write_class_json(cfg)
        r = run_build_config(self.root, "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("storage_bucket", r.stdout)

    def test_public_template_using_private_key_refused(self):
        self._write_class_json(self._full_cfg())
        tdir = self.root / "templates"
        tdir.mkdir(parents=True)
        (tdir / "manifest.json").write_text(json.dumps({"templates": [
            {"src": "leak.js.tmpl", "dest": "site/js/leak.js", "public": True}]}), encoding="utf-8")
        (tdir / "leak.js.tmpl").write_text("window.X = {{TEACHER_EMAIL_KEY}};\n", encoding="utf-8")
        r = run_build_config(self.root)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("TEACHER_EMAIL_KEY", r.stdout)
        self.assertFalse((self.root / "site" / "js" / "leak.js").exists())

    def test_non_public_template_may_use_teacher_key(self):
        self._write_class_json(self._full_cfg())
        tdir = self.root / "templates"
        tdir.mkdir(parents=True)
        (tdir / "manifest.json").write_text(json.dumps({"templates": [
            {"src": "rules.tmpl", "dest": "firestore.rules", "public": False}]}), encoding="utf-8")
        (tdir / "rules.tmpl").write_text("teacher = {{TEACHER_EMAIL_KEY}};\n", encoding="utf-8")
        r = run_build_config(self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = (self.root / "firestore.rules").read_text(encoding="utf-8")
        self.assertEqual(out, 'teacher = "wang.teacher' + AT + 'example.com";\n')

    # ── Windows 記事本的 BOM（A3）與 v1.1 通知信模組的產生檔 ──────────────────────
    def test_class_json_with_bom_is_read(self):
        cfg_dir = self.root / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        # 記事本「UTF-8（含 BOM）」存出來的樣子：檔頭多三個位元組 EF BB BF
        (cfg_dir / "class.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(self._full_cfg(), ensure_ascii=False).encode("utf-8"))
        r = run_build_config(self.root, "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = run_build_config(self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.root / ".firebaserc").exists())

    def test_classcfg_and_build_config_agree_on_bom(self):
        # 管理腳本（lib/classcfg.py）與 build_config.py 讀同一份含 BOM 的檔，兩邊都要讀得懂
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from lib import classcfg, paths
        cfg_dir = self.root / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "class.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(self._full_cfg(), ensure_ascii=False).encode("utf-8"))
        paths.set_root(str(self.root))
        try:
            self.assertEqual(classcfg.load().project_id, "my-class-2026")
        finally:
            paths.reset_root()

    def test_functions_config_generated_without_any_email(self):
        cfg = self._full_cfg()
        cfg["notifications"] = {"enabled": True, "sender_name": "王老師", "gmail_address": "class.mail" + AT + "example.com",
                                "time_zone": "Asia/Taipei", "digest_hour": 6}
        self._write_class_json(cfg)
        r = run_build_config(self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("playbooks/notify.md", r.stdout)
        p = self.root / "functions" / "cmw.generated.json"
        text = p.read_text(encoding="utf-8")
        got = json.loads(text)
        self.assertEqual(got["format"], 1)
        self.assertEqual(got["projectId"], "my-class-2026")
        self.assertEqual(got["region"], "asia-east1")
        self.assertEqual(got["siteUrl"], "https://my-class-2026.firebaseapp.com")
        self.assertEqual((got["timeZone"], got["digestHour"]), ("Asia/Taipei", 6))
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from lib import thresholds
        import status
        self.assertEqual((got["backupRemindDays"], got["backupUrgentDays"]),
                         (thresholds.BACKUP_REMIND_DAYS, thresholds.BACKUP_URGENT_DAYS))
        self.assertEqual((status.REMIND_DAYS, status.URGENT_DAYS), (got["backupRemindDays"], got["backupUrgentDays"]),
                         "每日摘要與 status.py 的備份門檻要同一組")
        self.assertNotIn(AT, text, "Functions 的產生檔不放任何信箱")

    def test_notifications_fields_validated(self):
        for bad in ({"enabled": "yes"}, {"digest_hour": 24}, {"digest_hour": True}, {"time_zone": "Asia/Taipei; rm"},
                    {"gmail_address": "not-an-email"}, {"sender_name": "a\nb"}, {"signature": "x" * 301}):
            cfg = self._full_cfg()
            cfg["notifications"] = dict({"enabled": False}, **bad)
            self._write_class_json(cfg)
            r = run_build_config(self.root, "--check")
            self.assertNotEqual(r.returncode, 0, "%r 應該被擋：%s" % (bad, r.stdout))
            self.assertIn("notifications", r.stdout)
        cfg = self._full_cfg()
        cfg["notifications"] = {"enabled": False}
        self._write_class_json(cfg)
        r = run_build_config(self.root, "--check")
        self.assertEqual(r.returncode, 0, "只寫 enabled 的舊設定檔也要能用：" + r.stdout)

    def test_real_manifest_marks_site_config_public(self):
        manifest = json.loads((REPO_ROOT / "templates" / "manifest.json").read_text(encoding="utf-8"))
        entries = {e["dest"]: e for e in manifest["templates"]}
        self.assertTrue(entries["site/js/site-config.js"].get("public"))

    # ── --emulator（模擬器冒煙測試用） ─────────────────────────────────────
    def test_emulator_switches_to_demo_project(self):
        self._write_class_json(self._full_cfg())
        r = run_build_config(self.root, "--emulator")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        js = (self.root / "site" / "js" / "site-config.js").read_text(encoding="utf-8")
        self.assertIn("emulator: true", js)
        self.assertIn('projectId: "demo-cmw"', js)
        self.assertNotIn("my-class-2026", js, "--emulator 不能留著真的專案 id")
        rc = json.loads((self.root / ".firebaserc").read_text(encoding="utf-8"))
        self.assertEqual(rc["projects"]["default"], "demo-cmw")

    def test_emulator_accepts_placeholders_and_keeps_demo_ids(self):
        cfg = self._example()
        cfg["firebase"]["project_id"] = "demo-other"
        self._write_class_json(cfg)
        r = run_build_config(self.root, "--emulator")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        js = (self.root / "site" / "js" / "site-config.js").read_text(encoding="utf-8")
        self.assertIn('projectId: "demo-other"', js)
        self.assertIn('apiKey: "demo-api-key"', js)

    def test_emulator_refuses_to_write_into_repo(self):
        # 沒給 --root（＝這份 repo 本身）就拒跑，而且在寫任何檔之前就停
        cmd = [sys.executable, str(REPO_ROOT / "scripts" / "build_config.py"), "--emulator", "--check"]
        env = dict(os.environ)
        env.pop("CMW_ROOT", None)
        r = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60, env=env)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("--root", r.stdout)

    def test_normal_build_is_not_emulator(self):
        self._write_class_json(self._full_cfg())
        r = run_build_config(self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        js = (self.root / "site" / "js" / "site-config.js").read_text(encoding="utf-8")
        self.assertIn("emulator: false", js)


class TestComputeValues(unittest.TestCase):
    """import 進來直接驗 compute_values()：導師 email 鍵與 lib/emailkey.py 同一套正規化。"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import build_config  # noqa: E402
        cls.bc = build_config

    def _cfg(self, email):
        return {"class_name": "x", "teacher": {"email": email},
                "firebase": {"project_id": "my-class-2026"}}

    def test_teacher_key_is_normalized_gmail(self):
        v = self.bc.compute_values(self._cfg(" T.Eacher" + AT + "GoogleMail.com "))
        self.assertEqual(v["TEACHER_EMAIL_KEY"], "teacher" + AT + "gmail.com")

    def test_teacher_key_keeps_dots_elsewhere(self):
        v = self.bc.compute_values(self._cfg("T.Eacher" + AT + "Example.com"))
        self.assertEqual(v["TEACHER_EMAIL_KEY"], "t.eacher" + AT + "example.com")

    def test_public_keys_cover_site_config_template_exactly(self):
        text = (REPO_ROOT / "templates" / "site-config.js.tmpl").read_text(encoding="utf-8")
        used = {t[2:-2] for t in self.bc._PLACEHOLDER_TOKEN_RE.findall(text)}
        self.assertTrue(used <= self.bc.PUBLIC_KEYS, used - self.bc.PUBLIC_KEYS)

    def test_private_keys_not_public(self):
        for k in ("TEACHER_EMAIL_KEY", "REGION"):
            self.assertNotIn(k, self.bc.PUBLIC_KEYS)
        values = self.bc.compute_values(self._cfg("a" + AT + "example.com"))
        for gone in ("SCHOOL_NAME", "STUDENTS_COUNT", "CALENDAR_ICS_URL", "NOTIFICATIONS_ENABLED",
                     "TEACHER_EMAIL", "TEACHER_DISPLAY_NAME", "FIREBASE_STORAGE_BUCKET"):
            self.assertNotIn(gone, values)


if __name__ == "__main__":
    unittest.main()
