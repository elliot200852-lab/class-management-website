#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""資料庫備份的核心（scripts/lib/fsbackup.py）：走遍資料庫（葉子不再往下、空殼照樣往下、照片只列名稱）、
照片增量、快照讀寫與 md5、只刪自己建的快照、還原要寫哪些。不連網：用記憶體裡的假資料庫。"""
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from lib import fsbackup as fsb  # noqa: E402

DB = "projects/demo-x/databases/(default)"


def sv(s):
    return {"stringValue": s}


class FakeFirestore(object):
    """夠 Walker、fetch_photos 用的假客戶端。docs：{路徑: fields}；時間固定。"""

    def __init__(self, docs):
        self.docs = dict(docs)
        self.db = DB
        self.calls = []

    def _rel_docs(self, path=""):
        return "%s/documents%s" % (self.db, ("/" + path) if path else "")

    def name(self, p):
        return "%s/documents/%s" % (self.db, p)

    def _exists_or_parent(self):
        out = set()
        for p in self.docs:
            segs = p.split("/")
            for i in range(2, len(segs) + 1, 2):
                out.add("/".join(segs[:i]))
        return out

    def _raw(self, p, masked=False):
        r = {"name": self.name(p), "createTime": "2026-01-01T00:00:00Z", "updateTime": "2026-01-02T00:00:00Z"}
        if not masked:
            r["fields"] = self.docs[p]
        return r

    def list_collection_ids(self, doc_path):
        self.calls.append(("ids", doc_path))
        n = doc_path.count("/") + 1
        return sorted({p.split("/")[n] for p in self._exists_or_parent() if p.startswith(doc_path + "/")})

    def request(self, method, rel, body=None, params=None, what="", **kw):
        prefix = self.db + "/documents"
        if rel == prefix + ":listCollectionIds":
            return 200, {"collectionIds": sorted({p.split("/")[0] for p in self.docs})}
        if rel == prefix + ":batchGet":
            self.calls.append(("batchGet", len(body["documents"])))
            out = []
            for n in body["documents"]:
                p = n[len(prefix) + 1:]
                out.append({"found": self._raw(p)} if p in self.docs else {"missing": n})
            return 200, out
        coll = rel[len(prefix) + 1:]
        params = dict(params or [])
        masked = "mask.fieldPaths" in params
        show = params.get("showMissing") == "true"
        depth = coll.count("/") + 2
        out = []
        for p in sorted(self._exists_or_parent()):
            if p.startswith(coll + "/") and p.count("/") + 1 == depth:
                if p in self.docs:
                    out.append(self._raw(p, masked))
                elif show:
                    out.append({"name": self.name(p)})
        self.calls.append(("list", coll, masked, show))
        return 200, {"documents": out}


WORLD = {
    "posts/p1": {"title": sv("紀事")},
    "posts/p1/content/main": {"blocks": sv("[]")},
    "posts/p1/comments/c1": {"body": sv("好")},
    "posts/p1/thumbs/aaaaaaaaaaaaaaaa": {"data": sv("T")},
    "posts/p1/images/aaaaaaaaaaaaaaaa": {"data": sv("I" * 10)},
    "student_blogs/01": {"seat": sv("01")},
    "student_blogs/01/entries/2026-10-01-abcdefgh": {"title": sv("文")},
    "student_blogs/01/entries/2026-10-01-abcdefgh/images/0": {"data": sv("J")},
    "ghost/g1/sub/s1": {"k": sv("v")},
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cmw-fsb-"))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)


class TestWalk(Base):
    def test_walk_whole_database(self):
        c = FakeFirestore(WORLD)
        ex = fsb.Walker(c).walk()
        docs = {d["path"] for d in ex.docs}
        photos = {r["path"] for r in ex.photos}
        self.assertEqual(docs | photos, set(WORLD))
        self.assertEqual(photos, {p for p in WORLD if fsb.is_photo_path(p)})
        self.assertEqual(ex.phantoms, ["ghost/g1"], "本身不存在、底下有資料的路徑要記下來，而且要往下走")
        asked = {x[1] for x in c.calls if x[0] == "ids"}
        self.assertNotIn("posts/p1/comments/c1", asked, "葉子集合的文件不再問子集合")
        self.assertNotIn("posts/p1/content/main", asked)
        self.assertIn("ghost/g1", asked)
        photo_lists = [x for x in c.calls if x[0] == "list" and x[1].split("/")[-1] in ("thumbs", "images")]
        self.assertTrue(photo_lists and all(x[2] for x in photo_lists), "照片只列名稱（mask），不下載內容")

    def test_walk_roots_and_names_only(self):
        c = FakeFirestore(WORLD)
        ex = fsb.Walker(c).walk(roots=["student_blogs"], names_only=True)
        self.assertEqual({d["path"] for d in ex.docs}, {"student_blogs/01", "student_blogs/01/entries/2026-10-01-abcdefgh"})
        self.assertTrue(all(d["fields"] == {} for d in ex.docs))

    def test_fetch_photos_incremental(self):
        c = FakeFirestore(WORLD)
        ex = fsb.Walker(c).walk()
        pool = fsb.Pool(self.tmp / "pool", self.tmp / "sync")
        rows, n = fsb.fetch_photos(c, ex.photos, pool)
        self.assertEqual(n, 3)
        self.assertEqual({r["path"] for r in rows}, {p for p in WORLD if fsb.is_photo_path(p)})
        doc = pool.load(rows[0]["key"])
        self.assertEqual(doc["fields"], WORLD[doc["path"]])
        c.calls.clear()
        known = {r["key"]: r["md5"] for r in rows}
        rows2, n2 = fsb.fetch_photos(c, ex.photos, pool, known_md5=known)
        self.assertEqual(n2, 0, "照片池已經有的不再下載")
        self.assertFalse([x for x in c.calls if x[0] == "batchGet"])
        self.assertEqual(rows, rows2)
        del c.docs["posts/p1/images/aaaaaaaaaaaaaaaa"]
        refs = [dict(r, updateTime="2026-02-02T00:00:00Z") for r in ex.photos]
        rows3, _ = fsb.fetch_photos(c, refs, pool)
        self.assertNotIn("posts/p1/images/aaaaaaaaaaaaaaaa", {r["path"] for r in rows3}, "下載途中被刪掉的照片略過")

    def test_pool_push_verifies_and_skips_existing(self):
        pool = fsb.Pool(self.tmp / "pool", self.tmp / "sync")
        (self.tmp / "sync").mkdir()
        key = fsb.pool_key("posts/p1/images/x", "t1")
        md5 = pool.save({"path": "posts/p1/images/x", "fields": {"data": sv("x")}}, key)
        self.assertTrue(pool.push(key, md5))
        self.assertFalse(pool.push(key, md5))
        with self.assertRaises(fsb.CopyError):
            pool.push(fsb.pool_key("nope", "t"))


class TestKeysAndMask(unittest.TestCase):
    def test_pool_key(self):
        a = fsb.pool_key("posts/p/images/x", "t1")
        self.assertEqual(a, fsb.pool_key("posts/p/images/x", "t1"))
        self.assertNotEqual(a, fsb.pool_key("posts/p/images/x", "t2"), "內容改過（時間不同）＝新檔")
        self.assertEqual(a[:32], fsb.pool_prefix("posts/p/images/x"))
        self.assertTrue(fsb.POOL_RE.match(a + ".json"))

    def test_is_photo_path(self):
        self.assertTrue(fsb.is_photo_path("posts/p/thumbs/x"))
        self.assertTrue(fsb.is_photo_path("student_blogs/01/entries/e/images/0"))
        self.assertFalse(fsb.is_photo_path("posts/p/comments/x"))
        self.assertFalse(fsb.is_photo_path("thumbs/x"))

    def test_mask_path(self):
        self.assertEqual(fsb.mask_path("allowlist/parent-a@example.com"), "allowlist/p***@example.com")
        self.assertEqual(fsb.mask_path("posts/p/reads/x.y@example.com"), "posts/p/reads/x***@example.com")
        self.assertEqual(fsb.mask_path("posts/p"), "posts/p")

    def test_free_snapshot_id(self):
        taken = {fsb.snapshot_id(1000000000), fsb.snapshot_id(1000000001)}
        self.assertEqual(fsb.free_snapshot_id(lambda i: i in taken, t=1000000000), fsb.snapshot_id(1000000002))
        self.assertTrue(fsb.SNAP_RE.match(fsb.snapshot_id()))


class TestSnapshots(Base):
    def make(self, base, sid, kind="regular"):
        ex = fsb.Export()
        ex.docs = [{"path": "posts/p", "fields": {"t": sv("x")}, "createTime": "", "updateTime": ""}]
        rows = [{"path": "posts/p/images/a", "updateTime": "t", "key": fsb.pool_key("posts/p/images/a", "t"), "md5": "m"}]
        return fsb.write_snapshot(base, sid, "demo-x", ex, rows, kind=kind)

    def test_roundtrip_and_tamper(self):
        d, man = self.make(self.tmp, "20260101-000000")
        m, docs, rows = fsb.load_snapshot(d)
        self.assertEqual(m["counts"], {"documents": 1, "photos": 1, "phantoms": 0})
        self.assertEqual(docs[0]["fields"], {"t": sv("x")})
        (d / fsb.DOCS_FILE).write_text((d / fsb.DOCS_FILE).read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(fsb.SnapshotError):
            fsb.load_snapshot(d)
        with self.assertRaises(fsb.SnapshotError):
            self.make(self.tmp, "20260101-000000")

    def test_prune_only_ours_keep_n(self):
        for i in range(5):
            self.make(self.tmp, "2026010%d-000000" % (i + 1))
        (self.tmp / "20250101-000000").mkdir()
        (self.tmp / "20250101-000000" / "manifest.json").write_text('{"tool": "別的工具"}', encoding="utf-8")
        (self.tmp / "老師自己的資料夾").mkdir()
        snaps = fsb.list_snapshots(self.tmp)
        self.assertEqual([i for i, _ in snaps], ["2026010%d-000000" % (i + 1) for i in range(5)])
        gone = fsb.prune(snaps, 3)
        self.assertEqual(gone, ["20260101-000000", "20260102-000000"])
        self.assertTrue((self.tmp / "20250101-000000").exists(), "別人的資料夾不碰")
        self.assertTrue((self.tmp / "老師自己的資料夾").exists())
        with self.assertRaises(ValueError):
            fsb.prune(snaps, 0)

    def test_sync_snapshots_month_folders(self):
        local, _ = self.make(self.tmp / "local", "20260930-100000")
        local2, _ = self.make(self.tmp / "local", "20261001-100000")
        sync = self.tmp / "sync"
        latest = self.tmp / "latest"
        sync.mkdir()
        latest.mkdir()
        fsb.push_snapshot(local, sync, latest)
        fsb.push_snapshot(local2, sync, latest)
        (sync / "2026-09" / "筆記.txt").write_text("老師放的", encoding="utf-8")
        got = fsb.list_sync_snapshots(sync)
        self.assertEqual([i for i, _ in got], ["20260930-100000", "20261001-100000"])
        self.assertEqual((latest / fsb.MANIFEST).read_text(encoding="utf-8"),
                         (local2 / fsb.MANIFEST).read_text(encoding="utf-8"))
        fsb.prune(got, 1)
        self.assertTrue((sync / "2026-09").exists(), "月份夾裡還有別的東西就不收掉")
        self.assertEqual([i for i, _ in fsb.list_sync_snapshots(sync)], ["20261001-100000"])
        self.assertEqual(fsb.find_snapshot("latest", self.tmp / "local"), local2)
        self.assertEqual(fsb.find_snapshot("20260930-100000", self.tmp / "local"), local)
        self.assertIsNone(fsb.find_snapshot("20200101-000000", self.tmp / "local", sync))

    def test_find_snapshot_skips_pre_restore_for_latest(self):
        a, _ = self.make(self.tmp, "20260101-000000")
        self.make(self.tmp, "20260102-000000", kind="pre-restore")
        self.assertEqual(fsb.find_snapshot("latest", self.tmp), a)

    def test_clean_partials(self):
        (self.tmp / "20260101-000000.partial").mkdir()
        (self.tmp / "別的.partial").mkdir()
        fsb.clean_partials(self.tmp)
        self.assertFalse((self.tmp / "20260101-000000.partial").exists())
        self.assertTrue((self.tmp / "別的.partial").exists())


class TestRestorePlan(Base):
    def test_create_overwrite_same_and_order(self):
        pool = fsb.Pool(self.tmp / "pool")
        k_old = fsb.pool_key("posts/p/images/a", "t1")
        k_new = fsb.pool_key("posts/p/images/a", "t2")
        pool.save({"path": "posts/p/images/a", "fields": {"data": sv("A")}}, k_old)
        pool.save({"path": "posts/p/images/a", "fields": {"data": sv("A")}}, k_new)
        k_b = fsb.pool_key("posts/p/images/b", "t1")
        pool.save({"path": "posts/p/images/b", "fields": {"data": sv("B")}}, k_b)
        snap_docs = [{"path": "posts/p", "fields": {"t": sv("原本")}},
                     {"path": "posts/p/comments/c", "fields": {"b": sv("留言")}},
                     {"path": "pages/about", "fields": {"t": sv("一樣")}}]
        snap_ph = [{"path": "posts/p/images/a", "key": k_old}, {"path": "posts/p/images/b", "key": k_b}]
        cur_docs = [{"path": "posts/p", "fields": {"t": sv("被改掉")}}, {"path": "pages/about", "fields": {"t": sv("一樣")}},
                    {"path": "posts/new", "fields": {}}]
        cur_ph = [{"path": "posts/p/images/a", "key": k_new}]
        c = FakeFirestore({})
        writes, s = fsb.restore_writes(c, snap_docs, snap_ph, pool, cur_docs, cur_ph)
        self.assertEqual(s["create"], ["posts/p/comments/c", "posts/p/images/b"])
        self.assertEqual(s["overwrite"], ["posts/p"])
        self.assertEqual(s["same"], 2, "照片內容一樣（只是時間不同）也算一樣")
        names = [w["update"]["name"].split("/documents/")[1] for w in writes]
        self.assertEqual(names[-1], "posts/p", "摘要文件最後寫")
        self.assertNotIn("posts/new", names, "快照之後新增的不動、不刪")
        self.assertFalse(any("delete" in w for w in writes))
        w2, s2 = fsb.restore_writes(c, snap_docs, snap_ph, pool, cur_docs, cur_ph, only=["pages"])
        self.assertEqual((w2, s2["same"]), ([], 1))

    def test_select_paths(self):
        ps = ["posts/a", "posts/a/comments/x", "posts/ab", "pages/a"]
        self.assertEqual(fsb.select_paths(ps, ["posts/a"]), ["posts/a", "posts/a/comments/x"])
        self.assertEqual(fsb.select_paths(ps, ["/pages/"]), ["pages/a"])
        self.assertEqual(fsb.select_paths(ps, []), ps)

    def test_purge_pool_paths(self):
        pool = fsb.Pool(self.tmp / "pool")
        a1 = fsb.pool_key("student_blogs/03/entries/e/images/0", "t1")
        a2 = fsb.pool_key("student_blogs/03/entries/e/images/0", "t2")
        b = fsb.pool_key("posts/p/images/x", "t1")
        for k, p in ((a1, "x"), (a2, "x"), (b, "y")):
            pool.save({"path": p, "fields": {}}, k)
        (self.tmp / "pool" / "README.txt").write_text("別的", encoding="utf-8")
        n = fsb.purge_pool_paths([self.tmp / "pool", None], ["student_blogs/03/entries/e/images/0", "student_blogs/03"])
        self.assertEqual(n, 2, "同一張照片的每個版本都刪")
        self.assertEqual(sorted(p.name for p in (self.tmp / "pool").iterdir()), sorted([b + ".json", "README.txt"]))


if __name__ == "__main__":
    unittest.main()
