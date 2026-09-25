#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""drive_init.py — 找到 Google 雲端硬碟桌面版的同步夾，在裡面建好這個班的資料夾樹。

**這是唯一會建頂層資料夾樹的腳本。** 其他腳本（備份、歸檔、資料退場）找不到樹就停下來，不會自己建。

資料夾樹：
  <同步夾>/<班名> 班級網站/
    這個資料夾是什麼.txt            ← 說明檔兼標記；其他腳本靠它確認「是這一棵」
    01_機密（只有導師）/ 班級文件/{通用文件, 會議紀錄, 課程, <學年>/<每個學期一夾>}
                        學生個別資料/   課堂檔案/<學年>/   紀錄備份/照片與附件/
    02_分享給家長/科任課程大綱/      ← **只建立、不分享**。要給家長看，由老師自己在雲端硬碟網頁按「共用」
    03_相簿原圖/
    04_部落格歸檔/                   ← 底下只用座號（<座號>/<學年>/），不用姓名
    05_全站備份/firestore/{latest, snapshots, photos}/

用法（Windows 把 python3 換成 py -3）：
  python3 scripts/drive_init.py                      列出這台電腦找得到的同步夾（唯讀），讓代理問老師選哪一個
  python3 scripts/drive_init.py --pick 1 --apply     選第 1 個：寫進 config/class.json（drive.sync_root、drive.class_folder）並建樹
  python3 scripts/drive_init.py --path "<路徑>" --apply   找不到時，老師自己貼同步夾的路徑
  python3 scripts/drive_init.py --apply              已經設定過：把缺的資料夾補回來（已經有的不動；新學年也跑這個）

學年從幾月開始、學期叫什麼，照 config/class.json 的 school_year（沒寫就是 8 月、上學期／下學期；依學校）。
  python3 scripts/drive_init.py --check              唯讀檢查樹還在不在

exit code：0 成功；2 停下來了（沒選、路徑不對、設定檔有問題；什麼都沒寫）。
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, hostos, progress  # noqa: E402
from lib import drivetree as dt  # noqa: E402
from lib.filesafe import write_text_atomic  # noqa: E402
from lib.hostos import PY  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

EXIT_STOPPED = 2


def load_raw():
    p = paths.rpath("config", "class.json")
    if not p.exists():
        raise SystemExit("✗ 找不到 config/class.json。先照 AGENTS.md 安裝步驟 3 建立它，再回來設定同步夾。")
    try:
        return p, json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise SystemExit("✗ config/class.json 讀不懂。先跑 %s scripts/build_config.py --check 看哪裡錯。" % PY)


def save_drive(cfg_path, raw, sync_root, class_folder):
    """只改 drive.sync_root 與 drive.class_folder，其他欄位原樣保留（原子寫）。"""
    drive = dict(raw.get("drive") or {})
    drive["sync_root"] = str(sync_root)
    drive["class_folder"] = class_folder
    raw = dict(raw)
    raw["drive"] = drive
    write_text_atomic(cfg_path, json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
    return raw


def print_tree(class_folder, start_month=dt.DEFAULT_START_MONTH, terms=dt.DEFAULT_TERMS):
    print("  會建立（已經有的不動）：")
    print("    %s/" % class_folder)
    for rel in sorted(dt.tree_folders(None, terms, start_month)):
        print("    %s%s/" % ("  " * len(rel), rel[-1]))
    print("    %s%s" % ("  ", dt.MARKER_NAME))


def main(argv=None):
    ap = argparse.ArgumentParser(description="找雲端硬碟同步夾、建這個班的資料夾樹（只有這支會建頂層樹）")
    paths.add_root_arg(ap)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--pick", type=int, metavar="N", help="選清單裡第 N 個同步夾")
    g.add_argument("--path", metavar="路徑", help="老師自己貼的同步夾路徑")
    ap.add_argument("--apply", action="store_true", help="真的寫設定、建資料夾")
    ap.add_argument("--check", action="store_true", help="唯讀檢查樹還在不在")
    a = ap.parse_args(argv)
    paths.apply_root(a)
    cfg_path, raw = load_raw()
    tree = dt.DriveTree.from_config(raw)
    configured = tree.sync_root is not None

    if a.check:
        probs = tree.problems(tuple(k for k in dt.LOCATIONS if k != "root"))
        if probs:
            print(probs[0].plain())
            return EXIT_STOPPED
        print("✓ 同步夾與資料夾樹都在：%s" % tree.root)
        return 0

    cands = dt.detect_candidates(hostos.OS, str(Path.home()))
    chosen = None
    if a.path:
        chosen = Path(a.path).expanduser()
        if not chosen.is_dir():
            print("✗ 這個路徑不是一個存在的資料夾：%s" % chosen)
            print("  → 請老師在檔案總管（Finder）裡找到「我的雲端硬碟」或「My Drive」，把它的完整路徑貼過來。")
            return EXIT_STOPPED
        if not dt.looks_like_drive(chosen):
            print("！ 這個路徑看起來不像 Google 雲端硬碟的同步夾（名字裡沒有「雲端硬碟」「My Drive」）。")
            print("  放在這裡的東西不會自動上傳到雲端。確定要用的話，照樣加 --apply 就會建。")
    elif a.pick is not None:
        if not (1 <= a.pick <= len(cands)):
            print("✗ 沒有第 %d 個（找到 %d 個）。先不加參數跑一次看清單。" % (a.pick, len(cands)))
            return EXIT_STOPPED
        chosen = Path(cands[a.pick - 1])
    elif configured:
        chosen = tree.sync_root

    if chosen is None:
        if not cands:
            print("找不到 Google 雲端硬碟桌面版的同步夾。")
            print("  → 請老師先安裝並登入「Google 雲端硬碟」桌面版（官方下載：https://www.google.com/drive/download/）。")
            print("    登入時用想放備份的那個 Google 帳號；裝好後，Mac 的 Finder 左邊、Windows 的「本機」裡會出現「Google Drive」。")
            print("  → 裝好後再跑一次：%s scripts/drive_init.py" % PY)
            print("  → 已經裝了卻找不到：請老師打開那個資料夾，把「我的雲端硬碟」（或 My Drive）的完整路徑貼給你，再跑")
            print("       %s scripts/drive_init.py --path \"<路徑>\" --apply" % PY)
            return EXIT_STOPPED
        print("這台電腦找到 %d 個 Google 雲端硬碟同步夾：" % len(cands))
        for i, c in enumerate(cands, start=1):
            print("  %d. %s" % (i, c))
        print("\n請問老師要把班級備份放在哪一個？（路徑裡的帳號名稱就是那個雲端硬碟的 Google 帳號；"
              "學校帳號的雲端硬碟可能會在離職後被收回，建議選自己長期用的帳號。）")
        print("老師選好後跑：%s scripts/drive_init.py --pick <號碼> --apply" % PY)
        return 0

    class_folder = (raw.get("drive") or {}).get("class_folder") or dt.class_folder_name(raw.get("class_name"))
    if configured and chosen != tree.sync_root and tree.root is not None and tree.root.is_dir():
        print("！ config 原本設定的同步夾是 %s（裡面已經有資料夾樹）。" % tree.sync_root)
        print("  換成新的位置以後，舊的備份不會自動搬過去；需要的話請老師自己在雲端硬碟裡搬。")
    print("同步夾：%s" % chosen)
    print("資料夾樹的根：%s" % class_folder)
    print_tree(class_folder, tree.start_month, tree.terms)
    print("  「%s」只建立，不會分享給任何人；要給家長看，由老師自己在雲端硬碟網頁按「共用」。" % dt.SHARE)
    if not a.apply:
        print("\n這只是預覽，什麼都還沒建。老師說好之後加 --apply。")
        return 0
    try:
        created = dt.build_tree(chosen, class_folder, None, tree.terms, tree.start_month)
    except dt.DriveTreeError as e:
        print(e.plain())
        return EXIT_STOPPED
    except OSError as e:
        print("✗ 建資料夾失敗（%s）。雲端硬碟程式有開著嗎？同步夾是不是唯讀？" % (e.strerror or type(e).__name__))
        return EXIT_STOPPED
    if not configured or str(chosen) != str(tree.sync_root) or (raw.get("drive") or {}).get("class_folder") != class_folder:
        save_drive(cfg_path, raw, chosen, class_folder)
        print("  已寫進 config/class.json：drive.sync_root、drive.class_folder")
    tree = dt.DriveTree(chosen, class_folder, tree.start_month, tree.terms)
    probs = tree.problems(tuple(k for k in dt.LOCATIONS if k != "root"))
    if probs:
        print(probs[0].plain())
        return EXIT_STOPPED
    print("✓ 資料夾樹好了（這次新建 %d 個）。雲端硬碟程式會自己把它同步上去。" % len(created))
    prog = progress.read()
    if prog is not None and not progress.step_done(prog, 6):
        # 安裝做到一半（網站還沒部署、名單還沒上去）：備份是步驟 9 的事，現在跑只會撲空
        print("  下一步：回 AGENTS.md 接著做安裝的下一步（備份等到步驟 9 再做）。")
    else:
        print("  下一步：跑一次備份 %s scripts/backup.py all（劇本 playbooks/backup.md）。" % PY)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
