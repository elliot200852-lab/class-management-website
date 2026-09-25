#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""schema.py — docs/DATA-MODEL.md 欄位白名單的 Python 版：腳本寫入前先驗，不合就不寫。

管理腳本走 IAM、不受安全規則管，所以「規則寫 if false 的集合」全靠這支守門：
多一欄、少一欄、型別不對、超過上限，一律拒絕（problems() 回問題清單，ensure() 丟 SchemaError）。

時間欄（updatedAt 等）可以是 firestore_rest.SERVER_TIME（寫入時由伺服器填）或讀回來的 Timestamp。
"""
import re

from . import blocks as blk
from .firestore_rest import SERVER_TIME, Timestamp

SEAT_RE = re.compile(r"^(0[1-9]|[1-3][0-9]|40)$")
ALIAS_RE = re.compile(r"^[a-z0-9]{12}$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
SLUG_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(-[a-z0-9]+)+$")
POST_ID_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]{8}$")
PAGE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
PID_HASH_RE = re.compile(r"^[0-9a-f]{16}$")
PID_BLOG_RE = re.compile(r"^[0-2]$")
B64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
LABEL_RE = re.compile(r"^座號 [0-9、]+ (家長|同仁)$")

MAX_SLUG = 80
THUMB_MAX = 49152
IMAGE_MAX = 716800
INLINE_THUMB_MAX = 32768       # coverThumb、avatar
DOC_MAX = 1048576
BLOCKS_DOC_MAX = 800 * 1024
PAGE_KINDS = ("home", "course", "schedule", "about", "fun", "calendar", "standalone", "poem")

# v1.1（DATA-MODEL §2.11 每日一詩、§2.18 座位表／家長合照／個人照）
PLAN_ID_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(-[1-9][0-9]?)?$")
POEM_PAGE_RE = re.compile(r"^poems-([0-9]{4}-[0-9]{2})$")
MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
SEAT_AISLE = "-"               # 座位表的走道（不畫桌子）；空字串＝空位（畫一張空桌子）
SEATING_MAX_ROWS = 15
SEATING_MAX_COLS = 15
POEM_MAX_ITEMS = 31
POEM_TEXT_MAX = 2000
POEM_GUIDE_MAX = 1000


class SchemaError(ValueError):
    def __init__(self, kind, problems):
        super().__init__("%s：%s" % (kind, "；".join(problems)))
        self.kind = kind
        self.problems = list(problems)


def valid_slug(s):
    return isinstance(s, str) and len(s) <= MAX_SLUG and bool(SLUG_RE.match(s))


def valid_date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        return False
    y, m, d = (int(x) for x in s.split("-"))
    return 1 <= m <= 12 and 1 <= d <= 31 and 2000 <= y <= 2100


# ── 小工具 ───────────────────────────────────────────────────────────────

class _V(object):
    def __init__(self, data, problems):
        self.d = data
        self.p = problems

    def _bad(self, f, msg):
        self.p.append("%s %s" % (f, msg))

    def keys(self, required, optional=()):
        if not isinstance(self.d, dict):
            self.p.append("文件不是物件")
            return False
        extra = set(self.d) - set(required) - set(optional)
        if extra:
            self.p.append("多了不准有的欄位：%s" % "、".join(sorted(extra)))
        missing = [k for k in required if k not in self.d]
        if missing:
            self.p.append("少了必填欄位：%s" % "、".join(missing))
        return True

    def has(self, f):
        return isinstance(self.d, dict) and f in self.d

    def string(self, f, lo, hi, allow_missing=False):
        if not self.has(f):
            return
        v = self.d[f]
        if not isinstance(v, str):
            self._bad(f, "要是文字")
        elif not (lo <= len(v) <= hi):
            self._bad(f, "長度要在 %d–%d 字之間（現在 %d）" % (lo, hi, len(v)))

    def match(self, f, rx, what):
        if self.has(f) and (not isinstance(self.d[f], str) or not rx.match(self.d[f])):
            self._bad(f, "格式不對（%s）" % what)

    def integer(self, f, lo=None, hi=None):
        if not self.has(f):
            return
        v = self.d[f]
        if isinstance(v, bool) or not isinstance(v, int):
            self._bad(f, "要是整數")
        elif (lo is not None and v < lo) or (hi is not None and v > hi):
            self._bad(f, "要在 %s–%s 之間" % (lo, hi))

    def boolean(self, f):
        if self.has(f) and not isinstance(self.d[f], bool):
            self._bad(f, "要是 true／false")

    def ts(self, f):
        if self.has(f) and not (self.d[f] is SERVER_TIME or isinstance(self.d[f], Timestamp)):
            self._bad(f, "要是時間（伺服器時間）")

    def https(self, f, allow_empty=False):
        if not self.has(f):
            return
        v = self.d[f]
        if allow_empty and v == "":
            return
        if not blk.is_https(v, 500):
            self._bad(f, "要是 https:// 開頭的網址（≤ 500 字）")

    def date(self, f):
        if self.has(f) and not valid_date(self.d[f]):
            self._bad(f, "要是 YYYY-MM-DD 的日期")


def _b64(v, hi):
    return isinstance(v, str) and 1 <= len(v) <= hi and bool(B64_RE.match(v)) and len(v) % 4 == 0


def _inline_photo(v, p, f):
    """coverThumb／avatar：null 或 {data ≤ 32768, w, h}。"""
    if v is None:
        return
    if not isinstance(v, dict) or set(v) != {"data", "w", "h"}:
        p.append("%s 要是 null 或 {data, w, h}" % f)
        return
    if not _b64(v["data"], INLINE_THUMB_MAX):
        p.append("%s.data 不是 base64 或超過 %d 字元" % (f, INLINE_THUMB_MAX))
    for k in ("w", "h"):
        if isinstance(v[k], bool) or not isinstance(v[k], int) or not (1 <= v[k] <= 480):
            p.append("%s.%s 要是 1–480 的整數" % (f, k))


def _blocks(v, p):
    for x in blk.problems(v):
        p.append("正文：" + x)


# ── 各種文件 ─────────────────────────────────────────────────────────────

def _allowlist(d, p):
    v = _V(d, p)
    v.keys(["kind", "alias", "updatedAt"])
    if v.has("kind") and d["kind"] not in ("teacher", "parent", "staff"):
        p.append("kind 只能是 teacher／parent／staff")
    v.match("alias", ALIAS_RE, "12 碼小寫英數")
    v.ts("updatedAt")


def _private_allowlist(d, p):
    v = _V(d, p)
    v.keys(["updatedAt"])
    v.ts("updatedAt")


def _parent_child_map(d, p):
    v = _V(d, p)
    v.keys(["seats", "kind", "active", "label", "updatedAt"], ["relation"])
    seats = d.get("seats") if isinstance(d, dict) else None
    if not isinstance(seats, list) or not (1 <= len(seats) <= 3) or \
            not all(isinstance(s, str) and SEAT_RE.match(s) for s in seats) or len(set(seats)) != len(seats):
        p.append("seats 要是 1–3 個不重複的座號（01–40）")
    if v.has("kind") and d["kind"] not in ("parent", "staff"):
        p.append("kind 只能是 parent／staff")
    v.boolean("active")
    v.string("relation", 1, 10)
    if v.has("relation") and d.get("kind") == "staff":
        p.append("同仁不填 relation")
    v.string("label", 1, 20)
    v.match("label", LABEL_RE, "「座號 04 家長」這種不含姓名的字樣")
    v.ts("updatedAt")


def _config_site(d, p):
    v = _V(d, p)
    v.keys(["teacherDisplayName", "schoolName", "studentsCount", "calendarIcsUrl", "updatedAt"])
    v.string("teacherDisplayName", 1, 20)
    v.string("schoolName", 0, 60)
    v.integer("studentsCount", 1, 40)
    v.https("calendarIcsUrl", allow_empty=True)
    v.ts("updatedAt")


def _roster_students(d, p):
    v = _V(d, p)
    v.keys(["students", "updatedAt"])
    st = d.get("students") if isinstance(d, dict) else None
    if not isinstance(st, list) or len(st) > 40:
        p.append("students 要是最多 40 筆的陣列")
    else:
        seen = set()
        for i, s in enumerate(st):
            if not isinstance(s, dict) or set(s) != {"seat", "name", "displayName"}:
                p.append("students 第 %d 筆要剛好是 {seat, name, displayName}" % (i + 1))
                continue
            if not isinstance(s["seat"], str) or not SEAT_RE.match(s["seat"]) or s["seat"] in seen:
                p.append("students 第 %d 筆的座號不對或重複" % (i + 1))
            seen.add(s["seat"])
            if not isinstance(s["name"], str) or not (1 <= len(s["name"]) <= 40):
                p.append("students 第 %d 筆的 name 要 1–40 字" % (i + 1))
            if not isinstance(s["displayName"], str) or not (1 <= len(s["displayName"]) <= 10):
                p.append("students 第 %d 筆的 displayName 要 1–10 字" % (i + 1))
    v.ts("updatedAt")


def _cover(d, p):
    cp = d.get("coverPid") if isinstance(d, dict) else None
    if cp is not None and (not isinstance(cp, str) or not PID_HASH_RE.match(cp)):
        p.append("coverPid 要是 null 或照片 pid")
    _inline_photo(d.get("coverThumb") if isinstance(d, dict) else None, p, "coverThumb")
    if isinstance(d, dict) and (cp is None) != (d.get("coverThumb") is None):
        p.append("coverPid 與 coverThumb 要同時有或同時沒有")


def _post(d, p):
    v = _V(d, p)
    v.keys(["title", "date", "category", "excerpt", "coverPid", "coverThumb", "photoCount", "visible",
            "publishedAt", "updatedAt"])
    v.string("title", 1, 120)
    v.date("date")
    v.string("category", 1, 40)
    v.string("excerpt", 0, 200)
    _cover(d, p)
    v.integer("photoCount", 0, 9999)
    v.boolean("visible")
    v.ts("publishedAt")
    v.ts("updatedAt")


def _post_content(d, p):
    v = _V(d, p)
    v.keys(["blocks", "updatedAt"])
    _blocks(d.get("blocks") if isinstance(d, dict) else None, p)
    v.ts("updatedAt")


def _album(d, p):
    v = _V(d, p)
    v.keys(["title", "date", "order", "coverPid", "coverThumb", "photoCount", "videos", "visible", "updatedAt"],
           ["description", "linkUrl"])
    v.string("title", 1, 80)
    v.date("date")
    v.string("description", 0, 1000)
    v.integer("order", -999999999, 999999999)
    _cover(d, p)
    v.integer("photoCount", 0, 9999)
    vids = d.get("videos") if isinstance(d, dict) else None
    if not isinstance(vids, list) or len(vids) > 20:
        p.append("videos 要是最多 20 支的陣列")
    else:
        for i, x in enumerate(vids):
            if not isinstance(x, dict) or set(x) != {"title", "url"} or not isinstance(x["title"], str) \
                    or not (0 <= len(x["title"]) <= 80) or not blk.is_https(x["url"], 500):
                p.append("videos 第 %d 支要是 {title ≤ 80 字, url 是 https://}" % (i + 1))
    v.https("linkUrl")
    v.boolean("visible")
    v.ts("updatedAt")


def _private_post(d, p):
    v = _V(d, p)
    v.keys(["title", "date", "excerpt", "blocks", "coverPid", "coverThumb", "photoCount", "visible",
            "publishedAt", "updatedAt"])
    v.string("title", 1, 120)
    v.date("date")
    v.string("excerpt", 0, 200)
    _blocks(d.get("blocks") if isinstance(d, dict) else None, p)
    _cover(d, p)
    v.integer("photoCount", 0, 9999)
    v.boolean("visible")
    v.ts("publishedAt")
    v.ts("updatedAt")


def _page(d, p):
    v = _V(d, p)
    v.keys(["title", "kind", "order", "visible", "updatedAt"], ["blocks", "data"])
    v.string("title", 1, 80)
    kind = d.get("kind") if isinstance(d, dict) else None
    if kind not in PAGE_KINDS:
        p.append("kind 不認得")
    v.integer("order", -999999, 999999)
    v.boolean("visible")
    v.ts("updatedAt")
    if v.has("blocks"):
        _blocks(d["blocks"], p)
    data = d.get("data") if isinstance(d, dict) else None
    if kind == "poem" and v.has("blocks"):
        p.append("poem 頁不用 blocks")
    if data is None:
        if kind in ("home", "fun", "poem"):
            p.append("%s 頁要有 data" % kind)
        return
    if not isinstance(data, dict):
        p.append("data 要是物件")
        return
    if kind in ("about", "standalone"):
        p.append("%s 頁不用 data" % kind)
    elif kind == "home":
        if set(data) - {"bannerText", "bannerPid"} or not isinstance(data.get("bannerText"), str) \
                or len(data.get("bannerText", "")) > 200:
            p.append("home 的 data 要是 {bannerText ≤ 200 字, bannerPid?}")
        if "bannerPid" in data and (not isinstance(data["bannerPid"], str) or not PID_HASH_RE.match(data["bannerPid"])):
            p.append("bannerPid 格式不對")
    elif kind == "fun":
        cards = data.get("cards")
        if set(data) != {"cards"} or not isinstance(cards, list) or len(cards) > 100:
            p.append("fun 的 data 要是 {cards: [...]}（最多 100 張）")
        else:
            for i, c in enumerate(cards):
                if not isinstance(c, dict) or set(c) - {"title", "text", "pid"} or \
                        not isinstance(c.get("title"), str) or not (1 <= len(c["title"]) <= 40) or \
                        not isinstance(c.get("text"), str) or len(c["text"]) > 300 or \
                        ("pid" in c and (not isinstance(c["pid"], str) or not PID_HASH_RE.match(c["pid"]))):
                    p.append("fun 卡片第 %d 張要是 {title 1–40 字, text ≤ 300 字, pid?}" % (i + 1))
    elif kind == "poem":
        _poem_data(data, p)


def _poem_data(data, p):
    """每日一詩（一個月一份）：{ month: 'YYYY-MM', items: [{date, title, author, text, source?, guide?}] }。"""
    if set(data) != {"month", "items"}:
        p.append("poem 的 data 要剛好是 {month, items}")
        return
    month = data.get("month")
    if not isinstance(month, str) or not MONTH_RE.match(month):
        p.append("poem 的 month 要是 YYYY-MM")
        month = None
    items = data.get("items")
    if not isinstance(items, list) or not (1 <= len(items) <= POEM_MAX_ITEMS):
        p.append("poem 的 items 要是 1–%d 首" % POEM_MAX_ITEMS)
        return
    seen = set()
    for i, it in enumerate(items):
        n = i + 1
        if not isinstance(it, dict) or not {"date", "title", "author", "text"} <= set(it) or \
                set(it) - {"date", "title", "author", "text", "source", "guide"}:
            p.append("第 %d 首要是 {date, title, author, text, source?, guide?}" % n)
            continue
        d = it["date"]
        if not valid_date(d):
            p.append("第 %d 首的 date 要是 YYYY-MM-DD" % n)
        elif month and not d.startswith(month + "-"):
            p.append("第 %d 首的日期（%s）不在 %s" % (n, d, month))
        elif d in seen:
            p.append("%s 有兩首詩" % d)
        seen.add(d)
        for f, lo, hi in (("title", 1, 80), ("author", 1, 40), ("text", 1, POEM_TEXT_MAX), ("source", 0, 200),
                          ("guide", 0, POEM_GUIDE_MAX)):
            if f in it and (not isinstance(it[f], str) or not (lo <= len(it[f]) <= hi)):
                p.append("第 %d 首的 %s 要 %d–%d 字" % (n, f, lo, hi))


def seating_cell_ok(s):
    return isinstance(s, str) and (s in ("", SEAT_AISLE) or bool(SEAT_RE.match(s)))


def _seating(d, p):
    v = _V(d, p)
    v.keys(["title", "date", "rows", "note", "updatedAt"])
    v.string("title", 1, 60)
    v.date("date")
    v.string("note", 0, 500)
    rows = d.get("rows") if isinstance(d, dict) else None
    if not isinstance(rows, list) or not (1 <= len(rows) <= SEATING_MAX_ROWS):
        p.append("rows 要是 1–%d 排" % SEATING_MAX_ROWS)
    else:
        seen = set()
        for i, r in enumerate(rows):
            seats = r.get("seats") if isinstance(r, dict) and set(r) == {"seats"} else None
            if not isinstance(seats, list) or not (1 <= len(seats) <= SEATING_MAX_COLS):
                p.append("rows 第 %d 排要是 {seats: [1–%d 格]}" % (i + 1, SEATING_MAX_COLS))
                continue
            for s in seats:
                if not seating_cell_ok(s):
                    p.append("rows 第 %d 排有一格不是座號、空位（\"\"）或走道（\"-\"）" % (i + 1))
                elif s not in ("", SEAT_AISLE):
                    if s in seen:
                        p.append("座號 %s 在座位表裡出現兩次" % s)
                    seen.add(s)
        if not seen:
            p.append("座位表裡至少要有一位學生")
    v.ts("updatedAt")


def _pid_list(d, p, f="photoPids"):
    pids = d.get(f) if isinstance(d, dict) else None
    if not isinstance(pids, list) or not (1 <= len(pids) <= 3) or \
            not all(isinstance(x, str) and PID_HASH_RE.match(x) for x in pids) or len(set(pids)) != len(pids):
        p.append("%s 要是 1–3 個不重複的照片 pid" % f)


def _personal_photos(d, p):
    v = _V(d, p)
    v.keys(["photoPids", "updatedAt"])
    _pid_list(d, p)
    v.ts("updatedAt")


def _parent_photo_display(d, p):
    v = _V(d, p)
    v.keys(["relations", "note", "photoPids", "updatedAt"])
    rel = d.get("relations") if isinstance(d, dict) else None
    if not isinstance(rel, list) or len(rel) > 4 or \
            not all(isinstance(x, str) and 1 <= len(x) <= 10 for x in rel) or len(set(rel)) != len(rel):
        p.append("relations 要是 0–4 個不重複的稱謂（每個 1–10 字，例如 母、父）")
    v.string("note", 0, 200)
    _pid_list(d, p)
    v.ts("updatedAt")


def _student_blog(d, p):
    v = _V(d, p)
    v.keys(["seat", "displayName", "avatar", "updatedAt"], ["intro"])
    v.match("seat", SEAT_RE, "01–40")
    v.string("displayName", 1, 10)
    v.string("intro", 0, 500)
    if isinstance(d, dict) and "avatar" in d:
        _inline_photo(d["avatar"], p, "avatar")
    v.ts("updatedAt")


def _entry(d, p):
    v = _V(d, p)
    v.keys(["title", "body", "date", "author", "authorAlias", "photos", "visible", "createdAt"], ["updatedAt"])
    v.string("title", 1, 200)
    v.string("body", 1, 10000)
    v.date("date")
    if v.has("author") and d["author"] not in ("parent", "teacher"):
        p.append("author 只能是 parent／teacher")
    v.match("authorAlias", ALIAS_RE, "12 碼小寫英數")
    photos = d.get("photos") if isinstance(d, dict) else None
    if not isinstance(photos, list) or len(photos) > 3:
        p.append("photos 要是 0–3 張")
    else:
        for i, ph in enumerate(photos):
            if not isinstance(ph, dict) or set(ph) - {"pid", "w", "h", "caption"} or ph.get("pid") != str(i):
                p.append("photos 第 %d 張要是 {pid: '%d', w, h, caption?}" % (i + 1, i))
                continue
            for k, hi in (("w", 1600), ("h", 1600)):
                if isinstance(ph.get(k), bool) or not isinstance(ph.get(k), int) or not (1 <= ph[k] <= hi):
                    p.append("photos 第 %d 張的 %s 不對" % (i + 1, k))
            if "caption" in ph and (not isinstance(ph["caption"], str) or len(ph["caption"]) > 300):
                p.append("photos 第 %d 張的圖說超過 300 字" % (i + 1))
    v.boolean("visible")
    if v.has("visible") and d["visible"] is not True:
        p.append("新文章的 visible 要是 true")
    v.ts("createdAt")
    v.ts("updatedAt")


def _thumb(d, p, blog=False, pid=None):
    v = _V(d, p)
    if blog:
        v.keys(["data", "w", "h", "order"])
    else:
        v.keys(["data", "w", "h", "order"], ["caption"])
    if isinstance(d, dict) and "data" in d and not _b64(d["data"], THUMB_MAX):
        p.append("縮圖 data 不是 base64 或超過 %d 字元" % THUMB_MAX)
    v.integer("w", 1, 480)
    v.integer("h", 1, 480)
    v.integer("order", 0, 9999)
    v.string("caption", 0, 300)
    if blog and pid is not None and isinstance(d, dict) and d.get("order") != int(pid):
        p.append("部落格照片的 order 要等於 pid")


def _image(d, p):
    v = _V(d, p)
    v.keys(["data", "w", "h"])
    if isinstance(d, dict) and "data" in d and not _b64(d["data"], IMAGE_MAX):
        p.append("顯示圖 data 不是 base64 或超過 %d 字元" % IMAGE_MAX)
    v.integer("w", 1, 1600)
    v.integer("h", 1, 1600)


CHECKERS = {
    "allowlist": _allowlist,
    "private_allowlist": _private_allowlist,
    "parent_child_map": _parent_child_map,
    "config_site": _config_site,
    "roster_students": _roster_students,
    "post": _post,
    "post_content": _post_content,
    "album": _album,
    "private_post": _private_post,
    "page": _page,
    "student_blog": _student_blog,
    "entry": _entry,
    "thumb": lambda d, p: _thumb(d, p),
    "image": _image,
    "seating": _seating,
    "personal_photos": _personal_photos,
    "parent_photo_display": _parent_photo_display,
}


def problems(kind, data, **kw):
    if kind == "blog_thumb":
        out = []
        _thumb(data, out, blog=True, pid=kw.get("pid"))
        return out
    if kind == "blog_image":
        kind = "image"
    out = []
    CHECKERS[kind](data, out)
    return out


def ensure(kind, data, **kw):
    p = problems(kind, data, **kw)
    if p:
        raise SchemaError(kind, p)


# ── 文件大小（官方算法的近似：名稱＋每欄 (欄名＋1＋值)＋32）─────────────────

def _value_size(v):
    if v is None or isinstance(v, bool):
        return 1
    if isinstance(v, (int, float)):
        return 8
    if v is SERVER_TIME or isinstance(v, Timestamp):
        return 8
    if isinstance(v, str):
        return len(v.encode("utf-8")) + 1
    if isinstance(v, (bytes, bytearray)):
        return len(v)
    if isinstance(v, (list, tuple)):
        return sum(_value_size(x) for x in v)
    if isinstance(v, dict):
        return sum(len(str(k).encode("utf-8")) + 1 + _value_size(x) for k, x in v.items())
    return 8


def doc_size(path, data):
    name = sum(len(s.encode("utf-8")) + 1 for s in path.split("/")) + 16
    return name + _value_size(data) + 32


def size_problem(path, data, limit=DOC_MAX):
    n = doc_size(path, data)
    if n > limit:
        return "文件太大（約 %d KB，上限 %d KB）：%s" % (n // 1024, limit // 1024, path)
    return None
