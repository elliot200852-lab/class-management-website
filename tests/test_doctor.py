#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doctor.py 的測試：缺工具時不丟例外，report 印得出來。"""
import sys
import unittest
from io import StringIO
from pathlib import Path
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import doctor


class TestDoctor(unittest.TestCase):
    def test_run_checks_does_not_raise_when_tools_missing(self):
        with mock.patch("shutil.which", return_value=None):
            items = doctor.run_checks()
        self.assertIsInstance(items, list)
        self.assertTrue(all({"key", "label", "ok", "required", "detail"} <= set(i) for i in items))

    def test_run_checks_does_not_raise_when_subprocess_fails(self):
        def boom(*a, **k):
            raise OSError("這台機器故意壞掉的假錯誤")
        with mock.patch("subprocess.run", side_effect=boom):
            items = doctor.run_checks()
        self.assertIsInstance(items, list)

    def test_print_report_does_not_raise(self):
        items = doctor.run_checks()
        buf = StringIO()
        with redirect_stdout(buf):
            doctor.print_report(items)
        self.assertIn("健檢", buf.getvalue())

    def test_git_and_agent_cli_are_optional(self):
        with mock.patch("shutil.which", return_value=None):
            items = {i["key"]: i for i in doctor.run_checks()}
        self.assertFalse(items["git"]["required"], "用 ZIP 下載的人不需要 git")
        self.assertFalse(items["agents"]["required"], "桌面版代理找不到終端機指令，不算失敗")
        for key in ("python", "node", "firebase", "gcloud"):
            self.assertTrue(items[key]["required"], key)

    def test_agy_is_detected_and_desktop_note_printed(self):
        self.assertIn("agy", doctor.hostos.AGENT_ORDER)
        self.assertEqual(doctor.hostos.AGENT_CLIS["agy"]["cmd"], "agy")
        with mock.patch.object(doctor.hostos, "agent_clis_found", return_value={"agy": "/x/agy", "claude": ""}):
            item = doctor.check_agents()
        self.assertTrue(item["ok"])
        self.assertIn("Antigravity", item["detail"])
        with mock.patch.object(doctor.hostos, "agent_clis_found", return_value={}):
            item = doctor.check_agents()
        buf = StringIO()
        with redirect_stdout(buf):
            doctor.print_report([item])
        out = buf.getvalue()
        self.assertTrue(any(line.startswith("！ AI 代理") for line in out.splitlines()), out)
        self.assertFalse(any(line.startswith("✗") for line in out.splitlines()), out)
        self.assertIn("桌面版", out)

    def test_main_exit_code_follows_required_items(self):
        def item(key, ok, required):
            return {"key": key, "label": key, "ok": ok, "required": required, "detail": ""}

        cases = (
            ([item("python", True, True), item("node", True, True)], 0),
            ([item("python", True, True), item("pillow", False, False), item("agents", False, False)], 0),
            ([item("python", True, True), item("firebase", False, True)], 1),
        )
        for items, want in cases:
            buf = StringIO()
            with mock.patch.object(doctor, "run_checks", return_value=items), redirect_stdout(buf):
                rc = doctor.main([])
            self.assertEqual(rc, want, [i["key"] for i in items if not i["ok"]])

    def test_windows_python_note_matches_agents(self):
        note = doctor.LINKS["python"]["note"]
        self.assertIn("Python install manager", note)
        self.assertIn("py -3 --version", note)
        self.assertNotIn("Add python.exe to PATH", note)


if __name__ == "__main__":
    unittest.main()
