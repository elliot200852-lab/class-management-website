#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""progress.py — 讀安裝進度檔 setup/progress.json（AGENTS.md「進度檔」一節；代理寫、腳本只讀）。

安裝還沒做完的時候，腳本的「下一步」提示要把代理帶回 AGENTS.md 的下一步，而不是日常操作
（例如還沒部署網站就叫人去備份）。這裡只回答兩件事：某一步做完沒、第一個還沒做完的是第幾步。
檔案不在或讀不懂 → 當作「不知道」（回 None），呼叫端照原本的說法印。
"""
import json

from . import paths

STEPS = tuple(str(n) for n in range(0, 11))


def read():
    """setup/progress.json 的內容（dict）；不在、讀不懂、形狀不對 → None。"""
    p = paths.rpath("setup", "progress.json")
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("steps"), dict):
        return None
    return raw


def step_done(prog, n):
    st = (prog or {}).get("steps", {}).get(str(n))
    return isinstance(st, dict) and st.get("done") is True


def first_open_step(prog):
    """第一個還沒做完的步驟（int）；0–10 全部做完 → None。prog 是 None 也回 None（不知道）。"""
    if prog is None:
        return None
    for n in STEPS:
        if not step_done(prog, n):
            return int(n)
    return None
