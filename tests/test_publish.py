#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""發文腳本（publish_post／album／private／page／blog）與共用流程（lib/publishing.py）、欄位白名單（lib/schema.py）。

不連網：預覽階段本來就不連網；上線流程用一個記憶體裡的假資料庫（FakeClient）驗「寫入順序、
已上線要 --update、publishedAt 保留、舊照片最後才刪」。照片相關的在沒裝 Pillow 時略過。
"""
import io
import sys
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
import publish_post  # noqa: E402
import publish_album  # noqa: E402
import publish_page  # noqa: E402
import publish_blog  # noqa: E402
import publish_private  # noqa: E402
from lib import paths, schema, classcfg, images  # noqa: E402
from lib import publishing as pub  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402


class FakeClient(object):
    """只實作發文流程用得到的幾個方法；寫入依序套用並記錄。"""

    def __init__(self):
        self.docs = {}
        self.log = []
        self.tick = 0
        self.tokens = type("T", (), {"notes": []})()

    def describe_target(self):
        return "假資料庫"

    def get(self, path, mask=None):
        d = self.docs.get(path)
        return fr.Doc(path, dict(d)) if d is not None else None

    def batch_get(self, paths_):
        return {p: self.get(p) for p in paths_}

    def list_docs(self, coll, mask=None):
        n = coll.count("/") + 1
        out = []
        for p, d in sorted(self.docs.items()):
            if p.startswith(coll + "/") and p.count("/") == n:
                out.append(fr.Doc(p, {k: v for k, v in d.items() if not mask or k in mask}))
        return out

    def set_write(self, path, data, must_not_exist=False, mask_fields=None):
        return ("set", path, dict(data))

    def delete_write(self, path):
        return ("delete", path, None)

    def commit_all(self, writes, what="", progress=None):
        self.tick += 1
        for op, path, data in writes:
            self.log.append((op, path))
            if op == "delete":
                self.docs.pop(path, None)
            else:
                self.docs[path] = {k: (fr.Timestamp("t%d" % self.tick) if v is fr.SERVER_TIME else v) for k, v in data.items()}
        return 1


class Base(unittest.TestCase):
    photos = False

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cmw-pub-"))
        self.root = fx.make_root(self.tmp / "root", photos=self.photos)
        paths.set_root(self.root)
        self.cfg = classcfg.load()

    def tearDown(self):
        paths.reset_root()
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def quiet(self, fn, *a, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = fn(*a, **kw)
        return rc, buf.getvalue()


class TestPreviewOffline(Base):
    def test_post_preview_escapes_and_writes_nothing(self):
        with mock.patch.object(fr, "make_client", side_effect=AssertionError("預覽不准連資料庫")):
            rc, out = self.quiet(publish_post.main, ["2026-10-01-autumn-walk", "--root", str(self.root)])
        self.assertEqual(rc, 0, out)
        html = (self.root / "exports" / "preview" / "post-2026-10-01-autumn-walk.html").read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertIn("noindex", html)
        self.assertIn("--publish", out)

    def test_post_validation_errors(self):
        md = self.root / "data" / "class-posts" / "2026-10-01-autumn-walk.md"
        text = md.read_text(encoding="utf-8")
        md.write_text(text.replace("category: 班級生活", "category: 沒有這類\ncatagory: x"), encoding="utf-8")
        rc, out = self.quiet(publish_post.main, ["2026-10-01-autumn-walk", "--root", str(self.root)])
        self.assertEqual(rc, 2)
        self.assertIn("catagory", out)
        md.write_text(text.replace("category: 班級生活", "category: 沒有這類"), encoding="utf-8")
        rc, out = self.quiet(publish_post.main, ["2026-10-01-autumn-walk", "--root", str(self.root)])
        self.assertIn("不在 config/class.json 的分類裡", out)
        rc, out = self.quiet(publish_post.main, ["Bad_Slug", "--root", str(self.root)])
        self.assertEqual(rc, 2)
        rc, out = self.quiet(publish_post.main, ["2026-10-09-missing", "--root", str(self.root)])
        self.assertIn("找不到", out)

    def test_missing_photo_file(self):
        md = self.root / "data" / "class-posts" / "2026-10-01-autumn-walk.md"
        md.write_text(md.read_text(encoding="utf-8") + "\n![x](nope.jpg)\n", encoding="utf-8")
        rc, out = self.quiet(publish_post.main, ["2026-10-01-autumn-walk", "--root", str(self.root)])
        self.assertEqual(rc, 2)
        self.assertIn("nope.jpg", out)

    def test_album_page_private_build(self):
        d = publish_album.build("2026-10-02-sports-day", self.cfg)
        self.assertEqual(d.docs[0][1]["videos"], [{"title": "大隊接力", "url": "https://www.youtube.com/watch?v=abcdefghijk"}])
        self.assertEqual(d.docs[0][1]["description"], "運動會當天的照片。")
        d.validate()
        fun = publish_page.build("fun", self.cfg)
        data = fun.docs[0][1]
        self.assertEqual([c["title"] for c in data["data"]["cards"]], ["落葉收集", "蝸牛賽跑"])
        self.assertEqual(data["blocks"][0]["t"], "p")
        fun.validate()
        about = publish_page.build("about", self.cfg)
        self.assertEqual(about.docs[0][1]["kind"], "about")
        self.assertNotIn("data", about.docs[0][1])
        about.validate()
        pv = publish_private.build("2026-10-04-note", self.cfg)
        self.assertEqual(pv.owner, "private_posts/2026-10-04-note")
        pv.validate()

    def test_page_rules(self):
        md = self.root / "data" / "pages" / "trip.md"
        md.write_text("---\ntitle: 校外教學\nkind: about\n---\n內容\n", encoding="utf-8")
        with self.assertRaises(pub.PublishError):
            publish_page.build("trip", self.cfg)
        md.write_text("---\ntitle: 校外教學\n---\n內容\n", encoding="utf-8")
        d = publish_page.build("trip", self.cfg)
        self.assertEqual(d.docs[0][1]["kind"], "standalone")
        with self.assertRaises(pub.PublishError):
            publish_page.build("Trip_Guide", self.cfg)

    def test_blog_body_verbatim_and_limits(self):
        b = publish_blog.build("01", "math-day")
        self.assertEqual(b["body"], "今天他在數學課上\n  很專心。\n\n謝謝！")
        md = self.root / "data" / "blog-drafts" / "01" / "math-day.md"
        md.write_text("---\ntitle: t\nphotos:\n  - a.jpg\n  - b.jpg\n  - c.jpg\n  - d.jpg\n---\n文\n", encoding="utf-8")
        with self.assertRaises(pub.PublishError) as cm:
            publish_blog.build("01", "math-day")
        self.assertIn("最多 3 張", "\n".join(cm.exception.lines))

    def test_post_id_format(self):
        pid = publish_blog.new_post_id("2026-10-03")
        self.assertTrue(schema.POST_ID_RE.match(pid))
        self.assertNotEqual(pid, publish_blog.new_post_id("2026-10-03"))


class TestPublishFlow(Base):
    def run_post(self, fake, *extra):
        with mock.patch.object(fr, "make_client", return_value=fake):
            return self.quiet(publish_post.main, ["2026-10-01-autumn-walk", "--root", str(self.root), "--publish"] + list(extra))

    def test_publish_update_guard_and_published_at(self):
        fake = FakeClient()
        rc, out = self.run_post(fake)
        self.assertEqual(rc, 0, out)
        first = fake.docs["posts/2026-10-01-autumn-walk"]["publishedAt"]
        self.assertEqual([p for _, p in fake.log], ["posts/2026-10-01-autumn-walk/content/main", "posts/2026-10-01-autumn-walk"])
        rc, out = self.run_post(fake)
        self.assertEqual(rc, 2)
        self.assertIn("--update", out)
        rc, out = self.run_post(fake, "--update")
        self.assertEqual(rc, 0, out)
        self.assertEqual(fake.docs["posts/2026-10-01-autumn-walk"]["publishedAt"], first)
        self.assertNotEqual(fake.docs["posts/2026-10-01-autumn-walk"]["updatedAt"], first)
        idx = (self.root / "data" / "class-posts" / "index.md").read_text(encoding="utf-8")
        self.assertIn("2026-10-01-autumn-walk", idx)

    def test_verify_catches_mismatch(self):
        fake = FakeClient()
        orig = fake.commit_all

        def corrupt(writes, what="", progress=None):
            orig(writes, what, progress)
            fake.docs["posts/2026-10-01-autumn-walk"]["title"] = "被改掉了"
        fake.commit_all = corrupt
        rc, out = self.run_post(fake)
        self.assertEqual(rc, 2)
        self.assertIn("比對不一致", out)


@unittest.skipUnless(images.have_pillow(), "沒裝 Pillow（CI 會裝）")
class TestPublishPhotos(Base):
    photos = True

    def test_order_images_thumbs_content_summary_then_deletes(self):
        fake = FakeClient()
        fake.docs["posts/2026-10-01-autumn-walk/thumbs/00000000000000aa"] = {"order": 0, "w": 1, "h": 1, "data": "AAAA"}
        fake.docs["posts/2026-10-01-autumn-walk/images/00000000000000aa"] = {"w": 1, "h": 1, "data": "AAAA"}
        fake.docs["posts/2026-10-01-autumn-walk"] = {"title": "舊", "publishedAt": fr.Timestamp("t0")}
        with mock.patch.object(fr, "make_client", return_value=fake):
            rc, out = self.quiet(publish_post.main, ["2026-10-01-autumn-walk", "--root", str(self.root), "--publish", "--update"])
        self.assertEqual(rc, 0, out)
        kinds = [("images" if "/images/" in p else "thumbs" if "/thumbs/" in p else "content" if p.endswith("/main")
                  else "summary") + ("-del" if op == "delete" else "") for op, p in fake.log]
        self.assertEqual(kinds, ["images", "thumbs", "content", "summary", "thumbs-del", "images-del"])
        s = fake.docs["posts/2026-10-01-autumn-walk"]
        self.assertEqual(s["publishedAt"], fr.Timestamp("t0"))
        self.assertEqual(s["photoCount"], 1)
        # 再發一次：照片已經在 → 不重寫照片
        fake.log.clear()
        with mock.patch.object(fr, "make_client", return_value=fake):
            rc, out = self.quiet(publish_post.main, ["2026-10-01-autumn-walk", "--root", str(self.root), "--publish", "--update"])
        self.assertEqual([p.rsplit("/", 1)[-1] for _, p in fake.log], ["main", "2026-10-01-autumn-walk"])

    def test_same_photo_twice_uploaded_once(self):
        folder = self.root / "data" / "class-posts" / "2026-10-01-autumn-walk"
        shutil.copy(str(folder / "leaves.jpg"), str(folder / "copy.jpg"))
        md = self.root / "data" / "class-posts" / "2026-10-01-autumn-walk.md"
        md.write_text(md.read_text(encoding="utf-8") + "\n![另一張](copy.jpg)\n", encoding="utf-8")
        d = self.quiet(publish_post.build, "2026-10-01-autumn-walk", self.cfg)[0]
        self.assertEqual(len(d.photos), 1)
        pids = [b["pid"] for b in d.docs[0][1]["blocks"] if b["t"] == "img"]
        self.assertEqual(len(set(pids)), 1)

    def test_album_captions_and_order(self):
        d = self.quiet(publish_album.build, "2026-10-02-sports-day", self.cfg)[0]
        self.assertEqual([p.src.name for p in d.photos], ["p1.jpg", "p2.jpg"])
        self.assertEqual([p.order for p in d.photos], [0, 1])
        self.assertEqual(d.photos[0].caption, "起跑")
        image, thumb = pub.photo_docs(d.photos[0])
        self.assertEqual(thumb["caption"], "起跑")
        self.assertNotIn("caption", image)

    def test_home_banner(self):
        folder = self.root / "data" / "pages" / "home"
        shutil.copy(str(self.root / "data" / "albums" / "2026-10-02-sports-day" / "p1.jpg"), str(folder.parent / "p.jpg"))
        folder.mkdir(parents=True, exist_ok=True)
        shutil.move(str(folder.parent / "p.jpg"), str(folder / "banner.jpg"))
        (self.root / "data" / "pages" / "home.md").write_text(
            "---\ntitle: 首頁\nbanner: 歡迎來到我們班\nbanner_image: banner.jpg\n---\n", encoding="utf-8")
        d = self.quiet(publish_page.build, "home", self.cfg)[0]
        doc = d.docs[0][1]
        self.assertEqual(doc["kind"], "home")
        self.assertEqual(doc["data"]["bannerText"], "歡迎來到我們班")
        self.assertEqual(doc["data"]["bannerPid"], d.photos[0].pid)
        self.assertNotIn("blocks", doc)
        d.validate()

    def test_blog_photo_pids(self):
        b = self.quiet(publish_blog.build, "01", "math-day")[0]
        d = publish_blog.make_draft("01", "math-day", b, "2026-10-03-abcdefgh", "teacheralias")
        d.validate()
        self.assertEqual(d.docs[0][1]["photos"], [{"pid": "0", "w": 800, "h": 1000, "caption": "作品"}])
        image, thumb = pub.photo_docs(d.photos[0], blog=True)
        self.assertEqual(thumb["order"], 0)
        self.assertNotIn("caption", thumb)


class TestSchema(unittest.TestCase):
    def test_rejects_extra_and_missing(self):
        ok = {"kind": "parent", "alias": "abcdefabcdef", "updatedAt": fr.SERVER_TIME}
        self.assertEqual(schema.problems("allowlist", ok), [])
        self.assertTrue(schema.problems("allowlist", dict(ok, email="x")))
        self.assertTrue(schema.problems("allowlist", {"kind": "parent", "alias": "abcdefabcdef"}))
        self.assertTrue(schema.problems("allowlist", dict(ok, kind="admin")))
        self.assertTrue(schema.problems("allowlist", dict(ok, alias="ABCDEFABCDEF")))

    def test_map_label_has_no_name(self):
        m = {"seats": ["01"], "kind": "parent", "active": True, "label": "座號 01 家長", "updatedAt": fr.SERVER_TIME}
        self.assertEqual(schema.problems("parent_child_map", m), [])
        self.assertTrue(schema.problems("parent_child_map", dict(m, label="學生 A 的媽媽")))
        self.assertTrue(schema.problems("parent_child_map", dict(m, seats=["1"])))
        self.assertTrue(schema.problems("parent_child_map", dict(m, seats=["01", "02", "03", "04"])))
        self.assertTrue(schema.problems("parent_child_map", dict(m, kind="staff", relation="母")))

    def test_photos(self):
        good = {"data": "QUJD", "w": 320, "h": 240, "order": 0}
        self.assertEqual(schema.problems("thumb", good), [])
        self.assertTrue(schema.problems("thumb", dict(good, data="not base64!")))
        self.assertTrue(schema.problems("thumb", dict(good, data="Q" * 49156)))
        self.assertTrue(schema.problems("blog_thumb", dict(good, caption="x"), pid="0"))
        self.assertTrue(schema.problems("blog_thumb", dict(good, order=1), pid="0"))
        self.assertTrue(schema.problems("image", {"data": "QUJD", "w": 2000, "h": 10}))

    def test_post_cover_pairing_and_entry(self):
        post = {"title": "t", "date": "2026-01-01", "category": "c", "excerpt": "", "coverPid": None, "coverThumb": None,
                "photoCount": 0, "visible": True, "publishedAt": fr.SERVER_TIME, "updatedAt": fr.SERVER_TIME}
        self.assertEqual(schema.problems("post", post), [])
        self.assertTrue(schema.problems("post", dict(post, coverPid="0123456789abcdef")))
        self.assertTrue(schema.problems("post", dict(post, date="2026-13-01")))
        entry = {"title": "t", "body": "b", "date": "2026-01-01", "author": "teacher", "authorAlias": "abcdefabcdef",
                 "photos": [{"pid": "0", "w": 10, "h": 10}], "visible": True, "createdAt": fr.SERVER_TIME}
        self.assertEqual(schema.problems("entry", entry), [])
        self.assertTrue(schema.problems("entry", dict(entry, photos=[{"pid": "1", "w": 10, "h": 10}])))
        self.assertTrue(schema.problems("entry", dict(entry, author="admin")))

    def test_doc_size(self):
        self.assertIsNone(schema.size_problem("a/b", {"x": "a" * 1000}))
        self.assertIsNotNone(schema.size_problem("a/b", {"x": "a" * 1048576}))


if __name__ == "__main__":
    unittest.main()
