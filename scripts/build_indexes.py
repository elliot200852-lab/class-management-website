#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_indexes.py — 查詢形狀登記表 → firestore.indexes.json（＋前端的 queries.js）。

  讀：templates/queries.json（查詢形狀登記表，正本；格式見 docs/DATA-MODEL.md §4）
  產：firestore.indexes.json        repo 根目錄；`firebase deploy --only firestore:indexes` 用
      site/js/core/queries.js      前端 Store 只准用這裡登記過的查詢名（window.CMW.QUERIES）

  兩個產生檔都**進 git**（跟班級設定無關、不含任何秘密），而且**永遠由這支產生**，不准手改。
  為什麼要有這一步：Firestore 模擬器不檢查複合索引，查詢在本機全綠、上線才噴「需要索引」。
  所以每個查詢形狀都先登記，由程式推導出需要哪些索引，單元測試再比對「每個查詢都有索引、
  沒有多餘的索引、產生檔是最新的」。

用法：
  python3 scripts/build_indexes.py              # 重新產生兩個檔
  python3 scripts/build_indexes.py --check      # 只檢查登記表合法、產生檔是最新的；不寫檔（CI／測試用）
  python3 scripts/build_indexes.py --markdown   # 印出 DATA-MODEL §4.4 那張表（貼回文件用）

  （Windows：py -3 scripts/build_indexes.py）

部署索引**絕對不加 `--force`**：那會刪掉線上有、檔案裡沒有的索引。
"""
import re
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths
from lib.console import setup_utf8

setup_utf8()

REGISTRY_REL = ("templates", "queries.json")
INDEXES_REL = ("firestore.indexes.json",)
QUERIES_JS_REL = ("site", "js", "core", "queries.js")

ROLES = ("teacher", "reader", "privateReader", "seatReader", "seatParent", "functions")
PRIVILEGED = ("teacher", "functions")          # 不受「成員必帶過濾條件」限制的角色
EQ_OPS = ("==",)
RANGE_OPS = ("<", "<=", ">", ">=")
ALL_OPS = EQ_OPS + RANGE_OPS
DIRS = {"asc": "ASCENDING", "desc": "DESCENDING"}
BATCHES = ("v1", "v1.1")
CURSORS = ("startAfter", "endBefore")
MAX_LIMIT = 500

NAME_RE = re.compile(r"^[a-z][A-Za-z]*(\.[a-z][A-Za-z]*)+$")
FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
COLL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PARAM_SEG_RE = re.compile(r"^\{[a-zA-Z]+\}$")
QUERY_KEYS = {"use", "who", "path", "group", "where", "orderBy", "limit", "limitToLast",
              "cursor", "count", "watch", "sortClient", "batch"}

# fieldOverride 會「取代」該欄位的預設單欄索引；要加集合群組索引時，必須把預設的三個
# 集合範圍索引也一起列回去，否則原本自動有的單欄查詢會壞掉。
DEFAULT_COLLECTION_INDEXES = (
    {"order": "ASCENDING", "queryScope": "COLLECTION"},
    {"order": "DESCENDING", "queryScope": "COLLECTION"},
    {"arrayConfig": "CONTAINS", "queryScope": "COLLECTION"},
)


class RegistryError(Exception):
    pass


# ── 讀與驗 ──────────────────────────────────────────────────────────────────

def load_registry(path=None):
    p = Path(path) if path else paths.pkg_path(*REGISTRY_REL)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise RegistryError("找不到查詢登記表：%s" % p)
    except json.JSONDecodeError as e:
        raise RegistryError("%s 不是合法的 JSON（第 %d 行第 %d 欄：%s）" % (p, e.lineno, e.colno, e.msg))


def collection_id(q):
    """查詢打的集合 id（路徑最後一段，或集合群組名）。"""
    if q.get("group"):
        return q["group"]
    return q["path"].split("/")[-1]


def is_param(v):
    return isinstance(v, str) and v.startswith(":")


def _where(q):
    return [tuple(w) for w in q.get("where", [])]


def _order(q):
    return [tuple(o) for o in q.get("orderBy", [])]


def validate_registry(reg):
    """回傳錯誤清單（字串）。空清單＝合法。"""
    errs = []
    if not isinstance(reg, dict):
        return ["登記表最外層要是物件"]
    colls = reg.get("collections")
    queries = reg.get("queries")
    exempt = reg.get("exempt", [])
    if not isinstance(colls, dict) or not colls:
        errs.append("缺 collections（每個被查詢的集合都要宣告成員過濾條件或 teacherOnly）")
        colls = {}
    if not isinstance(queries, dict) or not queries:
        errs.append("缺 queries")
        queries = {}
    if not isinstance(exempt, list):
        errs.append("exempt 要是清單")
        exempt = []

    for cid, spec in colls.items():
        if not COLL_ID_RE.match(cid):
            errs.append("collections：集合 id 格式不對：%r" % cid)
        kinds = [k for k in ("memberFilter", "teacherOnly", "gatedByParent") if k in spec]
        if len(kinds) != 1:
            errs.append("collections.%s：memberFilter／teacherOnly／gatedByParent 三選一" % cid)
            continue
        if "memberFilter" in spec:
            mf = spec["memberFilter"]
            if not (isinstance(mf, list) and len(mf) == 3 and mf[1] == "=="):
                errs.append("collections.%s.memberFilter 要寫成 [欄位, \"==\", 值]" % cid)

    exempt_pairs = set()
    for e in exempt:
        if not isinstance(e, dict) or not COLL_ID_RE.match(str(e.get("collectionGroup", ""))) \
                or not FIELD_RE.match(str(e.get("fieldPath", ""))):
            errs.append("exempt 項目格式不對：%r" % (e,))
            continue
        exempt_pairs.add((e["collectionGroup"], e["fieldPath"]))

    for name, q in sorted(queries.items()):
        pre = "queries.%s：" % name
        if not NAME_RE.match(name):
            errs.append(pre + "名稱要像 posts.recent（小寫開頭、用點分段）")
        if not isinstance(q, dict):
            errs.append(pre + "要是物件")
            continue
        extra = set(q) - QUERY_KEYS
        if extra:
            errs.append(pre + "不認得的鍵：%s" % "、".join(sorted(extra)))
        if not isinstance(q.get("use"), str) or not q.get("use").strip():
            errs.append(pre + "缺 use（這個查詢用在哪裡）")
        who = q.get("who")
        if not (isinstance(who, list) and who and all(w in ROLES for w in who)):
            errs.append(pre + "who 要是非空清單，值只能是 %s" % "、".join(ROLES))
            who = []
        if q.get("batch") not in BATCHES:
            errs.append(pre + "batch 要是 %s" % "／".join(BATCHES))

        has_path, has_group = bool(q.get("path")), bool(q.get("group"))
        if has_path == has_group:
            errs.append(pre + "path 與 group 恰好要有一個")
            continue
        if has_group:
            if not COLL_ID_RE.match(q["group"]):
                errs.append(pre + "group 格式不對")
            if any(w not in PRIVILEGED for w in who):
                errs.append(pre + "集合群組查詢只准導師（規則的 {path=**} 只開給導師）")
        else:
            segs = q["path"].split("/")
            for s in segs:
                if not (COLL_ID_RE.match(s) or PARAM_SEG_RE.match(s)):
                    errs.append(pre + "path 段落格式不對：%r" % s)
            if not COLL_ID_RE.match(segs[-1]):
                errs.append(pre + "path 最後一段必須是固定的集合 id")
        cid = collection_id(q)
        cspec = colls.get(cid)
        if cspec is None:
            errs.append(pre + "集合 %s 沒有在 collections 宣告" % cid)
            cspec = {}

        where = q.get("where", [])
        order = q.get("orderBy", [])
        if not isinstance(where, list) or not isinstance(order, list):
            errs.append(pre + "where／orderBy 要是清單")
            continue
        eq_fields, rng_fields = [], []
        for w in where:
            if not (isinstance(w, list) and len(w) == 3):
                errs.append(pre + "where 每一項要是 [欄位, 運算子, 值]")
                continue
            f, op, v = w
            if not FIELD_RE.match(str(f)):
                errs.append(pre + "where 欄位名稱不對：%r" % f)
            if op not in ALL_OPS:
                errs.append(pre + "where 運算子只能是 %s（%r 不支援）" % (" ".join(ALL_OPS), op))
            if isinstance(v, (list, dict)) or v is None:
                errs.append(pre + "where 的值只能是文字、數字、布林或 :參數")
            if (cid, f) in exempt_pairs:
                errs.append(pre + "欄位 %s 被 exempt 關掉索引，不能拿來查" % f)
            (eq_fields if op in EQ_OPS else rng_fields).append(f)
        if len(set(rng_fields)) > 1:
            errs.append(pre + "範圍條件（< <= > >=）只能用在一個欄位")
        for o in order:
            if not (isinstance(o, list) and len(o) == 2 and FIELD_RE.match(str(o[0])) and o[1] in DIRS):
                errs.append(pre + "orderBy 每一項要是 [欄位, \"asc\"|\"desc\"]")
                continue
            if o[0] in eq_fields:
                errs.append(pre + "orderBy 的欄位 %s 同時是 == 條件（沒意義，拿掉）" % o[0])
            if (cid, o[0]) in exempt_pairs:
                errs.append(pre + "欄位 %s 被 exempt 關掉索引，不能拿來排序" % o[0])
        if rng_fields and order and order[0][0] != rng_fields[0]:
            errs.append(pre + "有範圍條件時，第一個 orderBy 必須是那個欄位（Firestore 的要求）")

        is_count = bool(q.get("count"))
        if is_count:
            for k in ("orderBy", "limit", "limitToLast", "cursor", "watch"):
                if q.get(k):
                    errs.append(pre + "count 查詢不能帶 %s" % k)
        else:
            lim = q.get("limit")
            if not (isinstance(lim, int) and not isinstance(lim, bool) and 1 <= lim <= MAX_LIMIT):
                errs.append(pre + "要有 limit（1–%d）；不設上限的查詢會把讀取額度吃光" % MAX_LIMIT)
        cur = q.get("cursor")
        if cur is not None and cur not in CURSORS:
            errs.append(pre + "cursor 只能是 %s" % "／".join(CURSORS))
        if (cur or q.get("limitToLast")) and not order:
            errs.append(pre + "cursor／limitToLast 需要 orderBy")
        if q.get("limitToLast") and cur == "startAfter":
            errs.append(pre + "limitToLast 要搭 endBefore，不是 startAfter")
        for k in ("limitToLast", "count", "watch"):
            if k in q and not isinstance(q[k], bool):
                errs.append(pre + "%s 要是 true／false" % k)
        sc = q.get("sortClient", [])
        if not (isinstance(sc, list) and all(isinstance(s, list) and len(s) == 2 and s[1] in DIRS for s in sc)):
            errs.append(pre + "sortClient 每一項要是 [欄位, \"asc\"|\"desc\"]")

        members = [w for w in who if w not in PRIVILEGED]
        if members:
            if cspec.get("teacherOnly"):
                errs.append(pre + "集合 %s 只准導師查（who 裡有 %s）" % (cid, "、".join(members)))
            mf = cspec.get("memberFilter")
            if mf and list(mf) not in [list(w) for w in where]:
                errs.append(pre + "非導師查 %s 一定要帶 where %s %s %r（規則不是過濾器，少了整個查詢被拒）"
                            % (cid, mf[0], mf[1], mf[2]))
    return errs


# ── 推導索引 ────────────────────────────────────────────────────────────────

def required_indexes(q):
    """一個查詢需要的索引。回傳 dict：
         {"composite": (集合id, scope, ((欄位, ASC|DESC), ...))}   需要複合索引
         {"group_single": [(集合id, 欄位, ASC|DESC), ...]}          集合群組的單欄索引
         {}                                                        自動的單欄索引就夠（不產生任何東西）
    規則（DATA-MODEL §4.3）：
      1. 只有 == 條件、沒有範圍也沒有排序 → Firestore 用單欄索引合併，不需要複合索引。
      2. 沒有 == 條件、而且總共只牽涉一個欄位 → 單欄索引就夠。
      3. 其他 → 複合索引：== 欄位（↑，照登記順序）＋ orderBy 欄位（照方向）＋ 沒排序的範圍欄位（↑）。
      4. 集合群組查詢不走複合時，每個牽涉的欄位都要一個「集合群組範圍」的單欄索引（預設沒有）。
    """
    scope = "COLLECTION_GROUP" if q.get("group") else "COLLECTION"
    cid = collection_id(q)
    where, order = _where(q), _order(q)
    eq = []
    for f, op, _ in where:
        if op in EQ_OPS and f not in eq:
            eq.append(f)
    rng = []
    for f, op, _ in where:
        if op in RANGE_OPS and f not in rng:
            rng.append(f)
    order_fields = [f for f, _ in order]
    involved = list(eq) + [f for f in rng if f not in eq] + [f for f in order_fields if f not in eq and f not in rng]

    if not rng and not order:
        composite = None
    elif not eq and len(set(involved)) == 1:
        composite = None
    else:
        fields = [(f, "ASCENDING") for f in eq]
        fields += [(f, DIRS[d]) for f, d in order]
        fields += [(f, "ASCENDING") for f in rng if f not in order_fields]
        composite = tuple(fields)

    if composite:
        return {"composite": (cid, scope, composite)}
    if scope == "COLLECTION_GROUP":
        out = []
        for f in involved:
            d = "ASCENDING"
            for of, od in order:
                if of == f and od == "desc":
                    d = "DESCENDING"
            out.append((cid, f, d))
        return {"group_single": out}
    return {}


def build_index_file(reg):
    composites = set()
    group_single = {}
    for name, q in reg["queries"].items():
        need = required_indexes(q)
        if "composite" in need:
            composites.add(need["composite"])
        for cid, f, d in need.get("group_single", []):
            group_single.setdefault((cid, f), set()).add(d)

    indexes = []
    for cid, scope, fields in sorted(composites):
        indexes.append({
            "collectionGroup": cid,
            "queryScope": scope,
            "fields": [{"fieldPath": f, "order": d} for f, d in fields],
        })

    overrides = []
    exempt_pairs = {(e["collectionGroup"], e["fieldPath"]) for e in reg.get("exempt", [])}
    for (cid, f) in sorted(set(group_single) | exempt_pairs):
        if (cid, f) in exempt_pairs:
            if (cid, f) in group_single:
                raise RegistryError("%s.%s 同時被 exempt 又被集合群組查詢用到" % (cid, f))
            overrides.append({"collectionGroup": cid, "fieldPath": f, "indexes": []})
            continue
        idx = [dict(x) for x in DEFAULT_COLLECTION_INDEXES]
        for d in sorted(group_single[(cid, f)]):
            idx.append({"order": d, "queryScope": "COLLECTION_GROUP"})
        overrides.append({"collectionGroup": cid, "fieldPath": f, "indexes": idx})
    return {"indexes": indexes, "fieldOverrides": overrides}


# ── 輸出 ────────────────────────────────────────────────────────────────────

def render_indexes_json(reg):
    return json.dumps(build_index_file(reg), ensure_ascii=False, indent=2) + "\n"


def render_queries_js(reg):
    lines = []
    names = sorted(reg["queries"])
    for i, name in enumerate(names):
        q = dict(reg["queries"][name])
        q.pop("use", None)
        body = json.dumps(q, ensure_ascii=False, sort_keys=True, separators=(", ", ": "))
        lines.append("    %s: %s%s" % (json.dumps(name), body, "," if i < len(names) - 1 else ""))
    return (
        "/* 由 scripts/build_indexes.py 從 templates/queries.json 產生 —— 不要手改。\n"
        "   前端 Store.query／watch／count 只准用這裡的查詢名（docs/ARCHITECTURE.md §2.4）。\n"
        "   新增查詢：改 templates/queries.json → python3 scripts/build_indexes.py。 */\n"
        "(function (g) {\n"
        "  var C = g.CMW = g.CMW || {};\n"
        "  C.QUERIES = {\n" + "\n".join(lines) + "\n  };\n"
        "})(typeof window !== 'undefined' ? window : globalThis);\n"
    )


def _fmt_where(q):
    parts = []
    for f, op, v in _where(q):
        vv = v if is_param(v) else json.dumps(v, ensure_ascii=False)
        parts.append("%s %s %s" % (f, op, vv))
    return "、".join(parts) or "—"


def _fmt_index(q):
    need = required_indexes(q)
    arrow = {"ASCENDING": "↑", "DESCENDING": "↓"}
    if "composite" in need:
        cid, scope, fields = need["composite"]
        kind = "複合（集合群組）" if scope == "COLLECTION_GROUP" else "複合"
        return "%s：%s" % (kind, " ".join("%s%s" % (f, arrow[d]) for f, d in fields))
    if need.get("group_single"):
        return "集合群組單欄：%s" % " ".join("%s%s" % (f, arrow[d]) for _, f, d in need["group_single"])
    if not _order(q) and not any(op in RANGE_OPS for _, op, _ in _where(q)):
        return "不用（只有等號）" if _where(q) else "不用"
    return "不用（自動單欄）"


def render_markdown(reg):
    lines = [
        "| 查詢名 | 誰 | 集合 | where | orderBy | 上限／游標 | 索引 | 用在哪 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name in sorted(reg["queries"]):
        q = reg["queries"][name]
        coll = ("群組 `%s`" % q["group"]) if q.get("group") else "`%s`" % q["path"]
        order = "、".join("%s %s" % (f, d) for f, d in _order(q)) or "—"
        if q.get("count"):
            lim = "count"
        else:
            lim = str(q.get("limit"))
            if q.get("limitToLast"):
                lim += " limitToLast"
            if q.get("cursor"):
                lim += " " + q["cursor"]
            if q.get("watch"):
                lim += " 即時"
        if q.get("batch") != "v1":
            lim += "（%s）" % q["batch"]
        use = q["use"].replace("|", "／")
        lines.append("| `%s` | %s | %s | %s | %s | %s | %s | %s |" % (
            name, "、".join(q["who"]), coll, _fmt_where(q), order, lim, _fmt_index(q), use))
    return "\n".join(lines) + "\n"


def outputs(reg):
    """回傳 [(相對路徑 tuple, 內容字串)]。"""
    return [(INDEXES_REL, render_indexes_json(reg)), (QUERIES_JS_REL, render_queries_js(reg))]


def main(argv=None):
    ap = argparse.ArgumentParser(description="查詢形狀登記表 → firestore.indexes.json 與 site/js/core/queries.js")
    ap.add_argument("--check", action="store_true", help="只檢查（登記表合法＋產生檔是最新），不寫檔")
    ap.add_argument("--markdown", action="store_true", help="印出 DATA-MODEL §4.4 的查詢表")
    paths.add_root_arg(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)

    try:
        reg = load_registry()
        errs = validate_registry(reg)
        if errs:
            print("✗ 查詢登記表 templates/queries.json 有問題：")
            for e in errs:
                print("  ✗ %s" % e)
            return 1
        outs = outputs(reg)
    except RegistryError as e:
        print("✗ %s" % e)
        return 1

    if a.markdown:
        sys.stdout.write(render_markdown(reg))
        return 0

    if a.check:
        stale = []
        for rel, text in outs:
            p = paths.rpath(*rel)
            try:
                cur = p.read_text(encoding="utf-8")
            except OSError:
                cur = None
            if cur != text:
                stale.append("/".join(rel))
        if stale:
            print("✗ 產生檔不是最新的：%s" % "、".join(stale))
            print("  → 跑 python3 scripts/build_indexes.py 重新產生，連同 templates/queries.json 一起 commit。")
            return 1
        print("✓ 查詢登記表合法，firestore.indexes.json 與 site/js/core/queries.js 都是最新的"
              "（%d 個查詢）。" % len(reg["queries"]))
        return 0

    for rel, text in outs:
        p = paths.rpath(*rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("✓ 已產生 %s" % "/".join(rel))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
