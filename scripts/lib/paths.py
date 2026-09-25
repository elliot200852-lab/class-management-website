#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paths.py — repo 根目錄與 data/ 路徑的唯一正本。

兩個概念：
  PKG  ＝ 這份程式碼在哪（scripts/lib/ 的上兩層）。templates/、config/class.example.json、
         data-template/ 這些「跟著程式碼走」的檔案住這裡。
  ROOT ＝ 這位老師的資料與設定在哪。平常 ROOT == PKG；測試或進階安裝時用 `--root <目錄>`
         或環境變數 CMW_ROOT 指到別處，讓真實的班級資料跟 repo 本身分開。

找檔一律走 pkg_path()：ROOT 有就用 ROOT 的，沒有才回頭找 PKG 的（範本用得到）。

刻意不寫死這份 repo 的資料夾名稱——一律用 `__file__` 往上算，改資料夾名字（例如
clone 下來自己改名）也不會壞。
"""
import os
from pathlib import Path

# scripts/lib/paths.py → scripts/lib → scripts → repo 根
_PKG = Path(__file__).resolve().parent.parent.parent
_root_override = None


def set_root(path):
    """把資料根目錄改到別的地方（`--root` 或測試用）。回傳新的根目錄（Path）。"""
    global _root_override
    _root_override = Path(path).expanduser().resolve()
    return _root_override


def reset_root():
    """清掉 set_root() 的覆蓋，回到預設（CMW_ROOT 或 PKG）。測試的 tearDown 用。"""
    global _root_override
    _root_override = None


def root():
    """這位老師的資料根目錄（Path）。"""
    if _root_override is not None:
        return _root_override
    env = os.environ.get("CMW_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return _PKG


def pkg_root():
    """程式碼本身所在的資料夾（Path），不受 --root／CMW_ROOT 影響。"""
    return _PKG


def rpath(*parts):
    """ROOT 底下的路徑（Path）。"""
    return root().joinpath(*parts)


def pkg_path(*parts):
    """先找 ROOT 底下有沒有，沒有才用 PKG 的（範本、樣板這類跟著程式碼走的檔案）。"""
    p = root().joinpath(*parts)
    if p.exists():
        return p
    return _PKG.joinpath(*parts)


def data_dir():
    """這位老師的資料夾（Path）：data/。"""
    return rpath("data")


def add_root_arg(ap):
    """給每支腳本的 argparse 加上共用的 `--root`。"""
    ap.add_argument("--root", metavar="目錄",
                     help="資料根目錄（測試或進階安裝才需要；預設＝這份 repo 所在資料夾）")
    return ap


def apply_root(args):
    """套用 argparse 解析出來的 `--root`（沒給就不動）。回傳目前的 root()。"""
    if getattr(args, "root", None):
        set_root(args.root)
    return root()


def rerun_flags(args):
    """腳本印「再跑：…」時要原樣帶回的旗標：`--root`（有給的話）與 `--emulator`（模擬器／試玩環境）。

    少了它們，照著提示再跑一次就會打到別的資料夾，或從模擬器跑到真的雲端。回傳前面帶一個空白的字串
    （沒有要帶的就回空字串），直接接在指令後面用。路徑一律用正斜線（Mac、Windows 三種終端機都看得懂）。
    """
    out = ""
    r = getattr(args, "root", None)
    if r:
        out += ' --root "%s"' % str(r).replace("\\", "/")
    if getattr(args, "emulator", False):
        out += " --emulator"
    return out
