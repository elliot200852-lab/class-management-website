#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_rules.py — 安全規則測試一鍵跑（Firestore 模擬器）。開發與 CI 用；老師的電腦不需要跑這支。

這個框架只用 Firestore＋Auth＋Hosting，安全規則（templates/firestore.rules.tmpl）是唯一的伺服器端防線；
作者不開任何真雲端測試專案，所以這裡的模擬器測試就是規則唯一的驗證。

做的事（依序，任何一步失敗就停、exit 1）：
  1. 用一份測試用設定（導師 email 是 @example.com）呼叫 scripts/build_config.py，把規則產生到暫存資料夾
     ——測的就是 build_config.py 真的會產生的那份，不另外手寫規則副本。另外產一份「導師用 gmail 信箱」
     的規則（信箱在執行時才組出來），測導師 email 的 gmail 點號寫法。
  2. 文件存取次數靜態檢查（scripts/lib/rules_budget.py）：每條 allow 最壞情況 ≤ 10、瀏覽器批次 ≤ 20。
     模擬器對查詢量到的上限是 20、正式環境是 10，這一項只能靠靜態檢查。
  3. 找 Java（21 以上）與 Node.js（20 以上）。找不到只印官方下載頁，**不代裝**。
  4. tests/rules/ 裡 `npm ci`（版本釘在 package-lock.json；裝過而且沒變就跳過）。
  5. `firebase emulators:exec --only firestore --project demo-cmw`（firebase-tools 用 tests/rules 裡釘住的版本）
     跑 tests/rules/run.mjs。專案 id 是 demo- 開頭：模擬器保證不連任何真的雲端專案。

用法：
  python3 scripts/test_rules.py              （Windows：py -3 scripts/test_rules.py）
  python3 scripts/test_rules.py --verbose    每個案例都印出來（預設只印每一段的統計與失敗的案例）
  python3 scripts/test_rules.py --budget-only  只跑第 1、2 步（不需要 Java／Node）
  python3 scripts/test_rules.py --reinstall  強制重跑 npm ci
  python3 scripts/test_rules.py --clean      跑完刪掉 tests/rules/node_modules（公開前的隱私掃描會把它當成二進位檔擋下）
"""
import os
import re
import sys
import json
import shutil
import hashlib
import argparse
import tempfile
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import hostos, rules_budget
from lib.emailkey import email_key
from lib.console import setup_utf8

setup_utf8()

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = REPO_ROOT / "tests" / "rules"
PROJECT_ID = "demo-cmw"
MIN_JAVA = 21
MIN_NODE = 20

# 測試用的導師信箱：主要那份用 example.com；gmail 那份拆兩段、執行時才接起來（repo 裡不出現完整的非 example 信箱）。
TEACHER_MAIN = ("class.teacher", "example.com")
TEACHER_GMAIL = ("Class.Teacher", "GoogleMail.com")

LINKS = {
    "java": ("Java（JDK 21 以上）", "https://adoptium.net/",
             "Firestore 模擬器要 Java 才能跑；選 Temurin 21（LTS）以上。"),
    "node": ("Node.js（20 以上）", "https://nodejs.org/en/download",
             "規則測試用官方的 @firebase/rules-unit-testing 與 firebase-tools；選標著 LTS 的版本。"),
}


def test_config(teacher_email):
    """測試用的 class.json（範本值全部換成不像範本的假值，build_config.py 才不會拒跑）。"""
    example = json.loads((REPO_ROOT / "config" / "class.example.json").read_text(encoding="utf-8"))
    example["teacher"]["email"] = teacher_email
    example["firebase"].update({"project_id": PROJECT_ID, "api_key": "demo-api-key",
                                "app_id": "demo-app-id", "auth_domain": ""})
    return example


def render_rules(dest_root, teacher_email):
    """在 dest_root 放一份測試用 config/class.json，跑 build_config.py，回傳產生的 firestore.rules 路徑。"""
    cfg_dir = Path(dest_root) / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "class.json").write_text(json.dumps(test_config(teacher_email), ensure_ascii=False),
                                        encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "build_config.py"), "--root", str(dest_root)],
                       cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        raise SystemExit("✗ build_config.py 產生規則失敗（上面是它的輸出）")
    out = Path(dest_root) / "firestore.rules"
    if not out.exists():
        raise SystemExit("✗ build_config.py 跑完了，但沒有產生 firestore.rules（templates/manifest.json 少了那一筆？）")
    return out


def budget_check(rules_text):
    rows = rules_budget.analyze(rules_text)
    batches = rules_budget.batch_totals(rows)
    for line in rules_budget.report_lines(rows, batches):
        print(line)
    total, seen = rules_budget.coverage(rules_text)
    if total != seen:
        print("✗ 靜態檢查的解析器漏看了規則的一部分（檔內 %d 個文件讀取，只解析到 %d 個）" % (total, seen))
        return False
    bad = rules_budget.problems(rows, batches)
    for b in bad:
        print("✗ 超過上限：%s" % b)
    return not bad


# ── 工具偵測（只找、只提示，不代裝）─────────────────────────────────────

def _run_version(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, ""
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def java_major(path):
    rc, out = _run_version([path, "-version"])
    if rc != 0:
        return None
    m = re.search(r'version "(\d+)(?:\.(\d+))?', out)
    if not m:
        return None
    major = int(m.group(1))
    if major == 1 and m.group(2):
        major = int(m.group(2))
    return major


def node_major(path):
    rc, out = _run_version([path, "--version"])
    if rc != 0:
        return None
    m = re.search(r"v(\d+)\.", out)
    return int(m.group(1)) if m else None


def find_tool(name, version_fn, minimum):
    """回傳 (路徑, 主版本, 是否在 PATH 上) 或 (None, 看到的版本清單, False)。"""
    seen = []
    for path, on_path in hostos.find_exe_all(name):
        major = version_fn(path)
        if major is None:
            seen.append("%s（跑不起來）" % path)
            continue
        if major >= minimum:
            return path, major, on_path
        seen.append("%s（版本 %d，太舊）" % (path, major))
    return None, seen, False


def print_missing(key, seen):
    label, url, note = LINKS[key]
    print("✗ %s — 找不到可用的版本" % label)
    for s in seen:
        print("   看到：%s" % s)
    print("   官方下載頁　Mac: %s" % url)
    print("   官方下載頁　Windows: %s" % url)
    print("   說明：%s" % note)
    print("   這支只檢查、只提示，不會幫你裝；裝完重開一個新的終端機再跑一次。")


# ── npm ci ─────────────────────────────────────────────────────────────

def _lock_digest():
    h = hashlib.sha256()
    for name in ("package.json", "package-lock.json"):
        h.update((RULES_DIR / name).read_bytes())
    return h.hexdigest()


def ensure_node_modules(npm, env, force):
    stamp = RULES_DIR / "node_modules" / ".cmw-lock-sha256"
    digest = _lock_digest()
    if not force and stamp.exists() and stamp.read_text(encoding="utf-8").strip() == digest:
        print("✓ tests/rules 的相依套件已經裝好（package-lock.json 沒變，跳過 npm ci）")
        return True
    print("… tests/rules：npm ci（版本照 package-lock.json；第一次要幾分鐘）")
    r = subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=str(RULES_DIR), env=env)
    if r.returncode != 0:
        print("✗ npm ci 失敗（exit %d）。上面是 npm 的原始輸出。" % r.returncode)
        return False
    stamp.write_text(digest + "\n", encoding="utf-8")
    return True


def _remove_logs():
    for name in ("firestore-debug.log", "firebase-debug.log", "ui-debug.log"):
        p = RULES_DIR / name
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="安全規則測試（Firestore 模擬器）：靜態存取次數檢查＋模擬器規則測試")
    ap.add_argument("--verbose", action="store_true", help="每個案例都印出來")
    ap.add_argument("--budget-only", action="store_true", help="只產生規則並做存取次數靜態檢查（不需要 Java／Node）")
    ap.add_argument("--reinstall", action="store_true", help="強制重跑 npm ci")
    ap.add_argument("--clean", action="store_true", help="跑完刪掉 tests/rules/node_modules")
    a = ap.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="cmw-rules-") as tmp:
        tmp = Path(tmp)
        main_rules = render_rules(tmp / "main", "@".join(TEACHER_MAIN))
        gmail_rules = render_rules(tmp / "gmail", "@".join(TEACHER_GMAIL))
        rules_text = main_rules.read_text(encoding="utf-8")
        print("✓ 規則已由 build_config.py 產生（測試用設定；導師 email 為 example.com）")

        print("")
        if not budget_check(rules_text):
            return 1
        if a.budget_only:
            print("\n✓ 靜態檢查通過（--budget-only：沒有跑模擬器）")
            return 0

        print("")
        java, java_v, java_on_path = find_tool("java", java_major, MIN_JAVA)
        node, node_v, node_on_path = find_tool("node", node_major, MIN_NODE)
        if not java:
            print_missing("java", java_v)
        if not node:
            print_missing("node", node_v)
        if not java or not node:
            return 1
        print("✓ Java %d：%s%s" % (java_v, java, "" if java_on_path else "（不在 PATH 上，這次先直接用它）"))
        print("✓ Node.js %d：%s%s" % (node_v, node, "" if node_on_path else "（不在 PATH 上，這次先直接用它）"))
        npm = shutil.which("npm", path=os.path.dirname(node)) or shutil.which("npm")
        if not npm:
            print_missing("node", ["找得到 node 卻找不到 npm（Node.js 安裝不完整）"])
            return 1

        env = os.environ.copy()
        env["PATH"] = os.pathsep.join([os.path.dirname(java), os.path.dirname(node), env.get("PATH", "")])
        if not ensure_node_modules(npm, env, a.reinstall):
            return 1
        firebase_js = RULES_DIR / "node_modules" / "firebase-tools" / "lib" / "bin" / "firebase.js"
        if not firebase_js.exists():
            print("✗ 找不到 %s（npm ci 沒裝好？加 --reinstall 再試一次）" % firebase_js.relative_to(REPO_ROOT))
            return 1

        manifest = {
            "projectId": PROJECT_ID,
            "repoRoot": str(REPO_ROOT),
            "verbose": bool(a.verbose),
            "variants": {
                "main": {"rulesFile": str(main_rules), "teacher": list(TEACHER_MAIN),
                         "teacherKey": email_key("@".join(TEACHER_MAIN))},
                "gmail": {"rulesFile": str(gmail_rules), "teacher": list(TEACHER_GMAIL),
                          "teacherKey": email_key("@".join(TEACHER_GMAIL))},
            },
        }
        manifest_path = tmp / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        env["CMW_RULES_MANIFEST"] = str(manifest_path)

        # 交給 emulators:exec 的指令用「真的 node 的絕對路徑」：有些 firebase CLI 的單檔版會在子行程 PATH
        # 塞一個假的 node，直接寫 node 會跑到它。
        script = '"%s" run.mjs' % node
        cmd = [node, str(firebase_js), "emulators:exec", "--only", "firestore", "--project", PROJECT_ID, script]
        print("… 啟動 Firestore 模擬器（專案 %s）並跑 tests/rules/run.mjs" % PROJECT_ID)
        sys.stdout.flush()
        r = subprocess.run(cmd, cwd=str(RULES_DIR), env=env)

    if r.returncode == 0:
        _remove_logs()
    else:
        print("\n✗ 規則測試沒有全部通過（exit %d）。模擬器的紀錄在 tests/rules/firestore-debug.log。" % r.returncode)
    if a.clean:
        nm = RULES_DIR / "node_modules"
        if nm.is_dir() and nm.name == "node_modules" and nm.parent == RULES_DIR:
            shutil.rmtree(str(nm), ignore_errors=True)
            print("已刪除 tests/rules/node_modules（--clean）")
    if r.returncode == 0:
        print("\n✓ 規則測試全部通過。")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
