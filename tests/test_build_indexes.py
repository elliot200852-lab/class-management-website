#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_indexes.py 與查詢形狀登記表（templates/queries.json）的測試。

要守住的事（docs/DATA-MODEL.md §4）：
  1. 每個登記的查詢，在產生的 firestore.indexes.json 裡都找得到撐得住它的索引
     （這裡用一支跟產生器寫法不同的「比對器」獨立驗，不是拿產生器驗自己）。
  2. 單欄位／只有等號的查詢不產生多餘的複合索引；檔案裡每一個複合索引都至少有一個查詢要用。
  3. 進 git 的兩個產生檔（firestore.indexes.json、site/js/core/queries.js）是最新的。
  4. 非導師的查詢一定帶成員過濾條件（visible／status），規則才不會整批拒絕。
  5. DATA-MODEL §4.4 的查詢表跟登記表逐字一致；兩份文件裡提到的查詢名都真的有登記。
"""
import re
import sys
import copy
import json
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import build_indexes as bi  # noqa: E402

REG = bi.load_registry(REPO_ROOT / "templates" / "queries.json")
INDEX_FILE = json.loads((REPO_ROOT / "firestore.indexes.json").read_text(encoding="utf-8"))

ASC, DESC = "ASCENDING", "DESCENDING"


# ── 獨立比對器：只看「檔案裡有什麼」，不呼叫 required_indexes() ─────────────────

def _cid(q):
    return q["group"] if q.get("group") else q["path"].split("/")[-1]


def _overrides(idx_file):
    out = {}
    for o in idx_file.get("fieldOverrides", []):
        out[(o["collectionGroup"], o["fieldPath"])] = o["indexes"]
    return out


def _has_group_single(idx_file, cid, field, order):
    for i in _overrides(idx_file).get((cid, field), []):
        if i.get("queryScope") == "COLLECTION_GROUP" and i.get("order") == order:
            return True
    return False


def _collection_single_ok(idx_file, cid, field):
    """集合範圍的單欄索引：沒被覆寫就是預設有；被覆寫的話，覆寫清單裡要有集合範圍的升降冪。"""
    ov = _overrides(idx_file)
    if (cid, field) not in ov:
        return True
    scopes = {(i.get("queryScope"), i.get("order")) for i in ov[(cid, field)]}
    return ("COLLECTION", ASC) in scopes and ("COLLECTION", DESC) in scopes


def satisfied(q, idx_file):
    cid = _cid(q)
    group = bool(q.get("group"))
    scope = "COLLECTION_GROUP" if group else "COLLECTION"
    where = q.get("where", [])
    order = q.get("orderBy", [])
    eq = {w[0] for w in where if w[1] == "=="}
    rng = {w[0] for w in where if w[1] in ("<", "<=", ">", ">=")}
    order_pairs = [(o[0], ASC if o[1] == "asc" else DESC) for o in order]
    fields = eq | rng | {f for f, _ in order_pairs}

    # 可以不靠複合索引的情況
    if not rng and not order:
        if not group:
            return all(_collection_single_ok(idx_file, cid, f) for f in fields)
        return all(_has_group_single(idx_file, cid, f, ASC) for f in fields)
    if not eq and len(fields) == 1:
        (f,) = tuple(fields)
        d = order_pairs[0][1] if order_pairs else ASC
        if not group:
            return _collection_single_ok(idx_file, cid, f)
        return _has_group_single(idx_file, cid, f, d)

    # 需要複合索引：前段是等號欄位（任意順序、升冪），接著是排序欄位，最後是沒排序的範圍欄位
    for idx in idx_file.get("indexes", []):
        if idx["collectionGroup"] != cid or idx["queryScope"] != scope:
            continue
        flds = [(f["fieldPath"], f.get("order")) for f in idx["fields"]]
        head = flds[:len(eq)]
        if {f for f, _ in head} != eq or any(d != ASC for _, d in head):
            continue
        rest = flds[len(eq):]
        want = list(order_pairs) + [(f, ASC) for f in sorted(rng) if f not in {x for x, _ in order_pairs}]
        if rest == want:
            return True
    return False


def _q(**kw):
    base = {"use": "測試", "who": ["teacher"], "batch": "v1", "limit": 10}
    base.update(kw)
    return base


class TestRegistryIsValid(unittest.TestCase):
    def test_no_validation_errors(self):
        self.assertEqual(bi.validate_registry(REG), [])

    def test_generated_files_are_fresh(self):
        r = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "build_indexes.py"), "--check"],
                           cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_committed_index_file_equals_generator_output(self):
        self.assertEqual(INDEX_FILE, bi.build_index_file(REG))


class TestEveryQueryHasIndex(unittest.TestCase):
    def test_every_registered_query_is_satisfied(self):
        for name, q in sorted(REG["queries"].items()):
            with self.subTest(query=name):
                self.assertTrue(satisfied(q, INDEX_FILE), "%s 在 firestore.indexes.json 找不到撐得住它的索引" % name)

    def test_no_orphan_composite(self):
        needed = set()
        for q in REG["queries"].values():
            need = bi.required_indexes(q)
            if "composite" in need:
                needed.add(need["composite"])
        for idx in INDEX_FILE["indexes"]:
            key = (idx["collectionGroup"], idx["queryScope"],
                   tuple((f["fieldPath"], f["order"]) for f in idx["fields"]))
            with self.subTest(index=key):
                self.assertIn(key, needed, "多出一個沒有任何查詢在用的複合索引")

    def test_single_field_queries_add_no_composite(self):
        for name, q in sorted(REG["queries"].items()):
            where = q.get("where", [])
            order = q.get("orderBy", [])
            eq_only = where and all(w[1] == "==" for w in where) and not order
            single = not where and len(order) <= 1
            if eq_only or single:
                with self.subTest(query=name):
                    self.assertNotIn("composite", bi.required_indexes(q))

    def test_expected_composites_present(self):
        # DATA-MODEL §4.1：模擬器不檢查複合索引，這幾個一定要在產生檔裡
        keys = {(i["collectionGroup"], tuple((f["fieldPath"], f["order"]) for f in i["fields"]))
                for i in INDEX_FILE["indexes"]}
        self.assertIn(("posts", (("category", ASC), ("date", DESC))), keys)
        self.assertIn(("posts", (("visible", ASC), ("category", ASC), ("date", DESC))), keys)
        self.assertIn(("posts", (("visible", ASC), ("date", DESC))), keys)
        self.assertIn(("comments", (("status", ASC), ("createdAt", DESC))), keys)

    def test_group_override_keeps_default_collection_indexes(self):
        ov = _overrides(INDEX_FILE)
        comments = ov[("comments", "createdAt")]
        scopes = {(i.get("queryScope"), i.get("order"), i.get("arrayConfig")) for i in comments}
        self.assertIn(("COLLECTION", ASC, None), scopes)
        self.assertIn(("COLLECTION", DESC, None), scopes)
        self.assertIn(("COLLECTION", None, "CONTAINS"), scopes)
        self.assertIn(("COLLECTION_GROUP", DESC, None), scopes)

    def test_base64_fields_exempt(self):
        ov = _overrides(INDEX_FILE)
        for key in (("thumbs", "data"), ("images", "data")):
            with self.subTest(key=key):
                self.assertEqual(ov.get(key), [])


class TestDerivationRules(unittest.TestCase):
    def test_eq_plus_order_needs_composite(self):
        need = bi.required_indexes(_q(path="posts", where=[["visible", "==", True]], orderBy=[["date", "desc"]]))
        self.assertEqual(need["composite"], ("posts", "COLLECTION", (("visible", ASC), ("date", DESC))))

    def test_order_only_is_automatic(self):
        self.assertEqual(bi.required_indexes(_q(path="posts", orderBy=[["date", "desc"]])), {})

    def test_equalities_only_are_merged(self):
        self.assertEqual(bi.required_indexes(_q(path="pages", where=[["visible", "==", True], ["kind", "==", ":k"]])), {})

    def test_range_on_order_field_alone_is_automatic(self):
        self.assertEqual(bi.required_indexes(_q(path="posts", where=[["date", "<", ":d"]], orderBy=[["date", "desc"]])), {})

    def test_eq_plus_range_without_order(self):
        need = bi.required_indexes(_q(path="posts", where=[["visible", "==", True], ["date", ">=", ":d"]]))
        self.assertEqual(need["composite"], ("posts", "COLLECTION", (("visible", ASC), ("date", ASC))))

    def test_group_single_order(self):
        need = bi.required_indexes(_q(group="comments", orderBy=[["createdAt", "desc"]]))
        self.assertEqual(need, {"group_single": [("comments", "createdAt", DESC)]})

    def test_group_eq_plus_order_is_group_composite(self):
        need = bi.required_indexes(_q(group="entries", where=[["author", "==", "parent"]], orderBy=[["createdAt", "desc"]]))
        self.assertEqual(need["composite"], ("entries", "COLLECTION_GROUP", (("author", ASC), ("createdAt", DESC))))

    def test_path_params_do_not_change_collection_id(self):
        need = bi.required_indexes(_q(path="{thread}/comments", where=[["status", "==", "visible"]],
                                      orderBy=[["createdAt", "desc"]]))
        self.assertEqual(need["composite"][0], "comments")


class TestValidation(unittest.TestCase):
    def _reg_with(self, name, q):
        reg = copy.deepcopy(REG)
        reg["queries"] = {name: q}
        return bi.validate_registry(reg)

    def assertRejected(self, q, fragment):
        errs = self._reg_with("posts.test", q)
        self.assertTrue(any(fragment in e for e in errs), "沒擋下來，錯誤清單：%r" % errs)

    def test_member_query_without_visible_filter_rejected(self):
        self.assertRejected(_q(who=["reader"], path="posts", orderBy=[["date", "desc"]]), "一定要帶 where")

    def test_member_query_on_teacher_only_collection_rejected(self):
        self.assertRejected(_q(who=["reader"], path="{thread}/reads"), "只准導師查")

    def test_group_query_for_members_rejected(self):
        self.assertRejected(_q(who=["reader"], group="comments", where=[["status", "==", "visible"]],
                               orderBy=[["createdAt", "desc"]]), "集合群組查詢只准導師")

    def test_two_range_fields_rejected(self):
        self.assertRejected(_q(path="posts", where=[["date", ">", ":a"], ["order", "<", ":b"]]), "範圍條件")

    def test_range_field_must_be_first_order(self):
        self.assertRejected(_q(path="posts", where=[["date", ">", ":a"]], orderBy=[["title", "asc"]]), "第一個 orderBy")

    def test_missing_limit_rejected(self):
        q = _q(path="posts")
        del q["limit"]
        self.assertRejected(q, "limit")

    def test_exempt_field_cannot_be_queried(self):
        self.assertRejected(_q(path="{owner}/thumbs", orderBy=[["data", "asc"]]), "exempt")

    def test_unknown_operator_rejected(self):
        self.assertRejected(_q(path="posts", where=[["tags", "array-contains", "x"]]), "運算子")

    def test_limit_to_last_needs_order(self):
        self.assertRejected(_q(path="posts", limitToLast=True, cursor="endBefore"), "需要 orderBy")

    def test_undeclared_collection_rejected(self):
        self.assertRejected(_q(path="secrets"), "沒有在 collections 宣告")

    def test_count_with_order_rejected(self):
        q = _q(path="posts", count=True, orderBy=[["date", "desc"]])
        del q["limit"]
        self.assertRejected(q, "count 查詢不能帶")


class TestQueriesJs(unittest.TestCase):
    def test_queries_js_matches_registry(self):
        text = (REPO_ROOT / "site" / "js" / "core" / "queries.js").read_text(encoding="utf-8")
        body = text.split("C.QUERIES = ", 1)[1].rsplit(";\n})", 1)[0]
        shapes = json.loads(body)
        want = {k: {kk: vv for kk, vv in v.items() if kk != "use"} for k, v in REG["queries"].items()}
        self.assertEqual(shapes, want)


class TestDocsInSync(unittest.TestCase):
    NAME_TOKEN = re.compile(
        r"`((?:posts|comments|reads|albums|photos|private|pages|blogs|entries|blogComments|"
        r"allowlist|privateAllowlist|parentMap|seating|personalPhotos|parentPhotos|notifyQueue)\.[A-Za-z.]+)`")
    BEGIN = "<!-- queries-table:begin（由 python3 scripts/build_indexes.py --markdown 產生，不要手改） -->"
    END = "<!-- queries-table:end -->"

    def _doc(self, name):
        return (REPO_ROOT / "docs" / name).read_text(encoding="utf-8")

    def test_data_model_table_is_generated_output(self):
        doc = self._doc("DATA-MODEL.md")
        self.assertIn(self.BEGIN, doc)
        self.assertIn(self.END, doc)
        block = doc.split(self.BEGIN, 1)[1].split(self.END, 1)[0].strip("\n") + "\n"
        self.assertEqual(block, bi.render_markdown(REG),
                         "DATA-MODEL §4.4 的表跟登記表不一致：跑 build_indexes.py --markdown 貼回去")

    def test_query_names_in_docs_are_registered(self):
        names = set(REG["queries"])
        for doc in ("DATA-MODEL.md", "ARCHITECTURE.md"):
            for m in self.NAME_TOKEN.finditer(self._doc(doc)):
                if m.group(1).rsplit(".", 1)[-1] in ("html", "js", "py", "md", "json"):
                    continue   # 檔名（例如 private.html），不是查詢名
                with self.subTest(doc=doc, name=m.group(1)):
                    self.assertIn(m.group(1), names)


if __name__ == "__main__":
    unittest.main()
