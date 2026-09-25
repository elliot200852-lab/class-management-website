#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parent_note.py — 家長通知信：把代理寫好、老師看過的草稿，用這台電腦的**預設郵件程式**打開成一封待寄的信。

**這支不寄信**：它只把收件人、主旨、內文填進郵件程式（mailto:），由老師自己看過、自己按「傳送」。
沒有接任何寄信服務，也不需要任何密碼。只在老師明講「寄給幾號的家長」時才用（playbooks/parent-note.md）。

為什麼要這支（而不是代理自己組 mailto）：家長信箱在 data/contacts.csv、孩子的稱呼在 data/roster.csv，
**代理不准打開這兩個檔**（AGENTS.md 鐵則 5）。代理寫草稿時用「〔孩子〕」代替孩子的稱呼，這支在打開郵件程式的那一刻
才換成真的稱呼、填上家長信箱——代理從頭到尾看不到名字與信箱，螢幕上只印座號、稱謂與遮住的信箱。

草稿檔（代理寫；UTF-8）：data/parent-notes/<座號>-<日期>.md
    ---
    subject: 〔孩子〕最近在學校的情形
    ---
    〔孩子〕的家長您好：
    ……（正文，純文字；空一行＝分段。開頭、稱呼、署名照老師自己的習慣寫）

用法（Windows 把 python3 換成 py -3）：
  python3 scripts/parent_note.py --seat 3 --draft data/parent-notes/03-2026-10-01.md
      預覽（唯讀）：會寄給這個座號的哪幾位家長（稱謂＋遮住的信箱）、主旨與內文長度、〔孩子〕出現幾次
  python3 scripts/parent_note.py --seat 3 --draft … --to 母 --to 父
      只寄給這幾個稱謂（不加＝這個座號所有登記的家長；暫停的不算）
  python3 scripts/parent_note.py --seat 3 --draft … --open
      用預設郵件程式打開（老師看過、自己按傳送）。內文太長、郵件程式吃不下時，會另外打開一份純文字檔讓老師複製貼上
exit：0＝成功（或只是預覽）；2＝輸入或名單有問題（包括草稿檔名開頭的座號跟 --seat 不一樣）、什麼都沒打開。
"""
import os
import re
import sys
import argparse
import subprocess
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, hostos, sources  # noqa: E402
from lib import frontmatter as fm  # noqa: E402
from lib.seats import parse_seat  # noqa: E402
from lib.filesafe import write_text_atomic  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

PLACEHOLDER = "〔孩子〕"
EXIT_STOPPED = 2
MAX_SUBJECT, MAX_BODY = 120, 4000
# mailto: 整串網址的長度上限（Windows 的「用預設程式打開」大約 2,000 字就截斷；Mac 與 Linux 寬很多）
URL_LIMIT = {"win": 2000, "mac": 60000, "linux": 30000}


def mask(key):
    a, b = key.split("@", 1)
    return "%s***@%s" % (a[:1], b)


def read_draft(p):
    """回 (主旨, 內文) 或丟 ValueError（白話）。"""
    try:
        text = Path(p).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        raise ValueError("讀不到草稿檔 %s（要是 UTF-8 文字檔）" % p)
    try:
        meta, body, _ = fm.split(text)
    except fm.FrontmatterError as e:
        raise ValueError("草稿檔頭有問題：%s" % "；".join(e.problems))
    probs = fm.check_keys(meta, ("subject",), ("subject",))
    if probs:
        raise ValueError("草稿檔頭：%s" % "；".join(probs))
    subject = re.sub(r"[\r\n\t]+", " ", str(meta["subject"])).strip()
    body = fm.normalize_text(body).strip("\n")
    if not (1 <= len(subject) <= MAX_SUBJECT):
        raise ValueError("主旨要 1–%d 字" % MAX_SUBJECT)
    if not body.strip():
        raise ValueError("內文是空的")
    if len(body) > MAX_BODY:
        raise ValueError("內文超過 %d 字：家長信寫短一點" % MAX_BODY)
    return subject, body


DRAFT_SEAT_RE = re.compile(r"^(\d{1,2})(?=[-_.])")


def draft_seat(filename):
    """草稿檔名開頭的座號（'03-2026-10-01.md' → '03'）；檔名不是座號開頭 → None（不檢查）。"""
    m = DRAFT_SEAT_RE.match(filename or "")
    if not m:
        return None
    try:
        return parse_seat(m.group(1))
    except ValueError:
        return None


def recipients(contacts, seat, relations):
    """這個座號的家長（不含同仁、不含暫停、要有信箱）。relations 給了就只留這幾個稱謂。回 [(稱謂, email 鍵)]。"""
    out = []
    for c in contacts:
        if c.staff or c.paused or not c.key or c.seat != seat:
            continue
        if relations and c.relation not in relations:
            continue
        out.append((c.relation, c.key))
    seen, uniq = set(), []
    for rel, key in out:
        if key not in seen:
            seen.add(key)
            uniq.append((rel, key))
    return uniq


def fill(text, display):
    return text.replace(PLACEHOLDER, display)


def mailto(to_keys, subject, body=None):
    q = [("subject", subject)]
    if body is not None:
        q.append(("body", body.replace("\n", "\r\n")))
    query = "&".join("%s=%s" % (k, urllib.parse.quote(v, safe="")) for k, v in q)
    return "mailto:%s?%s" % (",".join(urllib.parse.quote(k, safe="@.+-_") for k in to_keys), query)


def open_with_system(target):
    if hostos.OS == "mac":
        subprocess.run(["open", target], check=False)
    elif hostos.OS == "win":
        os.startfile(target)  # noqa: S606（Windows 的標準做法）
    else:
        subprocess.run(["xdg-open", target], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="家長通知信：用預設郵件程式打開一封待寄的信（不寄信；老師自己按傳送）")
    ap.add_argument("--seat", required=True, help="座號（1–40）")
    ap.add_argument("--draft", required=True, help="草稿檔（data/parent-notes/<座號>-<日期>.md）")
    ap.add_argument("--to", action="append", default=[], metavar="稱謂", help="只寄給這個稱謂（可以給好幾次，例如 --to 母 --to 父）")
    ap.add_argument("--open", action="store_true", help="用預設郵件程式打開（老師看過、同意之後才加）")
    paths.add_root_arg(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        seat = parse_seat(a.seat)
    except ValueError:
        print("✗ 座號要是 1–40")
        return EXIT_STOPPED
    draft = Path(a.draft)
    if not draft.is_absolute():
        draft = paths.root() / draft
    named = draft_seat(draft.name)
    if named is not None and named != seat:
        # 草稿檔名 <座號>-<日期>.md：檔名的座號跟 --seat 對不上，多半是拿錯草稿（會把別人孩子的事寄給這一家）
        print("✗ 草稿檔名開頭是座號 %s，可是 --seat 是 %s：是不是拿錯草稿了？什麼都沒打開。" % (named, seat))
        print("  → 確認要寄給幾號，--seat 與草稿檔名的座號要一樣（草稿檔名：<座號>-<日期>.md）。")
        return EXIT_STOPPED
    try:
        subject, body = read_draft(draft)
    except ValueError as e:
        print("✗ %s" % e)
        return EXIT_STOPPED
    data = paths.data_dir()
    try:
        students, notes1 = sources.load_roster(data / "roster.csv")
        contacts, notes2 = sources.load_contacts(data / "contacts.csv")
    except sources.SourceError as e:
        print("✗ 名單讀不懂（什麼都沒打開）：")
        for p in e.problems:
            print("  → " + p)
        return EXIT_STOPPED
    for n in notes1 + notes2:
        print("提醒：" + n)
    stu = next((s for s in students if s.seat == seat), None)
    if stu is None:
        print("✗ data/roster.csv 裡沒有座號 %s" % seat)
        return EXIT_STOPPED
    to = recipients(contacts, seat, set(a.to))
    if not to:
        print("✗ 座號 %s 找不到可以寄的家長%s（data/contacts.csv 裡要有信箱、不能是暫停）。"
              % (seat, "（稱謂：%s）" % "、".join(a.to) if a.to else ""))
        return EXIT_STOPPED
    n_ph = subject.count(PLACEHOLDER) + body.count(PLACEHOLDER)
    print("家長通知信（不寄信：只是用郵件程式打開，老師自己按傳送）")
    print("  座號 %s｜收件 %d 位：%s" % (seat, len(to), "、".join("%s %s" % (r, mask(k)) for r, k in to)))
    print("  主旨 %d 字、內文 %d 字；「%s」出現 %d 次（打開郵件程式時才換成孩子的稱呼）"
          % (len(subject), len(body), PLACEHOLDER, n_ph))
    if n_ph == 0:
        print("  提醒：草稿裡沒有「%s」——稱呼那一行（例如「〔孩子〕的家長您好：」）要用它，不要直接寫名字。" % PLACEHOLDER)
    if not a.open:
        print("\n這只是預覽。老師看過草稿、說「好」之後，加 --open 用郵件程式打開。")
        return 0
    subj = fill(subject, stu.display)
    text = fill(body, stu.display)
    keys = [k for _, k in to]
    url = mailto(keys, subj, text)
    limit = URL_LIMIT.get(hostos.OS, 2000)
    if len(url) <= limit:
        open_with_system(url)
        print("✓ 已用預設郵件程式打開。請老師看過收件人、主旨、內文，自己按「傳送」。這支不會寄任何信。")
        return 0
    # 太長：郵件程式只帶收件人與主旨，內文另存純文字檔打開，請老師複製貼上
    out = data / "exports" / "parent-notes" / ("%s-內文（貼進信裡）.txt" % seat)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(out, text + "\n")
    open_with_system(mailto(keys, subj))
    open_with_system(str(out))
    print("✓ 內文比較長，郵件程式一次吃不下：已打開一封只有收件人與主旨的信，另外打開一份純文字檔。")
    print("  請老師把純文字檔的內容全部複製、貼進信裡，看過再自己按「傳送」。寄出後那份純文字檔可以刪掉。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
