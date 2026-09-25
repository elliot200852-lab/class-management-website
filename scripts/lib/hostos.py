#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hostos.py — 平台差異只寫在這一個檔（精簡版）。

這支只服務 class-management-website 用得到的東西：判斷 mac／windows／linux、
找可執行檔、列出 Google 雲端硬碟桌面版可能的同步夾、列出找得到哪幾支 AI 代理 CLI。

**這支不負責代裝任何工具**（那是這個專案的鐵則：依賴工具只給官方連結，
使用者自己去官方頁面裝——見 scripts/doctor.py）。

零第三方相依，只用標準庫。
"""
import os
import glob
import shutil
import sys


def _detect():
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("win") or sys.platform == "cygwin":
        return "win"
    return "linux"


OS = _detect()
OS_LABEL = {"mac": "macOS", "win": "Windows", "linux": "Linux"}.get(OS, OS)


def python_cmd():
    """文件裡寫 `python3 scripts/x.py`；這支回這台電腦上真的該用的叫法。"""
    return "py -3" if OS == "win" else "python3"


PY = python_cmd()


def home():
    return os.path.expanduser("~")


def exe(name):
    """外部工具的絕對路徑，找不到回 None。只查 PATH（P1 夠用；找不到就是真的沒裝）。"""
    return shutil.which(name)


# ── 找工具：先查 PATH，找不到再查常見安裝位置（docs/ARCHITECTURE.md §6）──────
# Windows 裝完工具後，已經開著的終端機 PATH 不會更新；Mac 的 Homebrew openjdk 是 keg-only、
# 本來就不在 PATH；Mac 的 /usr/bin/java 是個殼，沒裝 JDK 時一跑就失敗。所以「PATH 上有」不代表能用，
# 呼叫端要自己跑一次版本指令確認（例如 scripts/test_rules.py 的 Java 檢查）。

def _glob_dirs(patterns):
    out = []
    for pat in patterns:
        for p in sorted(glob.glob(os.path.expandvars(os.path.expanduser(pat))), reverse=True):
            if _isdir_safe(p) and p not in out:
                out.append(p)
    return out


def common_dirs(name):
    """這個工具在這個平台上常見的安裝資料夾（找不到的不列）。"""
    if name == "java":
        dirs = []
        java_home = os.environ.get("JAVA_HOME")
        if java_home:
            dirs.append(os.path.join(java_home, "bin"))
        if OS == "mac":
            dirs += _glob_dirs(["/opt/homebrew/opt/openjdk*/bin", "/usr/local/opt/openjdk*/bin",
                                "/Library/Java/JavaVirtualMachines/*/Contents/Home/bin",
                                "~/Library/Java/JavaVirtualMachines/*/Contents/Home/bin"])
        elif OS == "win":
            dirs += _glob_dirs([r"%ProgramFiles%\Eclipse Adoptium\*\bin", r"%ProgramFiles%\Java\*\bin",
                                r"%ProgramFiles%\Microsoft\jdk-*\bin", r"%ProgramFiles%\Zulu\*\bin",
                                r"%LOCALAPPDATA%\Programs\Eclipse Adoptium\*\bin"])
        else:
            dirs += _glob_dirs(["/usr/lib/jvm/*/bin", "/usr/local/lib/jvm/*/bin"])
        return [d for d in dirs if _isdir_safe(d)]
    if name in ("node", "npm"):
        if OS == "mac":
            return _glob_dirs(["/opt/homebrew/bin", "/usr/local/bin"])
        if OS == "win":
            return _glob_dirs([r"%ProgramFiles%\nodejs", r"%LOCALAPPDATA%\Programs\nodejs"])
        return _glob_dirs(["/usr/local/bin", "/usr/bin"])
    # gcloud：官方安裝程式放的位置（Windows 是 gcloud.cmd；shutil.which 會照 PATHEXT 找到它）
    if name == "gcloud":
        if OS == "mac":
            return _glob_dirs(["/opt/homebrew/bin", "/usr/local/bin", "~/google-cloud-sdk/bin",
                               "/opt/homebrew/share/google-cloud-sdk/bin",
                               "/opt/homebrew/Caskroom/google-cloud-sdk/*/google-cloud-sdk/bin",
                               "/usr/local/Caskroom/google-cloud-sdk/*/google-cloud-sdk/bin"])
        if OS == "win":
            return _glob_dirs([r"%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk\bin",
                               r"%ProgramFiles(x86)%\Google\Cloud SDK\google-cloud-sdk\bin",
                               r"%ProgramFiles%\Google\Cloud SDK\google-cloud-sdk\bin"])
        return _glob_dirs(["~/google-cloud-sdk/bin", "/usr/lib/google-cloud-sdk/bin", "/snap/bin", "/usr/bin"])
    # firebase：npm 全域安裝（Windows 是 %APPDATA%\npm\firebase.cmd）或官方單檔版
    if name == "firebase":
        if OS == "mac":
            return _glob_dirs(["/opt/homebrew/bin", "/usr/local/bin", "~/.local/bin", "~/.npm-global/bin"])
        if OS == "win":
            return _glob_dirs([r"%APPDATA%\npm", r"%ProgramFiles%\nodejs"])
        return _glob_dirs(["/usr/local/bin", "~/.local/bin", "~/.npm-global/bin", "/usr/bin"])
    return []


def find_exe_all(name):
    """這個工具所有找得到的位置：[(絕對路徑, 是否在 PATH 上)]，PATH 上的排第一。"""
    found = []
    try:
        p = shutil.which(name)
    except OSError:
        p = None
    if p:
        found.append((os.path.abspath(p), True))
    for d in common_dirs(name):
        try:
            cand = shutil.which(name, path=d)
        except OSError:
            cand = None
        if cand:
            cand = os.path.abspath(cand)
            if all(cand != f[0] for f in found):
                found.append((cand, False))
    return found


# ── Google 雲端硬碟桌面版的同步夾 ──────────────────────────────────────────
DRIVE_ROOT_NAMES = ("My Drive", "我的雲端硬碟", "我的云端硬盘")


def _isdir_safe(path):
    try:
        return os.path.isdir(path)
    except OSError:
        return False


def drive_desktop_candidates():
    """這台電腦上找得到的「Google 雲端硬碟」根資料夾，找不到就回空清單。"""
    found = []

    def add(p):
        if p and p not in found and _isdir_safe(p):
            found.append(p)

    if OS == "mac":
        for base in sorted(glob.glob(os.path.join(home(), "Library", "CloudStorage", "GoogleDrive-*"))):
            for n in DRIVE_ROOT_NAMES:
                add(os.path.join(base, n))
    elif OS == "win":
        # 桌面版常把自己掛成一個獨立磁碟機代號（例如 G:）；找不到掛載點資訊就退而求其次，
        # 掃常見磁碟機代號 ＋ 使用者資料夾底下常見的名字。
        for letter in "GHIJKLMNOPQRSTUVWXYZ":
            for n in DRIVE_ROOT_NAMES:
                add("%s:\\%s" % (letter, n))
        for n in DRIVE_ROOT_NAMES:
            add(os.path.join(home(), n))
            add(os.path.join(home(), "Google Drive", n))
    else:
        for n in ("GoogleDrive", "google-drive", "Google Drive", "My Drive"):
            add(os.path.join(home(), n))
    return found


def onedrive_root():
    """Windows：OneDrive 同步根目錄（環境變數找得到就回，找不到回空字串）。"""
    if OS != "win":
        return ""
    return os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer") or ""


# ── AI 代理的 CLI ────────────────────────────────────────────────────────
AGENT_CLIS = {
    "claude": {"label": "Claude Code", "cmd": "claude"},
    "codex": {"label": "OpenAI Codex CLI", "cmd": "codex"},
    "agy": {"label": "Antigravity CLI", "cmd": "agy"},
    "gemini": {"label": "Gemini CLI", "cmd": "gemini"},
}
AGENT_ORDER = ["claude", "codex", "agy", "gemini"]


def agent_clis_found():
    """這台電腦上找得到哪些代理的 CLI。回 {名字: 絕對路徑或 ""}。"""
    return {n: (exe(AGENT_CLIS[n]["cmd"]) or "") for n in AGENT_ORDER}


def summary():
    return {"os": OS, "os_label": OS_LABEL, "python_cmd": PY}


if __name__ == "__main__":
    import json
    print(json.dumps(dict(summary(), drive=drive_desktop_candidates(), agents=agent_clis_found()),
                      ensure_ascii=False, indent=2))
