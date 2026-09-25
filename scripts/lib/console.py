"""主控台輸出統一改 UTF-8。

Windows 的主控台預設編碼（英文版 cp1252、繁中版 cp950）印不出部分中文與 ✓ ✗ 這類符號，
Python 一印就丟 UnicodeEncodeError 整支中斷。每支腳本開頭呼叫 setup_utf8() 一次，
印不出的字元改用替代符號，不讓程式因為「顯示」而失敗。
"""
import sys


def setup_utf8():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
