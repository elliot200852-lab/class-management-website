#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docs_index.py — 班級文件索引：掃雲端硬碟同步夾「01_機密（只有導師）/班級文件/」，產生那一層的 index.md。

  · 資料夾是唯一的正本：丟檔進去、改名、搬到別的學期、刪掉，重跑一次就對齊。
  · index.md 一列一份文件：名稱｜類別｜學年｜學期｜位置（相對「班級文件」的路徑）。
  · 「類別」欄是人工欄：第一次照檔案種類給預設值（PDF、文件、表格、簡報、表單、圖片、影音、其他）；
    老師（或代理照老師的話）在 index.md 裡改過的，下次重跑會保留（先認位置，搬了家再認檔名）。
  · 學年＝路徑裡「2030-2031」或「119學年」這種資料夾名；學期＝名稱是 config/class.json 的 school_year.terms
    其中一個的資料夾（「下學期」，或「119學年 下學期」這種用空白隔開的其中一段）；老師自己的資料夾用別的叫法時，
    在 school_year.term_aliases 登記別名（選填，預設沒有）；「通用文件」那一格標成「通用」。
  · 這支只讀檔名與資料夾名，**不打開任何文件的內容**。
  · 螢幕上只印數量，不印檔名（班級文件的檔名可能有孩子的名字；它們只該待在機密資料夾裡）。

  index.md 在同步夾裡，雲端硬碟會自己上傳（跟文件一樣只在「01_機密（只有導師）」，不要分享這個資料夾）。
  導師專用頁的「班級文件」卡片可以放一個按鈕直接打開它：在雲端硬碟網頁版打開 index.md、複製網址，
  再用 scripts/publish_site.py --class-docs <網址> 設定（playbooks/class-docs.md）。

用法（Windows 把 python3 換成 py -3）：
  python3 scripts/docs_index.py            預覽：會新增幾列、移除幾列、保留幾個人工類別（不寫檔）
  python3 scripts/docs_index.py --apply    真的寫 index.md
  python3 scripts/docs_index.py --check    index.md 是不是最新的（不是就 exit 1；唯讀）
  python3 scripts/docs_index.py --open     用系統預設程式打開 index.md（給老師看）
exit：0＝成功；1＝--check 發現不是最新；2＝找不到同步夾或資料夾（什麼都沒寫）。
"""
import re
import sys
import argparse
import datetime
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths  # noqa: E402
from lib import drivetree as dt  # noqa: E402
from lib.filesafe import write_text_atomic, TMP_PREFIX  # noqa: E402
from lib.hostos import PY  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

INDEX_NAME = "index.md"
HEAD = ("名稱", "類別", "學年", "學期", "位置")
PERENNIAL = "通用"
IGNORE_NAMES = {"desktop.ini", "thumbs.db", "icon\r", INDEX_NAME}
CATEGORY_BY_EXT = [
    ("PDF", (".pdf",)),
    ("文件", (".doc", ".docx", ".odt", ".pages", ".rtf", ".txt", ".md", ".gdoc")),
    ("表格", (".xls", ".xlsx", ".ods", ".numbers", ".csv", ".gsheet")),
    ("簡報", (".ppt", ".pptx", ".odp", ".key", ".gslides")),
    ("表單", (".gform",)),
    ("圖片", (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif", ".tif", ".tiff", ".bmp", ".svg", ".gdraw")),
    ("影音", (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac")),
]
YEAR_RE = re.compile(r"^(\d{4})-(\d{4})$")
CAL_YEAR_RE = re.compile(r"^(\d{4})$")
ROC_YEAR_RE = re.compile(r"(\d{2,3})\s*學年")


def default_category(name):
    ext = PurePosixPath(name.lower()).suffix
    for cat, exts in CATEGORY_BY_EXT:
        if ext in exts:
            return cat
    return "其他"


def term_of(label, terms, aliases=None):
    """一段資料夾名 → 學期名稱（對不到回 ""）。整段、或用空白隔開的其中一段等於學期名稱就算；
    等於 aliases（{別名: 學期名稱}，來自 config 的 school_year.term_aliases）裡的別名也算，回傳對到的學期名稱。"""
    tokens = [label] + label.split()
    for t in terms:
        if t in tokens:
            return t
    for tok in tokens:
        t = (aliases or {}).get(tok)
        if t in terms:
            return t
    return ""


def classify(parts, terms=dt.DEFAULT_TERMS, start_month=dt.DEFAULT_START_MONTH, aliases=None):
    """資料夾路徑（不含檔名）→ (學年, 學期)。terms、start_month、aliases 來自 config 的 school_year。"""
    year, term = "", ""
    for seg in parts:
        m = YEAR_RE.match(seg)
        c = CAL_YEAR_RE.match(seg) if start_month == 1 else None
        if m:
            year = "%s-%s" % (m.group(1), m.group(2))
        elif c:
            year = c.group(1)
        else:
            r = ROC_YEAR_RE.search(seg)
            if r:
                year = "%s學年" % r.group(1)
        label = re.sub(r"^\d+_", "", seg)
        if label == dt.GENERAL_DOCS:
            term = PERENNIAL
        else:
            term = term_of(label, terms, aliases) or term
    return year, term


def skip(name):
    n = name.lower()
    return name.startswith((".", "~$", TMP_PREFIX)) or n in IGNORE_NAMES or n.endswith((".tmp", ".partial"))


def scan(base, terms=dt.DEFAULT_TERMS, start_month=dt.DEFAULT_START_MONTH, aliases=None):
    """走「班級文件」整棵樹。回 [{'name','pos','year','term','cat'}]（pos＝相對路徑，用 / 分隔）。"""
    out = []
    base = Path(base)
    for p in sorted(base.rglob("*")):
        rel = p.relative_to(base)
        if any(skip(part) for part in rel.parts):
            continue
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        if len(rel.parts) == 1 and rel.name == INDEX_NAME:
            continue
        year, term = classify(rel.parts[:-1], terms, start_month, aliases)
        out.append({"name": rel.name, "pos": rel.as_posix(), "year": year, "term": term,
                    "cat": default_category(rel.name)})
    return out


def _cell(s):
    return str(s).replace("\\", "\\\\").replace("|", "\\|")


def _split_row(line):
    """一列 markdown 表格 → 欄位（處理 \\| 與 \\\\）。"""
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return None
    cells, cur, i = [], [], 1
    while i < len(s) - 1:
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) - 1 and s[i + 1] in "|\\":
            cur.append(s[i + 1])
            i += 2
            continue
        if ch == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    cells.append("".join(cur).strip())
    return cells


def read_manual(text):
    """舊的 index.md → ({位置: 類別}, {名稱: 類別（只收同名唯一的）})。"""
    by_pos, by_name, dup = {}, {}, set()
    in_table = False
    for line in (text or "").splitlines():
        cells = _split_row(line)
        if cells is None:
            in_table = False
            continue
        if cells[:2] == list(HEAD[:2]):
            in_table = True
            continue
        if not in_table or set("".join(cells)) <= set("-: "):
            continue
        if len(cells) < len(HEAD):
            continue
        name, cat, pos = cells[0], cells[1], cells[4].strip("`")
        if not cat:
            continue
        by_pos[pos] = cat
        if name in by_name and by_name[name] != cat:
            dup.add(name)
        by_name[name] = cat
    for n in dup:
        by_name.pop(n, None)
    return by_pos, by_name


def sort_key(d, terms=dt.DEFAULT_TERMS):
    y = d["year"]
    yn = int(re.sub(r"\D", "", y)[:4] or 0)
    bucket = 0 if d["term"] == PERENNIAL else (1 if yn else 2)
    order = {t: i for i, t in enumerate(terms)}
    return (bucket, -yn, order.get(d["term"], len(terms)), d["pos"])


def merge(docs, by_pos, by_name, terms=dt.DEFAULT_TERMS):
    kept = added = 0
    for d in docs:
        manual = by_pos.get(d["pos"]) or by_name.get(d["name"])
        if manual:
            d["cat"] = manual
            kept += 1
        elif d["pos"] not in by_pos:
            added += 1
    docs.sort(key=lambda d: sort_key(d, terms))
    removed = len(set(by_pos) - {d["pos"] for d in docs})
    return kept, added, removed


def render(docs, now=None):
    now = now or datetime.datetime.now()
    lines = [
        "# 班級文件索引",
        "",
        "> 由 `scripts/docs_index.py` 掃這個資料夾自動產生（最後更新 %s）。" % now.strftime("%Y-%m-%d %H:%M"),
        "> 新增文件＝放進對應的資料夾，再跟 AI 助理說「更新班級文件索引」。「類別」欄可以直接改，下次產生會保留；其他欄會重新對齊資料夾。",
        "> 這份索引跟文件一樣只放在「01_機密（只有導師）」裡，不要分享這個資料夾。",
        "",
        "| %s |" % " | ".join(HEAD),
        "|---|---|---|---|---|",
    ]
    for d in docs:
        lines.append("| %s | %s | %s | %s | %s |" % (_cell(d["name"]), _cell(d["cat"]), d["year"] or "—",
                                                      _cell(d["term"]) or "—", _cell(d["pos"])))
    if not docs:
        lines.append("| （還沒有文件） | | | | |")
    return "\n".join(lines) + "\n"


def _body(text):
    """比對「是不是最新」時忽略更新時間那一行。"""
    return "\n".join(ln for ln in (text or "").splitlines() if not ln.startswith("> 由 `scripts/docs_index.py`"))


def locate():
    import json
    cfgp = paths.rpath("config", "class.json")
    raw = {}
    if cfgp.exists():
        try:
            raw = json.loads(cfgp.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise dt.DriveTreeError(["config/class.json 讀不懂。", "→ 先跑 %s scripts/build_config.py --check。" % PY])
    tree = dt.DriveTree.from_config(raw)
    return tree.require("class_docs")["class_docs"], tree


def main(argv=None):
    ap = argparse.ArgumentParser(description="掃同步夾的「班級文件」，產生那一層的 index.md（預設只預覽）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="真的寫 index.md")
    g.add_argument("--check", action="store_true", help="index.md 是不是最新的（唯讀；不是就 exit 1）")
    ap.add_argument("--open", action="store_true", help="用系統預設程式打開 index.md")
    paths.add_root_arg(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        base, tree = locate()
    except dt.DriveTreeError as e:
        print(e.plain())
        return 2
    index = base / INDEX_NAME
    old = index.read_text(encoding="utf-8-sig") if index.exists() else ""
    by_pos, by_name = read_manual(old)
    docs = scan(base, tree.terms, tree.start_month, tree.term_aliases)
    kept, added, removed = merge(docs, by_pos, by_name, tree.terms)
    text = render(docs)
    same = _body(text) == _body(old)
    per_year = {}
    for d in docs:
        per_year[d["year"] or "（沒有學年）"] = per_year.get(d["year"] or "（沒有學年）", 0) + 1
    print("班級文件：%d 份（%s）" % (len(docs), "、".join("%s %d" % kv for kv in sorted(per_year.items())) or "空的"))
    print("  跟現在的 index.md 比：新增 %d 列、移除 %d 列、保留原本的類別 %d 個%s"
          % (added, removed, kept, "（沒有 index.md，這次是第一次產生）" if not old else ""))
    if a.check:
        print("✓ index.md 是最新的" if same else "✗ index.md 不是最新的：跑 %s scripts/docs_index.py --apply" % PY)
        return 0 if same else 1
    if a.apply:
        if same and old:
            print("✓ index.md 已經是最新的，不用改。")
        else:
            write_text_atomic(index, text)
            print("✓ 已寫入 index.md（在「01_機密（只有導師）/班級文件」裡；雲端硬碟會自己上傳）。")
    elif not same:
        print("\n這只是預覽，還沒寫。要更新就加 --apply。")
    else:
        print("\n✓ index.md 已經是最新的。")
    if a.open:
        if index.exists():
            import where
            where.open_target(index)
        else:
            print("還沒有 index.md 可以打開：先跑 --apply。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
