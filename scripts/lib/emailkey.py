#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""emailkey.py — email 正規化成「email 鍵」（emailKey）的唯一 Python 正本。

為什麼要正規化：同一個信箱有好幾種寫法。Google 登入拿到的是帳號建立時的寫法（可能有大寫、
可能有點號），老師在通訊錄裡打的是另一種；兩邊對不上時，家長明明在名單裡卻被擋在門外，
而且畫面上看不出原因。所以名單的 doc id、規則裡的比對、前端讀自己的名單文件，三邊一律先轉成
同一個鍵再比。

規則（跟 docs/DATA-MODEL.md §0.3 的安全規則骨架、前端 site/js/core/emailkey.js 是同一套，
三邊共用測試向量 tests/fixtures/emailkey_vectors.json）：

  1. 前後空白去掉，全部轉小寫。
  2. 一定剛好一個 @，@ 前後都不能是空的；字元集照 EMAIL_RE（嚴格，擋引號、反斜線、空白）。
  3. 網域是 gmail.com 或 googlemail.com：@ 前面的點號全部拿掉，網域統一寫成 gmail.com
     （Gmail 本來就不看點號；googlemail.com 是同一個信箱的舊網域）。
  4. 其他網域（包括學校的 Google Workspace 網域）：點號照留——那些網域的點號是有意義的。
  5. 「+」後綴不處理（照原樣保留）。

這支只用標準庫。
"""
import re

# 嚴格的信箱字元集。**不要放寬它**：導師的 email 鍵會被插進安全規則的字串字面值裡。
# 寬鬆的 pattern（例如 `[^@\s]+`）會放行帶引號、管線符號的字串——那種字串貼進規則以後，
# 判斷「是不是老師本人」的條件可能被改寫成恆真。scripts/build_config.py 也用這一個。
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

GMAIL_DOMAINS = ("gmail.com", "googlemail.com")
CANONICAL_GMAIL = "gmail.com"


def email_key(raw):
    """把一個 email 轉成 email 鍵。不合法就丟 ValueError（訊息不含原字串，避免把 email 印進紀錄）。"""
    if not isinstance(raw, str):
        raise ValueError("email 必須是文字")
    e = raw.strip().lower()
    if e.count("@") != 1:
        raise ValueError("email 必須剛好有一個 @")
    local, domain = e.split("@")
    if not local or not domain:
        raise ValueError("email 的 @ 前後都不能是空的")
    if not EMAIL_RE.match(e):
        raise ValueError("email 含有不允許的字元或格式不對")
    if domain in GMAIL_DOMAINS:
        local = local.replace(".", "")
        if not local:
            raise ValueError("gmail 信箱去掉點號後是空的")
        domain = CANONICAL_GMAIL
    return local + "@" + domain


def is_valid(raw):
    """合法回 True，不合法回 False（不丟例外）。"""
    try:
        email_key(raw)
        return True
    except ValueError:
        return False
