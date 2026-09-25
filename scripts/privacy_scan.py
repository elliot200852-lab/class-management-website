#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""privacy_scan.py — 公開 repo 內建的通用隱私掃描器（不含任何私有字典）。

自己用 os.walk 走檔案樹（不呼叫 grep、不吃 .gitignore 的排除規則），跳過 .git/、
node_modules/、__pycache__/、.venv/。抓：
  · 非 example.com／example.org 的 email
  · Google 形狀的長 ID（Drive／Docs：'1' 開頭 25–44 字元；以及網址 /d/…、/folders/… 裡的值）
  · AIza 開頭的 API key
  · 服務帳號信箱（gserviceaccount.com 網域、帳號名稱通常帶 iam 字樣）
  · 台灣身分證字號形狀
  · 台灣手機號碼形狀
  · 文字檔內嵌的 base64 圖片（data:image/...;base64, 後面很長一串）
  · 二進位檔（公開 repo 不該有，列出檔名）

**只印「路徑:行號｜類別」，絕不印命中的字串本身**（CI 紀錄公開後，字串本身也會公開）。
有命中就 exit 1。

允許清單：<掃描根目錄>/privacy-allow.txt，逐行「路徑:行號」（# 開頭當註解、空白行忽略）。
在允許清單裡的那一行，不管命中幾種類別，整行都會被放行——請只在確定是誤判時才加進去。

用法：
  python3 scripts/privacy_scan.py .          # 掃目前目錄（repo 根）
  python3 scripts/privacy_scan.py <目錄>
"""
import os
import re
import sys
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.console import setup_utf8

setup_utf8()

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache"}

ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org"}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Google Drive／Docs 常見的長 ID：'1' 開頭、後面 24–43 個英數字元／-/_（總長 25–44）
GOOGLE_ID_RE = re.compile(r"\b1[A-Za-z0-9_-]{24,43}\b")
# 網址裡 /d/... 或 /folders/... 後面的值（不論長度、不論開頭是不是 1）
GOOGLE_URL_ID_RE = re.compile(r"/(?:d|folders)/([A-Za-z0-9_-]{10,})")
API_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
SERVICE_ACCOUNT_RE = re.compile(r"iam\.gserviceaccount\.com")
# 台灣身分證字號形狀：一個英文字母 + 1或2 + 8 位數字
TW_ID_RE = re.compile(r"\b[A-Za-z][12]\d{8}\b")
# 台灣手機號碼形狀：09 開頭共 10 碼
TW_PHONE_RE = re.compile(r"\b09\d{8}\b")
# 文字檔內嵌的 base64 圖片，門檻抓長一點（200 字元以上）避免誤判小圖示
BASE64_IMAGE_RE = re.compile(r"data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]{200,}")


def classify_line(line):
    """回傳這一行命中的類別集合（set），不含命中字串本身。"""
    hits = set()
    for m in EMAIL_RE.finditer(line):
        domain = m.group(0).split("@", 1)[1].lower()
        if domain not in ALLOWED_EMAIL_DOMAINS:
            hits.add("email")
    if GOOGLE_ID_RE.search(line) or GOOGLE_URL_ID_RE.search(line):
        hits.add("google_id")
    if API_KEY_RE.search(line):
        hits.add("api_key")
    if SERVICE_ACCOUNT_RE.search(line):
        hits.add("service_account")
    if TW_ID_RE.search(line):
        hits.add("tw_id")
    if TW_PHONE_RE.search(line):
        hits.add("tw_phone")
    if BASE64_IMAGE_RE.search(line):
        hits.add("base64_image")
    return hits


def load_allowlist(root: Path):
    p = root / "privacy-allow.txt"
    allow = set()
    if p.exists():
        for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
            s = raw.strip()
            if s and not s.startswith("#"):
                allow.add(s)
    return allow


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in sorted(filenames):
            yield Path(dirpath) / fn


def scan_file(path: Path, root: Path, allow):
    """回傳這個檔案的命中清單 [(相對路徑, 行號, 類別), ...]（不含命中字串）。"""
    rel = path.relative_to(root).as_posix()
    try:
        raw = path.read_bytes()
    except OSError:
        return []

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        key = "%s:1" % rel
        if key in allow:
            return []
        return [(rel, 1, "binary_file")]

    out = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        key = "%s:%d" % (rel, lineno)
        if key in allow:
            continue
        for cat in sorted(classify_line(line)):
            out.append((rel, lineno, cat))
    return out


def scan_tree(root):
    root = Path(root).resolve()
    allow = load_allowlist(root)
    hits = []
    for path in iter_files(root):
        hits.extend(scan_file(path, root, allow))
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description="通用隱私掃描：只印路徑與類別，絕不印命中字串本身")
    ap.add_argument("root", nargs="?", default=".", help="要掃描的目錄（預設：目前目錄）")
    a = ap.parse_args(argv)

    hits = scan_tree(a.root)
    if hits:
        for rel, lineno, cat in sorted(hits):
            print("%s:%d｜%s" % (rel, lineno, cat))
        print("\n共 %d 筆可能的個資／機密痕跡。公開前必須清乾淨；"
              "確定是誤判才加進 privacy-allow.txt（格式：路徑:行號）。" % len(hits), file=sys.stderr)
        return 1
    print("privacy_scan：乾淨，沒有命中。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
