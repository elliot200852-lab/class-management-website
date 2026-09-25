#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frontmatter.py — 本機 md 檔最上面那段「檔頭」（--- 包起來的設定）。

只收兩種寫法（刻意很小，不是 YAML）：

    ---
    title: 秋天的散步
    visible: true
    videos:
      - 散步的影片 | https://www.youtube.com/watch?v=xxxxxxxxxxx
    ---

  · `key: value`：值去掉前後空白；前後成對的引號會拿掉；true／false（不分大小寫）變成布林，其他一律是文字。
  · `key:`（冒號後面空白）接著幾行 `- 項目`：變成文字清單。
  · `#` 開頭的整行是註解。不收任何會執行的語法、不收巢狀結構、不收同一個 key 寫兩次。

只用標準庫。
"""
import re

KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(.*)$")
ITEM_RE = re.compile(r"^\s*-\s+(.*)$|^\s*-\s*$")


class FrontmatterError(ValueError):
    def __init__(self, problems):
        super().__init__("；".join(problems))
        self.problems = list(problems)


def normalize_text(text):
    """去掉 BOM、換行統一成 \\n。"""
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _scalar(raw):
    v = raw.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    return v


def split(text):
    """回 (檔頭 dict, 正文字串, 正文從第幾行開始)。沒有檔頭 → ({}, 全文, 1)。"""
    text = normalize_text(text)
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text, 1
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        raise FrontmatterError(["檔頭（第一行的 ---）沒有結束的 ---"])
    meta, problems = {}, []
    current_list = None
    for i in range(1, end):
        line = lines[i]
        lineno = i + 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m_item = ITEM_RE.match(line)
        if m_item and current_list is not None:
            item = (m_item.group(1) or "").strip()
            if len(item) >= 2 and item[0] == item[-1] and item[0] in ("'", '"'):
                item = item[1:-1]
            meta[current_list].append(item)
            continue
        m = KEY_RE.match(line)
        if not m or line[:1].isspace():
            problems.append("檔頭第 %d 行看不懂（只能寫「名稱: 值」或「- 項目」）" % lineno)
            current_list = None
            continue
        key, raw = m.group(1), m.group(2)
        if key in meta:
            problems.append("檔頭第 %d 行：「%s」寫了兩次" % (lineno, key))
            current_list = None
            continue
        if raw.strip() == "":
            meta[key] = []
            current_list = key
        else:
            meta[key] = _scalar(raw)
            current_list = None
    if problems:
        raise FrontmatterError(problems)
    # 「key:」後面沒有任何 - 項目 → 當成空字串（例如 excerpt: 留空）
    for k, v in list(meta.items()):
        if v == []:
            meta[k] = ""
    body = "\n".join(lines[end + 1:])
    return meta, body, end + 2


def check_keys(meta, allowed, required=()):
    """未知的 key（多半是打錯字）與缺少的必填 key。回問題清單（空＝沒問題）。"""
    problems = []
    for k in meta:
        if k not in allowed:
            problems.append("檔頭有不認得的欄位「%s」（可以用的：%s）" % (k, "、".join(sorted(allowed))))
    for k in required:
        v = meta.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            problems.append("檔頭少了必填的「%s」" % k)
    return problems


def as_list(v):
    """清單欄位：單一值也接受（當成一項）。"""
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return v
    return [v]


def as_bool(v, default, key):
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return v
    raise FrontmatterError(["檔頭「%s」只能寫 true 或 false" % key])


def as_int(v, default, key, lo=None, hi=None):
    if v is None or v == "":
        return default
    if isinstance(v, bool) or not re.match(r"^-?\d+$", str(v).strip()):
        raise FrontmatterError(["檔頭「%s」要是整數" % key])
    n = int(str(v).strip())
    if (lo is not None and n < lo) or (hi is not None and n > hi):
        raise FrontmatterError(["檔頭「%s」要在 %s–%s 之間" % (key, lo, hi)])
    return n


def pair(item):
    """「左邊 | 右邊」拆成兩段（只拆第一個 |）。沒有 | 回 (整段, "")。"""
    if "|" in item:
        a, b = item.split("|", 1)
        return a.strip(), b.strip()
    return item.strip(), ""
