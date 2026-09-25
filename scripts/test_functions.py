#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_functions.py — v1.1 選配通知信模組（functions/）的模擬器測試。開發與 CI 用；老師的電腦不需要跑這支。

**只連本機模擬器、專案一律 demo- 開頭、郵差一律是假的：不碰任何真的 Firebase／GCP 專案，也絕不真的寄信。**

做的事（依序，任何一步失敗就停、exit 1）：
  1. 找 Java（21 以上）與 Node.js（20 以上）。找不到只印官方下載頁，**不代裝**。
  2. tests/rules 的 npm ci（firebase-tools 用那裡釘住的版本）、functions/ 的 npm ci（版本照 functions/package-lock.json；
     裝過而且沒變就跳過）。
  3. 第一輪：`emulators:exec --only firestore` 跑 tests/functions/core.test.js（直接呼叫 functions/lib/core.js，
     時間可以往後撥：30 分鐘延遲與取消、回填閘、dryrun、逐人台帳、重試、兩輪同時掃、即時信、每日摘要、清舊資料），
     接著跑管理腳本：notify_config.py（階段切換的規矩、寫進去的設定 Functions 讀得懂）、publish_site.py、publish_courses.py。
  4. 第二輪：`emulators:exec --only firestore,functions` 跑 tests/functions/triggers.test.js（寫文件 → 觸發器真的被叫到）。

用法：
  python3 scripts/test_functions.py            （Windows：py -3 scripts/test_functions.py）
  python3 scripts/test_functions.py --reinstall  強制重跑兩處的 npm ci
  python3 scripts/test_functions.py --clean      跑完刪掉 functions/node_modules（公開前的隱私掃描會把它當成二進位檔擋下）
  python3 scripts/test_functions.py --keep       保留暫存資料夾（除錯用）
"""
import os
import sys
import json
import shutil
import socket
import hashlib
import argparse
import tempfile
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_rules as tr  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

REPO = Path(__file__).resolve().parent.parent
FUNCTIONS = REPO / "functions"
TESTS = REPO / "tests" / "functions"
PROJECT = "demo-cmw-fn"
AT = "@"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def ensure_functions_modules(npm, env, force):
    stamp = FUNCTIONS / "node_modules" / ".cmw-lock-sha256"
    h = hashlib.sha256()
    for name in ("package.json", "package-lock.json"):
        h.update((FUNCTIONS / name).read_bytes())
    digest = h.hexdigest()
    if not force and stamp.exists() and stamp.read_text(encoding="utf-8").strip() == digest:
        print("✓ functions/ 的相依套件已經裝好（package-lock.json 沒變，跳過 npm ci）")
        return True
    print("… functions/：npm ci（版本照 package-lock.json）")
    r = subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=str(FUNCTIONS), env=env)
    if r.returncode != 0:
        print("✗ functions/ 的 npm ci 失敗（exit %d）" % r.returncode)
        return False
    stamp.write_text(digest + "\n", encoding="utf-8")
    return True


def run_exec(argv, cwd, env, limit=1200):
    """跑一輪 emulators:exec；卡住超過 limit 秒就算失敗（CI 不會無限等）。"""
    try:
        return subprocess.run(argv, cwd=str(cwd), env=env, timeout=limit).returncode
    except subprocess.TimeoutExpired:
        print("✗ 超過 %d 秒沒跑完，當成失敗" % limit)
        return 1


def firebase_json(dest, with_functions):
    ports = {k: free_port() for k in ("firestore", "hub", "logging", "ws", "functions")}
    emu = {"firestore": {"host": "127.0.0.1", "port": ports["firestore"], "websocketPort": ports["ws"]},
           "hub": {"host": "127.0.0.1", "port": ports["hub"]},
           "logging": {"host": "127.0.0.1", "port": ports["logging"]},
           "ui": {"enabled": False}}
    doc = {"firestore": {}, "emulators": emu}
    if with_functions:
        emu["functions"] = {"host": "127.0.0.1", "port": ports["functions"]}
        # firebase-tools 用 path.join(專案資料夾, source)：一定要相對路徑
        # （暫存資料夾在 Mac 上是 /var → /private/var 的捷徑：兩邊都先取真實路徑再算相對路徑）
        dest.mkdir(parents=True, exist_ok=True)
        rel = os.path.relpath(os.path.realpath(str(FUNCTIONS)), os.path.realpath(str(dest)))
        doc["functions"] = [{"source": rel.replace("\\", "/"), "codebase": "default",
                             "ignore": ["node_modules", ".git", "*.local", ".env*", ".test-run"]}]
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "firebase.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return ports


def class_root(tmp):
    """管理腳本測試用的虛構班級設定（專案 demo-cmw-fn、導師信箱 example.com）。"""
    root = tmp / "root"
    (root / "config").mkdir(parents=True)
    (root / "data").mkdir()
    cfg = json.loads((REPO / "config" / "class.example.json").read_text(encoding="utf-8"))
    cfg["class_name"] = "測試班"
    cfg["teacher"].update({"email": "class.teacher" + AT + "example.com", "display_name": "王老師"})
    cfg["firebase"].update({"project_id": PROJECT, "api_key": "demo-api-key", "app_id": "demo-app-id"})
    cfg["notifications"].update({"enabled": True, "signature": "測試班 王老師"})
    (root / "config" / "class.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return root


def functions_cfg(tmp):
    p = tmp / "fncfg.json"
    p.write_text(json.dumps({"format": 1, "projectId": PROJECT, "region": "asia-east1",
                             "siteUrl": "https://%s.firebaseapp.com" % PROJECT, "timeZone": "Asia/Taipei", "digestHour": 7,
                             "backupRemindDays": 7, "backupUrgentDays": 14}), encoding="utf-8")
    return p


# ════════════════════════════════════════════════════════════════════════
# 內層：在 emulators:exec 裡跑
# ════════════════════════════════════════════════════════════════════════

class Report(object):
    def __init__(self):
        self.fails = 0
        self.n = 0

    def check(self, label, cond, detail=""):
        self.n += 1
        if cond:
            print("  ✓ " + label)
        else:
            self.fails += 1
            print("  ✗ " + label + ((" — " + detail) if detail else ""))


def admin_scripts(root, node):
    """notify_config.py、publish_site.py、publish_courses.py 對模擬器。回失敗數。"""
    from lib import firestore_rest as fr
    host = os.environ["FIRESTORE_EMULATOR_HOST"]
    c = fr.Client(PROJECT, emulator_host=host)
    R = Report()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")

    def sh(script, *args):
        r = subprocess.run([sys.executable, str(REPO / "scripts" / script)] + list(args) + ["--root", str(root), "--emulator"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    # 上一段 node 測試留下的資料清掉，從一個空的資料庫開始
    import urllib.request
    req = urllib.request.Request("http://%s/emulator/v1/projects/%s/databases/(default)/documents" % (host, PROJECT),
                                 method="DELETE")
    urllib.request.urlopen(req, timeout=30).read()
    print("── notify_config.py")
    rc, out = sh("notify_config.py")
    R.check("看現況 exit 0、還沒建", rc == 0 and "還沒建" in out, out[-300:])
    rc, out = sh("notify_config.py", "--phase", "live", "--apply")
    R.check("沒經過 dryrun 直接 live → 擋下（exit 2）", rc == 2 and c.get("config/notify") is None, out[-300:])
    rc, out = sh("notify_config.py", "--phase", "dryrun")
    R.check("不加 --apply 只預覽、不寫", rc == 0 and c.get("config/notify") is None and "預覽" in out, out[-300:])
    rc, out = sh("notify_config.py", "--phase", "dryrun", "--apply")
    d = c.get("config/notify")
    R.check("--phase dryrun --apply：寫入並讀回一致", rc == 0 and d is not None and d.data.get("phase") == "dryrun", out[-300:])
    R.check("從 off 打開：寫下通知起始線（伺服器時間）", d is not None and isinstance(d.data.get("notifyFloor"), fr.Timestamp))
    R.check("寄件人、署名、信箱從 class.json 來", d is not None and d.data.get("signature") == "測試班 王老師"
            and d.data.get("teacherEmail") == "class.teacher" + AT + "example.com"
            and d.data.get("senderName") == "王老師（測試班）")
    R.check("螢幕輸出遮住信箱", ("class.teacher" + AT) not in out, out[-300:])
    # Functions 讀同一份設定：讀得懂階段與起始線
    probe = ("const {getApps,initializeApp}=require('firebase-admin/app');const {getFirestore}=require('firebase-admin/firestore');"
             "if(!getApps().length)initializeApp({projectId:%r});const core=require('./lib/core');"
             "core.loadSettings(getFirestore()).then(s=>{console.log(JSON.stringify(s));process.exit(0)})"
             ".catch(e=>{console.error(e);process.exit(1)});" % PROJECT)
    r = subprocess.run([node, "-e", probe], cwd=str(FUNCTIONS), capture_output=True, text=True, encoding="utf-8", env=env)
    try:
        s = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        s = {}
    R.check("functions/lib/core.js 讀 notify_config.py 寫的設定：dryrun、有起始線、沒有問題",
            s.get("phase") == "dryrun" and isinstance(s.get("floorMs"), (int, float)) and s.get("problems") == [],
            (r.stdout + r.stderr)[-300:])
    rc, out = sh("notify_config.py", "--phase", "live", "--apply")
    R.check("排程沒有心跳 → 不准切 live", rc == 2 and c.get("config/notify").data.get("phase") == "dryrun", out[-300:])
    c.commit([c.set_write("ops/notify_status", {"lastRunAt": fr.SERVER_TIME, "phase": "dryrun"})])
    rc, out = sh("notify_config.py", "--phase", "live", "--apply")
    d2 = c.get("config/notify")
    R.check("排程 10 分鐘內跑過 → 可以切 live，起始線不重設", rc == 0 and d2.data.get("phase") == "live"
            and d2.data.get("notifyFloor") == d.data.get("notifyFloor"), out[-300:])
    rc, out = sh("notify_config.py", "--parent-mail", "off", "--apply")
    R.check("--parent-mail off", rc == 0 and c.get("config/notify").data.get("parentMail") is False, out[-300:])
    rc, out = sh("notify_config.py", "--phase", "off", "--apply")
    R.check("--phase off（煞車）", rc == 0 and c.get("config/notify").data.get("phase") == "off", out[-300:])
    cfgp = root / "config" / "class.json"
    raw = json.loads(cfgp.read_text(encoding="utf-8"))
    raw["notifications"]["enabled"] = False
    cfgp.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    rc, out = sh("notify_config.py", "--phase", "dryrun", "--apply")
    R.check("class.json 沒開模組 → 不准打開", rc == 2 and c.get("config/notify").data.get("phase") == "off", out[-300:])

    print("── publish_site.py")
    url = "https://drive.google.com/file/d/EXAMPLE/view"
    rc, out = sh("publish_site.py", "--class-docs", url, "--apply")
    d = c.get("roster/links")
    R.check("--class-docs --apply：寫入 roster/links、另一欄補空字串", rc == 0 and d is not None
            and d.data.get("classDocsIndexUrl") == url and d.data.get("recordsKitUrl") == "", out[-300:])
    rc, out = sh("publish_site.py", "--records-kit", "http://example.com", "--apply")
    R.check("不是 https 的網址被擋（exit 2）", rc == 2 and c.get("roster/links").data.get("recordsKitUrl") == "", out[-300:])

    print("── publish_courses.py")
    (root / "data" / "courses").mkdir(parents=True, exist_ok=True)
    (root / "data" / "courses" / "courses-term.md").write_text(
        "---\ntitle: 本學期課程\n---\n這學期的課程單元是範例單元。\n\n## 各科課程大綱\n### 英文（王老師）\n讀繪本、唱歌。\n"
        "網址：https://drive.google.com/file/d/EXAMPLE/view\n", encoding="utf-8")
    (root / "data" / "courses" / "schedule.md").write_text(
        "---\ntitle: 課表\n---\n| 節次 | 一 |\n|---|---|\n| 第一節 | 國語 |\n", encoding="utf-8")
    rc, out = sh("publish_courses.py", "courses-term", "--publish")
    d = c.get("pages/courses-term")
    R.check("課程頁上線、讀回比對一致", rc == 0 and d is not None and d.data.get("kind") == "course"
            and d.data["data"]["cards"][0]["title"] == "英文（王老師）", out[-400:])
    rc, out = sh("publish_courses.py", "schedule", "--publish")
    d = c.get("pages/schedule")
    R.check("課表上線", rc == 0 and d is not None and d.data["data"]["rows"][1]["cells"] == ["第一節", "國語"], out[-400:])
    rc, out = sh("publish_courses.py", "courses-term", "--publish")
    R.check("已上線的沒加 --update 不覆蓋（exit 2）", rc == 2, out[-300:])
    print("  管理腳本：%d 項、失敗 %d" % (R.n, R.fails))
    return R.fails


def inner(a):
    node = a.node
    env = dict(os.environ, CMW_TEST_PROJECT=PROJECT)
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        print("✗ 沒有 FIRESTORE_EMULATOR_HOST：這一段只能在 emulators:exec 裡跑")
        return 1
    if a.inner == "core":
        r = subprocess.run([node, "--test", "--test-concurrency=1", str(TESTS / "core.test.js")], cwd=str(REPO), env=env)
        fails = admin_scripts(Path(a.root), node)
        return 1 if (r.returncode != 0 or fails) else 0
    r = subprocess.run([node, "--test", "--test-concurrency=1", str(TESTS / "triggers.test.js")], cwd=str(REPO), env=env)
    return r.returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description="通知信模組（functions/）的模擬器測試：不碰真的雲端、絕不寄信")
    ap.add_argument("--reinstall", action="store_true", help="強制重跑 npm ci")
    ap.add_argument("--clean", action="store_true", help="跑完刪掉 functions/node_modules")
    ap.add_argument("--keep", action="store_true", help="保留暫存資料夾")
    ap.add_argument("--only", choices=("core", "triggers"), help="只跑其中一輪（除錯用）")
    ap.add_argument("--inner", choices=("core", "triggers"), help=argparse.SUPPRESS)
    ap.add_argument("--root", help=argparse.SUPPRESS)
    ap.add_argument("--node", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.inner:
        return inner(a)

    java, java_v, _ = tr.find_tool("java", tr.java_major, tr.MIN_JAVA)
    node, node_v, _ = tr.find_tool("node", tr.node_major, tr.MIN_NODE)
    if not java:
        tr.print_missing("java", java_v)
    if not node:
        tr.print_missing("node", node_v)
    if not java or not node:
        return 1
    print("✓ Java %d、Node.js %d" % (java_v, node_v))
    npm = shutil.which("npm", path=os.path.dirname(node)) or shutil.which("npm")
    if not npm:
        tr.print_missing("node", ["找得到 node 卻找不到 npm（Node.js 安裝不完整）"])
        return 1
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([os.path.dirname(java), os.path.dirname(node), env.get("PATH", "")])
    for k in ("FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST", "CMW_EMULATOR", "GOOGLE_APPLICATION_CREDENTIALS"):
        env.pop(k, None)
    # Google 的函式庫預設會去問「是不是跑在 Google 的機器上」（metadata 伺服器）；測試一律不問
    env["METADATA_SERVER_DETECTION"] = "none"
    if not tr.ensure_node_modules(npm, env, a.reinstall) or not ensure_functions_modules(npm, env, a.reinstall):
        return 1
    firebase_js = tr.RULES_DIR / "node_modules" / "firebase-tools" / "lib" / "bin" / "firebase.js"
    tmp = Path(tempfile.mkdtemp(prefix="cmw-functions-"))
    # Functions 模擬器「讀程式、找出有哪些觸發器」那一步不會把這個行程的環境變數傳下去，只讀 functions/.env.local
    # （模擬器專用；正式部署不讀這個檔，而且 firebase.json 的 ignore 也擋掉 .env*）。測完一定刪掉。
    env_local = FUNCTIONS / ".env.local"
    if env_local.exists():
        print("✗ functions/.env.local 已經存在（不是這支測試建的）：先移走再跑，這支不覆蓋別人的檔。")
        return 1
    rc = 1
    try:
        cfg_path = functions_cfg(tmp)
        env["CMW_FUNCTIONS_CONFIG"] = str(cfg_path)
        root = class_root(tmp)
        me = str(Path(__file__).resolve())
        r1 = r2 = 0
        if a.only in (None, "core"):
            print("\n=== 第一輪：核心流程＋管理腳本（Firestore 模擬器，專案 %s） ===" % PROJECT)
            sys.stdout.flush()
            fb = tmp / "fb-core"
            firebase_json(fb, False)
            inner_cmd = '"%s" "%s" --inner core --root "%s" --node "%s"' % (sys.executable, me, root, node)
            r1 = run_exec([node, str(firebase_js), "emulators:exec", "--only", "firestore", "--project", PROJECT,
                           inner_cmd], fb, env)
        if a.only in (None, "triggers"):
            print("\n=== 第二輪：觸發器接線（Firestore＋Functions 模擬器） ===")
            sys.stdout.flush()
            fb2 = tmp / "fb-triggers"
            firebase_json(fb2, True)
            env_local.write_text("CMW_FUNCTIONS_CONFIG=%s\n" % str(cfg_path).replace("\\", "/"), encoding="utf-8")
            inner_cmd = '"%s" "%s" --inner triggers --node "%s"' % (sys.executable, me, node)
            r2 = run_exec([node, str(firebase_js), "emulators:exec", "--only", "firestore,functions", "--project",
                           PROJECT, inner_cmd], fb2, env)
        rc = 0 if (r1 == 0 and r2 == 0) else 1
        r1 = type("R", (), {"returncode": r1})
        r2 = type("R", (), {"returncode": r2})
        if rc:
            print("\n✗ 通知信模組測試沒有全部通過（第一輪 exit %d、第二輪 exit %d）。%s"
                  % (r1.returncode, r2.returncode, "暫存資料夾：%s" % tmp if a.keep else "加 --keep 保留暫存資料夾與模擬器紀錄。"))
        else:
            print("\n✓ 通知信模組測試全部通過（模擬器；沒有碰任何雲端、沒有寄任何信）。")
    finally:
        if env_local.exists():
            env_local.unlink()
        if a.keep:
            print("（保留暫存資料夾：%s）" % tmp)
        else:
            shutil.rmtree(str(tmp), ignore_errors=True)
        if a.clean:
            nm = FUNCTIONS / "node_modules"
            if nm.is_dir() and nm.name == "node_modules" and nm.parent == FUNCTIONS:
                shutil.rmtree(str(nm), ignore_errors=True)
                print("已刪除 functions/node_modules（--clean）")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
