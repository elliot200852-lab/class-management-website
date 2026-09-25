#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gauth.py — 管理腳本「用誰的身分」寫資料庫（docs/ARCHITECTURE.md §6）。

做法：老師自己裝 gcloud CLI、自己跑一次 `gcloud auth login`（用開 Firebase 專案的那個 Google 帳號）。
每次要用時呼叫 `gcloud auth print-access-token` 拿一把約一小時有效的權杖。

  · 權杖只放在這個行程的記憶體裡：**不印、不寫檔、不放進任何錯誤訊息**。
  · 沒有金鑰檔、沒有服務帳號——這個專案不產生任何長期有效的秘密。
  · 模擬器模式（本機測試）不需要 gcloud：權杖一律是字串 "owner"，模擬器把它當成管理身分。

找 gcloud 的順序在 lib/hostos.py：先查 PATH，再查官方安裝程式常放的位置
（Windows 裝完 gcloud 後，已經開著的終端機 PATH 不會更新，這是新手最常卡住的地方）。

只用標準庫。
"""
import subprocess

from . import hostos

INSTALL_URL = "https://cloud.google.com/sdk/docs/install"
EMULATOR_TOKEN = "owner"


class AuthError(Exception):
    """拿不到權杖。title＝一句話說發生什麼事；steps＝下一步怎麼做（給老師或代理看）。"""

    def __init__(self, title, steps):
        super().__init__(title)
        self.title = title
        self.steps = list(steps)

    def plain(self):
        lines = ["✗ " + self.title]
        lines += ["  → " + s for s in self.steps]
        return "\n".join(lines)


def find_gcloud():
    """回 (絕對路徑, 是否在 PATH 上)；找不到回 (None, False)。"""
    try:
        found = hostos.find_exe_all("gcloud")
    except OSError:
        found = []
    return found[0] if found else (None, False)


def _default_runner(argv, timeout):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")


# gcloud 的錯誤字樣 → 白話。只看關鍵字，不把 stderr 整段轉印給老師（可能很長、全是英文）。
_NOT_LOGGED_IN = ("do not currently have an active account", "no credentialed accounts",
                  "gcloud auth login", "you must log in")
_EXPIRED = ("reauthentication", "problem refreshing your current auth tokens", "invalid_grant",
            "token has been expired or revoked")


def explain_gcloud_failure(stderr):
    """gcloud print-access-token 失敗時的白話說明（AuthError）。"""
    low = (stderr or "").lower()
    if any(k in low for k in _EXPIRED):
        return AuthError("gcloud 的登入已經過期了。",
                         ["請老師在終端機跑：gcloud auth login",
                          "瀏覽器跳出來時，選「開這個 Firebase 專案的那個 Google 帳號」，按允許。",
                          "登入完再跑一次剛才的指令。"])
    if any(k in low for k in _NOT_LOGGED_IN):
        return AuthError("gcloud 還沒登入任何 Google 帳號。",
                         ["請老師在終端機跑：gcloud auth login",
                          "瀏覽器跳出來時，選「開這個 Firebase 專案的那個 Google 帳號」，按允許。",
                          "登入完再跑一次剛才的指令。"])
    first = ""
    for line in (stderr or "").splitlines():
        if line.strip():
            first = line.strip()[:200]
            break
    return AuthError("gcloud 沒辦法給出登入權杖。",
                     ["gcloud 的原始訊息：%s" % (first or "（沒有訊息）"),
                      "先跑 gcloud auth list 看目前登入的是哪個帳號；不對就跑 gcloud auth login 重新登入。"])


class TokenProvider:
    """拿權杖的地方。模擬器模式固定回 "owner"；真雲端呼叫 gcloud。

    runner 可以換（單元測試用假的，不真的跑 gcloud）。"""

    def __init__(self, emulator=False, runner=None, gcloud_path=None):
        self.emulator = bool(emulator)
        self._runner = runner or _default_runner
        self._gcloud = gcloud_path
        self._token = None
        self.notes = []          # 例如「gcloud 不在 PATH 上」這類提醒，給呼叫端印

    def _gcloud_exe(self):
        if self._gcloud:
            return self._gcloud
        path, on_path = find_gcloud()
        if not path:
            raise AuthError("這台電腦找不到 gcloud（Google Cloud CLI）。",
                            ["請老師照官方安裝頁自己安裝（Mac／Windows 同一頁）：%s" % INSTALL_URL,
                             "裝完一定要「重開一個新的終端機」，再跑：gcloud auth login",
                             "這個專案不會幫你代裝任何工具。"])
        if not on_path:
            self.notes.append("找到 gcloud（%s），但它不在 PATH 上：這次先直接用它；"
                              "之後請重開一個新的終端機，PATH 就會更新。" % path)
        self._gcloud = path
        return path

    def token(self):
        if self.emulator:
            return EMULATOR_TOKEN
        if self._token:
            return self._token
        exe = self._gcloud_exe()
        try:
            r = self._runner([exe, "auth", "print-access-token"], 120)
        except (OSError, subprocess.SubprocessError, ValueError):
            raise AuthError("跑 gcloud 時出錯（程式沒辦法啟動或逾時）。",
                            ["請老師在終端機自己跑一次：gcloud auth print-access-token（只看有沒有錯誤，"
                             "印出來的那串字不要貼給任何人）",
                             "有錯誤就照錯誤訊息處理；沒登入就跑 gcloud auth login。"])
        if r.returncode != 0:
            raise explain_gcloud_failure(r.stderr)
        lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
        tok = lines[-1] if lines else ""
        if not tok or any(ch.isspace() for ch in tok) or len(tok) < 20:
            raise AuthError("gcloud 回來的不是權杖。",
                            ["跑 gcloud auth list 確認有登入的帳號；沒有就跑 gcloud auth login。"])
        self._token = tok
        return tok

    def refresh(self):
        """伺服器說權杖無效（401）時叫這個：丟掉舊的、重拿一次。"""
        self._token = None
        return self.token()


def active_account(runner=None, gcloud_path=None):
    """gcloud 目前登入的帳號（字串）；拿不到回 ""。只給 doctor.py --cloud 比對帳號用。"""
    runner = runner or _default_runner
    exe = gcloud_path or find_gcloud()[0]
    if not exe:
        return ""
    try:
        r = runner([exe, "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"], 60)
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    if r.returncode != 0:
        return ""
    for line in (r.stdout or "").splitlines():
        if line.strip():
            return line.strip()
    return ""
