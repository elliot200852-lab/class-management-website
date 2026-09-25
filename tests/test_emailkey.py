#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""emailkey.email_key() 的測試：大小寫、gmail 點號、googlemail、非 gmail 保留點號、前後空白、非法輸入。

測試向量放在 tests/fixtures/emailkey_vectors.json（前端與規則測試共用同一份）。
向量裡的 email 拆成 [@ 前, @ 後] 兩段存，這裡才用 "@" 接起來——這個測試檔與向量檔都會被
privacy_scan 掃到，完整的非 example.com 信箱字樣不能連續出現在 repo 裡。
"""
import sys
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
from lib import emailkey  # noqa: E402

AT = "@"
VECTORS = json.loads((HERE / "fixtures" / "emailkey_vectors.json").read_text(encoding="utf-8"))


def _join(pair, sep=AT):
    return pair[0] + sep + pair[1]


class TestVectors(unittest.TestCase):
    def test_vector_file_has_both_kinds(self):
        self.assertGreaterEqual(len(VECTORS["valid"]), 8)
        self.assertGreaterEqual(len(VECTORS["invalid"]), 8)

    def test_valid_vectors(self):
        for v in VECTORS["valid"]:
            with self.subTest(why=v["why"]):
                self.assertEqual(emailkey.email_key(_join(v["in"])), _join(v["out"]))

    def test_invalid_vectors(self):
        for v in VECTORS["invalid"]:
            with self.subTest(why=v["why"]):
                raw = _join(v["in"], v.get("join", AT))
                with self.assertRaises(ValueError):
                    emailkey.email_key(raw)
                self.assertFalse(emailkey.is_valid(raw))

    def test_outputs_are_fixed_points(self):
        # 正規化兩次跟一次結果相同（名單同步重跑不會一直改 doc id）
        for v in VECTORS["valid"]:
            with self.subTest(why=v["why"]):
                once = emailkey.email_key(_join(v["in"]))
                self.assertEqual(emailkey.email_key(once), once)


class TestRules(unittest.TestCase):
    def test_case_folding(self):
        self.assertEqual(emailkey.email_key("Teacher" + AT + "Example.com"), "teacher" + AT + "example.com")

    def test_gmail_dots_removed_and_googlemail_unified(self):
        a = emailkey.email_key("p.a.r.e.n.t" + AT + "gmail.com")
        b = emailkey.email_key("Parent" + AT + "GoogleMail.com")
        c = emailkey.email_key("parent" + AT + "gmail.com")
        self.assertEqual(a, b)
        self.assertEqual(b, c)
        self.assertTrue(a.endswith(AT + "gmail.com"))

    def test_non_gmail_keeps_dots(self):
        k = emailkey.email_key("first.last" + AT + "school.example.com")
        self.assertEqual(k, "first.last" + AT + "school.example.com")
        self.assertNotEqual(k, emailkey.email_key("firstlast" + AT + "school.example.com"))

    def test_whitespace_stripped(self):
        self.assertEqual(emailkey.email_key("  a" + AT + "example.com\n"), "a" + AT + "example.com")

    def test_non_string_rejected(self):
        for bad in (None, 123, b"a@example.com", ["a"], True):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(ValueError):
                    emailkey.email_key(bad)

    def test_error_message_does_not_echo_input(self):
        # 錯誤訊息不能夾帶原字串（避免 email 被印進終端機紀錄或 CI log）
        raw = "secret.person" + AT + "example"
        with self.assertRaises(ValueError) as cm:
            emailkey.email_key(raw)
        self.assertNotIn("secret", str(cm.exception))

    def test_build_config_uses_same_regex(self):
        sys.path.insert(0, str(HERE.parent / "scripts"))
        import build_config  # noqa: E402
        self.assertIs(build_config.EMAIL_RE, emailkey.EMAIL_RE)


if __name__ == "__main__":
    unittest.main()
