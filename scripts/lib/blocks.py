#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""blocks.py — 正文結構化區塊的格式驗證（docs/ARCHITECTURE.md §4.1 的 Python 版）。

腳本寫進資料庫之前一定先過這支；前端 site/js/core/blocks.js 渲染前會再驗一次（不合的區塊跳過）。
這裡比前端嚴格：多一個不認得的欄位也算錯（腳本自己產生的東西，不該有多的）。

    Block =
      { t: 'p',     spans }                    段落
      { t: 'h',     level: 2|3|4, text }       標題（≤ 200 字）
      { t: 'list',  ordered, items: [{spans}] }清單（≤ 100 項）
      { t: 'quote', spans }                    引言
      { t: 'img',   pid, caption? }            圖片（pid 在同一個主人文件的 images/ 底下；圖說 ≤ 300 字）
      { t: 'video', url, title? }              影片連結（https://，≤ 500；標題 ≤ 80 字）
      { t: 'hr' }                              分隔線
    Span = { text ≤ 5000, b?: true, i?: true, href?: https:// ≤ 500 }
    每份 ≤ 400 個區塊、每個區塊 ≤ 200 個 span。
"""
import re
import urllib.parse

LIMITS = {
    "blocks": 400,
    "spans": 200,
    "span_text": 5000,
    "heading": 200,
    "list_items": 100,
    "caption": 300,
    "url": 500,
    "video_title": 80,
}

PID_RE = re.compile(r"^([0-9a-f]{16}|[0-2])$")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f\s]")


def is_https(url, max_len=500):
    """網址只准 https://、有主機、沒有空白與控制字元、長度在上限內。"""
    if not isinstance(url, str) or not url or len(url) > max_len or _CTRL_RE.search(url):
        return False
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return u.scheme == "https" and bool(u.netloc) and not u.netloc.startswith("@")


def _str(v, max_len, allow_empty=True):
    return isinstance(v, str) and len(v) <= max_len and (allow_empty or bool(v))


def _span_problem(s):
    if not isinstance(s, dict):
        return "span 不是物件"
    extra = set(s) - {"text", "b", "i", "href"}
    if extra:
        return "span 有多的欄位：%s" % ",".join(sorted(extra))
    if not _str(s.get("text"), LIMITS["span_text"]):
        return "span 的 text 不是文字或超過 %d 字" % LIMITS["span_text"]
    for f in ("b", "i"):
        if f in s and s[f] is not True:
            return "span 的 %s 只能是 true" % f
    if "href" in s and not is_https(s["href"], LIMITS["url"]):
        return "span 的連結不是 https://（或太長）"
    return None


def _spans_problem(arr):
    if not isinstance(arr, list):
        return "spans 不是陣列"
    if len(arr) > LIMITS["spans"]:
        return "一個區塊超過 %d 個 span" % LIMITS["spans"]
    for s in arr:
        p = _span_problem(s)
        if p:
            return p
    return None


def block_problem(b):
    """單一區塊的問題（字串）；沒問題回 None。"""
    if not isinstance(b, dict) or not isinstance(b.get("t"), str):
        return "區塊不是物件或沒有 t"
    t = b["t"]
    keys = set(b)
    if t in ("p", "quote"):
        if keys - {"t", "spans"}:
            return "多的欄位"
        return _spans_problem(b.get("spans"))
    if t == "h":
        if keys - {"t", "level", "text"}:
            return "多的欄位"
        if b.get("level") not in (2, 3, 4) or isinstance(b.get("level"), bool):
            return "標題 level 只能是 2、3、4"
        if not _str(b.get("text"), LIMITS["heading"]):
            return "標題超過 %d 字" % LIMITS["heading"]
        return None
    if t == "list":
        if keys - {"t", "ordered", "items"}:
            return "多的欄位"
        if not isinstance(b.get("ordered"), bool):
            return "清單的 ordered 要是 true／false"
        items = b.get("items")
        if not isinstance(items, list) or len(items) > LIMITS["list_items"]:
            return "清單項目不是陣列或超過 %d 項" % LIMITS["list_items"]
        for it in items:
            if not isinstance(it, dict) or set(it) - {"spans"}:
                return "清單項目格式不對"
            p = _spans_problem(it.get("spans"))
            if p:
                return p
        return None
    if t == "img":
        if keys - {"t", "pid", "caption"}:
            return "多的欄位"
        if not isinstance(b.get("pid"), str) or not PID_RE.match(b["pid"]):
            return "圖片的 pid 格式不對"
        if "caption" in b and not _str(b["caption"], LIMITS["caption"]):
            return "圖說超過 %d 字" % LIMITS["caption"]
        return None
    if t == "video":
        if keys - {"t", "url", "title"}:
            return "多的欄位"
        if not is_https(b.get("url"), LIMITS["url"]):
            return "影片網址不是 https://（或太長）"
        if "title" in b and not _str(b["title"], LIMITS["video_title"]):
            return "影片標題超過 %d 字" % LIMITS["video_title"]
        return None
    if t == "hr":
        if keys - {"t"}:
            return "多的欄位"
        return None
    return "不認得的區塊種類：%s" % t


def problems(blocks):
    """整份正文的問題清單（空＝合格）。"""
    if not isinstance(blocks, list):
        return ["正文不是陣列"]
    out = []
    if len(blocks) > LIMITS["blocks"]:
        out.append("正文超過 %d 個區塊（現在 %d 個）：請拆成兩篇" % (LIMITS["blocks"], len(blocks)))
    for i, b in enumerate(blocks):
        p = block_problem(b)
        if p:
            out.append("第 %d 個區塊：%s" % (i + 1, p))
    return out


def plain_text(blocks):
    """正文的純文字（段落、引言、清單；做摘要用）。"""
    parts = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        if b.get("t") in ("p", "quote"):
            parts.append("".join(s.get("text", "") for s in b.get("spans", [])))
        elif b.get("t") == "list":
            for it in b.get("items", []):
                parts.append("".join(s.get("text", "") for s in it.get("spans", [])))
    return "\n".join(p for p in parts if p)


def excerpt(blocks, limit=120):
    """列表卡片的摘要：第一段起的純文字，空白壓成一格，超過就截斷加「…」。"""
    text = re.sub(r"\s+", " ", plain_text(blocks)).strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "…"


def image_pids(blocks):
    return [b["pid"] for b in blocks or [] if isinstance(b, dict) and b.get("t") == "img" and "pid" in b]
