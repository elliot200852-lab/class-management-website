#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy.py — 部署網站：順序寫死（docs/ARCHITECTURE.md §7.3）。部署**不動任何資料**。

  0 check    雲端唯讀檢查的「部署前就要過」各項（doctor.py --cloud 的前半）
  1 build    build_config.py（不准範本值）＋ build_indexes.py --check（索引檔要是最新的）
             （firebase.json 的網站資料夾不是 site/ 時，另外跑 build_site.py 組網站）
  2 rules    firebase deploy --only firestore:rules      預設全拒的規則先上
  3 indexes  firebase deploy --only firestore:indexes    然後每 20 秒查一次，全部 READY 才往下（最多 20 分鐘）
  4 functions（只有 config/class.json 的 notifications.enabled 是 true 才做；沒開就略過，v1 預設沒開）
             v1.1 選配通知信模組：firebase functions:artifacts:setpolicy → firebase deploy --only functions
             （第一次部署時 CLI 會在「Functions 已部署」之後說 could not set up cleanup policy：照樣接著跑 setpolicy
             補設清理政策，不加 --force。docs/ARCHITECTURE.md §10、playbooks/notify.md）
  5 hosting  firebase deploy --only hosting              最後才讓網頁上線
  6 verify   部署後檢查：規則是本機這份、索引都 READY、網站 robots.txt 200 且帶 noindex、設定檔是這個專案

  · 每一步都帶 --only、--project、--non-interactive；**任何一步都不加 --force**
    （--force 會刪掉線上有、本機檔案裡沒有的索引）。
  · 一步失敗就停，印出那一步的指令、原始輸出的最後幾行、白話的可能原因。
  · 不加 --yes 只印「接下來要做什麼」，什麼都不做——代理先把計畫講給老師聽，老師點頭才加 --yes。

用法：
  python3 scripts/deploy.py                   # 只印計畫
  python3 scripts/deploy.py --yes             # 真的部署（0→6）
  python3 scripts/deploy.py --only rules --yes   # 單獨重跑某一步（check／build／rules／indexes／functions／hosting／verify）
"""
import sys
import json
import time
import argparse
import subprocess
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, cloudcheck, gauth, hostos, notify  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib.console import setup_utf8  # noqa: E402
from lib.hostos import PY  # noqa: E402

setup_utf8()

STEPS = ("check", "build", "rules", "indexes", "functions", "hosting", "verify")
TARGETS = {"rules": "firestore:rules", "indexes": "firestore:indexes", "hosting": "hosting"}
NEEDS_FIREBASE = ("rules", "indexes", "functions", "hosting")
POLL_SECONDS = 20
MAX_WAIT_MINUTES = 20
SCRIPTS = Path(__file__).resolve().parent

DESCRIBE = {
    "check": "檢查雲端設定（登入帳號、資料庫、登入網域、登入方式）——只讀不改",
    "build": "產生網站設定與安全規則（build_config.py），確認索引檔是最新的",
    "rules": "部署安全規則（只有名單上的人看得到內容的那套規定）",
    "indexes": "部署資料庫索引，等它們全部建好（通常 2–10 分鐘）",
    "functions": "部署通知信模組（v1.1 選配；沒開就略過）",
    "hosting": "部署網站（網頁本身）",
    "verify": "部署後檢查（規則、索引、網站是不是這個專案的）——只讀不改",
}


def firebase_argv(firebase, step, project_id):
    """firebase deploy 的指令。**絕不含 --force**（單元測試也守這一條）。"""
    argv = [firebase, "deploy", "--only", TARGETS[step], "--project", project_id, "--non-interactive"]
    if "--force" in argv or "-f" in argv:
        raise RuntimeError("deploy 不准帶 --force")
    return argv


HINTS = (
    # 新專案不一定有預設網站：CLI 在非互動模式會說 there is no Hosting site（要放在「not found／404」那條前面）
    (("there is no hosting site", "no hosting site", "could not determine the default site", "hosting:sites:create"),
     "這個 Firebase 專案還沒有網站（新專案不一定有預設網站）：請老師到 Firebase 主控台 → 左邊「Hosting」"
     "（可能在「Hosting & Serverless」底下）→ 按「開始使用」，畫面上的指令一行都不用打，一路按「下一步」到「前往主控台」。"
     "好了再跑 deploy.py --only hosting --yes，然後 deploy.py --only verify --yes。不要跑 firebase hosting:sites:create"
     "（那會另建一個名字不同的網站，網址就不是 <專案 ID>.firebaseapp.com）。"),
    (("not logged in", "failed to authenticate", "firebase login", "authentication error"),
     "Firebase CLI 還沒登入（或登入過期）：請老師跑 firebase login，用開專案、也是導師 email 的那個帳號。"),
    (("403", "permission denied", "does not have permission", "permission_denied"),
     "權限不足：跑 firebase login:list 看登入的帳號是不是開這個專案的那一個；不是就 firebase logout 再 firebase login。"),
    (("has not been used", "is disabled", "api has not been", "enable it by visiting"),
     "需要的 Google API 還沒啟用：照上面輸出裡的網址按「啟用」，等 2–3 分鐘再跑同一個指令。"),
    (("could not find", "not found", "404"),
     "找不到專案或資料庫：確認 config/class.json 的 project_id，並確認已在 Firebase 主控台建立 Firestore 資料庫。"),
    (("blaze", "billing"),
     "訊息提到付費方案：v1 不需要付費方案，請把這段輸出原樣回報。"),
    (("quota", "resource_exhausted", "429"),
     "額度或頻率限制：等幾分鐘再跑同一個指令。"),
)


def hint_for(lines):
    text = "\n".join(lines).lower()
    for keys, hint in HINTS:
        if any(k in text for k in keys):
            return hint
    return "看上面的原始輸出；看不懂就原樣回報。重跑同一個指令是安全的（部署不動資料）。"


def run_streaming(argv, cwd):
    """跑外部指令，邊跑邊印，留最後 40 行給錯誤說明。回 (exit code, 最後幾行)。"""
    tail = deque(maxlen=40)
    try:
        p = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        return 127, ["沒辦法啟動：%s" % type(e).__name__]
    for line in p.stdout:
        line = line.rstrip("\n")
        print("    " + line)
        tail.append(line)
    return p.wait(), list(tail)


def hosting_public():
    try:
        j = json.loads(paths.pkg_path("firebase.json").read_text(encoding="utf-8"))
        return ((j.get("hosting") or {}).get("public") or "site").strip("/")
    except (OSError, ValueError):
        return "site"


class Deployer(object):
    def __init__(self, cfg, client, firebase, runner=run_streaming, sleep=time.sleep, clock=time.time,
                 max_wait=MAX_WAIT_MINUTES * 60):
        self.cfg, self.client, self.firebase = cfg, client, firebase
        self.runner, self.sleep, self.clock, self.max_wait = runner, sleep, clock, max_wait
        self.cwd = paths.root()

    def fail(self, step, argv, lines, why=None):
        print("✗ 第 %d 步（%s）失敗，後面的步驟都沒有做。" % (STEPS.index(step), step))
        if argv:
            print("  指令：%s" % " ".join(str(x) for x in argv))
        if lines:
            print("  最後幾行輸出：")
            for ln in lines[-12:]:
                print("    " + ln)
        print("  → " + (why or hint_for(lines)))
        return False

    def step_check(self):
        items = cloudcheck.run(self.cfg, self.client, phases=("pre",))
        cloudcheck.print_items(items)
        bad = [i for i in items if i.ok is not True]
        if bad:
            return self.fail("check", None, [], "上面打 ✗／！ 的項目要先處理好（照每一項下面的說明做），再重跑部署。")
        return True

    def step_build(self):
        py = sys.executable
        cmds = [[py, str(SCRIPTS / "build_config.py")], [py, str(SCRIPTS / "build_indexes.py"), "--check"]]
        if hosting_public() != "site" and (SCRIPTS / "build_site.py").exists():
            cmds.append([py, str(SCRIPTS / "build_site.py")])
        if paths.root() != paths.pkg_root():
            cmds[0] += ["--root", str(paths.root())]
        for argv in cmds:
            rc, lines = self.runner(argv, paths.pkg_root())
            if rc != 0:
                return self.fail("build", argv, lines, "設定或產生檔有問題：照上面的訊息修 config/class.json，"
                                                       "或跑 %s scripts/build_indexes.py 重新產生索引檔。" % PY)
        return True

    def step_firebase(self, step):
        argv = firebase_argv(self.firebase, step, self.cfg.project_id)
        rc, lines = self.runner(argv, self.cwd)
        if rc != 0:
            return self.fail(step, argv, lines)
        return True

    def wait_indexes(self):
        local = cloudcheck.local_indexes()
        start = self.clock()
        while True:
            try:
                st = cloudcheck.index_status(local, self.client.list_indexes(), self.client.list_field_overrides())
            except (fr.FirestoreError, gauth.AuthError) as e:
                print(e.plain())
                return self.fail("indexes", None, [], "讀不到索引狀態；修好後跑 deploy.py --only indexes --yes 接著等。")
            if st["bad"]:
                return self.fail("indexes", None, st["bad"], "有索引建失敗：到 Firebase 主控台 → Firestore → 索引 看錯誤訊息。")
            if not st["missing"] and not st["building"]:
                print("  ✓ 索引全部建好了（READY）")
                return True
            waited = self.clock() - start
            if waited >= self.max_wait:
                return self.fail("indexes", None, st["missing"] + st["building"],
                                 "等了 %d 分鐘索引還沒建好。索引還在雲端繼續建；過一陣子跑 deploy.py --only indexes --yes 接著等，"
                                 "READY 之後再跑 deploy.py --only hosting --yes。" % (self.max_wait // 60))
            print("  … 索引還在建：還沒好 %d 個（已等 %d 秒，每 %d 秒看一次）"
                  % (len(st["missing"]) + len(st["building"]), int(waited), POLL_SECONDS))
            sys.stdout.flush()
            self.sleep(POLL_SECONDS)

    def step_functions(self):
        """v1.1 選配通知信模組。沒開就略過；開了就 setpolicy → deploy --only functions（都不加 --force）。"""
        raw = getattr(self.cfg, "raw", None) or {}
        if not notify.enabled(raw):
            print("  略過：沒有開通知信模組（config/class.json 的 notifications.enabled 不是 true）。")
            return True
        why = notify.functions_not_ready(self.cfg.project_id)
        if why:
            return self.fail("functions", None, [], why)
        pid, region = self.cfg.project_id, self.cfg.region
        argv = notify.setpolicy_argv(self.firebase, pid, region)
        rc, lines = self.runner(argv, self.cwd)
        if rc != 0:
            return self.fail("functions", argv, lines, notify.deploy_hint(lines))
        argv = notify.deploy_argv(self.firebase, pid)
        rc, lines = self.runner(argv, self.cwd)
        if notify.CLEANUP_POLICY_MISSING in "\n".join(lines).lower():
            # 第一次部署：映像檔倉庫是部署時才建的，所以部署前的 setpolicy 只會說「先部署」。現在倉庫有了，再設一次。
            print("  … Functions 已經部署上去；接著補設映像檔清理政策（第一次部署一定會遇到，不加 --force）")
            argv2 = notify.setpolicy_argv(self.firebase, pid, region)
            rc2, lines2 = self.runner(argv2, self.cwd)
            if rc2 != 0:
                return self.fail("functions", argv2, lines2, "清理政策沒設成功：重跑 deploy.py --only functions --yes（重跑是安全的）。")
            print("  ✓ 清理政策設好了（舊的映像檔留 1 天就自動刪，不會一直累積費用）")
            return True
        if rc != 0:
            return self.fail("functions", argv, lines, notify.deploy_hint(lines))
        return True

    def step_verify(self):
        items = cloudcheck.run(self.cfg, self.client, phases=("post",), include_access=False)
        cloudcheck.print_items(items)
        if any(i.ok is False for i in items):
            return self.fail("verify", None, [], "部署跑完了，但上面打 ✗ 的項目沒過：照說明處理後跑 deploy.py --only verify --yes。")
        return True

    def run(self, steps):
        for step in steps:
            print("\n── 第 %d 步：%s ──" % (STEPS.index(step), DESCRIBE[step]))
            sys.stdout.flush()
            if step == "check":
                ok = self.step_check()
            elif step == "build":
                ok = self.step_build()
            elif step in ("rules", "hosting"):
                ok = self.step_firebase(step)
            elif step == "indexes":
                ok = self.step_firebase("indexes") and self.wait_indexes()
            elif step == "functions":
                ok = self.step_functions()
            else:
                ok = self.step_verify()
            if not ok:
                return 1
        return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="部署網站：規則 → 索引（等 READY）→ 網站；不加 --yes 只印計畫")
    ap.add_argument("--yes", action="store_true", help="真的部署（老師點頭之後才加）")
    ap.add_argument("--only", choices=STEPS, help="只跑這一步")
    paths.add_root_arg(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    if fr.emulator_host_from_env():
        print("✗ 現在的環境變數指向模擬器（FIRESTORE_EMULATOR_HOST 或 CMW_EMULATOR）。部署一定是真雲端：請開一個新的終端機再跑。")
        return 2
    try:
        cfg = classcfg.load()
    except classcfg.ConfigError as e:
        print("✗ %s" % e)
        return 2
    steps = [a.only] if a.only else list(STEPS)
    print("部署計畫（專案 %s，網站 %s）：" % (cfg.project_id, cfg.site_url))
    for s in steps:
        extra = ""
        if s == "functions":
            extra = "：這次會做（通知信模組開著）" if notify.enabled(getattr(cfg, "raw", None)) else "：這次略過（沒開通知信模組）"
        print("  %d. %s%s" % (STEPS.index(s), DESCRIBE[s], extra))
    print("部署不會動到任何資料（紀事、相簿、名單都不變）；每一步都不加 --force。")
    if not a.yes:
        print("\n這只是計畫，什麼都還沒做。老師同意後再跑：%s scripts/deploy.py%s --yes"
              % (PY, (" --only " + a.only) if a.only else ""))
        return 0
    firebase = None
    if any(s in NEEDS_FIREBASE for s in steps):
        found = hostos.find_exe_all("firebase")
        if not found:
            print("✗ 找不到 Firebase CLI。請老師照官方說明自己安裝：%s ，裝完重開終端機，跑 firebase login。"
                  % cloudcheck.FIREBASE_CLI_URL)
            return 2
        firebase, on_path = found[0]
        if not on_path:
            print("提醒：找到 firebase（%s），但它不在 PATH 上；這次先直接用它，之後請重開一個終端機。" % firebase)
    try:
        client = fr.make_client(cfg.project_id)
    except ValueError as e:
        print("✗ %s" % e)
        return 2
    rc = Deployer(cfg, client, firebase).run(steps)
    if rc == 0:
        print("\n✓ 部署完成。%s" % ("網站：%s" % cfg.site_url if "hosting" in steps else ""))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
