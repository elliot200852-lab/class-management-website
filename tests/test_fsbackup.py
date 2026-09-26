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

    def test_lists_not_restored_by_default(self):
        pool = fsb.Pool(self.tmp / "pool")
        snap_docs = [{"path": "allowlist/p@example.com", "fields": {"alias": sv("a" * 12)}},
                     {"path": "private_allowlist/p@example.com", "fields": {}},
                     {"path": "parent_child_map/p@example.com", "fields": {"seats": sv("05")}},
                     {"path": "posts/p", "fields": {"t": sv("文")}}]
        c = FakeFirestore({})
        writes, s = fsb.restore_writes(c, snap_docs, [], pool, [], [])
        names = [w["update"]["name"].split("/documents/")[1] for w in writes]
        self.assertEqual(names, ["posts/p"], "名單類（已撤的人）不會被整庫還原寫回去")
        self.assertEqual(s["lists"], ["allowlist/p@example.com", "parent_child_map/p@example.com",
                                      "private_allowlist/p@example.com"])
        writes, s = fsb.restore_writes(c, snap_docs, [], pool, [], [], only=["allowlist"])
        self.assertEqual((writes, s["lists"]), ([], ["allowlist/p@example.com"]), "--only 指名名單也一樣不寫")
        writes, s = fsb.restore_writes(c, snap_docs, [], pool, [], [], include_lists=True)
        self.assertEqual(len(writes), 4)
        self.assertEqual(s["lists"], [])
        self.assertTrue(fsb.is_list_path("parent_child_map/x") and not fsb.is_list_path("posts/allowlist"))

    def test_overwrite_keeps_current_visibility(self):
        pool = fsb.Pool(self.tmp / "pool")
        f = {"booleanValue": False}
        t = {"booleanValue": True}
        snap_docs = [{"path": "posts/p", "fields": {"t": sv("舊標題"), "visible": t}},
                     {"path": "posts/p/comments/c", "fields": {"b": sv("留言"), "status": sv("visible")}},
                     {"path": "posts/q", "fields": {"t": sv("快照時下架"), "visible": f}},
                     {"path": "posts/r", "fields": {"t": sv("已刪"), "visible": t}}]
        cur_docs = [{"path": "posts/p", "fields": {"t": sv("新標題"), "visible": f}},
                    {"path": "posts/p/comments/c", "fields": {"b": sv("留言"), "status": sv("hidden")}},
                    {"path": "posts/q", "fields": {"t": sv("重新上架"), "visible": t}}]
        c = FakeFirestore({})
        writes, s = fsb.restore_writes(c, snap_docs, [], pool, cur_docs, [])
        got = {w["update"]["name"].split("/documents/")[1]: w["update"]["fields"] for w in writes}
        self.assertEqual(got["posts/p"], {"t": sv("舊標題"), "visible": f}, "內容照快照、下架留著")
        self.assertNotIn("posts/p/comments/c", got, "只差在收起 → 留現在的樣子＝一樣，不寫")
        self.assertEqual(got["posts/q"]["visible"], t, "快照之後重新上架的也留現在的樣子")
        self.assertEqual(got["posts/r"]["visible"], t, "現在不在的照快照新建")
        self.assertEqual(s["kept_hidden"], ["posts/p", "posts/p/comments/c"])
        self.assertEqual(s["revealed"], [])
        writes, s = fsb.restore_writes(c, snap_docs, [], pool, cur_docs, [], restore_visibility=True)
        got = {w["update"]["name"].split("/documents/")[1]: w["update"]["fields"] for w in writes}
        self.assertEqual(got["posts/p"]["visible"], t)
        self.assertEqual(got["posts/p/comments/c"]["status"], sv("visible"))
        self.assertEqual(s["revealed"], ["posts/p", "posts/p/comments/c"])
        self.assertEqual(s["kept_hidden"], [])

    def test_exit_hits(self):
        from lib.ledgers import exit_hash
        key = "p@example.com"
        roster = {"students": {"arrayValue": {"values": [
            {"mapValue": {"fields": {"seat": sv("03")}}}, {"mapValue": {"fields": {"seat": sv("05")}}}]}}}
        seating = {"rows": {"arrayValue": {"values": [
            {"mapValue": {"fields": {"seats": {"arrayValue": {"values": [sv("01"), sv("-"), sv("02")]}}}}}]}}}
        docs = [{"path": "student_blogs/05", "fields": {}},
                {"path": "student_blogs/05/entries/e", "fields": {}},
                {"path": "student_blogs/15", "fields": {}},
                {"path": "personal_photos/05", "fields": {}},
                {"path": "blog_notify_queue/05__e", "fields": {}},
                {"path": "blog_notify_queue/01__e/sent/" + exit_hash(key), "fields": {}},
                {"path": "posts/p/reads/" + key, "fields": {}},
                {"path": "posts/p/reads/q@example.com", "fields": {}},
                {"path": "posts/p/comments/c1", "fields": {"authorAlias": sv("x" * 12)}},
                {"path": "posts/p/comments/c2", "fields": {"authorAlias": sv("y" * 12)}},
                {"path": "roster/students", "fields": roster},
                {"path": "seating/2026-10-01", "fields": seating},
                {"path": "posts/p", "fields": {}}]
        photos = [{"path": "student_blogs/05/entries/e/images/0"}]
        chosen = [d["path"] for d in docs] + [photos[0]["path"]]
        exits = [{"kind": "seat", "at": "x", "seats": ["05"], "keyHashes": [exit_hash(key)],
                  "aliasHashes": [exit_hash("x" * 12)]}]
        hits = fsb.exit_hits(docs, photos, chosen, exits)
        self.assertEqual(hits, sorted(["student_blogs/05", "student_blogs/05/entries/e", "personal_photos/05",
                                       "blog_notify_queue/05__e", "blog_notify_queue/01__e/sent/" + exit_hash(key),
                                       "posts/p/reads/" + key, "posts/p/comments/c1", "roster/students",
                                       "student_blogs/05/entries/e/images/0"]))
        self.assertEqual(fsb.exit_hits(docs, photos, ["posts/p", "student_blogs/15"], exits), [], "--only 避開就沒事")
        self.assertEqual(fsb.exit_hits(docs, photos, chosen, []), [])
        self.assertEqual(fsb.exit_hits(docs, photos, ["posts/p"], [{"kind": "year-end", "at": "x"}]), ["posts/p"],
                         "學年封存：全部都算")

    def test_exit_hits_parent_photos_by_article_author(self):
        """家長退場：台帳沒有座號；文章底下的照片與對話本身不帶作者代號，要靠文章的作者代號認出來。"""
        from lib.ledgers import exit_hash
        e = "student_blogs/05/entries/2026-10-05-parentxx"
        t = "student_blogs/05/entries/2026-10-06-teacherx"
        docs = [{"path": e, "fields": {"authorAlias": sv("x" * 12), "author": sv("parent")}},
                {"path": e + "/blog_comments/b1", "fields": {"authorAlias": sv("t" * 12)}},
                {"path": t, "fields": {"authorAlias": sv("t" * 12), "author": sv("teacher")}}]
        photos = [{"path": e + "/thumbs/0"}, {"path": e + "/images/0"}, {"path": t + "/images/0"}]
        exits = [{"kind": "parent", "at": "x", "seats": [], "keyHashes": [exit_hash("p@example.com")],
                  "aliasHashes": [exit_hash("x" * 12)]}]
        self.assertEqual(fsb.exit_hits(docs, photos, [e + "/thumbs/0"], exits), [e + "/thumbs/0"],
                         "--only 只挑照片子路徑也要擋")
        chosen = [d["path"] for d in docs] + [r["path"] for r in photos]
        self.assertEqual(fsb.exit_hits(docs, photos, chosen, exits),
                         sorted([e, e + "/blog_comments/b1", e + "/thumbs/0", e + "/images/0"]),
                         "他那篇文章底下的全部（含導師回的對話）都算；導師自己的文章不算")

    def test_orphan_photos(self):
        e1 = "student_blogs/05/entries/2026-10-05-abcdefgh"
        docs = [{"path": e1, "fields": {"photos": {"arrayValue": {"values": [
            {"mapValue": {"fields": {"pid": sv("0"), "w": {"integerValue": "2"}}}}]}}}},
                {"path": "student_blogs/03/entries/2026-10-06-zzzzzzzz", "fields": {"photos": {"arrayValue": {}}}},
                {"path": "posts/p", "fields": {}}]
        entries = fsb.entries_from_docs(docs)
        self.assertEqual(entries, {e1: {"0"}, "student_blogs/03/entries/2026-10-06-zzzzzzzz": set()})
        photos = [e1 + "/images/0", e1 + "/thumbs/0", e1 + "/images/1",
                  "student_blogs/05/entries/2026-10-07-ghostxyz/thumbs/2",
                  "posts/p/images/aaaaaaaaaaaaaaaa"]
        orphans = fsb.find_orphan_photos(entries, photos)
        self.assertEqual(orphans, [e1 + "/images/1", "student_blogs/05/entries/2026-10-07-ghostxyz/thumbs/2"],
                         "pid 不在 photos 清單、或文章根本不在；紀事的照片不算")
        s = fsb.orphan_summary(orphans, lambda p: 100)
        self.assertEqual((s["count"], s["bytes"]), (2, 200))
        self.assertEqual(s["seats"]["05"]["count"], 2)
        self.assertEqual(s["seats"]["05"]["posts"], ["2026-10-05-a***", "2026-10-07-g***"], "postId 只留日期與第一個字")
        self.assertEqual(fsb.orphan_summary([])["count"], 0)

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
