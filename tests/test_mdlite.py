#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本機 md → 結構化區塊（scripts/lib/mdlite.py）、檔頭（frontmatter.py）、區塊驗證（blocks.py）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import mdlite, frontmatter as fm, blocks as blk  # noqa: E402


class TestFrontmatter(unittest.TestCase):
    def test_basic_and_lists(self):
        meta, body, first = fm.split("---\ntitle: 秋天: 散步\nvisible: FALSE\ncount: 3\nvideos:\n  - a | https://x.example\n"
                                     "  - 'b'\nempty:\n---\n正文\n")
        self.assertEqual(meta["title"], "秋天: 散步")
        self.assertIs(meta["visible"], False)
        self.assertEqual(meta["count"], "3")
        self.assertEqual(meta["videos"], ["a | https://x.example", "b"])
        self.assertEqual(meta["empty"], "")
        self.assertEqual(body, "正文\n")
        self.assertEqual(first, 10)

    def test_bom_crlf_quotes(self):
        meta, body, _ = fm.split("﻿---\r\ntitle: \"有引號\"\r\n---\r\n第一行\r\n")
        self.assertEqual(meta["title"], "有引號")
        self.assertEqual(body, "第一行\n")

    def test_no_frontmatter(self):
        meta, body, first = fm.split("只有正文")
        self.assertEqual((meta, body, first), ({}, "只有正文", 1))

    def test_errors(self):
        for bad in ("---\ntitle: a\n", "---\ntitle: a\ntitle: b\n---\n", "---\n這行不對\n---\n", "---\n  - 沒有 key\n---\n"):
            with self.assertRaises(fm.FrontmatterError):
                fm.split(bad)

    def test_check_keys(self):
        self.assertEqual(fm.check_keys({"title": "a"}, ("title", "date"), ("title",)), [])
        probs = fm.check_keys({"catagory": "x"}, ("title", "category"), ("title",))
        self.assertEqual(len(probs), 2)
        self.assertIn("catagory", probs[0])

    def test_helpers(self):
        self.assertEqual(fm.pair("a.jpg | 圖說 | 有直線"), ("a.jpg", "圖說 | 有直線"))
        self.assertEqual(fm.as_int("-3", 0, "order"), -3)
        self.assertEqual(fm.as_bool("", True, "visible"), True)
        with self.assertRaises(fm.FrontmatterError):
            fm.as_int("3.5", 0, "order")
        with self.assertRaises(fm.FrontmatterError):
            fm.as_bool("yes", True, "visible")


class TestMdlite(unittest.TestCase):
    def test_every_block_kind(self):
        md = ("第一段\n第二行\n\n## 標題二\n### 標題三\n#### 標題四\n\n- 一\n- 二\n  續行\n\n1. 甲\n2. 乙\n\n"
              "> 引言一\n>\n> 引言二\n\n---\n\n![圖說](a.jpg)\n\n[[video:https://www.youtube.com/watch?v=abcdefghijk|影片]]\n")
        b = mdlite.parse(md)
        self.assertEqual([x["t"] for x in b], ["p", "h", "h", "h", "list", "list", "quote", "hr", "img", "video"])
        self.assertEqual(b[0]["spans"], [{"text": "第一段\n第二行"}])
        self.assertEqual([x["level"] for x in b[1:4]], [2, 3, 4])
        self.assertFalse(b[4]["ordered"])
        self.assertEqual(b[4]["items"][1]["spans"][0]["text"], "二\n續行")
        self.assertTrue(b[5]["ordered"])
        self.assertEqual(b[6]["spans"][0]["text"], "引言一\n\n引言二")
        self.assertEqual(b[8], {"t": "img", "src": "a.jpg", "caption": "圖說"})
        self.assertEqual(b[9], {"t": "video", "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "影片"})

    def test_inline(self):
        b = mdlite.parse("一般 **粗** *斜* [連結](https://example.com/x) [壞連結](javascript:alert(1)) **[粗連結](https://example.com)**")
        spans = b[0]["spans"]
        self.assertIn({"text": "粗", "b": True}, spans)
        self.assertIn({"text": "斜", "i": True}, spans)
        self.assertIn({"text": "連結", "href": "https://example.com/x"}, spans)
        self.assertIn({"text": "粗連結", "b": True, "href": "https://example.com"}, spans)
        self.assertFalse(any("javascript" in s.get("href", "") for s in spans))
        self.assertEqual(blk.problems(b), [])

    def test_http_link_is_text(self):
        spans = mdlite.parse("[看](http://example.com)")[0]["spans"]
        self.assertEqual(spans, [{"text": "看"}])

    def test_stars_with_spaces_stay_literal(self):
        self.assertEqual(mdlite.parse("2 * 3 * 4")[0]["spans"], [{"text": "2 * 3 * 4"}])

    def test_other_syntax_is_text(self):
        b = mdlite.parse("# 一級標題\n<script>alert(1)</script>\n| a | b |")
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]["t"], "p")
        self.assertIn("<script>", b[0]["spans"][0]["text"])

    def test_image_line_splits_paragraph(self):
        b = mdlite.parse("前面\n![](x.png)\n後面")
        self.assertEqual([x["t"] for x in b], ["p", "img", "p"])
        self.assertNotIn("caption", b[1])

    def test_image_errors(self):
        for bad in ("![a](https://example.com/a.jpg)", "![a](../a.jpg)", "![a](sub/a.jpg)"):
            with self.assertRaises(mdlite.MdError):
                mdlite.parse(bad)
        with self.assertRaises(mdlite.MdError):
            mdlite.parse("[[video:http://example.com/v]]")

    def test_long_text_split_into_spans(self):
        b = mdlite.parse("字" * 12000)
        self.assertEqual([len(s["text"]) for s in b[0]["spans"]], [5000, 5000, 2000])
        self.assertEqual(blk.problems(b), [])

    def test_limits(self):
        with self.assertRaises(mdlite.MdError):
            mdlite.parse("\n\n".join("段%d" % i for i in range(401)))
        with self.assertRaises(mdlite.MdError):
            mdlite.parse("## " + "長" * 201)

    def test_fill_pids_and_sources(self):
        b = mdlite.parse("![a](x.jpg)\n\n![b](y.jpg)\n\n![c](x.jpg)")
        self.assertEqual(mdlite.image_sources(b), ["x.jpg", "y.jpg"])
        f = mdlite.fill_pids(b, {"x.jpg": "0123456789abcdef", "y.jpg": "fedcba9876543210"})
        self.assertEqual(f[2], {"t": "img", "pid": "0123456789abcdef", "caption": "c"})
        self.assertEqual(blk.problems(f), [])
        self.assertIn("src", b[0])     # 原本的不被改


class TestBlocksValidate(unittest.TestCase):
    def test_bad_blocks(self):
        bad = [
            {"t": "p", "spans": [{"text": "a", "href": "javascript:alert(1)"}]},
            {"t": "p", "spans": [{"text": "a", "href": "http://example.com"}]},
            {"t": "p", "spans": [{"text": "a", "b": False}]},
            {"t": "p", "spans": [{"text": "a", "onclick": "x"}]},
            {"t": "h", "level": 1, "text": "a"},
            {"t": "h", "level": True, "text": "a"},
            {"t": "img", "pid": "../x"},
            {"t": "video", "url": "https://exa mple.com"},
            {"t": "html", "html": "<b>x</b>"},
            {"t": "list", "ordered": False, "items": [["a"]]},
            {"t": "hr", "x": 1},
        ]
        for b in bad:
            self.assertTrue(blk.problems([b]), b)

    def test_is_https(self):
        self.assertTrue(blk.is_https("https://example.com/a?b=c"))
        for u in ("http://example.com", "https://", "https://@x", "https://ex ample.com", "javascript:x", "", None):
            self.assertFalse(blk.is_https(u), u)

    def test_excerpt(self):
        b = mdlite.parse("第一段  有空白\n換行\n\n- 清單")
        self.assertEqual(blk.excerpt(b), "第一段 有空白 換行 清單")
        self.assertTrue(blk.excerpt(mdlite.parse("長" * 300)).endswith("…"))
        self.assertEqual(len(blk.excerpt(mdlite.parse("長" * 300))), 120)


if __name__ == "__main__":
    unittest.main()
