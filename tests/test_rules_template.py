#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安全規則樣板的純 Python 檢查（scripts/check.py 會跑；不需要 Java、Node、模擬器）。

  · templates/manifest.json 有產生 firestore.rules（不公開），樣板只用 {{TEACHER_EMAIL_KEY}}；
  · 用 build_config.py 真的產生一份（測試用設定），導師的 email 鍵有插進去、沒有殘留的 {{…}}；
  · 最後一條是預設全拒（docs/ARCHITECTURE.md §8.1）；
  · 文件存取次數靜態檢查：每條 allow 最壞 ≤ 10、部落格發文批次 ≤ 20（scripts/lib/rules_budget.py），
    而且解析器沒有漏看任何一段；解析器本身用一份已知答案的小規則自我測試；
  · docs/DATA-MODEL.md 附錄 A 的程式碼區塊跟樣板逐字相同（文件是正本，兩邊要同一個 commit 一起改）。

模擬器規則測試在 tests/rules/（python3 scripts/test_rules.py；check.py 加 --rules 才跑）。
"""
import sys
import json
import re
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from lib import rules_budget  # noqa: E402
import test_rules  # noqa: E402  （scripts/test_rules.py：測試用設定與產生規則的函式）

TEMPLATE = REPO_ROOT / "templates" / "firestore.rules.tmpl"
AT = "@"


class TestManifestAndTemplate(unittest.TestCase):
    def test_manifest_generates_rules_privately(self):
        manifest = json.loads((REPO_ROOT / "templates" / "manifest.json").read_text(encoding="utf-8"))
        entries = {e["dest"]: e for e in manifest["templates"]}
        self.assertIn("firestore.rules", entries)
        self.assertEqual(entries["firestore.rules"]["src"], "firestore.rules.tmpl")
        self.assertFalse(entries["firestore.rules"].get("public"), "安全規則含導師的 email 鍵，不能標 public")

    def test_template_only_uses_teacher_key(self):
        used = set(re.findall(r"\{\{([A-Z_]+)\}\}", TEMPLATE.read_text(encoding="utf-8")))
        self.assertEqual(used, {"TEACHER_EMAIL_KEY"})

    def test_rules_file_is_gitignored(self):
        lines = [l.strip() for l in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
        self.assertIn("firestore.rules", lines)


class TestRenderedRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = test_rules.render_rules(cls.tmp.name, "Class.Teacher" + AT + "Example.com")
        cls.text = Path(out).read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_teacher_key_inserted_normalized(self):
        self.assertIn('emailKey() == "class.teacher' + AT + 'example.com"', self.text)
        self.assertNotIn("{{", self.text)

    def test_last_rule_is_default_deny(self):
        root = rules_budget.parse(self.text)
        docs_block = root.children[-1]
        self.assertEqual(docs_block.path, "/databases/{database}/documents")
        last = docs_block.children[-1]
        self.assertEqual(last.path, "/databases/{database}/documents/{document=**}")
        self.assertEqual(len(last.allows), 1)
        self.assertEqual(set(last.allows[0].ops), {"get", "list", "create", "update", "delete"})
        self.assertEqual(last.allows[0].expr, "false")

    def test_access_budget(self):
        rows = rules_budget.analyze(self.text)
        batches = rules_budget.batch_totals(rows)
        self.assertEqual(rules_budget.problems(rows, batches), [])
        total, seen = rules_budget.coverage(self.text)
        self.assertEqual(total, seen, "解析器漏看了規則的一部分")
        self.assertGreater(total, 5)
        # 每個會讀其他文件的查詢（list）都在估算表裡
        self.assertTrue(any(r["op"] == "list" and r["calls"] > 0 for r in rows))


class TestBudgetAnalyzerSelfTest(unittest.TestCase):
    """用一份已知答案的小規則驗 rules_budget 本身（註解、字串、.get() 方法都不能算；範圍與遞迴規則要算對）。"""

    SAMPLE = """rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    function a() { return get(/databases/$(database)/documents/x/$(request.auth.uid)).data.get('k', 1) == 1; }
    function b() { return a() && exists(/databases/$(database)/documents/y/z); }
    // get(/databases/$(database)/documents/comment/ignored) 註解裡的不算
    match /c/{id} {
      function inner() { return b() || a(); }
      allow get: if inner() && 'get(' != '';
      allow list: if a();
      allow write: if false;
      match /sub/{s} {
        allow read: if inner() && get(/databases/$(database)/documents/c/$(id)) != null;
      }
    }
    match /{path=**}/sub/{s} { allow read: if a(); }
  }
}
"""

    def test_counts(self):
        rows = {(r["path"], r["op"]): r for r in rules_budget.analyze(self.SAMPLE)}
        self.assertEqual(rows[("/c/{id}", "get")]["calls"], 4)        # inner()=3 ＋ 遞迴規則 a()=1
        self.assertEqual(rows[("/c/{id}", "list")]["calls"], 2)
        self.assertEqual(rows[("/c/{id}", "create")]["calls"], 0)
        self.assertEqual(rows[("/c/{id}/sub/{s}", "get")]["calls"], 5)
        self.assertEqual(rows[("/{path=**}/sub/{s}", "list")]["calls"], 1)
        self.assertEqual(len(rows[("/c/{id}", "get")]["docs"]), 2)     # x/… 與 y/z

    def test_coverage(self):
        self.assertEqual(rules_budget.coverage(self.SAMPLE), (3, 3))

    def test_over_limit_reported(self):
        many = " && ".join("exists(/databases/$(database)/documents/p/d%d)" % i for i in range(11))
        text = ("rules_version = '2';\nservice cloud.firestore {\n  match /databases/{database}/documents {\n"
                "    match /t/{id} { allow list: if %s; }\n  }\n}\n" % many)
        rows = rules_budget.analyze(text)
        self.assertEqual(len(rules_budget.problems(rows, [])), 1)

    def test_unknown_syntax_refused(self):
        with self.assertRaises(rules_budget.RulesParseError):
            rules_budget.parse("service cloud.firestore { match /x/{y} { permit read; } }")


class TestAppendixMatchesTemplate(unittest.TestCase):
    def test_data_model_appendix_a_is_the_template(self):
        doc = (REPO_ROOT / "docs" / "DATA-MODEL.md").read_text(encoding="utf-8")
        start = doc.index("\n## A. ")
        fence = doc.index("\n```\n", start)
        end = doc.index("\n```\n", fence + 1)
        appendix = doc[fence + len("\n```\n"):end + 1]
        self.assertEqual(appendix, TEMPLATE.read_text(encoding="utf-8"),
                         "docs/DATA-MODEL.md 附錄 A 跟 templates/firestore.rules.tmpl 不一樣——兩邊要一起改")


if __name__ == "__main__":
    unittest.main()
