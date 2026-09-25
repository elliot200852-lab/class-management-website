#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preview.py — 發文前的本機預覽頁（exports/preview/*.html）：讓老師先看「上線後大概長這樣」。

  · 一個檔、零外部相依：CSS 寫在頁面裡，照片是處理過（已清 EXIF、已壓縮）的那一份，用 data: 內嵌。
  · 所有文字一律 html.escape；連結只有 https:// 才畫成連結——跟網站的渲染規則同一個方向。
  · 這個檔只在老師自己的電腦（exports/ 不進 git）；確認完可以刪，腳本下次會重產。
"""
import html

from . import blocks as blk

CSS = """
:root{--bg:#f7f7f2;--ink:#22262e;--muted:#5a606e;--line:#c8ccbe;--accent:#34487f;--card:#fff;--bar:#8a1f2d}
@media (prefers-color-scheme:dark){:root{--bg:#1b1f27;--ink:#edeee6;--muted:#b9bdb0;--line:#3a404c;--accent:#a9b8e6;--card:#242933;--bar:#8a1f2d}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.8 system-ui,-apple-system,"PingFang TC","Microsoft JhengHei",sans-serif}
.bar{background:var(--bar);color:#fff;padding:10px 16px;font-weight:600}
main{max-width:760px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6em;line-height:1.35;margin:.2em 0}h2{font-size:1.3em}h3{font-size:1.15em}h4{font-size:1.05em}
.meta{color:var(--muted);font-size:.92em}.tag{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:0 10px;margin-right:6px}
figure{margin:1.2em 0}figure img{max-width:100%;height:auto;border-radius:8px;display:block}
figcaption{color:var(--muted);font-size:.9em;margin-top:.3em}
blockquote{border-left:4px solid var(--line);margin:1em 0;padding:.2em 1em;color:var(--muted)}
hr{border:0;border-top:1px dashed var(--line);margin:2em 0}
.video{border:1px solid var(--line);border-radius:8px;padding:10px 14px;background:var(--card)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.grid figure{margin:0}.grid img{aspect-ratio:1/1;object-fit:cover;width:100%}
.card{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:var(--card);margin:10px 0}
.summary{border:1px solid var(--line);border-radius:10px;padding:10px 14px;background:var(--card);font-size:.92em;margin-bottom:1.5em}
.summary li{margin:.1em 0}.body-pre{white-space:pre-wrap}
a{color:var(--accent)}
"""


def esc(s):
    return html.escape(s if isinstance(s, str) else str(s), quote=True)


def data_uri(b64):
    return "data:image/jpeg;base64," + b64


def spans_html(spans):
    out = []
    for s in spans:
        t = "<br>".join(esc(x) for x in s.get("text", "").split("\n"))
        if s.get("href") and blk.is_https(s["href"]):
            t = '<a href="%s" rel="noopener noreferrer" target="_blank">%s</a>' % (esc(s["href"]), t)
        if s.get("i"):
            t = "<em>%s</em>" % t
        if s.get("b"):
            t = "<strong>%s</strong>" % t
        out.append(t)
    return "".join(out)


def blocks_html(blocks, pid_src):
    """區塊 → HTML。pid_src：{pid: data URI}。"""
    out = []
    for b in blocks:
        t = b.get("t")
        if t == "p":
            out.append("<p>%s</p>" % spans_html(b["spans"]))
        elif t == "quote":
            out.append("<blockquote>%s</blockquote>" % spans_html(b["spans"]))
        elif t == "h":
            out.append("<h%d>%s</h%d>" % (b["level"], esc(b["text"]), b["level"]))
        elif t == "list":
            tag = "ol" if b["ordered"] else "ul"
            out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % spans_html(it["spans"]) for it in b["items"]), tag))
        elif t == "hr":
            out.append("<hr>")
        elif t == "img":
            src = pid_src.get(b.get("pid"), "")
            cap = b.get("caption", "")
            out.append('<figure><img src="%s" alt="%s">%s</figure>'
                       % (esc(src), esc(cap), ("<figcaption>%s</figcaption>" % esc(cap)) if cap else ""))
        elif t == "video":
            title = b.get("title") or "影片"
            out.append('<div class="video">▶ %s：<a href="%s" rel="noopener noreferrer" target="_blank">%s</a></div>'
                       % (esc(title), esc(b["url"]), esc(b["url"])))
    return "\n".join(out)


def page(doc_title, heading, meta_bits, summary_lines, body_html):
    tags = "".join('<span class="tag">%s</span>' % esc(m) for m in meta_bits if m)
    summary = "".join("<li>%s</li>" % esc(s) for s in summary_lines)
    return ("<!doctype html>\n<html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex, nofollow\">"
            "<title>%s</title><style>%s</style></head><body>"
            "<div class=\"bar\">預覽：這一頁只在你的電腦上，還沒有上線。</div>"
            "<main><ul class=\"summary\">%s</ul><h1>%s</h1><div class=\"meta\">%s</div>%s</main></body></html>\n"
            % (esc(doc_title), CSS, summary, esc(heading), tags, body_html))


def grid_html(items):
    """相簿格：[(data URI, 圖說)]。"""
    cells = []
    for src, cap in items:
        cells.append('<figure><img src="%s" alt="%s">%s</figure>'
                     % (esc(src), esc(cap), ("<figcaption>%s</figcaption>" % esc(cap)) if cap else ""))
    return '<div class="grid">%s</div>' % "".join(cells)
