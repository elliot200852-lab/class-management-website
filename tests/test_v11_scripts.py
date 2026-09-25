#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.1 的資料腳本：座位表、個人照、家長合照、每日一詩（＋lib/schema.py 的欄位白名單、lib/multipub.py 的多份上線流程）。

不連網：預覽本來就不連網；上線流程把 multipub.connect 換成記憶體裡的假資料庫（沿用 test_publish.FakeClient），
驗「一樣的略過、改過的要 --update、換照片刪舊的、拿掉」。照片相關的在沒裝 Pillow 時略過；照片一律執行時用 Pillow 當場畫。
"""
import io
import sys
import json
import base64
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from contextlib import redirect_stdout

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
import admin_support as fx  # noqa: E402
import test_publish  # noqa: E402
import publish_seating  # noqa: E402
import publish_personal_photos  # noqa: E402
import publish_parent_photo  # noqa: E402
import publish_poems  # noqa: E402
import publish_page  # noqa: E402
from lib import paths, schema, classcfg, images  # noqa: E402
from lib import publishing as pub  # noqa: E402
from lib import multipub as mp  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402


class Fake(test_publish.FakeClient):
    def delete_recursive(self, doc_path, writes_out=None):
        gone = sorted(p for p in self.docs if p == doc_path or p.startswith(doc_path + "/"))
        for p in gone:
            self.docs.pop(p, None)
        return gone


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cmw-v11-"))
        self.root = fx.make_root(self.tmp / "root", photos=False)
        paths.set_root(self.root)
        self.cfg = classcfg.load()
        self.db = Fake()

    def tearDown(self):
        paths.reset_root()
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def run_main(self, fn, *args):
        buf = io.StringIO()
        with mock.patch.object(mp, "connect", return_value=self.db), \
                mock.patch.object(fr, "make_client", side_effect=AssertionError("這一步不該連資料庫")), \
                redirect_stdout(buf):
            rc = fn(list(args) + ["--root", str(self.root)])
        return rc, buf.getvalue()

    def write(self, rel, text):
        return fx.write(self.root / rel, text)


# ── 欄位白名單 ─────────────────────────────────────────────────────────

class TestSchema(unittest.TestCase):
    def seating(self, **kw):
        d = {"title": "十月", "date": "2026-10-01", "rows": [{"seats": ["01", "", "-", "02"]}], "note": "",
             "updatedAt": fr.SERVER_TIME}
        d.update(kw)
        return d

    def test_seating(self):
        self.assertEqual(schema.problems("seating", self.seating()), [])
        self.assertTrue(schema.problems("seating", self.seating(rows=[{"seats": ["01", "01"]}])))
        self.assertTrue(schema.problems("seating", self.seating(rows=[{"seats": ["1"]}])))
        self.assertTrue(schema.problems("seating", self.seating(rows=[{"seats": ["", "-"]}])), "至少一位學生")
        self.assertTrue(schema.problems("seating", self.seating(rows=[["01"]])), "每一排要包一層 {seats}")
        self.assertTrue(schema.problems("seating", self.seating(names=["x"])))
        self.assertTrue(schema.problems("seating", self.seating(title="")))

    def test_photo_owners(self):
        pid = "0123456789abcdef"
        self.assertEqual(schema.problems("personal_photos", {"photoPids": [pid], "updatedAt": fr.SERVER_TIME}), [])
        self.assertTrue(schema.problems("personal_photos", {"photoPids": ["0"], "updatedAt": fr.SERVER_TIME}))
        ok = {"relations": ["母", "父"], "note": "", "photoPids": [pid], "updatedAt": fr.SERVER_TIME}
        self.assertEqual(schema.problems("parent_photo_display", ok), [])
        self.assertTrue(schema.problems("parent_photo_display", dict(ok, names=["某人"])), "不收家長姓名欄位")
        self.assertTrue(schema.problems("parent_photo_display", dict(ok, relations=["母", "母"])))
        self.assertTrue(schema.problems("parent_photo_display", dict(ok, note="x" * 201)))

    def test_poem_page(self):
        item = {"date": "2026-10-01", "title": "早晨", "author": "示範", "text": "一行\n  兩行"}
        doc = {"title": "每日一詩", "kind": "poem", "order": 0, "visible": True, "updatedAt": fr.SERVER_TIME,
               "data": {"month": "2026-10", "items": [item]}}
        self.assertEqual(schema.problems("page", doc), [])
        bad = dict(doc, data={"month": "2026-10", "items": [dict(item, date="2026-11-01")]})
        self.assertTrue(any("不在 2026-10" in x for x in schema.problems("page", bad)))
        dup = dict(doc, data={"month": "2026-10", "items": [item, dict(item)]})
        self.assertTrue(any("兩首" in x for x in schema.problems("page", dup)))
        self.assertTrue(schema.problems("page", dict(doc, data={"month": "2026-10", "items": [dict(item, text="")]})))
        self.assertTrue(schema.problems("page", dict(doc, data=None)))
        self.assertTrue(schema.problems("page", dict(doc, blocks=[])))


# ── 座位表 ─────────────────────────────────────────────────────────────

class TestSeating(Base):
    PLAN = {"title": "十月的座位", "note": "靠窗那排怕熱", "rows": [["01", "02", "-", "03", "04"], ["05", "", "-", "07"]]}

    def plan(self, pid="2026-10-01", data=None):
        return self.write("data/seating/%s.json" % pid, json.dumps(data or self.PLAN, ensure_ascii=False))

    def test_preview_offline_and_ascii(self):
        self.plan()
        rc, out = self.run_main(publish_seating.main)
        self.assertEqual(rc, 0, out)
        self.assertIn("[01][02]    [03][04]", out)
        self.assertIn("[05][  ]    [07]", out)
        self.assertIn("沒有排進", out)
        html = (self.root / "exports" / "preview" / "seating-all.html").read_text(encoding="utf-8")
        self.assertIn("十月的座位", html)
        self.assertEqual(self.db.docs, {})

    def test_bad_cells_do_not_echo_names(self):
        self.plan(data={"title": "x", "rows": [["01", "甲同學", 3, "4", "26"]]})
        rc, out = self.run_main(publish_seating.main)
        self.assertEqual(rc, 2)
        self.assertNotIn("甲同學", out)
        self.assertIn("名字不要寫在這裡", out)
        self.assertIn('"03"', out)
        self.assertIn('"04"', out)
        self.assertIn("座號 26 不在名冊", out)

    def test_plan_id_and_json_errors(self):
        self.write("data/seating/october.json", "{}")
        rc, out = self.run_main(publish_seating.main)
        self.assertEqual(rc, 2)
        self.assertIn("檔名要是方案代號", out)
        (self.root / "data" / "seating" / "october.json").unlink()
        self.write("data/seating/2026-10-01.json", '{"title": "x", "rows": [["01",]]}')
        rc, out = self.run_main(publish_seating.main)
        self.assertIn("不是合法的 JSON", out)
        rc, out = self.run_main(publish_seating.main, "2026-12-01")
        self.assertIn("找不到", out)

    def test_publish_skip_update_remove(self):
        self.plan()
        self.plan("2026-11-01", {"title": "十一月", "date": "2026-11-02", "rows": [["01"]]})
        rc, out = self.run_main(publish_seating.main, "--publish")
        self.assertEqual(rc, 0, out)
        doc = self.db.docs["seating/2026-10-01"]
        self.assertEqual(doc["rows"][1], {"seats": ["05", "", "-", "07"]})
        self.assertEqual(self.db.docs["seating/2026-11-01"]["date"], "2026-11-02")
        self.assertEqual(schema.problems("seating", doc), [])
        rc, out = self.run_main(publish_seating.main, "--publish")
        self.assertIn("網站上已經是最新的", out)
        self.plan(data=dict(self.PLAN, title="十月（改）"))
        rc, out = self.run_main(publish_seating.main, "--publish")
        self.assertEqual(rc, 2)
        self.assertIn("--update", out)
        self.assertEqual(self.db.docs["seating/2026-10-01"]["title"], "十月的座位")
        rc, out = self.run_main(publish_seating.main, "--publish", "--update")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.db.docs["seating/2026-10-01"]["title"], "十月（改）")
        rc, out = self.run_main(publish_seating.main, "--remove", "2026-11-01")
        self.assertIn("--publish", out)
        self.assertIn("seating/2026-11-01", self.db.docs)
        rc, out = self.run_main(publish_seating.main, "--remove", "2026-11-01", "--publish")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("seating/2026-11-01", self.db.docs)
        led = (self.root / "data" / "ledgers" / "published.jsonl").read_text(encoding="utf-8")
        self.assertIn('"action": "remove"', led)


# ── 每日一詩 ───────────────────────────────────────────────────────────

POEM = """---
date: 2026-10-01
title: 早晨（示範）
author: 示範文字
source: 示範用自寫短句
rights: 自己寫的
---

窗外的光慢慢走進來
  落在桌上

也落在肩上

## 導讀
一小段導讀。
"""


class TestPoems(Base):
    def test_verbatim_text_and_guide(self):
        p = self.write("data/poems/2026-10-01.md", POEM)
        item, rights = publish_poems.read_poem(p)
        self.assertEqual(item["text"], "窗外的光慢慢走進來\n  落在桌上\n\n也落在肩上")
        self.assertEqual(item["guide"], "一小段導讀。")
        self.assertEqual(rights, "自己寫的")

    def test_rights_required_for_publish_only(self):
        self.write("data/poems/2026-10-01.md", POEM)
        self.write("data/poems/2026-10-02.md", POEM.replace("2026-10-01", "2026-10-02").replace("rights: 自己寫的\n", ""))
        rc, out = self.run_main(publish_poems.main)
        self.assertEqual(rc, 0)
        self.assertIn("2026-10：2 首（rights 已確認 1 首）", out)
        rc, out = self.run_main(publish_poems.main, "2026-10")
        self.assertEqual(rc, 0, out)
        self.assertIn("還不能上線", out)
        self.assertNotIn("--publish", out, "rights 還空著：不給「說上傳之後再跑 --publish」的指令")
        self.assertNotIn("說「上傳」", out)
        rc, out = self.run_main(publish_poems.main, "2026-10", "--publish")
        self.assertEqual(rc, 2)
        self.assertEqual(self.db.docs, {})
        self.write("data/poems/2026-10-02.md", POEM.replace("2026-10-01", "2026-10-02").replace("自己寫的", "公版"))
        rc, out = self.run_main(publish_poems.main, "2026-10", "--publish")
        self.assertEqual(rc, 0, out)
        doc = self.db.docs["pages/poems-2026-10"]
        self.assertEqual(doc["kind"], "poem")
        self.assertEqual([x["date"] for x in doc["data"]["items"]], ["2026-10-01", "2026-10-02"])
        self.assertNotIn("rights", doc["data"]["items"][0], "rights 只留在老師的電腦")
        self.assertEqual(schema.problems("page", doc), [])

    def test_duplicate_date_and_foreign_page(self):
        self.write("data/poems/a.md", POEM)
        self.write("data/poems/b.md", POEM)
        rc, out = self.run_main(publish_poems.main, "2026-10")
        self.assertEqual(rc, 2)
        self.assertIn("有兩首詩", out)
        (self.root / "data" / "poems" / "b.md").unlink()
        self.db.docs["pages/poems-2026-10"] = {"title": "x", "kind": "standalone", "order": 0, "visible": True}
        rc, out = self.run_main(publish_poems.main, "2026-10", "--publish")
        self.assertEqual(rc, 2)
        self.assertIn("不是每日一詩", out)
        self.assertEqual(self.db.docs["pages/poems-2026-10"]["kind"], "standalone")

    def test_publish_page_reserves_poem_ids(self):
        self.write("data/pages/poems-2026-10.md", "---\ntitle: x\n---\n正文\n")
        with self.assertRaises(pub.PublishError) as cm:
            publish_page.build("poems-2026-10", self.cfg)
        self.assertIn("保留給每日一詩", cm.exception.lines[0])


# ── 照片：個人照、家長合照 ─────────────────────────────────────────────

@unittest.skipUnless(images.have_pillow(), "沒裝 Pillow")
class TestPhotos(Base):
    def test_personal_photos_names_and_publish(self):
        d = self.root / "data" / "personal-photos"
        fx.make_jpeg(d / "01.jpg", (1200, 1600), orientation=1, seed=1)
        fx.make_jpeg(d / "2.jpg", (1600, 1200), orientation=6, seed=2)
        fx.make_jpeg(d / "學生甲.jpg", (300, 300), orientation=1, seed=3)
        rc, out = self.run_main(publish_personal_photos.main)
        self.assertEqual(rc, 2)
        self.assertNotIn("學生甲", out)
        self.assertIn("檔名不是座號", out)
        (d / "學生甲.jpg").unlink()
        rc, out = self.run_main(publish_personal_photos.main, "--publish")
        self.assertEqual(rc, 0, out)
        p1 = self.db.docs["personal_photos/01"]["photoPids"][0]
        img = self.db.docs["personal_photos/02/images/" + self.db.docs["personal_photos/02"]["photoPids"][0]]
        self.assertEqual((img["w"], img["h"]), (960, 1280), "EXIF 方向 6 要轉正成直的")
        raw = base64.b64decode(img["data"])
        self.assertEqual(images.metadata_markers(raw), [])
        self.assertEqual(self.db.docs["personal_photos/01/thumbs/" + p1]["order"], 0)
        rc, out = self.run_main(publish_personal_photos.main, "--publish")
        self.assertIn("已經是最新的", out)
        fx.make_jpeg(d / "01.jpg", (1000, 1000), orientation=1, seed=9)
        rc, out = self.run_main(publish_personal_photos.main, "--publish")
        self.assertEqual(rc, 2)
        self.assertIn("01", out)
        rc, out = self.run_main(publish_personal_photos.main, "--publish", "--update")
        self.assertEqual(rc, 0, out)
        p1b = self.db.docs["personal_photos/01"]["photoPids"][0]
        self.assertNotEqual(p1, p1b)
        self.assertNotIn("personal_photos/01/images/" + p1, self.db.docs, "換照片要刪掉舊的")
        rc, out = self.run_main(publish_personal_photos.main, "--remove", "1", "--publish")
        self.assertEqual(rc, 0, out)
        self.assertFalse([k for k in self.db.docs if k.startswith("personal_photos/01")])
        fx.make_jpeg(d / "26.jpg", (300, 300), orientation=1, seed=4)
        rc, out = self.run_main(publish_personal_photos.main)
        self.assertIn("座號 26 不在名冊", out)

    def test_parent_photo_relations_file_and_blog(self):
        src = fx.make_jpeg(self.root / "data" / "parent-photos" / "01.jpg", (1600, 1200), orientation=3, seed=5)
        rc, out = self.run_main(publish_parent_photo.main, "--seat", "1", "--from-file", "data/parent-photos/01.jpg",
                                "--publish")
        self.assertEqual(rc, 0, out)
        doc = self.db.docs["parent_photo_display/01"]
        self.assertEqual(doc["relations"], ["母", "父"], "預設是 parent-roles.yaml 那個座號的全部稱謂")
        self.assertEqual(schema.problems("parent_photo_display", doc), [])
        rc, out = self.run_main(publish_parent_photo.main, "--seat", "1", "--from-file", str(src), "--who", "祖母")
        self.assertEqual(rc, 2)
        self.assertIn("不在 data/parent-roles.yaml", out)
        rc, out = self.run_main(publish_parent_photo.main, "--seat", "5", "--from-file", str(src), "--who", "母",
                                "--note", "運動會那天", "--publish")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.db.docs["parent_photo_display/05"]["note"], "運動會那天")
        # 從部落格文章挑一張：先在假資料庫放一篇有照片的文章
        ph = images.process(src)
        entry = "student_blogs/03/entries/2026-10-03-abcd1234"
        self.db.docs[entry] = {"title": "t", "photos": [{"pid": "0", "w": ph.image.w, "h": ph.image.h}]}
        self.db.docs[entry + "/images/0"] = {"data": ph.image.data, "w": ph.image.w, "h": ph.image.h}
        rc, out = self.run_main(publish_parent_photo.main, "--seat", "3", "--from-blog", "2026-10-03-abcd1234",
                                "--photo", "1")
        self.assertEqual(rc, 2)
        self.assertIn("沒有第 2 張", out)
        rc, out = self.run_main(publish_parent_photo.main, "--seat", "3", "--from-blog", "2026-10-03-abcd1234",
                                "--publish")
        self.assertEqual(rc, 0, out)
        pid = self.db.docs["parent_photo_display/03"]["photoPids"][0]
        self.assertIn("parent_photo_display/03/images/" + pid, self.db.docs)
        rc, out = self.run_main(publish_parent_photo.main, "--seat", "3", "--from-blog", "2026-10-03-abcd1234",
                                "--who", "母", "--publish")
        self.assertEqual(rc, 2, "稱謂改了＝內容不一樣，要 --update")

    def test_parent_photo_without_roles_needs_who(self):
        (self.root / "data" / "parent-roles.yaml").unlink()
        src = fx.make_jpeg(self.root / "data" / "parent-photos" / "02.jpg", seed=6)
        rc, out = self.run_main(publish_parent_photo.main, "--seat", "2", "--from-file", str(src))
        self.assertEqual(rc, 2)
        self.assertIn("--who", out)
        rc, out = self.run_main(publish_parent_photo.main, "--seat", "2", "--from-file", str(src), "--who", "阿姨")
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
