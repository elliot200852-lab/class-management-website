#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""where.py — 「我的資料在哪？」一次印出這個班所有東西的位置。唯讀、不連網。

  · 網站網址、Firebase 主控台（資料、使用者、用量）
  · 雲端硬碟同步夾的每一個資料夾（在不在）
  · 這台電腦 data/ 的每一個資料夾
  · 最新一份備份在哪（本機快照、同步夾快照、紀錄備份）

用法（Windows 把 python3 換成 py -3）：
  python3 scripts/where.py
  python3 scripts/where.py --open media          用系統預設程式打開「課堂檔案」資料夾
  python3 scripts/where.py --open inbox          打開 data/inbox/
  python3 scripts/where.py --open site           用瀏覽器打開網站
  python3 scripts/where.py --list-names          列出 --open 可以用的名稱
  python3 scripts/where.py --open data/personal-photos       也可以給這個資料夾裡的路徑（資料夾或要看的檔）
  python3 scripts/where.py --open exports/preview/post-x.html

要打開資料夾或檔案給老師看，一律用這一支：Mac、Windows 的命令提示字元、PowerShell、Git Bash 都是同一個寫法，
路徑的斜線照寫 /（open、explorer、start 各有各的毛病：explorer 看不懂 /、start 在 PowerShell 是另一個指令）。
"""
import os
import sys
import json
import argparse
import subprocess
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, hostos  # noqa: E402
from lib import drivetree as dt  # noqa: E402
from lib import fsbackup as fsb  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

EXIT_STOPPED = 2

DATA_FOLDERS = [
    ("data", "", "這個班的全部資料（不進 git）"),
    ("inbox", "inbox", "待歸檔的課堂照片、影片、音檔、文件"),
    ("class-posts", "class-posts", "班級紀事母本"),
    ("private-posts", "private-posts", "私密紀事母本"),
    ("albums", "albums", "相簿（說明檔＋原圖）"),
    ("pages", "pages", "關於我們、專題活動等單頁"),
    ("blog-drafts", "blog-drafts", "導師替孩子發的部落格草稿"),
    ("student-blogs", "student-blogs", "學生部落格的本機備份（每個座號一個夾）"),
    ("units", "units", "課程單元資料（大綱、教案、學生文本）"),
    ("courses", "courses", "課程紀錄（每個單元一份 records.md）"),
    ("ledgers", "ledgers", "台帳（備份狀態、歸檔紀錄）"),
    ("backups", "backups", "本機的資料庫快照"),
    ("exports", "exports", "預覽與匯出檔"),
]


def console_links(project_id):
    base = "https://console.firebase.google.com/project/%s" % project_id
    return [("console", "Firebase 主控台", base + "/overview"),
            ("console-data", "資料庫內容（Firestore）", base + "/firestore/databases/-default-/data"),
            ("console-users", "登入過的帳號（Authentication）", base + "/authentication/users"),
            ("console-usage", "用量與方案", base + "/usage")]


def open_target(target):
    """用系統預設程式打開資料夾或網址。"""
    t = str(target)
    if t.startswith("https://"):
        webbrowser.open(t)
        return
    if hostos.OS == "mac":
        subprocess.run(["open", t], check=False)
    elif hostos.OS == "win":
        os.startfile(t)  # noqa: S606（Windows 的標準做法）
    else:
        subprocess.run(["xdg-open", t], check=False)


# --open 給路徑時只開「看的」檔（網頁、文字、表格、PDF、照片）；程式、指令檔一律不開（雙擊等於執行）。
VIEW_EXTS = {".html", ".htm", ".txt", ".md", ".csv", ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif",
             ".heic", ".yaml", ".yml", ".json"}


def resolve_path(text):
    """--open 給的是路徑：相對這個班的根目錄解析，只准打開根目錄底下的東西。回 (Path, 錯誤訊息)。"""
    p = Path(str(text).replace("\\", "/")).expanduser()
    base = paths.root().resolve()
    if not p.is_absolute():
        p = base / p
    try:
        rp = p.resolve()
        rp.relative_to(base)
    except (OSError, ValueError):
        return None, "只能打開這個資料夾裡面的東西：%s" % text
    if not rp.exists():
        return None, "這個位置還不存在：%s" % text
    if rp.is_file() and rp.suffix.lower() not in VIEW_EXTS:
        return None, "這種檔不用這支打開（只開資料夾、網頁、文字、表格、PDF、照片）：%s" % rp.name
    return rp, ""


def targets(raw):
    """名稱 → 路徑或網址。"""
    out = {}
    fb = (raw or {}).get("firebase") or {}
    pid = str(fb.get("project_id") or "").strip()
    if pid and not pid.startswith("your-"):
        out["site"] = "https://%s.firebaseapp.com" % pid
        for name, _, url in console_links(pid):
            out[name] = url
    tree = dt.DriveTree.from_config(raw or {})
    if tree.root is not None:
        for k in dt.LOCATIONS:
            out[k] = tree.path(k)
    data = paths.data_dir()
    for name, sub, _ in DATA_FOLDERS:
        out[name] = data / sub if sub else data
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="印出這個班所有東西的位置；--open 打開其中一個")
    paths.add_root_arg(ap)
    ap.add_argument("--open", metavar="名稱或路徑",
                    help="打開這個位置：名稱看 --list-names，或這個資料夾裡的路徑（例如 data/personal-photos；斜線照寫 /）")
    ap.add_argument("--list-names", action="store_true", help="列出 --open 可以用的名稱")
    a = ap.parse_args(argv)
    paths.apply_root(a)
    cfgp = paths.rpath("config", "class.json")
    raw = {}
    if cfgp.exists():
        try:
            raw = json.loads(cfgp.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raw = {}
    tg = targets(raw)
    if a.list_names:
        for k in tg:
            print("  %s" % k)
        return 0
    if a.open:
        t = tg.get(a.open)
        if t is None and ("/" in a.open or "\\" in a.open or "." in a.open):
            t, err = resolve_path(a.open)
            if t is None:
                print("✗ %s" % err)
                return EXIT_STOPPED
        if t is None:
            print("✗ 沒有「%s」這個名稱。可以用的：%s（或給這個資料夾裡的路徑，例如 data/inbox）" % (a.open, "、".join(tg)))
            return EXIT_STOPPED
        if not str(t).startswith("https://") and not Path(t).exists():
            print("✗ 這個位置還不存在：%s" % t)
            return EXIT_STOPPED
        open_target(t)
        print("已打開：%s" % t)
        return 0

    print("這個班的東西在這裡（括號裡是 --open 用的名稱）")
    print("\n網站與雲端：")
    if "site" in tg:
        print("  網站（site）：%s" % tg["site"])
        for name, label, url in console_links(((raw.get("firebase") or {}).get("project_id")) or ""):
            print("  %s（%s）：%s" % (label, name, url))
    else:
        print("  （config/class.json 還沒填 Firebase 專案，網站還沒有網址）")

    tree = dt.DriveTree.from_config(raw)
    print("\nGoogle 雲端硬碟同步夾：")
    if tree.root is None:
        print("  （還沒設定；跑 %s scripts/drive_init.py）" % hostos.PY)
    else:
        probs = tree.problems()
        if probs:
            print("  ！ %s" % probs[0].lines[0])
        for k in dt.LOCATIONS:
            p = tree.path(k)
            mark = "✓" if p.is_dir() else "✗ 不在"
            print("  %s %s（%s）：%s" % (mark, dt.LABELS[k], k, p))

    print("\n這台電腦（data/）：")
    for name, sub, label in DATA_FOLDERS:
        p = tg[name]
        print("  %s %s（%s）：%s" % ("✓" if p.is_dir() else "✗ 不在", label, name, p))

    print("\n最新的備份：")
    base = paths.data_dir() / "backups" / "firestore"
    local = [(i, p) for i, p in fsb.list_snapshots(base) if (fsb.read_manifest(p) or {}).get("kind") == "regular"]
    print("  資料庫快照（本機）：%s" % (local[-1][1] if local else "（還沒有）"))
    if tree.root is not None and not tree.problems(("fs_snapshots", "records_backup")):
        sync = fsb.list_sync_snapshots(tree.path("fs_snapshots"))
        print("  資料庫快照（同步夾）：%s" % (sync[-1][1] if sync else "（還沒有）"))
        latest = tree.path("fs_latest")
        print("  資料庫最新一份（同步夾 latest）：%s" % latest)
        zips = sorted(p for p in tree.path("records_backup").glob("records-*.zip") if p.name != "records-latest.zip")
        print("  紀錄備份（同步夾）：%s" % (zips[-1] if zips else "（還沒有）"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
