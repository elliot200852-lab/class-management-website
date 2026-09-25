#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""init_data.py — 把 data-template/ 複製成 data/（已存在的檔不覆蓋、不刪任何東西）。

data-template/ 是進 git 的空白資料框架；data/ 是這個班真正的資料，一律不進 git
（見 .gitignore）。這支只做「補上缺的」，已經有的檔一個字都不動——重跑很安全。

順便檢查：這個 repo 現在放的位置會不會被雲端同步軟體（iCloud「桌面與文件」、OneDrive）
悄悄同步走——那些地方常常會鎖檔、或把 data/ 裡的真實名冊同步到你意料之外的雲端帳號。
這裡只提醒，不會自動搬動任何東西。

用法：
  python3 scripts/init_data.py          （Windows：py -3 scripts/init_data.py）
"""
import sys
import shutil
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, hostos
from lib.console import setup_utf8

setup_utf8()


def copy_tree_no_overwrite(src: Path, dst: Path):
    """把 src 底下的每一個檔案複製到 dst，目的地已經有的檔不覆蓋、不比對內容。
    回傳 (copied, skipped)，兩者都是相對 src 的路徑清單（Path）。"""
    copied, skipped = [], []
    if not src.exists():
        return copied, skipped
    for s in sorted(src.rglob("*")):
        rel = s.relative_to(src)
        d = dst / rel
        if s.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            continue
        if d.exists():
            skipped.append(rel)
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
        copied.append(rel)
    return copied, skipped


def sync_warnings(repo_root: Path):
    """repo 路徑是否落在 iCloud「桌面與文件」或 OneDrive 同步範圍——回傳警告字串清單。
    判斷不出來（例如 mac 上不確定 iCloud 桌面同步有沒有開）的情況，一律「只提醒」。"""
    warnings = []
    home = Path.home()
    try:
        resolved = repo_root.resolve()
    except OSError:
        resolved = repo_root

    if hostos.OS == "mac":
        mobile_docs = home / "Library" / "Mobile Documents"
        try:
            if mobile_docs.exists() and str(resolved).startswith(str(mobile_docs.resolve())):
                warnings.append(
                    "這個資料夾在 iCloud「Mobile Documents」同步範圍裡——data/ 會被同步到 iCloud。"
                    "建議把整個資料夾搬到不會被 iCloud 同步的位置。")
        except OSError:
            pass
        for name in ("Desktop", "Documents"):
            d = home / name
            try:
                if d.exists() and str(resolved).startswith(str(d.resolve())):
                    warnings.append(
                        "這個資料夾在 ~/%s 裡。如果你的 Mac 開著「iCloud 雲碟 → 桌面與文件夾」同步，"
                        "data/ 也會被同步到 iCloud——這裡沒辦法自動判斷你有沒有開，"
                        "請自己到「系統設定 → 你的 Apple 帳號 → iCloud 雲碟」確認；"
                        "開著的話建議把整個資料夾搬出 ~/%s。" % (name, name))
            except OSError:
                pass
    elif hostos.OS == "win":
        od = hostos.onedrive_root()
        if od:
            try:
                if str(resolved).lower().startswith(str(Path(od).resolve()).lower()):
                    warnings.append(
                        "這個資料夾在 OneDrive 同步範圍裡（%s）。OneDrive 會鎖檔，"
                        "也可能把 data/ 裡的真實名冊同步到雲端。建議把整個資料夾搬到 OneDrive 外面"
                        "（例如 C:\\Users\\你\\class-management-website）。" % od)
            except OSError:
                pass
    return warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description="把 data-template/ 複製成 data/（不覆蓋既有檔）")
    paths.add_root_arg(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)

    root = paths.root()
    for w in sync_warnings(root):
        print("！ %s" % w)

    src = paths.pkg_path("data-template")
    dst = paths.rpath("data")
    copied, skipped = copy_tree_no_overwrite(src, dst)

    print("已建立 data/（來源：data-template/）")
    print("  新增 %d 個檔案" % len(copied))
    if skipped:
        print("  已存在、沒有覆蓋 %d 個檔案（%s）" %
              (len(skipped), "、".join(str(p) for p in skipped[:5]) + ("…" if len(skipped) > 5 else "")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
