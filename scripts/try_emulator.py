#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""try_emulator.py — 先試玩：在這台電腦上開一個虛構班級的網站（Firebase 模擬器），不用任何 Google 帳號、不碰任何雲端。

給還沒決定要不要裝、想先看看網站長什麼樣的老師（劇本 playbooks/try.md）。做的事：
  1. 找 Java（21 以上；Homebrew 的 openjdk 這類不在 PATH 上的常見位置也找）與 Node.js（20 以上）。
     找不到只印官方下載頁，**不代裝**。Java 只有試玩需要，正式網站用不到。
  2. 模擬器工具（firebase-tools）用 tests/rules/ 裡版本釘死的那一份（package-lock.json）。第一次要下載，
     全部放在這個資料夾的 tests/rules/node_modules/ 裡，**不裝到電腦的其他地方**：不用 npm install -g；
     npm 的下載快取放暫存資料夾、裝完就刪；Firestore 模擬器本體（一個 Java 檔）也下載到同一個地方
     （個人資料夾的快取裡本來就有同一版的話直接用那一份）。要下載時先停下來說明，老師同意後加 --download。
  3. 在這個資料夾建 try/（試玩資料夾，已被 .gitignore 擋住）：虛構的班級設定（專案 id 是 demo- 開頭：
     Firebase 保證 demo- 專案只連本機模擬器）→ build_config.py --root try --emulator 產生網站設定與安全規則；
     虛構的名冊與聯絡人（學生 A～Y、@example.com 信箱）。
  4. 起 Firestore＋Auth 模擬器（127.0.0.1:8080、9099；網站寫死連這兩個埠）與本機網站（預設 127.0.0.1:8765），
     種進虛構的一班：內容跟示範站同一份（site/js/core/demo-data.js，照片是程式畫的色塊圖），名單用真的
     access_sync.py、open_blogs.py 寫進去——之後在試玩環境跑其他腳本（加 --root try --emulator）看到的是一致的狀態。
  5. 印出網址、可以直接點的假帳號、其他腳本在試玩環境的用法，打開瀏覽器。按 Ctrl-C 收掉一切（模擬器、網站、try/）。

用法（Windows 把 python3 換成 py -3）：
  python3 scripts/try_emulator.py --check      只檢查（唯讀）：Java、Node.js、模擬器工具下載了沒、埠有沒有被占用
  python3 scripts/try_emulator.py              開試玩環境（缺模擬器工具時先停下來說明要下載什麼）
  python3 scripts/try_emulator.py --download   老師同意下載之後（只下載到這個資料夾裡）
  python3 scripts/try_emulator.py --status     試玩環境開著嗎（網址、試玩資料夾）
  python3 scripts/try_emulator.py --no-open    開好之後不要自動打開瀏覽器
  python3 scripts/try_emulator.py --port 9000  本機網站換一個埠（預設 8765）

試玩環境開著的時候，其他腳本加 `--root try --emulator` 就寫進這個模擬器、不碰雲端，例如：
  python3 scripts/access_sync.py --root try --emulator
  python3 scripts/publish_post.py <slug> --root try --emulator --publish

exit code：0＝正常收掉（--check／--status：都好）；2＝停下來了（缺工具、要先同意下載、埠被占用；什麼都沒開）；
1＝啟動或種資料失敗（try/ 會清掉；看印出來的最後幾行）。
"""
import os
import sys
import json
import math
import time
import base64
import shutil
import signal
import socket
import hashlib
import argparse
import datetime
import tempfile
import functools
import threading
import subprocess
import webbrowser
import http.server
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, hostos  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib.hostos import PY  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

REPO = paths.pkg_root()
RULES_DIR = REPO / "tests" / "rules"
TRY_NAME = "try"
MARKER = "這是試玩資料夾.txt"
STATE_FILE = "try.json"
PROJECT_ID = "demo-cmw-try"
FS_PORT, AUTH_PORT, SITE_PORT = 8080, 9099, 8765     # 前兩個是網站（store-firestore.js）寫死的模擬器埠
MIN_JAVA, MIN_NODE = 21, 20
EXIT_STOPPED = 2
START_LIMIT = 900        # 等模擬器起來最多幾秒（第一次要下載 Firestore 模擬器本體）

AT = "@"
TEACHER_EMAIL = "teacher" + AT + "example.com"        # site/js/core/demo-data.js 的示範導師
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXY"                 # 學生 A～Y（座號 01–25），跟示範站同一班

# 預先建在 Auth 模擬器裡的假 Google 帳號：登入視窗（模擬器的假登入頁）直接點一個就進去
ACCOUNTS = (
    ("try-teacher", TEACHER_EMAIL, "示範導師", "導師：全部都看得到（導師專用、留言後台、我的孩子全班格）"),
    ("try-parent-a", "parent-a" + AT + "example.com", "學生 A 家長（母）", "座號 01 的家長，也是私密讀者"),
    ("try-parent-b", "parent-b" + AT + "example.com", "學生 B 家長（父）", "座號 02 的家長"),
    ("try-staff", "staff-1" + AT + "example.com", "示範同仁", "同仁：讀得到座號 03 的部落格"),
    ("try-outsider", "outsider" + AT + "example.com", "名單外的人", "不在名單上：登入後看不到任何內容，只有換帳號的說明"),
)

LINKS = {
    "java": ("Java（JDK 21 以上）", "https://adoptium.net/",
             "選 Temurin 21（LTS）以上：Mac 下載 .pkg、Windows 下載 .msi，一路下一步。只有試玩要用，正式網站用不到。"),
    "node": ("Node.js（20 以上）", "https://nodejs.org/en/download",
             "選標著 LTS 的版本（安裝步驟 1-3 本來就要裝這個）。"),
}


class Stop(Exception):
    """停下來了（缺工具、要先同意、埠被占用）：什麼都沒開，exit 2。lines 是要印的白話說明。"""

    def __init__(self, lines):
        super().__init__(lines[0] if lines else "")
        self.lines = list(lines)


class Fail(Stop):
    """啟動或種資料失敗：exit 1。"""


class Interrupted(Exception):
    """Ctrl-C 以外的收掉訊號（例如代理停掉背景工作）。"""


# ════════════════════════════════════════════════════════════════════════
# 找工具（只找、只提示，不代裝）
# ════════════════════════════════════════════════════════════════════════

def _mac_has_jdk():
    """Mac 的 /usr/bin/java 是個殼：沒裝 JDK 時一跑就跳出「要安裝 Java」的視窗。先用 java_home 安靜地問一次。"""
    try:
        r = subprocess.run(["/usr/libexec/java_home"], capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def find_java():
    """回 (路徑, 主版本) 或 (None, [看到了什麼])。"""
    import test_rules as tr
    seen = []
    for path, _ in hostos.find_exe_all("java"):
        if hostos.OS == "mac" and os.path.realpath(path) == "/usr/bin/java" and not _mac_has_jdk():
            seen.append("%s（Mac 內建的空殼，還沒裝 JDK）" % path)
            continue
        major = tr.java_major(path)
        if major is None:
            seen.append("%s（跑不起來）" % path)
        elif major >= MIN_JAVA:
            return path, major
        else:
            seen.append("%s（版本 %d，太舊）" % (path, major))
    return None, seen


def find_node():
    import test_rules as tr
    seen = []
    for path, _ in hostos.find_exe_all("node"):
        major = tr.node_major(path)
        if major is None:
            seen.append("%s（跑不起來）" % path)
        elif major >= MIN_NODE:
            return path, major
        else:
            seen.append("%s（版本 %d，太舊）" % (path, major))
    return None, seen


def missing_lines(key, seen):
    label, url, note = LINKS[key]
    out = ["✗ %s：找不到可以用的版本" % label]
    out += ["   看到：%s" % s for s in seen]
    out += ["   官方下載頁　Mac: %s" % url, "   官方下載頁　Windows: %s" % url, "   說明：%s" % note,
            "   這支只檢查、只提示，不會幫你裝；老師自己裝好後，關掉所有終端機再開，回到這個資料夾再跑一次。"]
    return out


def firebase_js():
    return RULES_DIR / "node_modules" / "firebase-tools" / "lib" / "bin" / "firebase.js"


def tools_ready():
    """tests/rules/node_modules 是不是照 package-lock.json 裝好的（跟 scripts/test_rules.py 同一個記號）。"""
    import test_rules as tr
    stamp = RULES_DIR / "node_modules" / ".cmw-lock-sha256"
    try:
        same = stamp.read_text(encoding="utf-8").strip() == tr._lock_digest()
    except OSError:
        return False
    return same and firebase_js().is_file()


def emulator_cache(home=None):
    """Firestore 模擬器本體放哪裡。個人資料夾的快取（~/.cache/firebase/emulators）已經有同一版 → 回 None（直接用，
    不重複下載、也不多寫東西）；沒有 → 回 tests/rules/node_modules/.cmw-emulators（跟著這個資料夾走）。"""
    info = RULES_DIR / "node_modules" / "firebase-tools" / "lib" / "emulator" / "downloadableEmulatorInfo.json"
    try:
        rel = json.loads(info.read_text(encoding="utf-8"))["firestore"]["downloadPathRelativeToCacheDir"]
    except (OSError, ValueError, KeyError, TypeError):
        rel = None
    home = Path(home) if home else Path(os.path.expanduser("~"))
    if rel and (home / ".cache" / "firebase" / "emulators" / rel).is_file():
        return None
    return RULES_DIR / "node_modules" / ".cmw-emulators"


def child_env(java=None, node=None):
    """給子行程的環境：Java、Node 放最前面；清掉會把腳本導到別處的變數；不讓 firebase-tools 檢查更新。"""
    env = os.environ.copy()
    for k in ("FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST", "CMW_EMULATOR", "CMW_ROOT"):
        env.pop(k, None)
    front = [os.path.dirname(x) for x in (java, node) if x]
    if front:
        env["PATH"] = os.pathsep.join(front + [env.get("PATH", "")])
    env["NO_UPDATE_NOTIFIER"] = "1"
    return env


def download_tools(npm, env):
    """npm ci 到 tests/rules/node_modules（版本照 package-lock.json）。npm 的下載快取放暫存資料夾，裝完就刪。"""
    import test_rules as tr
    cache = tempfile.mkdtemp(prefix="cmw-npm-cache-")
    try:
        e = dict(env, npm_config_cache=cache, npm_config_update_notifier="false")
        if not tr.ensure_node_modules(npm, e, False):
            raise Fail(["✗ 模擬器工具沒有下載成功（上面是 npm 的原始輸出）。",
                        "  → 多半是網路斷了或被擋：確認連得上網，再跑一次同一個指令（會從頭重新下載）。"])
    finally:
        shutil.rmtree(cache, ignore_errors=True)


def port_busy(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ════════════════════════════════════════════════════════════════════════
# 試玩資料夾：設定、網站、名單檔
# ════════════════════════════════════════════════════════════════════════

def try_root():
    return REPO / TRY_NAME


def make_root(root):
    """建試玩資料夾。已經有、而且是這支建的（有記號檔）→ 上次沒收乾淨，整個清掉重建；不是這支建的 → 不動它。"""
    root = Path(root)
    if root.exists():
        if not (root / MARKER).is_file():
            raise Stop(["✗ 這個資料夾裡已經有一個 %s/，但不是試玩程式建的，不動它。" % root.name,
                        "  → 請老師看一下裡面是什麼；確定不要了再移到垃圾桶，然後再跑一次。"])
        shutil.rmtree(str(root))
    root.mkdir(parents=True)
    (root / MARKER).write_text("這個資料夾是 scripts/try_emulator.py 的試玩環境（虛構的一班）。"
                               "按 Ctrl-C 收掉試玩時會整個刪掉，不要把真的資料放進來。\n", encoding="utf-8")
    return root


def remove_root(root):
    root = Path(root)
    if root.is_dir() and (root / MARKER).is_file():
        shutil.rmtree(str(root), ignore_errors=True)


def try_config():
    """虛構的班級設定：從 config/class.example.json 出發，換成試玩用的值（新版範本多的欄位照樣帶著走）。"""
    cfg = json.loads((REPO / "config" / "class.example.json").read_text(encoding="utf-8"))
    cfg["class_name"] = "試玩班級"
    cfg["school_name"] = ""
    cfg["teacher"] = dict(cfg.get("teacher") or {}, email=TEACHER_EMAIL, display_name="示範導師")
    cfg["students"] = dict(cfg.get("students") or {}, count=len(LETTERS))
    cfg["region"] = cfg.get("region") or "asia-east1"
    cfg["firebase"] = dict(cfg.get("firebase") or {}, project_id=PROJECT_ID, api_key="demo-api-key",
                           app_id="demo-app-id", auth_domain="", messaging_sender_id="")
    cfg["calendar_ics_url"] = ""
    cfg["drive"] = dict(cfg.get("drive") or {}, sync_root="")
    cfg["notifications"] = dict(cfg.get("notifications") or {}, enabled=False)
    return cfg


def run_py(script, *args, env=None):
    return subprocess.run([sys.executable, str(REPO / "scripts" / script)] + [str(x) for x in args],
                          cwd=str(REPO), env=env or child_env(), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def tail(r, n=12):
    text = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    return ["    " + x for x in text[-n:]]


def firebase_json(ws, hub, logging_port):
    return {
        "firestore": {"rules": "firestore.rules"},
        "emulators": {
            "auth": {"host": "127.0.0.1", "port": AUTH_PORT},
            "firestore": {"host": "127.0.0.1", "port": FS_PORT, "websocketPort": ws},
            "hub": {"host": "127.0.0.1", "port": hub},
            "logging": {"host": "127.0.0.1", "port": logging_port},
            "ui": {"enabled": False},
            "singleProjectMode": True,
        },
    }


def prepare(root):
    """設定檔 → build_config.py --emulator（網站設定＋安全規則）→ 網站資料夾 www/ ＋ 模擬器設定。回 (設定, www)。"""
    root = Path(root)
    cfg = try_config()
    (root / "config").mkdir(parents=True, exist_ok=True)
    with open(root / "config" / "class.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    r = run_py("build_config.py", "--root", root, "--emulator")
    if r.returncode != 0:
        raise Fail(["✗ build_config.py --emulator 沒有成功（下面是它最後幾行）："] + tail(r))
    gen = root / "site" / "js" / "site-config.js"
    text = gen.read_text(encoding="utf-8") if gen.is_file() else ""
    if "emulator: true" not in text or ('"%s"' % PROJECT_ID) not in text:
        raise Fail(["✗ 產生的網站設定不對（沒有連模擬器，或專案 id 不是 %s）；為了安全先停下來。" % PROJECT_ID])
    www = root / "www"
    shutil.copytree(str(REPO / "site"), str(www), ignore=shutil.ignore_patterns("site-config.js", ".DS_Store"))
    shutil.copyfile(str(gen), str(www / "js" / "site-config.js"))
    with open(root / "firebase.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(firebase_json(free_port(), free_port(), free_port()), indent=2) + "\n")
    return cfg, www


def relation(i):
    return "母" if i % 2 == 0 else "父"        # 跟 demo-data.js 的家長稱謂一樣


def class_files(root):
    """data/（init_data.py）＋虛構的名冊、聯絡人、家長稱謂：跟示範站同一班，名單同步才會跟資料庫一致。"""
    root = Path(root)
    r = run_py("init_data.py", "--root", root)
    if r.returncode != 0:
        raise Fail(["✗ init_data.py 沒有成功："] + tail(r))
    data = root / "data"
    roster = ["座號,姓名,稱呼,備註"] + ["%02d,學生 %s,學生 %s," % (i + 1, c, c) for i, c in enumerate(LETTERS)]
    contacts = ["座號,關係,姓名,Email,私密讀者,暫停,備註"]
    contacts += ["%02d,%s,學生 %s 家長,parent-%s%sexample.com,%s,," % (i + 1, relation(i), c, c.lower(), AT, "是" if i == 0 else "")
                 for i, c in enumerate(LETTERS)]
    contacts.append("03,同仁,示範同仁,staff-1%sexample.com,,," % AT)
    roles = ["# 試玩用的虛構班級（scripts/try_emulator.py 寫的）"] + ['"%02d": [%s]' % (i + 1, relation(i))
                                                          for i in range(len(LETTERS))]
    for name, lines in (("roster.csv", roster), ("contacts.csv", contacts), ("parent-roles.yaml", roles)):
        with open(data / name, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    return data


# ════════════════════════════════════════════════════════════════════════
# 示範內容（跟示範站同一份：site/js/core/demo-data.js）與色塊照片
# ════════════════════════════════════════════════════════════════════════

DEMO_JS = r"""'use strict';
// try_emulator.py 用：在 Node 的 vm 裡載入 site/js 的示範資料，印成 JSON（時間寫成 {"__ts": ISO 字串}）。
const fs = require('fs'), path = require('path'), vm = require('vm');
const args = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const ctx = { console: console, SITE_CONFIG: { categories: args.categories } };
vm.createContext(ctx);
for (const f of ['core/ns.js', 'core/util.js', 'core/emailkey.js', 'core/demo-data.js']) {
  vm.runInContext(fs.readFileSync(path.join(args.siteJs, f), 'utf8'), ctx, { filename: f });
}
ctx.__today = args.today;
process.stdout.write(vm.runInContext(
  '(function () { var r = CMW.demoData.build(__today); return JSON.stringify({ docs: r.docs, info: r.info },' +
  ' function (k, v) { var o = this[k]; return Object.prototype.toString.call(o) === "[object Date]" ? { __ts: o.toISOString() } : v; }); })()',
  ctx));
"""


def demo_docs(node, today, categories, workdir):
    """回 ([(路徑, 資料)], info)。時間是 {"__ts": …}（to_fs() 轉成 Firestore 時間）。"""
    workdir = Path(workdir)
    js = workdir / "demo-docs.js"
    argf = workdir / "demo-args.json"
    js.write_text(DEMO_JS, encoding="utf-8")
    argf.write_text(json.dumps({"siteJs": str(REPO / "site" / "js"), "today": today, "categories": list(categories)},
                               ensure_ascii=False), encoding="utf-8")
    try:
        r = subprocess.run([node, str(js), str(argf)], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise Fail(["✗ 用 Node.js 產生示範內容失敗（%s）。" % type(e).__name__])
    if r.returncode != 0:
        raise Fail(["✗ 用 Node.js 產生示範內容失敗："] + tail(r))
    got = json.loads(r.stdout)
    return [(p, d) for p, d in got["docs"]], got.get("info") or {}


def to_fs(v):
    if isinstance(v, dict):
        if set(v) == {"__ts"}:
            return fr.Timestamp(v["__ts"])
        return {k: to_fs(x) for k, x in v.items()}
    if isinstance(v, list):
        return [to_fs(x) for x in v]
    return v


# ── 最小的 JPEG 編碼器：每 8×8 一格一個顏色（只有 DC 係數），畫得出天空、太陽、山丘的色塊圖 ──
# 只用標準庫、不需要 Pillow；repo 裡不放任何圖檔。網站把照片一律當 image/jpeg 顯示。
_DC_BITS = (0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0)       # JPEG 標準亮度 DC 霍夫曼表
_DC_VALS = tuple(range(12))
_PALETTES = (
    ((150, 196, 226), (244, 196, 88), (118, 160, 98), (92, 124, 78)),
    ((236, 180, 150), (250, 226, 150), (150, 120, 160), (104, 86, 120)),
    ((176, 214, 206), (255, 240, 200), (96, 150, 140), (70, 110, 104)),
    ((214, 222, 240), (240, 150, 110), (170, 150, 110), (130, 110, 80)),
    ((120, 150, 200), (250, 250, 230), (60, 90, 120), (40, 60, 80)),
    ((242, 220, 170), (230, 120, 90), (200, 160, 90), (150, 110, 60)),
)
N_VARIANTS = len(_PALETTES)


def _huff(bits, vals):
    codes, code, k = {}, 0, 0
    for length in range(1, 17):
        for _ in range(bits[length - 1]):
            codes[vals[k]] = (code, length)
            code += 1
            k += 1
        code <<= 1
    return codes


class _BitWriter(object):
    def __init__(self):
        self.out = bytearray()
        self.acc = 0
        self.n = 0

    def put(self, value, length):
        self.acc = (self.acc << length) | (value & ((1 << length) - 1))
        self.n += length
        while self.n >= 8:
            self.n -= 8
            b = (self.acc >> self.n) & 0xFF
            self.out.append(b)
            if b == 0xFF:
                self.out.append(0)            # 位元組填充
        self.acc &= (1 << self.n) - 1

    def flush(self):
        if self.n:
            self.put((1 << (8 - self.n)) - 1, 8 - self.n)
        return bytes(self.out)


def _seg(marker, payload):
    return bytes((0xFF, marker)) + (len(payload) + 2).to_bytes(2, "big") + payload


def jpeg_blocks(w, h, color_at):
    """color_at(bx, by) → (r, g, b)：第 bx 欄、第 by 列那個 8×8 格子的顏色。回 JPEG 位元組（4:4:4、基線）。"""
    bw, bh = (w + 7) // 8, (h + 7) // 8
    dc = _huff(_DC_BITS, _DC_VALS)
    bits = _BitWriter()
    prev = [0, 0, 0]
    ycc_of = {}
    for by in range(bh):
        for bx in range(bw):
            rgb = color_at(bx, by)
            ycc = ycc_of.get(rgb)
            if ycc is None:
                r, g, b = rgb
                y = 0.299 * r + 0.587 * g + 0.114 * b
                cb = -0.168736 * r - 0.331264 * g + 0.5 * b + 128
                cr = 0.5 * r - 0.418688 * g - 0.081312 * b + 128
                ycc = ycc_of[rgb] = tuple(int(round(8 * (v - 128))) for v in (y, cb, cr))
            for c in range(3):
                diff = ycc[c] - prev[c]
                prev[c] = ycc[c]
                s = abs(diff).bit_length()
                code, length = dc[s]
                bits.put(code, length)
                if s:
                    bits.put(diff if diff > 0 else diff + (1 << s) - 1, s)
                bits.put(0, 1)                # AC 全是 0：只有一個「區塊結束」碼（AC 表只有這一個符號，碼是 0）
    data = bits.flush()
    out = b"\xff\xd8"
    out += _seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    out += _seg(0xDB, b"\x00" + b"\x01" * 64)
    out += _seg(0xC0, b"\x08" + h.to_bytes(2, "big") + w.to_bytes(2, "big") + b"\x03"
                + b"\x01\x11\x00" + b"\x02\x11\x00" + b"\x03\x11\x00")
    out += _seg(0xC4, b"\x00" + bytes(_DC_BITS) + bytes(_DC_VALS))
    out += _seg(0xC4, b"\x10" + bytes((1,) + (0,) * 15) + b"\x00")
    out += _seg(0xDA, b"\x03" + b"\x01\x00" + b"\x02\x00" + b"\x03\x00" + b"\x00\x3f\x00")
    return out + data + b"\xff\xd9"


def jpeg_scene(w, h, variant=0):
    """一張色塊風景（天空漸層、太陽、起伏的山丘、地面）。variant 換配色與太陽位置。"""
    sky, sun, hill, ground = _PALETTES[variant % N_VARIANTS]
    bw, bh = (w + 7) // 8, (h + 7) // 8
    sx = bw * (0.2 + 0.12 * (variant % 6))
    sy = bh * 0.28
    sr2 = max(2.0, min(bw, bh) * 0.12) ** 2
    waves = 1 + variant % 3

    def at(bx, by):
        if (bx - sx) ** 2 + (by - sy) ** 2 <= sr2:
            return sun
        if by >= bh * 0.84:
            return ground
        ridge = bh * (0.62 + 0.08 * math.sin(bx * waves * 2 * math.pi / max(1, bw)))
        if by >= ridge:
            return hill
        t = 0.35 * by / max(1.0, ridge)
        return tuple(int(c + (255 - c) * t) for c in sky)
    return jpeg_blocks(w, h, at)


def fill_photos(docs):
    """示範資料的照片文件只有寬高：每一份補上一張色塊 JPEG（base64）。同一張照片的縮圖與顯示圖用同一個配色。"""
    cache = {}
    n = 0
    for path, data in docs:
        parts = path.split("/")
        if len(parts) < 2 or parts[-2] not in ("images", "thumbs") or "data" in data:
            continue
        w, h = data.get("w"), data.get("h")
        if not isinstance(w, int) or not isinstance(h, int):
            continue
        variant = int(hashlib.md5(("/".join(parts[:-2]) + "/" + parts[-1]).encode("utf-8")).hexdigest(), 16) % N_VARIANTS
        key = (w, h, variant)
        if key not in cache:
            cache[key] = base64.b64encode(jpeg_scene(w, h, variant)).decode("ascii")
        data["data"] = cache[key]
        n += 1
    # 列表卡片的封面縮圖（coverThumb）：示範資料留 null（示範站當場畫），正式網站是封面那張縮圖的副本（schema：
    # coverPid 與 coverThumb 要同時有或同時沒有）——照正式的形狀補上，列表才看得到封面
    thumbs = {p: d for p, d in docs if "/thumbs/" in p and "data" in d}
    for path, data in docs:
        pid = data.get("coverPid") if isinstance(data, dict) else None
        if pid and data.get("coverThumb") is None:
            th = thumbs.get("%s/thumbs/%s" % (path, pid))
            if th is not None:
                data["coverThumb"] = {"data": th["data"], "w": th["w"], "h": th["h"]}
    return n


# ════════════════════════════════════════════════════════════════════════
# 模擬器、種資料、網站
# ════════════════════════════════════════════════════════════════════════

FS_URL = "http://127.0.0.1:%d/" % FS_PORT
AUTH_URL = "http://127.0.0.1:%d/" % AUTH_PORT


def http_ok(url, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except (urllib.error.URLError, OSError, ValueError):
        return False


def start_emulators(node, java, root):
    """起 Auth＋Firestore 模擬器（自己一個行程群組：Ctrl-C 由這支統一轉交，才收得乾淨）。回 (行程, 紀錄檔)。"""
    env = child_env(java, node)
    cache = emulator_cache()
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
        env["FIREBASE_EMULATORS_PATH"] = str(cache)
    cmd = [node, str(firebase_js()), "emulators:start", "--only", "auth,firestore", "--project", PROJECT_ID,
           "--config", str(Path(root) / "firebase.json")]
    log = open(str(Path(root) / "emulator.log"), "w", encoding="utf-8", errors="replace")
    kw = {}
    if hostos.OS == "win":
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, cwd=str(root), env=env, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, **kw)
    return proc, log


def wait_ready(proc, limit=START_LIMIT):
    started = time.time()
    last = started
    while time.time() - started < limit:
        if proc.poll() is not None:
            return False
        if http_ok(FS_URL) and http_ok(AUTH_URL):
            return True
        if time.time() - last >= 20:
            print("  … 模擬器還在啟動（第一次要下載 Firestore 模擬器本體，約 140 MB，可能要幾分鐘）")
            sys.stdout.flush()
            last = time.time()
        time.sleep(1)
    return False


def stop_emulators(proc):
    """請模擬器自己收（posix 送一次 SIGINT＝Ctrl-C）；收不掉再強制，連它開的 Java 一起。"""
    if proc is None or proc.poll() is not None:
        return
    if hostos.OS == "win":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        return
    try:
        os.kill(proc.pid, signal.SIGINT)
        proc.wait(timeout=45)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)       # 它是自己那一組的組長：Java 在同一組
    except OSError:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def create_accounts():
    """在 Auth 模擬器建好幾個假的 Google 帳號，登入視窗裡直接點。模擬器接受 JSON 當假的 id_token。"""
    url = ("http://127.0.0.1:%d/identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key=demo-api-key" % AUTH_PORT)
    for sub, email, name, _ in ACCOUNTS:
        claims = json.dumps({"sub": sub, "email": email, "email_verified": True, "name": name}, ensure_ascii=False)
        body = {"postBody": "id_token=%s&providerId=google.com" % urllib.parse.quote(claims),
                "requestUri": "http://localhost", "returnIdpCredential": True, "returnSecureToken": True}
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                r.read()
        except (urllib.error.URLError, OSError) as e:
            raise Fail(["✗ 在登入模擬器建假帳號失敗（%s）。" % type(e).__name__])


def seed(node, cfg, root):
    """示範內容寫進 Firestore 模擬器（管理身分），再用真的 access_sync.py、open_blogs.py 把名單對齊本機的名單檔。"""
    client = fr.Client(PROJECT_ID, emulator_host="127.0.0.1:%d" % FS_PORT)
    docs, _info = demo_docs(node, datetime.date.today().isoformat(), cfg.get("categories") or [], root)
    n_photos = fill_photos(docs)
    try:
        client.commit_all([client.set_write(p, to_fs(d)) for p, d in docs], what="種試玩資料")
    except fr.FirestoreError as e:
        raise Fail([e.plain()])
    for script in ("access_sync.py", "open_blogs.py"):
        r = run_py(script, "--root", root, "--emulator", "--apply")
        if r.returncode != 0:
            raise Fail(["✗ %s 在試玩環境沒有成功（下面是它最後幾行）：" % script] + tail(r))
    return len(docs), n_photos


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def serve(www, port):
    handler = functools.partial(_Quiet, directory=str(www))
    httpd = None
    for p in (port, 0):
        try:
            httpd = http.server.ThreadingHTTPServer(("127.0.0.1", p), handler)
            break
        except OSError:
            continue
    if httpd is None:
        raise Fail(["✗ 本機網站起不來（連隨便一個空的埠都拿不到）。"])
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://127.0.0.1:%d/" % httpd.server_address[1]


def usage_lines(site, rel_root=TRY_NAME):
    again = '--root %s --emulator' % rel_root
    out = ["", "✓ 試玩環境開好了（全部在這台電腦上，不連任何雲端專案）：", "",
           "  網站：%s" % site, "",
           "  登入：按「用 Google 帳號登入」→ 跳出來的是模擬器的假登入頁，直接點一個身分（不用密碼）："]
    for _, email, name, what in ACCOUNTS:
        out.append("    · %s（%s）— %s" % (name, email, what))
    out += ["  換身分：網站上按「登出」再登入另一個（或開另一個瀏覽器、無痕視窗）。",
            "  這裡的班級、名單、照片都是虛構的，只在這台電腦上；收掉就不見。", "",
            "  在這個試玩環境裡，其他腳本加 %s 就寫進這裡、不碰雲端，例如：" % again,
            "    %s scripts/access_sync.py %s" % (PY, again),
            "    %s scripts/publish_post.py <slug> %s" % (PY, again),
            "    %s scripts/publish_post.py <slug> %s --publish" % (PY, again),
            "  試玩資料夾：%s/（母本與名單在 %s/data/；收掉時整個刪掉）" % (rel_root, rel_root), "",
            "  收掉：在這個視窗按 Ctrl-C（代理在背景跑的話，停掉那個背景工作）。模擬器、網站、%s/ 一起清掉。" % rel_root]
    return out


def write_state(root, site):
    st = {"site": site, "root": TRY_NAME, "pid": os.getpid(), "project": PROJECT_ID,
          "started": datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()}
    (Path(root) / STATE_FILE).write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ════════════════════════════════════════════════════════════════════════
# 指令
# ════════════════════════════════════════════════════════════════════════

def check_tools():
    """回 (java, node, npm, 問題行清單, 要下載嗎)。只找、不改任何東西。"""
    problems = []
    java, jv = find_java()
    node, nv = find_node()
    if not java:
        problems += missing_lines("java", jv)
    if not node:
        problems += missing_lines("node", nv)
    npm = None
    if node:
        npm = shutil.which("npm", path=os.path.dirname(node)) or shutil.which("npm")
        if not npm:
            problems += missing_lines("node", ["找得到 node 卻找不到 npm（Node.js 裝得不完整）：請老師重新執行 Node.js 的安裝程式"])
    need_dl = not tools_ready()
    return java, jv, node, nv, npm, problems, need_dl


def download_note():
    rel = (RULES_DIR / "node_modules").relative_to(REPO).as_posix()
    return ["要先下載試玩用的模擬器工具（Firebase 官方的 firebase-tools，版本照 tests/rules/package-lock.json 釘死）：",
            "  · 大約 400 MB，全部放在這個資料夾的 %s/ 裡；**不會安裝到電腦的其他地方**" % rel,
            "    （不用 npm install -g；npm 的下載暫存裝完就刪；第一次開模擬器時還會下載 Firestore 模擬器本體約 140 MB，也放在同一個地方）。",
            "  · 不想留了：把 %s/ 這個資料夾移到垃圾桶就乾乾淨淨（要再試玩會重新下載）。" % rel,
            "  → 先跟老師講一句「我要下載試玩用的模擬器工具，大約 400 MB，只放在這個資料夾裡」，他同意後跑：",
            "     %s scripts/try_emulator.py --download" % PY]


def cmd_check():
    java, jv, node, nv, npm, problems, need_dl = check_tools()
    print("試玩環境檢查（唯讀）")
    print("  %s Java：%s" % ("✓" if java else "✗", ("%s（%d）" % (java, jv)) if java else "找不到 %d 以上的版本" % MIN_JAVA))
    print("  %s Node.js：%s" % ("✓" if node else "✗", ("%s（%d）" % (node, nv)) if node else "找不到 %d 以上的版本" % MIN_NODE))
    print("  %s 模擬器工具：%s" % ("！" if need_dl else "✓", "還沒下載（開試玩前要先加 --download）" if need_dl else "已經下載好了"))
    busy = [p for p in (FS_PORT, AUTH_PORT) if port_busy(p)]
    print("  %s 埠 %d、%d：%s" % ("！" if busy else "✓", FS_PORT, AUTH_PORT,
                                 ("被占用了（%s；多半是試玩環境已經開著，跑 --status 看）" % "、".join(map(str, busy))) if busy else "空著"))
    for line in problems:
        print(line)
    if need_dl and not problems:
        print("")
        for line in download_note():
            print(line)
    return 0 if (not problems and not need_dl and not busy) else EXIT_STOPPED


def cmd_status():
    root = try_root()
    st = None
    try:
        st = json.loads((root / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = None
    if not st or not http_ok(st.get("site", "")) or not http_ok(FS_URL):
        print("試玩環境沒有開著。要開：%s scripts/try_emulator.py" % PY)
        return EXIT_STOPPED
    print("試玩環境開著（%s 開的）：" % str(st.get("started", ""))[:16].replace("T", " "))
    for line in usage_lines(st["site"])[2:]:
        print(line)
    return 0


def cmd_start(a):
    java, jv, node, nv, npm, problems, need_dl = check_tools()
    if problems:
        raise Stop(["試玩要先裝好這幾樣（老師自己從官方網站裝；你不跑任何安裝指令）："] + problems)
    if need_dl and not a.download:
        raise Stop(download_note())
    busy = [p for p in (FS_PORT, AUTH_PORT) if port_busy(p)]
    if busy:
        raise Stop(["✗ 埠 %s 已經有程式在用（網站固定連 %d 與 %d）。" % ("、".join(map(str, busy)), FS_PORT, AUTH_PORT),
                    "  → 多半是試玩環境已經開著：跑 %s scripts/try_emulator.py --status 看網址；" % PY,
                    "    或上一次沒收乾淨：關掉那個視窗（或重開電腦）再試。"])
    print("✓ Java %d：%s" % (jv, java))
    print("✓ Node.js %d：%s" % (nv, node))
    if need_dl:
        print("… 下載模擬器工具到 tests/rules/node_modules/（版本照 package-lock.json；第一次要幾分鐘）")
        sys.stdout.flush()
        download_tools(npm, child_env(java, node))
    print("✓ 模擬器工具準備好了")
    root = make_root(try_root())
    proc = log = httpd = None
    rc = 0
    try:
        cfg, www = prepare(root)
        class_files(root)
        print("✓ 試玩資料夾 %s/：虛構的班級設定、網站設定與安全規則（build_config.py --emulator）、名冊與聯絡人" % TRY_NAME)
        print("… 啟動 Firestore＋Auth 模擬器（專案 %s；第一次會比較久）" % PROJECT_ID)
        sys.stdout.flush()
        proc, log = start_emulators(node, java, root)
        if not wait_ready(proc):
            log.flush()
            lines = [x.rstrip() for x in (root / "emulator.log").read_text(encoding="utf-8", errors="replace").splitlines()]
            raise Fail(["✗ 模擬器沒有起來（下面是它最後幾行）："] + ["    " + x for x in lines[-15:]] +
                       ["  → 多半是 Java 版本不對、網路斷了（第一次要下載），或埠被別的程式搶走。修好再跑一次。"])
        print("✓ 模擬器起來了")
        create_accounts()
        n_docs, n_photos = seed(node, cfg, root)
        print("✓ 種好虛構的一班：%d 份文件（照片 %d 張是程式畫的色塊圖）；名單用 access_sync.py、open_blogs.py 寫進去"
              % (n_docs, n_photos))
        httpd, site = serve(www, a.port)
        write_state(root, site)
        for line in usage_lines(site):
            print(line)
        sys.stdout.flush()
        if not a.no_open:
            try:
                webbrowser.open(site)
            except webbrowser.Error:
                pass
        while True:
            if proc.poll() is not None:
                print("\n✗ 模擬器自己停了（紀錄在 %s/emulator.log，收掉時會一起刪）。試玩環境收掉。" % TRY_NAME)
                rc = 1
                break
            time.sleep(1)
    except (KeyboardInterrupt, Interrupted):
        print("\n收掉試玩環境……")
    except Stop as e:
        for line in e.lines:
            print(line)
        rc = 1 if isinstance(e, Fail) else EXIT_STOPPED
    finally:
        if httpd is not None:
            httpd.shutdown()
        stop_emulators(proc)
        if log is not None:
            log.close()
        remove_root(root)
    if rc == 0:
        print("✓ 收好了：模擬器、本機網站、%s/ 都清掉了。" % TRY_NAME)
    return rc


def _on_term(signum, frame):
    raise Interrupted()


def main(argv=None):
    ap = argparse.ArgumentParser(description="先試玩：在這台電腦上開一個虛構班級的網站（模擬器），不碰任何雲端")
    ap.add_argument("--check", action="store_true", help="只檢查（唯讀）：Java、Node.js、模擬器工具、埠")
    ap.add_argument("--status", action="store_true", help="試玩環境開著嗎（網址、試玩資料夾）")
    ap.add_argument("--download", action="store_true", help="老師同意後：把模擬器工具下載到這個資料夾裡（tests/rules/node_modules）")
    ap.add_argument("--port", type=int, default=SITE_PORT, help="本機網站的埠（預設 %d；被占用就自動換一個）" % SITE_PORT)
    ap.add_argument("--no-open", action="store_true", help="開好之後不要自動打開瀏覽器")
    a = ap.parse_args(argv)
    if a.check:
        return cmd_check()
    if a.status:
        return cmd_status()
    if hostos.OS != "win":
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, _on_term)
    try:
        return cmd_start(a)
    except Stop as e:
        for line in e.lines:
            print(line)
        return 1 if isinstance(e, Fail) else EXIT_STOPPED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
