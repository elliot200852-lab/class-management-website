#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check.py — 一行本機跑完全部驗證：unittest ＋ privacy_scan（有 Node.js 時加跑 tests/js/ 前端測試）。Mac／Windows 都能用（純 Python）。

CI（.github/workflows/ci.yml）跟你在自己電腦上跑的是同一支，不會有「本機過、CI 卻紅」的落差。

用法：
  python3 scripts/check.py           （Windows：py -3 scripts/check.py）
  python3 scripts/check.py --rules   另外跑安全規則的模擬器測試（scripts/test_rules.py；要 Java 21＋與 Node.js 20＋，
                                     老師的電腦不需要，所以預設不跑）
  python3 scripts/check.py --integration
                                     另外跑管理腳本的模擬器整合測試（scripts/test_admin.py：名單同步、發文、開部落格
                                     寫進 Firestore 模擬器，再用真規則讀回；接著備份→清空→還原逐欄比對、資料退場
                                     （tests/emulator_backup.py）；同樣要 Java＋Node.js，預設不跑）
  python3 scripts/check.py --functions
                                     另外跑 v1.1 選配通知信模組的模擬器測試（scripts/test_functions.py：Firestore＋Functions
                                     模擬器、假的郵差，絕不真的寄信；同樣要 Java＋Node.js，預設不跑）
"""
import sys
import shutil
import argparse
import subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.console import setup_utf8

setup_utf8()

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd, label):
    print("\n=== %s ===" % label)
    r = subprocess.run(cmd, cwd=str(REPO_ROOT))
    return r.returncode


def _run_web_tests():
    """前端純函式測試（tests/js/，Node 內建 test runner，零 npm 套件）。沒有 Node 就略過並提示。"""
    node = shutil.which("node")
    files = sorted(str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "tests" / "js").glob("*.test.js"))
    if not node:
        print("\n=== 前端測試（node --test tests/js/） ===\n略過：找不到 Node.js（18 以上）。裝了之後再跑一次就會加跑前端測試。")
        return 0
    if not files:
        return 0
    return _run([node, "--test"] + files, "前端測試（node --test tests/js/）")


def main(argv=None):
    ap = argparse.ArgumentParser(description="一行跑完全部驗證：unittest ＋ privacy_scan（加 --rules 另跑規則模擬器測試）")
    ap.add_argument("--rules", action="store_true", help="另外跑 scripts/test_rules.py（要 Java 與 Node.js）")
    ap.add_argument("--integration", action="store_true",
                    help="另外跑 scripts/test_admin.py：管理腳本的模擬器整合測試（要 Java 與 Node.js）")
    ap.add_argument("--functions", action="store_true",
                    help="另外跑 scripts/test_functions.py：通知信模組的模擬器測試（要 Java 與 Node.js）")
    a = ap.parse_args(argv)
    rc_tests = _run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], "unittest")
    rc_privacy = _run([sys.executable, "scripts/privacy_scan.py", "."], "privacy_scan")
    rc_web = _run_web_tests()
    rc_tests = rc_tests or rc_web
    rc_rules = _run([sys.executable, "scripts/test_rules.py"], "rules（模擬器）") if a.rules else 0
    rc_integ = _run([sys.executable, "scripts/test_admin.py"], "管理腳本整合測試（模擬器）") if a.integration else 0
    rc_fn = _run([sys.executable, "scripts/test_functions.py"], "通知信模組測試（模擬器）") if a.functions else 0
    rc_integ = rc_integ or rc_fn
    if rc_tests != 0 or rc_privacy != 0 or rc_rules != 0 or rc_integ != 0:
        print("\n✗ check 沒有全部通過（unittest exit=%d，privacy_scan exit=%d%s%s）"
              % (rc_tests, rc_privacy, "，rules exit=%d" % rc_rules if a.rules else "",
                 "，integration／functions exit=%d" % rc_integ if (a.integration or a.functions) else ""))
        return 1
    print("\n✓ check 全部通過（unittest ＋ privacy_scan%s%s%s）。" % (" ＋ 規則模擬器測試" if a.rules else "",
                                                                 " ＋ 管理腳本整合測試" if a.integration else "",
                                                                 " ＋ 通知信模組測試" if a.functions else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
