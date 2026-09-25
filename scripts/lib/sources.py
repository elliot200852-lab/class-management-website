#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sources.py — 讀本機那三個有真名的檔：data/roster.csv、data/contacts.csv、data/parent-roles.yaml。

格式（正本說明在 data-template/README.md 與各檔開頭）：

  roster.csv      座號,姓名,稱呼,備註
                  「稱呼」＝家長在網站上看到的孩子稱呼（只放名、不放姓，1–10 字）。
  contacts.csv    座號,關係,姓名,Email,私密讀者,暫停,備註
                  一列一個「人 × 座號」。家長：座號必填、關係寫父／母／祖母……；
                  同仁：關係寫「同仁」，座號可空（只看班網）或填授權閱讀的座號（一列一個座號）。
                  私密讀者、暫停：填「是」（或 Y／1／v）＝是，空白＝否。
  parent-roles.yaml  每個座號「應該有帳號」的家長稱謂（不放 email、不放姓名），例如：
                  "01": [母, 父]
                  這份是安全閘的正本：contacts.csv 被截斷、壞掉時，靠它算出的下限擋下來。

**錯誤訊息只用「第幾列、哪一欄、座號」，絕不印姓名或 email**——代理的對話紀錄會看到這些輸出。
Excel 存的 CSV 常是 Big5（cp950）或帶 BOM，都讀得懂。
"""
import re
import csv
import io

from .seats import parse_seat
from .emailkey import email_key

ROSTER_COLS = {"seat": ("座號", "seat"), "name": ("姓名", "name"), "display": ("稱呼", "display_name", "displayName"),
               "note": ("備註", "note")}
CONTACT_COLS = {"seat": ("座號", "seat"), "relation": ("關係", "relation"), "name": ("姓名", "name"),
                "email": ("Email", "email", "EMAIL", "信箱", "電子郵件"), "private": ("私密讀者", "private"),
                "paused": ("暫停", "paused"), "note": ("備註", "note")}
STAFF_WORD = "同仁"
TRUE_WORDS = ("是", "y", "yes", "1", "v", "true", "✓", "○", "o")


class SourceError(Exception):
    def __init__(self, problems):
        super().__init__("；".join(problems))
        self.problems = list(problems)


def read_text(path, label):
    """讀文字檔：utf-8（含 BOM）→ 不行再試 cp950（Excel 繁中預設）。回 (文字, 提醒或 "")。"""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise SourceError(["找不到 %s（%s）" % (label, path.name)])
    except OSError:
        raise SourceError(["讀不到 %s（%s）" % (label, path.name)])
    if not raw.strip():
        raise SourceError(["%s 是空的" % label])
    try:
        return raw.decode("utf-8-sig"), ""
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp950"), ("%s 是 Big5 編碼（Excel 的預設），已經自動讀取；"
                                     "建議下次在 Excel 另存新檔時選「CSV UTF-8」。" % label)
    except UnicodeDecodeError:
        raise SourceError(["%s 的文字編碼讀不懂：請用 Excel 另存新檔，格式選「CSV UTF-8（逗號分隔）」" % label])


def _header_map(header, spec, label):
    idx = {}
    clean = [h.strip() for h in header]
    for key, names in spec.items():
        for n in names:
            if n in clean:
                idx[key] = clean.index(n)
                break
    return idx


def _rows(text, spec, required, label):
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise SourceError(["%s 沒有表頭" % label])
    idx = _header_map(header, spec, label)
    missing = [spec[k][0] for k in required if k not in idx]
    if missing:
        raise SourceError(["%s 的第一列（表頭）少了這幾欄：%s（應該是：%s）"
                           % (label, "、".join(missing), ",".join(spec[k][0] for k in spec))])
    out = []
    for lineno, row in enumerate(reader, start=2):
        if not any(c.strip() for c in row):
            continue
        rec = {k: (row[i].strip() if i < len(row) else "") for k, i in idx.items()}
        rec["_line"] = lineno
        out.append(rec)
    return out


def truthy(v):
    return (v or "").strip().lower() in TRUE_WORDS


class Student(object):
    __slots__ = ("seat", "name", "display", "line")

    def __init__(self, seat, name, display, line):
        self.seat, self.name, self.display, self.line = seat, name, display, line


def load_roster(path):
    """回 (學生清單（依座號排）, 提醒清單)。"""
    text, note = read_text(path, "data/roster.csv")
    rows = _rows(text, ROSTER_COLS, ("seat", "name", "display"), "data/roster.csv")
    problems, out, seen = [], [], set()
    for r in rows:
        ln = r["_line"]
        try:
            seat = parse_seat(r.get("seat", ""))
        except ValueError:
            problems.append("data/roster.csv 第 %d 列：座號格式不對（要是 1–40 的數字）" % ln)
            continue
        if seat in seen:
            problems.append("data/roster.csv 第 %d 列：座號 %s 重複了" % (ln, seat))
            continue
        seen.add(seat)
        name, disp = r.get("name", ""), r.get("display", "")
        if not (1 <= len(name) <= 40):
            problems.append("data/roster.csv 第 %d 列（座號 %s）：姓名是空的或超過 40 字" % (ln, seat))
        if not (1 <= len(disp) <= 10):
            problems.append("data/roster.csv 第 %d 列（座號 %s）：「稱呼」要 1–10 字（家長看到的孩子稱呼，只放名）"
                            % (ln, seat))
        out.append(Student(seat, name, disp, ln))
    if problems:
        raise SourceError(problems)
    if not out:
        raise SourceError(["data/roster.csv 只有表頭、沒有任何學生"])
    return sorted(out, key=lambda s: s.seat), [note] if note else []


class Contact(object):
    __slots__ = ("line", "seat", "relation", "key", "private", "paused", "staff")

    def __init__(self, line, seat, relation, key, private, paused, staff):
        self.line, self.seat, self.relation, self.key = line, seat, relation, key
        self.private, self.paused, self.staff = private, paused, staff


def load_contacts(path):
    """回 (聯絡人清單, 提醒清單)。email 已轉成 email 鍵；沒填 email 的列 key 是 None（不算有帳號）。"""
    text, note = read_text(path, "data/contacts.csv")
    rows = _rows(text, CONTACT_COLS, ("seat", "relation", "email"), "data/contacts.csv")
    problems, out = [], []
    for r in rows:
        ln = r["_line"]
        rel = r.get("relation", "")
        staff = rel == STAFF_WORD
        seat = None
        if r.get("seat", ""):
            try:
                seat = parse_seat(r["seat"])
            except ValueError:
                problems.append("data/contacts.csv 第 %d 列：座號格式不對（要是 1–40 的數字）" % ln)
                continue
        elif not staff:
            problems.append("data/contacts.csv 第 %d 列：家長一定要填座號（同仁才可以空著）" % ln)
            continue
        if not staff and not (1 <= len(rel) <= 10):
            problems.append("data/contacts.csv 第 %d 列（座號 %s）：「關係」要填（父、母、祖母……，最多 10 字；同仁填「同仁」）"
                            % (ln, seat))
            continue
        raw_email = r.get("email", "")
        key = None
        if raw_email:
            try:
                key = email_key(raw_email)
            except ValueError:
                problems.append("data/contacts.csv 第 %d 列%s：Email 格式不對"
                                % (ln, "（座號 %s）" % seat if seat else ""))
                continue
        out.append(Contact(ln, seat, "" if staff else rel, key, truthy(r.get("private")), truthy(r.get("paused")), staff))
    if problems:
        raise SourceError(problems)
    if not out:
        raise SourceError(["data/contacts.csv 只有表頭、沒有任何一列"])
    return out, [note] if note else []


def contact_emails(path):
    """{email 鍵: contacts.csv 裡老師打的那一串信箱}。讀不到回 {}。

    **只給資料退場寫「只給老師自己打開」的清單檔用**（Firebase 主控台刪登入帳號要貼完整信箱）：
    回傳的信箱不准印到螢幕、不准寫進別的檔。"""
    try:
        text, _ = read_text(path, "data/contacts.csv")
        rows = _rows(text, CONTACT_COLS, ("email",), "data/contacts.csv")
    except SourceError:
        return {}
    out = {}
    for r in rows:
        raw = r.get("email", "")
        if not raw:
            continue
        try:
            out.setdefault(email_key(raw), raw.strip())
        except ValueError:
            pass
    return out


# ── parent-roles.yaml（小型解析：只收兩種寫法）─────────────────────────

_FLOW_RE = re.compile(r"""^["']?(\d{1,2})["']?\s*:\s*\[(.*)\]\s*(#.*)?$""")
_KEY_RE = re.compile(r"""^["']?(\d{1,2})["']?\s*:\s*(#.*)?$""")
_ITEM_RE = re.compile(r"^\s+-\s*(.+?)\s*(#.*)?$")


def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1].strip()
    return s


def load_roles(path):
    """回 {座號: [稱謂, ...]}。兩種寫法：
         "01": [母, 父]
       或
         "01":
           - 母
           - 父
    """
    text, _ = read_text(path, "data/parent-roles.yaml")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out, problems, current = {}, [], None
    for lineno, line in enumerate(text.split("\n"), start=1):
        s = line.rstrip()
        if not s.strip() or s.strip().startswith("#"):
            continue
        m = _FLOW_RE.match(s)
        if m and not line[:1].isspace():
            seat = _seat_or_problem(m.group(1), lineno, problems)
            current = None
            if seat is None:
                continue
            if seat in out:
                problems.append("data/parent-roles.yaml 第 %d 行：座號 %s 寫了兩次" % (lineno, seat))
                continue
            items = [_unquote(x) for x in m.group(2).split(",") if x.strip()]
            out[seat] = items
            continue
        m = _KEY_RE.match(s)
        if m and not line[:1].isspace():
            seat = _seat_or_problem(m.group(1), lineno, problems)
            current = None
            if seat is None:
                continue
            if seat in out:
                problems.append("data/parent-roles.yaml 第 %d 行：座號 %s 寫了兩次" % (lineno, seat))
                continue
            out[seat] = []
            current = seat
            continue
        m = _ITEM_RE.match(line)
        if m and current is not None:
            out[current].append(_unquote(m.group(1)))
            continue
        problems.append("data/parent-roles.yaml 第 %d 行看不懂（寫法見檔案開頭的說明）" % lineno)
    for seat, items in out.items():
        for it in items:
            if not (1 <= len(it) <= 10):
                problems.append("data/parent-roles.yaml 座號 %s：稱謂要 1–10 字" % seat)
        if len(set(items)) != len(items):
            problems.append("data/parent-roles.yaml 座號 %s：同一個稱謂寫了兩次（同一個座號兩位「母」請寫成「母」「母2」這種可區分的寫法）"
                            % seat)
    if problems:
        raise SourceError(problems)
    if not out:
        raise SourceError(["data/parent-roles.yaml 沒有宣告任何座號"])
    return out


def _seat_or_problem(s, lineno, problems):
    try:
        return parse_seat(s)
    except ValueError:
        problems.append("data/parent-roles.yaml 第 %d 行：座號格式不對" % lineno)
        return None
