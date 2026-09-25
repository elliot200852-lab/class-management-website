#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rules_budget.py — 安全規則「文件存取次數」的靜態估算（開發與測試用；老師不會用到）。

為什麼要有這支：Firestore 規則裡每呼叫一次 get()／exists()／getAfter() 算一次「文件存取」，
正式環境的上限是單筆讀取與**查詢**各 10 次、批次寫入整批 20 次，超過就整個請求被拒。
但模擬器對查詢（list）量到的上限是 20，比正式環境寬——模擬器測試全綠，上線後查詢照樣可能被拒。
所以對每一條 allow，用規則原文估「最壞情況」的存取次數，超過 10 就讓測試失敗。

估法（刻意高估，寧可多算）：
  · 一條 allow 的條件裡，每出現一次 get(／exists(／getAfter(（前面不是「.」，所以 m.data.get(…) 不算）算 1 次；
  · 條件裡呼叫的自訂函式，把函式本體的次數整個加進來（遞迴展開；函式照規則語言的範圍規則找：
    先找自己所在的 match，再往外層找）；
  · 不管 && ／ || 的短路，兩邊都算；同一份文件被讀兩次也算兩次（不假設引擎會快取）；
  · 同一個路徑＋同一個操作如果有好幾條 allow 會被評估（例如 allow get 與 allow read 同時存在、
    或 {path=**} 的集合群組規則），全部加總。
另外列出「不重複的文件」數，給人看實際大概會讀幾份（正式環境同一請求同一份文件只算一次讀取費用）。

解析器只認這份專案規則檔用到的語法（rules_version、service、match、function、allow），
看到不認得的東西就丟 RulesParseError——寧可停下來，也不要默默跳過一段、估出一個假的「沒超過」。
另外有覆蓋檢查：整份檔裡的 get(／exists( 出現次數，必須等於解析出來的函式與 allow 裡的總數。

只用標準庫。Python 3.9 可跑。
"""
import re

LIMIT_SINGLE = 10   # 單筆讀取、查詢、單一寫入
LIMIT_BATCH = 20    # 批次寫入、交易：整批

OPS = ("get", "list", "create", "update", "delete")
_OP_EXPAND = {
    "read": ("get", "list"),
    "write": ("create", "update", "delete"),
    "get": ("get",), "list": ("list",),
    "create": ("create",), "update": ("update",), "delete": ("delete",),
}

ACCESS_FUNCS = ("get", "exists", "getAfter")
_ACCESS_RE = re.compile(r"(?<![\w.$])(get|exists|getAfter)\s*\(")
_CALL_RE = re.compile(r"(?<![\w.$])([A-Za-z_]\w*)\s*\(")
_DOC_PREFIX = "/databases/{database}/documents"


class RulesParseError(ValueError):
    pass


# ── 前處理：去註解、遮字串 ─────────────────────────────────────────────

def _strip_comments(text):
    """去掉 // 與 /* */ 註解（字串裡的不算），保留換行與其他字元位置的長度不變（換成空白）。"""
    out = []
    i, n = 0, len(text)
    quote = None
    while i < n:
        c = text[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j < 0:
                raise RulesParseError("/* 註解沒有結尾")
            seg = text[i:j + 2]
            out.append("".join("\n" if ch == "\n" else " " for ch in seg))
            i = j + 2
            continue
        out.append(c)
        i += 1
    if quote:
        raise RulesParseError("字串沒有結尾")
    return "".join(out)


def _mask_strings(text):
    """字串字面值的內容換成空白（引號保留），讓正規式不會在字串裡找到 get( 之類的東西。"""
    out = []
    quote = None
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if quote:
            if c == "\\" and i + 1 < n:
                out.append("  ")
                i += 2
                continue
            if c == quote:
                quote = None
                out.append(c)
            else:
                out.append("\n" if c == "\n" else " ")
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
        out.append(c)
        i += 1
    return "".join(out)


def _match_close(masked, open_idx, open_ch, close_ch):
    depth = 0
    for j in range(open_idx, len(masked)):
        ch = masked[j]
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return j
    raise RulesParseError("%s 沒有配對的 %s（位置 %d）" % (open_ch, close_ch, open_idx))


# ── 結構 ───────────────────────────────────────────────────────────────

class Function(object):
    def __init__(self, name, params, body, masked_body, scope):
        self.name, self.params, self.body, self.masked_body, self.scope = name, params, body, masked_body, scope


class Allow(object):
    def __init__(self, ops, expr, masked_expr):
        self.ops, self.expr, self.masked_expr = ops, expr, masked_expr


class Block(object):
    def __init__(self, path, parent):
        self.path = path            # 完整路徑（含外層 match）
        self.parent = parent
        self.functions = {}
        self.allows = []
        self.children = []

    def lookup(self, name):
        b = self
        while b is not None:
            if name in b.functions:
                return b.functions[name]
            b = b.parent
        return None

    def walk(self):
        yield self
        for c in self.children:
            for x in c.walk():
                yield x

    @property
    def is_recursive(self):
        return "=**}" in self.path


_MATCH_HEAD_RE = re.compile(r"match\s+(/\S*)\s*\{")
_FUNC_HEAD_RE = re.compile(r"function\s+([A-Za-z_]\w*)\s*\(([^()]*)\)\s*\{")
_ALLOW_HEAD_RE = re.compile(r"allow\s+([a-z]+(?:\s*,\s*[a-z]+)*)\s*(:\s*if\b)?")


def _parse_body(text, masked, start, end, block):
    """解析 [start, end) 這段區塊內容，填進 block。"""
    i = start
    while i < end:
        m = re.compile(r"\S").search(masked, i, end)
        if not m:
            return
        i = m.start()
        rest = masked[i:end]
        if rest.startswith("match") and re.match(r"match\s", rest):
            mm = _MATCH_HEAD_RE.match(masked, i, end)
            if not mm:
                raise RulesParseError("看不懂的 match（位置 %d）" % i)
            brace = mm.end() - 1
            path = mm.group(1)
            close = _match_close(masked, brace, "{", "}")
            child = Block(block.path + path, block)
            block.children.append(child)
            _parse_body(text, masked, brace + 1, close, child)
            i = close + 1
            continue
        if rest.startswith("function"):
            fm = _FUNC_HEAD_RE.match(masked, i, end)
            if not fm:
                raise RulesParseError("看不懂的 function 宣告（位置 %d）" % i)
            name = fm.group(1)
            params = [p.strip() for p in fm.group(2).split(",") if p.strip()]
            brace = fm.end() - 1
            close = _match_close(masked, brace, "{", "}")
            if name in block.functions:
                raise RulesParseError("同一層重複定義函式 %s" % name)
            block.functions[name] = Function(name, params, text[brace + 1:close], masked[brace + 1:close], block)
            i = close + 1
            continue
        if rest.startswith("allow"):
            am = _ALLOW_HEAD_RE.match(masked, i, end)
            if not am:
                raise RulesParseError("看不懂的 allow（位置 %d）" % i)
            ops = []
            for raw in am.group(1).split(","):
                op = raw.strip()
                if op not in _OP_EXPAND:
                    raise RulesParseError("不認得的操作 %r（位置 %d）" % (op, i))
                ops.extend(_OP_EXPAND[op])
            j = am.end()
            if am.group(2):
                depth = 0
                k = j
                while k < end:
                    ch = masked[k]
                    if ch in "([{":
                        depth += 1
                    elif ch in ")]}":
                        depth -= 1
                        if depth < 0:
                            raise RulesParseError("allow 的條件括號不平衡（位置 %d）" % i)
                    elif ch == ";" and depth == 0:
                        break
                    k += 1
                if k >= end:
                    raise RulesParseError("allow 沒有分號結尾（位置 %d）" % i)
                expr, mexpr = text[j:k], masked[j:k]
            else:
                k = masked.index(";", j)
                if masked[j:k].strip():
                    raise RulesParseError("allow 後面看不懂（位置 %d）" % i)
                expr = mexpr = "true"
            block.allows.append(Allow(tuple(ops), expr.strip(), mexpr.strip()))
            i = k + 1
            continue
        raise RulesParseError("看不懂的內容，從這裡開始：%r" % rest[:40])


def parse(text):
    """規則原文 → 最外層 Block（path == ''）。第一層必須是 rules_version＋service cloud.firestore。"""
    clean = _strip_comments(text)
    masked = _mask_strings(clean)
    root = Block("", None)
    i = 0
    n = len(masked)
    m = re.compile(r"\s*rules_version\s*=\s*'2'\s*;").match(clean, 0)
    if m:
        i = m.end()
    sm = re.compile(r"\s*service\s+cloud\.firestore\s*\{").match(masked, i)
    if not sm:
        raise RulesParseError("找不到 service cloud.firestore {")
    brace = sm.end() - 1
    close = _match_close(masked, brace, "{", "}")
    if masked[close + 1:].strip():
        raise RulesParseError("service 區塊後面還有東西")
    _parse_body(clean, masked, brace + 1, close, root)
    root._clean, root._masked = clean, masked
    return root


# ── 估算 ───────────────────────────────────────────────────────────────

def _cost(masked, text, scope, stack):
    """回傳 (最壞情況呼叫次數, 不重複的文件路徑集合)。"""
    calls = 0
    docs = set()
    for m in _ACCESS_RE.finditer(masked):
        calls += 1
        open_idx = m.end() - 1
        close = _match_close(masked, open_idx, "(", ")")
        docs.add(re.sub(r"\s+", "", text[open_idx + 1:close]))
    for m in _CALL_RE.finditer(masked):
        name = m.group(1)
        if name in ACCESS_FUNCS:
            continue
        fn = scope.lookup(name)
        if fn is None:
            continue    # 內建函式（int、string、math…）或關鍵字（return (…)）
        if name in stack:
            raise RulesParseError("函式遞迴呼叫：%s（規則語言不准遞迴）" % " → ".join(stack + (name,)))
        c, d = _cost(fn.masked_body, fn.body, fn.scope, stack + (name,))
        calls += c
        docs |= d
    return calls, docs


def _short(path):
    return path[len(_DOC_PREFIX):] if path.startswith(_DOC_PREFIX) else path


def _short_doc(doc):
    return doc.replace("/databases/$(database)/documents", "")


def analyze(text):
    """回傳 [{path, op, calls, docs}]：每個 match 路徑 × 每種操作的最壞情況存取次數。

    只列有 allow 的路徑；{path=**} 那種遞迴規則的次數加到每一列（保守：假設它們都會被一起評估）。
    """
    root = parse(text)
    blocks = [b for b in root.walk() if b.allows]
    recursive = [b for b in blocks if b.is_recursive]
    rows = []
    for b in blocks:
        for op in OPS:
            stmts = [(b, a) for a in b.allows if op in a.ops]
            if not stmts:
                continue
            if not b.is_recursive:
                stmts += [(rb, a) for rb in recursive for a in rb.allows if op in a.ops]
            calls, docs = 0, set()
            for blk, a in stmts:
                c, d = _cost(a.masked_expr, a.expr, blk, ())
                calls += c
                docs |= d
            rows.append({"path": _short(b.path), "op": op, "calls": calls,
                         "docs": sorted(_short_doc(x) for x in docs)})
    return rows


def coverage(text):
    """(整份檔的 get(／exists(／getAfter( 次數, 解析出來的函式與 allow 裡的次數)。兩個數字必須相等。"""
    root = parse(text)
    total = len(_ACCESS_RE.findall(root._masked))
    seen = 0
    for b in root.walk():
        for fn in b.functions.values():
            seen += len(_ACCESS_RE.findall(fn.masked_body))
        for a in b.allows:
            seen += len(_ACCESS_RE.findall(a.masked_expr))
    return total, seen


# 瀏覽器會送的批次寫入（DATA-MODEL §1.6、§2.14）：[(路徑, 操作, 幾個)]
BATCHES = [
    ("部落格發文批次（1 篇文章＋3 縮圖＋3 顯示圖）", [
        ("/student_blogs/{seat}/entries/{postId}", "create", 1),
        ("/student_blogs/{seat}/entries/{postId}/thumbs/{pid}", "create", 3),
        ("/student_blogs/{seat}/entries/{postId}/images/{pid}", "create", 3),
    ]),
]


def batch_totals(rows):
    """回傳 [(批次名稱, 最壞情況總次數)]；找不到對應的路徑就丟 RulesParseError。"""
    index = {(r["path"], r["op"]): r["calls"] for r in rows}
    out = []
    for name, parts in BATCHES:
        total = 0
        for path, op, count in parts:
            if (path, op) not in index:
                raise RulesParseError("批次「%s」要的 %s %s 在規則裡找不到" % (name, op, path))
            total += index[(path, op)] * count
        out.append((name, total))
    return out


def problems(rows, batches):
    """超過上限的項目（空清單＝全部沒超過）。"""
    bad = ["%s %s：最壞 %d 次 > %d" % (r["op"], r["path"], r["calls"], LIMIT_SINGLE)
           for r in rows if r["calls"] > LIMIT_SINGLE]
    bad += ["%s：最壞 %d 次 > %d" % (name, total, LIMIT_BATCH) for name, total in batches if total > LIMIT_BATCH]
    return bad


def report_lines(rows, batches):
    """給人看的表（只列會讀文件的列；全部為 0 的列省略）。"""
    lines = ["文件存取次數靜態檢查（最壞情況：不短路、不假設快取；上限 單筆／查詢 %d、批次 %d）"
             % (LIMIT_SINGLE, LIMIT_BATCH)]
    shown = [r for r in rows if r["calls"] > 0]
    width = max([len(r["path"]) for r in shown] + [10])
    for r in shown:
        mark = "✓" if r["calls"] <= LIMIT_SINGLE else "✗"
        lines.append("  %s %-6s %-*s  最壞 %2d 次（不重複文件 %d 份）"
                     % (mark, r["op"], width, r["path"], r["calls"], len(r["docs"])))
    zero = len(rows) - len(shown)
    lines.append("  （另有 %d 個路徑×操作完全不讀其他文件，省略）" % zero)
    for name, total in batches:
        mark = "✓" if total <= LIMIT_BATCH else "✗"
        lines.append("  %s %s：整批最壞 %d 次" % (mark, name, total))
    list_max = max([r["calls"] for r in rows if r["op"] == "list"] + [0])
    lines.append("  查詢（list）最壞 %d 次；正式環境上限 %d（模擬器量到 20，所以這一項只能靠這支檢查）"
                 % (list_max, LIMIT_SINGLE))
    return lines
