#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""new_block.py — 開一個新的課程單元：從範本建 data/units/<單元>/ 與 data/courses/<單元>/records.md。

  data/units/<單元>/
    大綱.md          單元大綱（目標、每週安排、準備、參考資料）
    session.yaml     基本資料（名稱、學年、起訖日、預計堂數）
    lessons/         逐堂教案（01-主題.md …）
    texts/           學生文本（詩、故事、閱讀單）
  data/courses/<單元>/records.md   課程紀錄（每堂記一段；寫「課」，不寫某一個孩子）

範本在 templates/unit/ 與 templates/course-records.md。**已經存在的檔一律不覆蓋**（重跑很安全）。
單元名稱也是課堂檔案歸檔（archive_media.py）的資料夾名：只准一般文字，不准斜線這類符號，不准有學生名字。
學年照 config/class.json 的 school_year.start_month 算（沒有設定檔就用預設的 8 月）。

用法（Windows 把 python3 換成 py -3）：
  python3 scripts/new_block.py 範例單元
  python3 scripts/new_block.py 範例單元 --title "範例單元（示範）" --start 2031-03-03 --end 2031-03-28
"""
import sys
import json
import shutil
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, namecheck  # noqa: E402
from lib.drivetree import name_problem, school_year, to_date, year_settings  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

EXIT_STOPPED = 2


def render(text, values):
    for k, v in values.items():
        text = text.replace("{{%s}}" % k, v)
    return text


def start_month():
    """config/class.json 的 school_year.start_month（沒有設定檔、讀不懂就用預設值）。"""
    p = paths.rpath("config", "class.json")
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    except (OSError, ValueError):
        raw = {}
    return year_settings(raw if isinstance(raw, dict) else {})[0]


def plan_files(block, values):
    """回 [(範本檔, 目的地)]。"""
    src = paths.pkg_path("templates", "unit")
    dst = paths.data_dir() / "units" / block
    out = []
    for p in sorted(src.rglob("*")):
        if p.is_file():
            out.append((p, dst / p.relative_to(src)))
    out.append((paths.pkg_path("templates", "course-records.md"), paths.data_dir() / "courses" / block / "records.md"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="從範本開一個新的課程單元資料夾（不覆蓋既有檔）")
    paths.add_root_arg(ap)
    ap.add_argument("block", help="單元名稱（也是資料夾名，例如 範例單元）")
    ap.add_argument("--title", help="顯示用的單元名稱（預設＝資料夾名）")
    ap.add_argument("--start", default="", help="第一天 YYYY-MM-DD")
    ap.add_argument("--end", default="", help="最後一天 YYYY-MM-DD")
    a = ap.parse_args(argv)
    paths.apply_root(a)
    block = a.block
    prob = name_problem(block, "單元名稱", max_len=30)
    if not prob and block.startswith("_"):
        prob = "單元名稱不能用底線開頭"
    if prob:
        print("✗ %s：%r" % (prob, block))
        return EXIT_STOPPED
    for label, v in (("--start", a.start), ("--end", a.end)):
        if v:
            try:
                to_date(v)
            except ValueError:
                print("✗ %s 要寫成 YYYY-MM-DD" % label)
                return EXIT_STOPPED
    needles = namecheck.load(paths.data_dir())
    hit = namecheck.find(block + " " + (a.title or ""), needles or [])
    if hit:
        print("✗ 單元名稱或標題裡有學生的名字（座號 %s），換一個" % "、".join(hit))
        return EXIT_STOPPED
    if not paths.data_dir().is_dir():
        print("✗ 找不到 data/。先跑 python3 scripts/init_data.py")
        return EXIT_STOPPED
    values = {"block": block, "title": a.title or block, "start": a.start, "end": a.end,
              "school_year": school_year(a.start or None, start_month())}
    made, kept = [], []
    for src, dst in plan_files(block, values):
        if dst.exists():
            kept.append(dst)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in (".md", ".yaml", ".txt"):
            dst.write_text(render(src.read_text(encoding="utf-8"), values), encoding="utf-8")
        else:
            shutil.copyfile(str(src), str(dst))
        made.append(dst)
    root = paths.root()
    for p in made:
        print("  ＋ %s" % p.relative_to(root).as_posix())
    for p in kept:
        print("  － %s（已經有了，沒動）" % p.relative_to(root).as_posix())
    print("✓ 課程單元「%s」%s。課堂檔案歸檔時用 --block \"%s\"。" % (block, "開好了" if made else "本來就開好了", block))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
