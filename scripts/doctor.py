#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doctor.py — 健檢：這台電腦準備好了嗎？

只檢查、只提示官方下載頁，**絕不代裝任何東西**（這個專案的鐵則：依賴工具一律由使用者
自己到官方網站安裝，見 AGENTS.md）。

用法：
  python3 scripts/doctor.py           這台電腦裝好了沒（Windows：py -3 scripts/doctor.py）
  python3 scripts/doctor.py --cloud   另外檢查雲端（唯讀；只有真雲端才會壞的項目，docs/ARCHITECTURE.md §7.4）：
                                      gcloud／firebase 登入帳號＝導師 email、資料庫地區／模式／版本（Standard）、
                                      登入網域＝網址、登入方式、索引 READY、規則是本機這份、方案、網站上線、名單包含關係

必要項：Python、Node.js、Firebase CLI、Google Cloud CLI。選用（！不算失敗）：git（用 ZIP 下載的不需要）、Pillow、
雲端硬碟桌面版、AI 代理的終端機指令（用代理桌面版的人本來就找不到）。

exit code：0＝必要項都 ✓（選用的 ！不算）；1＝有必要項 ✗（照印出來的官方連結請老師自己裝，裝完重開終端機再跑）。
--cloud：0＝「部署前」的必要項都過；1＝有要處理的 ✗。
"""
import sys
import shutil
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import hostos
from lib.console import setup_utf8

setup_utf8()

MIN_PY_MINOR = 9

# 官方下載頁：mac／windows 分開寫（同一頁的話兩欄填一樣的網址）。
# 這份表是依 2026 年初的認知整理，正式公開前建議人工點過一次，確認網址還在、沒有跳轉。
LINKS = {
    "python": {
        "mac": "https://www.python.org/downloads/macos/",
        "win": "https://www.python.org/downloads/windows/",
        "note": ("Mac：下載黃色按鈕的 .pkg 一路安裝，裝完雙擊跳出來的「Install Certificates.command」。"
                 "Windows：按「Download Python install manager」安裝；裝好後在命令提示字元打 py -3 --version，"
                 "第一次問要不要下載 Python 本體、要不要加到 PATH，都答 Y（AGENTS.md 步驟 1-1）。"),
    },
    "git": {
        "mac": "https://git-scm.com/install/mac",
        "win": "https://git-scm.com/install/windows",
        "note": "選用：用 git 下載的，之後可以用 git pull 更新。用 ZIP 下載的不需要（更新改成重新下載 ZIP）。",
    },
    "node": {
        "mac": "https://nodejs.org/en/download",
        "win": "https://nodejs.org/en/download",
        "note": "Firebase CLI 要靠它才能跑；選標著「LTS」的版本就對了。",
    },
    "gcloud": {
        "mac": "https://cloud.google.com/sdk/docs/install",
        "win": "https://cloud.google.com/sdk/docs/install",
        "note": "發文、同步名單的腳本用它登入你的 Google 帳號（裝完跑一次 gcloud auth login）。",
    },
    "pillow": {
        "mac": "https://pillow.readthedocs.io/en/stable/installation/basic-installation.html",
        "win": "https://pillow.readthedocs.io/en/stable/installation/basic-installation.html",
        "note": "處理照片用（發有照片的紀事、上傳相簿才需要）；照官方說明貼一行 pip 指令就好。",
    },
    "firebase": {
        "mac": "https://firebase.google.com/docs/cli",
        "win": "https://firebase.google.com/docs/cli",
        "note": "部署網站與安全規則要用的指令工具；先裝好 Node.js 再照這頁指示裝。",
    },
    "drive": {
        "mac": "https://www.google.com/drive/download/",
        "win": "https://www.google.com/drive/download/",
        "note": "Google 雲端硬碟桌面版：班級資料備份靠這個同步夾；沒裝也能先架站，之後再補裝。",
    },
    "claude": {
        "mac": "https://docs.claude.com/en/docs/claude-code/setup",
        "win": "https://docs.claude.com/en/docs/claude-code/setup",
        "note": "Claude Code（需要 Claude 訂閱）。",
    },
    "codex": {
        "mac": "https://github.com/openai/codex",
        "win": "https://github.com/openai/codex",
        "note": "OpenAI Codex CLI（需要 ChatGPT 訂閱）。",
    },
    "agy": {
        "mac": "https://github.com/google-antigravity/antigravity-cli",
        "win": "https://github.com/google-antigravity/antigravity-cli",
        "note": "Antigravity CLI（Google；一般 Google 帳號用這個）。",
    },
    "gemini": {
        "mac": "https://github.com/google-gemini/gemini-cli",
        "win": "https://github.com/google-gemini/gemini-cli",
        "note": "Gemini CLI（Google；目前給企業授權或付費 API 金鑰的使用者）。",
    },
}

# 代理的「桌面版」（視窗程式，不是終端機指令）找不到執行檔很正常：不算失敗，只提示。
DESKTOP_AGENT_NOTE = ("這一項不算失敗：你如果用的是代理的桌面版（在視窗程式裡選這個資料夾、貼那一句話），"
                      "這台電腦本來就找不到它的終端機指令，照常往下做就好。沒有任何代理的話，照上面任一個官方連結裝一個。")


def _tool_version(cmd):
    """跑 `<cmd> --version`，拿第一行當版本字串；跑不動就回空字串，絕不讓例外往外丟。"""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=15, text=True,
                           encoding="utf-8", errors="replace")
        text = (r.stdout or r.stderr or "").strip()
        return text.splitlines()[0].strip() if text else ""
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


def check_python():
    ok = sys.version_info >= (3, MIN_PY_MINOR)
    return {"key": "python", "label": "Python 版本", "ok": ok, "required": True,
            "detail": "目前是 %s（最低需求 3.%d）" % (sys.version.split()[0], MIN_PY_MINOR)}


def check_exe(key, label, cmd, required, version_args=("--version",)):
    try:
        path = shutil.which(cmd)
    except OSError:
        path = None
    ok = bool(path)
    if ok:
        v = _tool_version([cmd, *version_args])
        detail = "%s（%s）" % (path, v) if v else path
    else:
        detail = "找不到 %s" % cmd
    return {"key": key, "label": label, "ok": ok, "required": required, "detail": detail}


def check_gcloud():
    try:
        found = hostos.find_exe_all("gcloud")
    except OSError:
        found = []
    if not found:
        return {"key": "gcloud", "label": "Google Cloud CLI（gcloud）", "ok": False, "required": True,
                "detail": "找不到 gcloud"}
    path, on_path = found[0]
    detail = path if on_path else "%s（不在 PATH 上：重開一個新的終端機就會好）" % path
    return {"key": "gcloud", "label": "Google Cloud CLI（gcloud）", "ok": True, "required": True, "detail": detail}


def check_pillow():
    try:
        import PIL
        ok, detail = True, "Pillow %s" % getattr(PIL, "__version__", "")
    except ImportError:
        ok, detail = False, "沒裝（處理照片時才需要）"
    return {"key": "pillow", "label": "Pillow（處理照片）", "ok": ok, "required": False, "detail": detail}


def check_drive():
    try:
        cands = hostos.drive_desktop_candidates()
    except OSError:
        cands = []
    ok = bool(cands)
    detail = cands[0] if cands else "沒找到常見安裝路徑（不代表一定沒裝，只是自動找不到）"
    return {"key": "drive", "label": "Google 雲端硬碟桌面版", "ok": ok, "required": False, "detail": detail}


def check_agents():
    """找得到任一支代理的終端機指令就 ✓；找不到只提示（！），因為桌面版代理不會留下指令。"""
    try:
        found = hostos.agent_clis_found()
    except OSError:
        found = {}
    have = {k: v for k, v in found.items() if v}
    ok = bool(have)
    detail = ("、".join("%s（%s）" % (hostos.AGENT_CLIS[k]["label"], v) for k, v in have.items()) if have
              else "找不到代理的終端機指令（claude、codex、agy、gemini）")
    return {"key": "agents", "label": "AI 代理（終端機版；桌面版不用）", "ok": ok, "required": False, "detail": detail}


def run_checks():
    """跑完全部健檢項目，回傳清單。每一項的形狀固定：key/label/ok/required/detail。
    絕不因為工具缺少或跑不動而丟出例外——缺什麼、壞什麼都用 ok=False 記錄下來，交給呼叫端處理。"""
    return [
        check_python(),
        check_exe("git", "git（選用：用 ZIP 下載的不需要）", "git", False),
        check_exe("node", "Node.js", "node", True),
        check_exe("firebase", "Firebase CLI", "firebase", True),
        check_gcloud(),
        check_pillow(),
        check_drive(),
        check_agents(),
    ]


def exit_code(items):
    """必要項有 ✗ → 1；只有選用項 ！（或全部 ✓）→ 0。"""
    return 1 if any(it["required"] and not it["ok"] for it in items) else 0


def print_report(items):
    print("=" * 60)
    print("健檢：class-management-website（%s）" % hostos.OS_LABEL)
    print("=" * 60)
    for it in items:
        mark = "✓" if it["ok"] else ("✗" if it["required"] else "！")
        print("%s %s — %s" % (mark, it["label"], it["detail"]))
        if it["ok"]:
            continue
        link = LINKS.get(it["key"])
        if link:
            print("   官方下載頁　Mac: %s" % link["mac"])
            print("   官方下載頁　Windows: %s" % link["win"])
            print("   說明：%s" % link["note"])
        if it["key"] == "pillow":
            print("   一行指令（請老師自己貼）：%s -m pip install --user Pillow" % hostos.PY)
        if it["key"] == "agents":
            for name in hostos.AGENT_ORDER:
                l = LINKS.get(name)
                if l:
                    print("   - %s　Mac: %s　Windows: %s"
                          % (hostos.AGENT_CLIS[name]["label"], l["mac"], l["win"]))
            print("   " + DESKTOP_AGENT_NOTE)
    print("=" * 60)
    print("✓＝好了；✗＝必要、要裝；！＝選用或可以先跳過（不算失敗）。")
    print("這支只檢查、只提示，不會幫你裝任何東西——請照上面的官方連結自己安裝，裝完重開一個新的終端機再跑一次。")


def cloud(argv_root=None):
    """雲端唯讀檢查。必要項（部署前、部署後）有 ✗ 就回 1。"""
    from lib import classcfg, cloudcheck, paths
    from lib import firestore_rest as fr
    if argv_root:
        paths.set_root(argv_root)
    try:
        cfg = classcfg.load()
        client = fr.make_client(cfg.project_id)
    except (classcfg.ConfigError, ValueError) as e:
        print("✗ %s" % e)
        return 1
    print("=" * 60)
    print("雲端檢查（唯讀）：專案 %s" % cfg.project_id)
    print("=" * 60)
    try:
        items = cloudcheck.run(cfg, client)
    except Exception as e:  # gcloud 沒裝／沒登入等：白話說明
        print(getattr(e, "plain", lambda: "✗ %s" % e)())
        return 1
    cloudcheck.print_items(items)
    from lib import notify
    if notify.enabled(cfg.raw):
        print("・通知信模組（v1.1 選配）開著：它的健檢另外跑 %s scripts/notify_setup.py --cloud（也是唯讀）。" % hostos.PY)
    print("=" * 60)
    print("全部是讀取，沒有改任何東西。✗＝要處理；！＝無法判斷（不算失敗）；部署前「部署後要過」的項目沒過是正常的。")
    return 1 if any(i.ok is False and i.phase == "pre" for i in items) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="健檢：這台電腦準備好了嗎（只檢查、只提示，不代裝）")
    ap.add_argument("--cloud", action="store_true", help="另外檢查雲端設定（唯讀）")
    ap.add_argument("--root", metavar="目錄", help="資料根目錄（測試用）")
    a = ap.parse_args(argv)
    if a.cloud:
        return cloud(a.root)
    items = run_checks()
    print_report(items)
    return exit_code(items)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
