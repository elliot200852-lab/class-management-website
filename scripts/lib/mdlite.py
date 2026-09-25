#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mdlite.py — 本機 md 正文 → 結構化區塊（docs/ARCHITECTURE.md §5.2）。只收一小撮寫法：

  | md 寫法                                   | 區塊                                   |
  |-------------------------------------------|----------------------------------------|
  | 空行分隔的文字                            | p（段內換行照留）                      |
  | `## `、`### `、`#### ` 開頭               | h（level 2–4）                          |
  | `- ` 或 `1. ` 開頭的連續行                | list（縮排兩格以上的下一行接在同一項） |
  | `> ` 開頭的連續行                         | quote                                  |
  | 單獨一行 `---`                            | hr                                     |
  | 單獨一行 `![圖說](本機檔名)`              | img（pid 等照片處理完才填）            |
  | 單獨一行 `[[video:https://…]]`（可加 `|標題`） | video                              |
  | `**粗體**`、`*斜體*`、`[文字](https://…)` | span 的 b、i、href（不是 https 的連結只留文字） |

其他任何寫法（`# 一級標題`、表格、原始 HTML、程式碼區塊……）一律**原樣當文字**，不解析。
圖片的 img 區塊先用 `src`（本機檔名）暫代，呼叫端處理完照片後用 fill_pids() 換成 pid。

只用標準庫。
"""
import re

from . import blocks as blk

HEADING_RE = re.compile(r"^(#{2,4}) +(.+?)\s*#*\s*$")
UL_RE = re.compile(r"^- (.*)$")
OL_RE = re.compile(r"^\d{1,3}\. (.*)$")
QUOTE_RE = re.compile(r"^> ?(.*)$")
HR_RE = re.compile(r"^---\s*$")
IMG_RE = re.compile(r"^!\[([^\]\n]*)\]\(([^)\n]+)\)\s*$")
VIDEO_RE = re.compile(r"^\[\[video:([^\]|\s]+)(?:\s*\|\s*([^\]]*))?\]\]\s*$")
CONT_RE = re.compile(r"^ {2,}\S")

_INLINE_RE = re.compile(
    r"(?P<link>\[(?P<ltext>[^\]\n]+)\]\((?P<lurl>[^)\s]+)\))"
    r"|(?P<bold>\*\*(?P<btext>[^*\s](?:[^\n]*?[^*\s])??)\*\*)"
    r"|(?P<ital>\*(?P<itext>[^*\s](?:[^*\n]*?[^*\s])??)\*)"
)


class MdError(ValueError):
    def __init__(self, problems):
        super().__init__("；".join(problems))
        self.problems = list(problems)


def _merge(spans):
    out = []
    for s in spans:
        if not s["text"]:
            continue
        if out and {k: v for k, v in out[-1].items() if k != "text"} == {k: v for k, v in s.items() if k != "text"}:
            out[-1]["text"] += s["text"]
        else:
            out.append(dict(s))
    return out


def _span(text, b, i, href):
    s = {"text": text}
    if b:
        s["b"] = True
    if i:
        s["i"] = True
    if href:
        s["href"] = href
    return s


def inline(text, b=False, i=False, href=None):
    """一段文字 → span 清單（粗體、斜體、https 連結）。"""
    out = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() < pos:
            continue
        if m.start() > pos:
            out.append(_span(text[pos:m.start()], b, i, href))
        if m.group("link"):
            url = m.group("lurl")
            if href is None and blk.is_https(url, blk.LIMITS["url"]):
                out += inline(m.group("ltext"), b, i, url)
            else:
                out += inline(m.group("ltext"), b, i, href)
        elif m.group("bold"):
            out += inline(m.group("btext"), True, i, href)
        else:
            out += inline(m.group("itext"), b, True, href)
        pos = m.end()
    if pos < len(text):
        out.append(_span(text[pos:], b, i, href))
    return out


def spans_of(text):
    """文字 → 合併過、每個不超過 5000 字的 span 清單。"""
    out = []
    for s in _merge(inline(text)):
        t = s["text"]
        limit = blk.LIMITS["span_text"]
        while len(t) > limit:
            piece = dict(s)
            piece["text"] = t[:limit]
            out.append(piece)
            t = t[limit:]
        piece = dict(s)
        piece["text"] = t
        out.append(piece)
    return out


def parse(body, first_line=1):
    """正文 → 區塊清單（img 區塊帶 src，還沒有 pid）。有問題丟 MdError（全部問題一起列）。"""
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, problems = [], []
    para = []            # 正在累積的段落行
    lst = None           # 正在累積的清單 {"ordered":bool, "items":[[行...]]}
    quote = None         # 正在累積的引言行

    def flush():
        nonlocal para, lst, quote
        if para:
            out.append({"t": "p", "spans": spans_of("\n".join(para))})
            para = []
        if lst:
            out.append({"t": "list", "ordered": lst["ordered"],
                        "items": [{"spans": spans_of("\n".join(it))} for it in lst["items"]]})
            lst = None
        if quote is not None:
            out.append({"t": "quote", "spans": spans_of("\n".join(quote).strip("\n"))})
            quote = None

    for idx, line in enumerate(lines):
        lineno = first_line + idx
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if lst is not None and CONT_RE.match(line):
            lst["items"][-1].append(stripped)
            continue
        m = QUOTE_RE.match(line)
        if m:
            if quote is None:
                flush()
                quote = []
            quote.append(m.group(1))
            continue
        if quote is not None:
            flush()
        if HR_RE.match(line):
            flush()
            out.append({"t": "hr"})
            continue
        m = HEADING_RE.match(line)
        if m:
            flush()
            text = m.group(2).strip()
            if len(text) > blk.LIMITS["heading"]:
                problems.append("第 %d 行：標題超過 %d 字" % (lineno, blk.LIMITS["heading"]))
            out.append({"t": "h", "level": len(m.group(1)), "text": text[:blk.LIMITS["heading"]]})
            continue
        m = IMG_RE.match(stripped)
        if m:
            flush()
            caption, src = m.group(1).strip(), m.group(2).strip()
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", src):
                problems.append("第 %d 行：圖片要放在本機資料夾、寫檔名，不能用網址" % lineno)
                continue
            if "/" in src or "\\" in src or src in (".", ".."):
                problems.append("第 %d 行：圖片只寫檔名就好（放在同名資料夾裡，不要寫路徑）" % lineno)
                continue
            if len(caption) > blk.LIMITS["caption"]:
                problems.append("第 %d 行：圖說超過 %d 字" % (lineno, blk.LIMITS["caption"]))
            b = {"t": "img", "src": src}
            if caption:
                b["caption"] = caption[:blk.LIMITS["caption"]]
            out.append(b)
            continue
        m = VIDEO_RE.match(stripped)
        if m:
            flush()
            url, title = m.group(1).strip(), (m.group(2) or "").strip()
            if not blk.is_https(url, blk.LIMITS["url"]):
                problems.append("第 %d 行：影片網址要是 https:// 開頭（最多 %d 字）" % (lineno, blk.LIMITS["url"]))
                continue
            if len(title) > blk.LIMITS["video_title"]:
                problems.append("第 %d 行：影片標題超過 %d 字" % (lineno, blk.LIMITS["video_title"]))
            b = {"t": "video", "url": url}
            if title:
                b["title"] = title[:blk.LIMITS["video_title"]]
            out.append(b)
            continue
        m_ul, m_ol = UL_RE.match(line), OL_RE.match(line)
        if m_ul or m_ol:
            ordered = bool(m_ol)
            text = (m_ol or m_ul).group(1)
            if para:
                flush()
            if lst is not None and lst["ordered"] != ordered:
                flush()
            if lst is None:
                lst = {"ordered": ordered, "items": []}
            lst["items"].append([text])
            continue
        if lst is not None:
            flush()
        para.append(line.rstrip())
    flush()

    for i, b in enumerate(out):
        if b["t"] == "list" and len(b["items"]) > blk.LIMITS["list_items"]:
            problems.append("第 %d 個區塊：清單超過 %d 項" % (i + 1, blk.LIMITS["list_items"]))
        for spans in ([b.get("spans")] if "spans" in b else []) + [it["spans"] for it in b.get("items", [])]:
            if spans is not None and len(spans) > blk.LIMITS["spans"]:
                problems.append("第 %d 個區塊：粗體、斜體、連結太多（超過 %d 段），請拆成幾段" % (i + 1, blk.LIMITS["spans"]))
    if len(out) > blk.LIMITS["blocks"]:
        problems.append("正文超過 %d 個區塊（現在 %d 個）：請拆成兩篇" % (blk.LIMITS["blocks"], len(out)))
    if problems:
        raise MdError(problems)
    return out


def image_sources(blocks):
    """正文裡用到的本機圖片檔名（照出現順序、不重複）。"""
    seen = []
    for b in blocks:
        if b.get("t") == "img" and b.get("src") not in seen:
            seen.append(b["src"])
    return seen


def fill_pids(blocks, src_to_pid):
    """把 img 區塊的 src 換成 pid（回新的清單，不改原本的）。"""
    out = []
    for b in blocks:
        if b.get("t") == "img":
            nb = {"t": "img", "pid": src_to_pid[b["src"]]}
            if b.get("caption"):
                nb["caption"] = b["caption"]
            out.append(nb)
        else:
            out.append(b)
    return out
