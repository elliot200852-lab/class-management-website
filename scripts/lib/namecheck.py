#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""namecheck.py — 檔名、資料夾名、說明文字裡有沒有學生的名字（拿 data/roster.csv 比對）。

用在「會變成檔名或資料夾名」的地方（課堂檔案歸檔、開新課程單元）：檔名會跟著檔案被複製、分享、
出現在搜尋結果裡，比內文更容易外流。**只回座號，不回名字本身**（輸出會進代理的對話紀錄）。

比對的字串：全名、稱呼、中文 3–4 字姓名去掉姓（取後 2 字）、英文名的每個字（3 個字母以上）。
1 個字的不比（太容易誤判）。這只是一道網，擋不住綽號與外號——說明一律寫「內容」、不寫「人」。
"""
import re

from .sources import load_roster, SourceError

_CJK_RE = re.compile(r"^[㐀-鿿]+$")


def needles(students):
    """名冊（sources.Student 清單）→ [(要擋的字串, 座號)]。"""
    out = []
    for s in students:
        cands = {s.name.strip(), s.display.strip()}
        n = s.name.replace(" ", "").strip()
        if _CJK_RE.match(n) and len(n) in (3, 4):
            cands.add(n[-2:])
        for tok in re.split(r"[\s·・.]+", s.name):
            if re.match(r"^[A-Za-z]{3,}$", tok):
                cands.add(tok)
        for c in cands:
            if len(c) >= 2:
                out.append((c, s.seat))
    return out


def find(text, ndl):
    """text 裡出現了哪些座號的名字（排序過的座號清單；英文不分大小寫）。"""
    low = (text or "").lower()
    return sorted({seat for needle, seat in ndl if needle.lower() in low})


def load(data_dir):
    """讀 data/roster.csv → needles；沒有名冊或讀不懂 → None（呼叫端要提醒「沒辦法比對」）。"""
    p = data_dir / "roster.csv"
    if not p.exists():
        return None
    try:
        students, _ = load_roster(p)
    except SourceError:
        return None
    return needles(students)
