#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""drivetree.py — Google 雲端硬碟桌面版的同步夾：找同步夾、資料夾樹的名字、確認樹還在。

備份、歸檔一律「寫進這台電腦上的同步夾」，由雲端硬碟程式自己上傳。
不用 Drive API、不申請任何憑證。

三條規矩：
  1. **頂層樹只有 scripts/drive_init.py 能建**（build_tree）。其他腳本一律用 DriveTree.require()
     拿路徑；找不到就丟 DriveTreeError（白話原因＋怎麼辦），**絕不自己再建一個**。
     同步夾沒掛上、資料夾被改名或搬走的時候「找不到就建」，會把備份寫進一個沒人知道的地方，
     而且看起來一切正常。
  2. 已經驗證過的夾底下，可以往下建日期、學年、座號、課程這種子夾（ensure_below）。
  3. 樹的根目錄放一份說明檔（MARKER_NAME），裡面有 MARKER_TAG。說明檔在＝這是 drive_init.py 建的那一棵。

設定（config/class.json，只留在老師的電腦）：
  drive.sync_root     同步夾本身（例如 …/GoogleDrive-某帳號/我的雲端硬碟，或 G:\\My Drive）
  drive.class_folder  樹的根目錄名稱（「<班名> 班級網站」；建好後固定，改班名不會跟著變）
  school_year         學年從幾月開始（start_month）、一學年分成哪幾個學期（terms）、學期資料夾的別名
                      （term_aliases，選填）；依學校，見 config/README.md
"""
import os
import re
import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

# ── 樹的名字（改這裡＝改所有腳本，也要同步改 docs 與 playbooks）─────────────
CLASS_SUFFIX = " 班級網站"
MARKER_NAME = "這個資料夾是什麼.txt"
MARKER_TAG = "class-management-website drive-tree v1"

CONF = "01_機密（只有導師）"
SHARE = "02_分享給家長"
ALBUMS = "03_相簿原圖"
BLOGS = "04_部落格歸檔"
SITE = "05_全站備份"

CLASS_DOCS = "班級文件"
GENERAL_DOCS = "通用文件"          # 班級文件裡「不分學年」的那一格（每年都用得到的）
STUDENT_FILES = "學生個別資料"      # 一個座號一個夾
MEDIA = "課堂檔案"
SYLLABI = "科任課程大綱"           # 在「分享給家長」底下；只建立、不分享

# 名稱 → 相對樹根的路徑（where.py 與各腳本都用這張表）
LOCATIONS = {
    "root": (),
    "confidential": (CONF,),
    "class_docs": (CONF, CLASS_DOCS),
    "cases": (CONF, STUDENT_FILES),
    "media": (CONF, MEDIA),
    "records_backup": (CONF, "紀錄備份"),
    "records_media": (CONF, "紀錄備份", "照片與附件"),
    "share": (SHARE,),
    "syllabi": (SHARE, SYLLABI),
    "album_originals": (ALBUMS,),
    "blog_archive": (BLOGS,),
    "site_backup": (SITE,),
    "fs_backup": (SITE, "firestore"),
    "fs_latest": (SITE, "firestore", "latest"),
    "fs_snapshots": (SITE, "firestore", "snapshots"),
    "fs_photos": (SITE, "firestore", "photos"),
}

LABELS = {
    "root": "班級網站總資料夾",
    "confidential": "機密（只有導師）",
    "class_docs": "班級文件",
    "cases": "學生個別資料（一個座號一個夾）",
    "media": "課堂檔案（照片、影片、音檔、文件）",
    "records_backup": "紀錄備份（名冊與母本的壓縮檔）",
    "records_media": "紀錄備份裡的照片與附件",
    "share": "分享給家長（要老師自己在雲端硬碟按分享）",
    "syllabi": "科任課程大綱（要給家長看的 PDF）",
    "album_originals": "相簿原圖",
    "blog_archive": "部落格歸檔（只用座號）",
    "site_backup": "全站備份",
    "fs_backup": "資料庫備份",
    "fs_latest": "資料庫備份：最新一份",
    "fs_snapshots": "資料庫備份：歷次快照",
    "fs_photos": "資料庫備份：照片",
}

# 班級文件底下固定的幾格；另外每個學年一夾，裡面每個學期一夾（學期名稱來自 config 的 school_year.terms）。
CLASS_DOC_FOLDERS = (GENERAL_DOCS, "會議紀錄", "課程")

# 學年從幾月開始、一學年分成哪幾個學期：依學校，寫在 config/class.json 的 school_year（config/README.md）。
# 沒寫就用這組預設值。分三個學期的學校就寫 ["第一學期", "第二學期", "第三學期"]。
# term_aliases（選填，預設空）：{學期名稱: [別名, …]}，只給 docs_index.py 認資料夾用
# （例如老師自己的舊資料夾叫「第一學期」、設定寫的是「上學期」）；資料夾永遠只照 terms 建。
DEFAULT_START_MONTH = 8
DEFAULT_TERMS = ("上學期", "下學期")
MAX_TERMS = 6
MAX_ALIASES = 5                    # 每個學期最多幾個別名

# Windows 檔名不准的字元、保留名稱（Mac 也一起擋，免得在 Mac 建的夾到 Windows 打不開）
_BAD_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}

DRIVE_ROOT_NAMES = ("我的雲端硬碟", "My Drive", "我的云端硬盘")
# 從 G 開始（桌面版預設 G:）；刻意不掃 D、E、F：常是光碟機或讀卡機，沒放片時問它可能跳出「磁碟機中沒有磁片」。
WIN_LETTERS = "GHIJKLMNOPQRSTUVWXYZ"


class DriveTreeError(Exception):
    """同步夾或資料夾樹有問題。lines：第一行是發生什麼事，後面是「→ 怎麼辦」。"""

    def __init__(self, lines):
        if isinstance(lines, str):
            lines = [lines]
        super().__init__("\n".join(lines))
        self.lines = list(lines)

    def plain(self):
        return "\n".join(["✗ " + self.lines[0]] + ["  " + x for x in self.lines[1:]])


# ── 名字檢查 ──────────────────────────────────────────────────────────────

def name_problem(name, what="名稱", max_len=60):
    """一段資料夾或檔名合不合法（Mac、Windows 都要能用）。合法回 None，不合法回白話原因。"""
    if not isinstance(name, str) or not name.strip():
        return "%s是空的" % what
    if name != name.strip():
        return "%s前後不能有空白" % what
    if len(name) > max_len:
        return "%s太長（最多 %d 字）" % (what, max_len)
    if _BAD_CHARS_RE.search(name):
        return '%s不能有這些符號：< > : " / \\ | ? * 或換行' % what
    if name in (".", "..") or name.startswith("."):
        return "%s不能用點開頭" % what
    if name.endswith("."):
        return "%s不能用點結尾（Windows 會出問題）" % what
    if name.split(".")[0].upper() in _WIN_RESERVED:
        return "%s是 Windows 保留的名字，換一個" % what
    return None


def class_folder_name(class_name):
    """「<班名> 班級網站」；班名裡 Windows 不准的符號換成底線。"""
    base = _BAD_CHARS_RE.sub("_", str(class_name or "").strip()).strip(" .")
    if not base or base.split(".")[0].upper() in _WIN_RESERVED:
        base = "我的班級"
    return base[:40] + CLASS_SUFFIX


def to_date(v):
    """date／datetime／"YYYY-MM-DD"／"YYYYMMDD" → datetime.date；格式不對丟 ValueError。"""
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    s = str(v).strip()
    if re.match(r"^\d{8}$", s):
        s = "%s-%s-%s" % (s[0:4], s[4:6], s[6:8])
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        raise ValueError("日期格式不對：%r" % (v,))
    return datetime.date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


def school_year(date=None, start_month=DEFAULT_START_MONTH):
    """學年資料夾名：start_month 月 1 日換學年（預設 8 月）。
    start_month=8：2030-09-25 → "2030-2031"；2031-03-01 → "2030-2031"。
    start_month=1（學年就是日曆年）：只寫年份，2031-03-01 → "2031"。"""
    d = to_date(date) if date else datetime.date.today()
    m = start_month if isinstance(start_month, int) and 1 <= start_month <= 12 else DEFAULT_START_MONTH
    if m == 1:
        return "%d" % d.year
    start = d.year if d.month >= m else d.year - 1
    return "%d-%d" % (start, start + 1)


def school_year_problems(sy):
    """config/class.json 的 school_year 欄位有沒有寫錯。回 [(問題, 怎麼辦)]；空清單＝沒問題（缺欄位不算錯，用預設值）。
    build_config.py --check 用這個；其他腳本用 year_settings()（寫錯就退回預設值）。"""
    if sy is None:
        return []
    if not isinstance(sy, dict):
        return [("school_year 要是物件", '格式是 {"start_month": 8, "terms": ["上學期", "下學期"]}；不確定就整欄拿掉，用預設值。')]
    out = []
    m = sy.get("start_month")
    if m is not None and (isinstance(m, bool) or not isinstance(m, int) or not 1 <= m <= 12):
        out.append(("school_year.start_month 要是 1–12 的整數（學年從幾月開始）",
                    "寫數字、不加引號，例如 8（八月開學）；照學校的行事曆填。"))
    terms = sy.get("terms")
    out.extend(_terms_problems(terms))
    out.extend(_alias_problems(sy.get("term_aliases"), _terms_or_default(terms)))
    return out


def _terms_problems(terms):
    """school_year.terms 有沒有寫錯（沒寫不算錯）。"""
    if terms is None:
        return []
    if not isinstance(terms, list) or not terms or len(terms) > MAX_TERMS:
        return [("school_year.terms 要是 1–%d 個學期名稱的清單" % MAX_TERMS,
                 '例如 ["上學期", "下學期"]；分三個學期的學校可以寫 ["第一學期", "第二學期", "第三學期"]。')]
    bad = [t for t in terms if not isinstance(t, str) or name_problem(t, "學期名稱", max_len=20)]
    if bad or len(set(terms)) != len(terms):
        return [("school_year.terms 裡有不能當資料夾名稱的學期名稱（空白、符號、太長）或重複的",
                 "每個學期名稱只用一般文字，最多 20 字，不能有 / \\ : * ? \" < > | 這些符號，也不能重複。")]
    return []


def _terms_or_default(terms):
    """terms 寫對了就用它，沒寫或寫錯就用預設值。"""
    return DEFAULT_TERMS if terms is None or _terms_problems(terms) else tuple(terms)


def _alias_problems(aliases, terms):
    """school_year.term_aliases 有沒有寫錯（沒寫、或空物件＝沒問題）。"""
    if aliases is None:
        return []
    fmt = '格式是 {"上學期": ["第一學期"], "下學期": ["第二學期"]}：鍵是 terms 裡的學期名稱，值是別名清單；用不到就整欄拿掉。'
    if not isinstance(aliases, dict):
        return [("school_year.term_aliases 要是物件", fmt)]
    out = []
    unknown = [k for k in aliases if k not in terms]
    if unknown:
        out.append(("school_year.term_aliases 的鍵要是 school_year.terms 裡的學期名稱（%d 個對不上）" % len(unknown), fmt))
    seen = set(terms)
    for k, v in aliases.items():
        if not isinstance(v, list) or not v or len(v) > MAX_ALIASES:
            out.append(("school_year.term_aliases 每個學期要給 1–%d 個別名的清單" % MAX_ALIASES, fmt))
            break
        bad = False
        for a in v:
            if not isinstance(a, str) or name_problem(a, "別名", max_len=20) or a in seen:
                bad = True
                break
            seen.add(a)
        if bad:
            out.append(("school_year.term_aliases 裡有不能當資料夾名稱的別名，或跟學期名稱、其他別名重複的",
                        "別名跟學期名稱一樣只用一般文字，最多 20 字；同一個字只能對到一個學期。"))
            break
    return out


def year_settings(raw):
    """config/class.json → (start_month, terms)。缺欄位或寫錯的欄位用預設值（錯在哪由 build_config.py --check 說）。"""
    sy = (raw or {}).get("school_year")
    if not isinstance(sy, dict):
        return DEFAULT_START_MONTH, DEFAULT_TERMS
    m = sy.get("start_month")
    if not isinstance(m, int) or isinstance(m, bool) or not 1 <= m <= 12:
        m = DEFAULT_START_MONTH
    return m, _terms_or_default(sy.get("terms"))


def term_aliases(raw):
    """config/class.json → {別名: 學期名稱}（沒寫或寫錯＝空的；錯在哪由 build_config.py --check 說）。"""
    sy = (raw or {}).get("school_year")
    if not isinstance(sy, dict) or not isinstance(sy.get("term_aliases"), dict):
        return {}
    _, terms = year_settings(raw)
    if _alias_problems(sy["term_aliases"], terms):
        return {}
    return {a: t for t, names in sy["term_aliases"].items() for a in names}


# ── 找同步夾 ─────────────────────────────────────────────────────────────

def _listdir_safe(listdir, p):
    try:
        return sorted(listdir(p))
    except OSError:
        return []


def detect_candidates(os_name, home, environ=None, isdir=None, listdir=None, letters=WIN_LETTERS):
    """這台電腦上看起來像「Google 雲端硬碟桌面版同步夾」的資料夾（字串清單，找不到回空清單）。

    os_name：'mac'／'win'／'linux'。isdir、listdir 可以換成假的（測試用暫存目錄或假的 Windows 路徑）。
    Mac：~/Library/CloudStorage/GoogleDrive-<帳號>/{我的雲端硬碟, My Drive}（新版）、
         /Volumes/GoogleDrive/…（舊版）、~/Google Drive/…（舊版鏡像）。
    Windows：磁碟代號 G:（最常見）到 Z: 底下的 My Drive／我的雲端硬碟、使用者資料夾底下的鏡像模式。
    """
    env = os.environ if environ is None else environ
    isdir = isdir or os.path.isdir
    listdir = listdir or os.listdir
    found = []

    def add(p):
        s = str(p)
        try:
            ok = isdir(s)
        except OSError:
            ok = False
        if ok and s not in found:
            found.append(s)

    if os_name == "win":
        P = PureWindowsPath
        for letter in letters:
            for n in DRIVE_ROOT_NAMES:
                add(P("%s:\\" % letter) / n)
        prof = env.get("USERPROFILE") or home
        if prof:
            for n in DRIVE_ROOT_NAMES:
                add(P(prof) / n)
                add(P(prof) / "Google Drive" / n)
        return found
    P = PurePosixPath
    if os_name == "mac":
        cs = P(home) / "Library" / "CloudStorage"
        for entry in _listdir_safe(listdir, str(cs)):
            if entry.startswith("GoogleDrive"):
                for n in DRIVE_ROOT_NAMES:
                    add(cs / entry / n)
        for n in DRIVE_ROOT_NAMES:
            add(P("/Volumes/GoogleDrive") / n)
            add(P(home) / "Google Drive" / n)
        return found
    for n in DRIVE_ROOT_NAMES:
        add(P(home) / n)
        add(P(home) / "Google Drive" / n)
    return found


def looks_like_drive(path_str):
    """路徑看起來是不是雲端硬碟同步夾（給「老師自己貼路徑」時提醒用，不擋）。"""
    s = str(path_str)
    return any(n in s for n in DRIVE_ROOT_NAMES) or "GoogleDrive" in s or "Google Drive" in s


# ── 樹 ─────────────────────────────────────────────────────────────────

def tree_folders(year=None, terms=DEFAULT_TERMS, start_month=DEFAULT_START_MONTH):
    """drive_init.py 要建的所有資料夾（相對樹根的 tuple 清單，父在前）。
    year＝這一學年的資料夾名（預設照今天與 start_month 算）；terms＝學期名稱（config 的 school_year.terms）。"""
    y = year or school_year(start_month=start_month)
    out = []
    for key in ("confidential", "class_docs", "cases", "media", "records_backup", "records_media", "share",
                "syllabi", "album_originals", "blog_archive", "site_backup", "fs_backup", "fs_latest",
                "fs_snapshots", "fs_photos"):
        out.append(LOCATIONS[key])
    for n in CLASS_DOC_FOLDERS:
        out.append((CONF, CLASS_DOCS, n))
    out.append((CONF, CLASS_DOCS, y))
    for t in (terms or ()):
        out.append((CONF, CLASS_DOCS, y, t))
    out.append((CONF, MEDIA, y))
    seen, ordered = set(), []
    for t in out:
        for i in range(1, len(t) + 1):
            if t[:i] not in seen:
                seen.add(t[:i])
                ordered.append(t[:i])
    return ordered


def marker_text(class_folder):
    return "\n".join([
        MARKER_TAG,
        "",
        "這個資料夾是「%s」的備份與歸檔，由 class-management-website 的 scripts/drive_init.py 建立。" % class_folder,
        "Google 雲端硬碟桌面版會把它同步到你的雲端硬碟。請不要刪掉或改名這份說明檔：",
        "程式靠它確認「這是當初建的那一個資料夾」，找不到就會停下來、不會亂寫到別的地方。",
        "",
        "%s：只有你自己（導師）看得到。班級文件、學生個別資料、課堂檔案、紀錄備份都在這裡。" % CONF,
        "%s：這個資料夾**只是建好，還沒有分享給任何人**。" % SHARE,
        "    要給家長看的時候，由你自己在雲端硬碟網頁上對這個資料夾按「共用」，自己選分享對象；",
        "    程式永遠不會替你分享任何東西。",
        "%s：相簿的原始照片（網站上的是縮小過的版本）。" % ALBUMS,
        "%s：每位孩子部落格的備份，資料夾只用座號、不用姓名。" % BLOGS,
        "%s：網站資料庫的完整備份（還原網站時用）。" % SITE,
        "",
        "整棵資料夾（包括機密夾）都在你自己的雲端硬碟裡，預設只有你看得到。",
        "",
    ])


class DriveTree(object):
    """一棵已設定的樹。建構不碰磁碟；check()／require() 才會看磁碟（唯讀）。"""

    def __init__(self, sync_root, class_folder, start_month=DEFAULT_START_MONTH, terms=DEFAULT_TERMS, term_aliases=None):
        self.sync_root = Path(sync_root) if sync_root else None
        self.class_folder = class_folder or ""
        self.root = (self.sync_root / self.class_folder) if (self.sync_root and self.class_folder) else None
        self.start_month = start_month
        self.terms = tuple(terms or ())
        self.term_aliases = dict(term_aliases or {})   # {別名: 學期名稱}

    @classmethod
    def from_config(cls, raw):
        drive = (raw or {}).get("drive") or {}
        sr = str(drive.get("sync_root") or "").strip()
        cf = str(drive.get("class_folder") or "").strip()
        if sr and not cf:
            cf = class_folder_name((raw or {}).get("class_name"))
        start_month, terms = year_settings(raw)
        return cls(sr or None, cf, start_month, terms, term_aliases(raw))

    def school_year(self, date=None):
        """照這個班設定的學年起始月算學年資料夾名。"""
        return school_year(date, self.start_month)

    def path(self, name, *more):
        if self.root is None:
            return None
        return self.root.joinpath(*(LOCATIONS[name] + tuple(more)))

    def problems(self, names=()):
        """唯讀檢查；回 [DriveTreeError]（空清單＝都好）。names＝這次會用到的位置。"""
        try:
            self.require(*names)
            return []
        except DriveTreeError as e:
            return [e]

    def require(self, *names):
        """確認同步夾、樹根、說明檔與指定的位置都在。回 {名稱: Path}；任何一個不在 → DriveTreeError。
        **只看不建**（規矩 1）。"""
        from .hostos import PY
        init = "%s scripts/drive_init.py" % PY
        if self.sync_root is None:
            raise DriveTreeError(["還沒設定 Google 雲端硬碟同步夾（config/class.json 的 drive.sync_root 是空的）。",
                                  "→ 照 playbooks/backup.md 第一次設定：先跑 %s 找同步夾，問老師選哪一個。" % init])
        if not _isdir(self.sync_root):
            raise DriveTreeError([
                "找不到雲端硬碟同步夾：%s" % self.sync_root,
                "→ 多半是 Google 雲端硬碟桌面程式沒有開、還沒登入，或換了磁碟代號。請老師打開它、確認已登入。",
                "→ 打開後再跑一次同一個指令。同步夾的位置真的換了，才重跑 %s 選新的。" % init,
                "→ 這支程式不會自己另外建一個資料夾（免得備份寫到沒人知道的地方）。"])
        if not _isdir(self.root):
            raise DriveTreeError([
                "同步夾裡找不到「%s」這個資料夾。" % self.class_folder,
                "→ 可能被改名、被搬走，或被刪掉了。請老師到雲端硬碟（網頁或同步夾）找回來、改回原來的名字。",
                "→ 確定要重新建一棵，才跑 %s --apply（會照 config 的名字重建）。" % init])
        marker = self.root / MARKER_NAME
        try:
            ok = marker.is_file() and MARKER_TAG in marker.read_text(encoding="utf-8", errors="replace")
        except OSError:
            ok = False
        if not ok:
            raise DriveTreeError([
                "「%s」裡少了說明檔「%s」，不確定這是不是當初建的那個資料夾。" % (self.class_folder, MARKER_NAME),
                "→ 先跑 %s --check 看看；確認是對的資料夾，再跑 %s --apply 把說明檔補回來。" % (init, init)])
        out = {"root": self.root}
        for n in names:
            p = self.path(n)
            if not _isdir(p):
                raise DriveTreeError([
                    "資料夾樹少了「%s」（%s）。" % ("/".join(LOCATIONS[n]), LABELS.get(n, n)),
                    "→ 可能被移動或刪掉了。跑 %s --apply 把缺的資料夾補回來（已經有的不會動）。" % init])
            out[n] = p
        return out


def _isdir(p):
    try:
        return p is not None and Path(p).is_dir()
    except OSError:
        return False


def ensure_below(base, *parts):
    """在一個**已經驗證過**的資料夾底下往下建子夾（學年、課程、座號、年月）。每一段都檢查名字。"""
    base = Path(base)
    if not _isdir(base):
        raise DriveTreeError(["要往下建資料夾的上層不在：%s" % base,
                              "→ 這是程式的問題（上層應該先驗證過），請回報；不要自己建。"])
    cur = base
    for part in parts:
        prob = name_problem(part, "資料夾名稱")
        if prob:
            raise DriveTreeError(["資料夾名稱不合法（%s）：%r" % (prob, part)])
        cur = cur / part
    cur.mkdir(parents=True, exist_ok=True)
    return cur


def build_tree(sync_root, class_folder, year=None, terms=DEFAULT_TERMS, start_month=DEFAULT_START_MONTH):
    """**只有 drive_init.py 呼叫**：在同步夾底下建整棵樹＋說明檔。已經有的不動。回新建的相對路徑清單。"""
    sync_root = Path(sync_root)
    if not _isdir(sync_root):
        raise DriveTreeError(["找不到同步夾：%s" % sync_root])
    prob = name_problem(class_folder, "樹根名稱", max_len=60)
    if prob:
        raise DriveTreeError(["樹根名稱不合法（%s）" % prob])
    root = sync_root / class_folder
    created = []
    if not root.exists():
        root.mkdir()
        created.append(class_folder)
    for rel in tree_folders(year, terms, start_month):
        p = root.joinpath(*rel)
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append("/".join((class_folder,) + rel))
    marker = root / MARKER_NAME
    text = marker_text(class_folder)
    try:
        current = marker.read_text(encoding="utf-8") if marker.is_file() else None
    except OSError:
        current = None
    if current is None or MARKER_TAG not in current:
        from .filesafe import write_text_atomic
        write_text_atomic(marker, text)
        created.append("%s/%s" % (class_folder, MARKER_NAME))
    return created
