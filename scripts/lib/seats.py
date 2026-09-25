#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seats.py — 座號只有一種寫法：兩位數字字串 "01".."40"。

不統一寫法的代價：程式、規則、路徑、測試四處各自比對，"1"、"01"、"座01" 這種寫法對不上時
權限會靜默拒絕（看起來像 bug，其實是格式不一致）。這支是唯一正本，其他程式一律
呼叫 seat_key() 或 parse_seat()，不准自己 zfill 或字串接來接去。
"""
import re

MIN_SEAT = 1
MAX_SEAT = 40

# 只接受 1～2 位數字（不接受帶符號、小數點、前後空白以外的其他字元）
_SEAT_STR_RE = re.compile(r"^\d{1,2}$")


def seat_key(n):
    """把整數座號轉成標準兩位數字字串："01".."40"。

    超出範圍、不是數字、是布林值，一律丟 ValueError（布林是 int 的子類別，
    不擋的話 seat_key(True) 會被當成 seat_key(1) 悄悄算出 "01"，那是錯的）。
    """
    if isinstance(n, bool):
        raise ValueError("座號不能是布林值：%r" % (n,))
    try:
        i = int(n)
    except (TypeError, ValueError):
        raise ValueError("座號必須是數字：%r" % (n,))
    if i != n and not isinstance(n, str):
        # 例如 1.5 這種帶小數的座號：int(1.5) == 1 會悄悄吃掉小數部分，這裡先擋掉。
        raise ValueError("座號不能有小數：%r" % (n,))
    if not (MIN_SEAT <= i <= MAX_SEAT):
        raise ValueError("座號超出範圍（%d–%d）：%r" % (MIN_SEAT, MAX_SEAT, n))
    return "%02d" % i


def parse_seat(value):
    """接受 1 / "1" / "01" 這幾種寫法，一律回傳標準兩位數字字串。

    其餘寫法（"座01"、"1.0"、空字串、None、list……）一律拒絕，丟 ValueError——
    這支故意比 seat_key() 嚴格：字串只准 1～2 位純數字，不接受任何多餘字元。
    """
    if isinstance(value, bool):
        raise ValueError("座號不能是布林值：%r" % (value,))
    if isinstance(value, int):
        return seat_key(value)
    if isinstance(value, str):
        s = value.strip()
        if not _SEAT_STR_RE.match(s):
            raise ValueError("座號格式不對，只能是 1～2 位數字（例如 1、01）：%r" % (value,))
        return seat_key(int(s))
    raise ValueError("座號型別不對（只接受整數或數字字串）：%r" % (value,))
