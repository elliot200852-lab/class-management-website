#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""smoke_emulator.py — 模擬器冒煙測試：用**真的 Firebase JS SDK**、**真的安全規則**、**正式站模式**把網站跑一遍
（docs/ARCHITECTURE.md §8.4）。開發與 CI 用；老師的電腦不需要跑這支。

示範模式不經過 SDK、也不經過安全規則（它只負責展示畫面），所以正式網站會走的那條路徑——
登入 → 讀名單解析身分 → 規則放行或拒絕 → 讀寫資料——要另外在這裡驗。全程只連本機模擬器，
專案 id 是 demo- 開頭（Firebase 保證 demo- 專案碰不到任何真的雲端資源）；測試帳號一律 @example.com。

  python3 scripts/smoke_emulator.py                 （Windows：py -3 scripts/smoke_emulator.py）
  python3 scripts/smoke_emulator.py --shots 目錄    每一頁存一張手機寬截圖（預設不存；不要存在 repo 裡）
  python3 scripts/smoke_emulator.py --require-chrome  找不到 Chrome 算失敗（CI 用；本機預設印 SKIP）

做的事（任何一步失敗就停、exit 1）：
  1. 用測試設定（導師 class.teacher@example.com）跑 `build_config.py --emulator`：產生**真的會被部署的那幾個檔**
     （網站設定＋安全規則），網站設定多一個 emulator: true，前端改連本機模擬器。
  2. 找 Chrome、Java 21＋、Node.js 20＋（找不到只印官方下載頁，不代裝）；tests/rules 的 firebase-tools（npm ci，跟規則測試共用）。
  3. `firebase emulators:exec --only auth,firestore --project demo-cmw` 跑這支的內層（--inner）：
     a. 用管理身分（REST＋Bearer owner，不受規則管）種一班測試資料：名單、紀事（其中一篇下架）、相簿、私密紀事、
        單頁、三個座號的部落格與對話。照片是在 Chrome 裡當場畫出來再轉成 JPEG 的（repo 裡沒有任何圖檔）。
     b. 本機起一個只聽 127.0.0.1 的小伺服器放網站（正式站模式，不是示範模式；Firebase SDK 從官方 CDN 載入，
        版本就是正式站寫死的那一個），無頭 Chrome 每個身分一個獨立的瀏覽器情境（互不共用登入狀態），
        用 Auth 模擬器接受的假 Google 憑證登入：導師、學生 A 家長（也是私密讀者）、學生 B 家長、同仁（座號 03）、名單外的人。
     c. 逐頁逐項驗：每一頁零主控台錯誤、手機寬沒有橫向溢出；家長看得到自己孩子、看不到別人（畫面與規則兩層）；
        名單外看到換帳號畫面；留言送出（即時出現）；已讀回條寫進資料庫；部落格發文（照片在瀏覽器重新編碼、
        帶 EXIF 的原圖驗出沒有 APP1／GPS）成功並在導師端出現、全班格亮起未讀；同一個文章編號重送被拒；
        家長收起自己的留言；同仁進不了對話串；導師收起留言、下架文章；點「用 Google 帳號登入」真的開出登入視窗；
        v1.1：導師看得到座位表、個人照與家長合照、匯出 PDF（照片載完才能列印）、每日一詩；家長打開導師限定頁只看到說明、
        規則也擋（連自己孩子的個人照都讀不到）。
  4. 結果一行一項，最後印 PASS n/n。

本機沒有 Chrome → 印「SKIP」並 exit 0（加 --require-chrome 就算失敗）。CI 的 ubuntu 機器一定有，一定跑。
模擬器驗不到的（要在真雲端才知道）：Auth 的登入方式有沒有開、authDomain 與網址、真的 Google 帳號選擇畫面、
真手機的 App 內建瀏覽器、複合索引（模擬器不檢查，交給 tests/test_build_indexes.py）——見 docs/ARCHITECTURE.md §8.5。
"""
import os
import sys
import json
import time
import base64
import shutil
import argparse
import datetime
import tempfile
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import cdp  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = REPO_ROOT / "tests" / "rules"
FIXTURE_JS = REPO_ROOT / "tests" / "fixtures" / "exif-jpeg.js"
PROJECT_ID = "demo-cmw"
FS_PORT = 8080
AUTH_PORT = 9099

# 測試身分（信箱一律 example.com；導師信箱跟 scripts/test_rules.py 同一個）
TEACHER = {"email": "class.teacher@example.com", "alias": "smkteacher01", "sub": "smoke-teacher"}
PARENT_A = {"email": "parent-a@example.com", "alias": "smkparenta01", "sub": "smoke-parent-a", "seat": "01"}
PARENT_B = {"email": "parent-b@example.com", "alias": "smkparentb02", "sub": "smoke-parent-b", "seat": "02"}
STAFF = {"email": "staff-1@example.com", "alias": "smkstaff0003", "sub": "smoke-staff", "seat": "03"}
OUTSIDER = {"email": "outsider@example.com", "sub": "smoke-outsider"}


# ════════════════════════════════════════════════════════════════════════
# 外層：產生設定、找工具、啟動模擬器
# ════════════════════════════════════════════════════════════════════════

def test_config():
    example = json.loads((REPO_ROOT / "config" / "class.example.json").read_text(encoding="utf-8"))
    example["class_name"] = "冒煙測試班"
    example["teacher"]["email"] = TEACHER["email"]
    example["teacher"]["display_name"] = "測試導師"
    example["students"]["count"] = 3
    example["firebase"].update({"project_id": PROJECT_ID, "api_key": "demo-api-key", "app_id": "demo-app-id",
                                "auth_domain": ""})
    return example


def prepare(tmp):
    """測試設定 → build_config.py --emulator → 網站資料夾（site/ 的複本＋產生的網站設定）與模擬器設定。"""
    root = tmp / "root"
    (root / "config").mkdir(parents=True)
    (root / "config" / "class.json").write_text(json.dumps(test_config(), ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "build_config.py"), "--root", str(root), "--emulator"],
                       cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        raise SystemExit("✗ build_config.py --emulator 失敗（上面是它的輸出）")
    cfg_js = root / "site" / "js" / "site-config.js"
    text = cfg_js.read_text(encoding="utf-8")
    if "emulator: true" not in text or ('"%s"' % PROJECT_ID) not in text:
        raise SystemExit("✗ build_config.py --emulator 產生的網站設定不對（沒有 emulator: true 或專案 id 不是 %s）" % PROJECT_ID)
    www = tmp / "www"
    shutil.copytree(str(REPO_ROOT / "site"), str(www), ignore=shutil.ignore_patterns("site-config.js", ".DS_Store"))
    shutil.copyfile(str(cfg_js), str(www / "js" / "site-config.js"))
    fb = {
        "firestore": {"rules": "firestore.rules"},
        "emulators": {
            "auth": {"host": "127.0.0.1", "port": AUTH_PORT},
            "firestore": {"host": "127.0.0.1", "port": FS_PORT},
            "ui": {"enabled": False},
            "singleProjectMode": True,
        },
    }
    (root / "firebase.json").write_text(json.dumps(fb, indent=2), encoding="utf-8")
    return root, www


def outer(a):
    chrome = cdp.find_chrome()
    if not chrome:
        msg = "找不到 Chrome（或 Chromium）。裝了之後再跑一次；也可以用環境變數 CMW_CHROME 指定執行檔。"
        if a.require_chrome:
            print("✗ " + msg)
            return 1
        print("SKIP：" + msg)
        return 0
    import test_rules as tr  # 找 Java／Node、npm ci 與規則測試共用同一套（tests/rules 的 firebase-tools）
    java, java_v, java_on_path = tr.find_tool("java", tr.java_major, tr.MIN_JAVA)
    node, node_v, node_on_path = tr.find_tool("node", tr.node_major, tr.MIN_NODE)
    if not java:
        tr.print_missing("java", java_v)
    if not node:
        tr.print_missing("node", node_v)
    if not java or not node:
        return 1
    print("✓ Chrome：%s" % chrome)
    print("✓ Java %d：%s%s" % (java_v, java, "" if java_on_path else "（不在 PATH 上，這次先直接用它）"))
    print("✓ Node.js %d：%s%s" % (node_v, node, "" if node_on_path else "（不在 PATH 上，這次先直接用它）"))
    npm = shutil.which("npm", path=os.path.dirname(node)) or shutil.which("npm")
    if not npm:
        tr.print_missing("node", ["找得到 node 卻找不到 npm（Node.js 安裝不完整）"])
        return 1
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([os.path.dirname(java), os.path.dirname(node), env.get("PATH", "")])
    if not tr.ensure_node_modules(npm, env, False):
        return 1
    firebase_js = RULES_DIR / "node_modules" / "firebase-tools" / "lib" / "bin" / "firebase.js"
    if not firebase_js.exists():
        print("✗ 找不到 %s（npm ci 沒裝好？跑一次 python3 scripts/test_rules.py --reinstall）" % firebase_js.relative_to(REPO_ROOT))
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="cmw-smoke-"))
    try:
        root, www = prepare(tmp)
        print("✓ 網站設定與安全規則由 build_config.py --emulator 產生（專案 %s、emulator: true）" % PROJECT_ID)
        manifest = {"www": str(www), "chrome": chrome, "shots": str(Path(a.shots).resolve()) if a.shots else "",
                    "verbose": bool(a.verbose)}
        mpath = tmp / "manifest.json"
        mpath.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        inner_cmd = '"%s" "%s" --inner "%s"' % (sys.executable, str(Path(__file__).resolve()), str(mpath))
        cmd = [node, str(firebase_js), "emulators:exec", "--only", "auth,firestore", "--project", PROJECT_ID,
               "--config", str(root / "firebase.json"), inner_cmd]
        print("… 啟動 Auth＋Firestore 模擬器（專案 %s）並開始冒煙測試" % PROJECT_ID)
        sys.stdout.flush()
        r = subprocess.run(cmd, cwd=str(root), env=env)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    if r.returncode == 0:
        print("\n✓ 模擬器冒煙測試全部通過。")
        return 0
    print("\n✗ 模擬器冒煙測試沒有全部通過（exit %d）。" % r.returncode)
    return 1


# ════════════════════════════════════════════════════════════════════════
# 內層：在模擬器裡種資料、開瀏覽器逐項驗
# ════════════════════════════════════════════════════════════════════════

FS_BASE = "http://127.0.0.1:%d/v1/projects/%s/databases/(default)/documents" % (FS_PORT, PROJECT_ID)
OWNER = {"Authorization": "Bearer owner", "Content-Type": "application/json"}
SDK_HOST = "www.gstatic.com"   # site/js/core/store-firestore.js 的 SDK_BASE


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def to_value(v):
    """Python 值 → Firestore REST 的 Value（測試專用的最小版本；正式的管理腳本另有 lib 與欄位白名單）"""
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, str):
        return {"stringValue": v}
    if isinstance(v, datetime.datetime):
        return {"timestampValue": v.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: to_value(x) for k, x in v.items()}}}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [to_value(x) for x in v]}}
    raise TypeError("不支援的型別：%r" % type(v))


def from_value(v):
    if "nullValue" in v:
        return None
    for k in ("booleanValue", "stringValue", "doubleValue", "timestampValue"):
        if k in v:
            return v[k]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "mapValue" in v:
        return {k: from_value(x) for k, x in (v["mapValue"].get("fields") or {}).items()}
    if "arrayValue" in v:
        return [from_value(x) for x in (v["arrayValue"].get("values") or [])]
    return None


def http(method, url, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=OWNER)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {}


def commit(docs):
    """[(路徑, 資料)] → 一次 commit（管理身分，不受規則管）"""
    name = "projects/%s/databases/(default)/documents/" % PROJECT_ID
    for i in range(0, len(docs), 100):
        writes = [{"update": {"name": name + p, "fields": {k: to_value(x) for k, x in d.items()}}}
                  for p, d in docs[i:i + 100]]
        code, _ = http("POST", FS_BASE + ":commit", {"writes": writes})
        if code != 200:
            raise SystemExit("✗ 種資料失敗（HTTP %d）" % code)


def read_doc(path):
    code, body = http("GET", FS_BASE + "/" + quote(path))
    if code != 200:
        return None
    return {k: from_value(v) for k, v in (body.get("fields") or {}).items()}


def list_docs(coll):
    code, body = http("GET", FS_BASE + "/" + quote(coll) + "?pageSize=300")
    if code != 200:
        return []
    return [(d["name"].split("/documents/", 1)[1], {k: from_value(v) for k, v in (d.get("fields") or {}).items()})
            for d in body.get("documents", [])]


def key_of(email):
    return email.strip().lower()   # 測試信箱都不是 gmail，email 鍵＝小寫


def ymd(days_ago):
    return (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()


class Data:
    """這一次種的測試資料的名字（slug、文章 id），給檢查用。"""

    def __init__(self):
        self.post = ymd(2) + "-smoke-visible"
        self.hidden = ymd(3) + "-smoke-hidden"
        self.album = ymd(4) + "-smoke-album"
        self.private = ymd(5) + "-smoke-private"
        self.e_teacher01 = ymd(1) + "-smkt0001"
        self.e_parent02 = ymd(2) + "-smkb0002"
        self.e_teacher03 = ymd(3) + "-smks0003"
        self.plan = ymd(1)
        self.today = ymd(0)
        self.personal_pid = "a1b2c3d4e5f60011"
        self.parent_pid = "a1b2c3d4e5f60012"


def seed(photo):
    """photo：{'thumb': (base64, w, h), 'image': (base64, w, h)}（在 Chrome 裡當場畫的 JPEG）"""
    D = Data()
    t = now_utc()
    docs = []

    def put(p, d):
        docs.append((p, d))

    def photos(owner, pids):
        for i, pid in enumerate(pids):
            put(owner + "/images/" + pid, {"data": photo["image"][0], "w": photo["image"][1], "h": photo["image"][2]})
            put(owner + "/thumbs/" + pid, {"data": photo["thumb"][0], "w": photo["thumb"][1], "h": photo["thumb"][2],
                                          "order": i})

    # 名單（導師一定也在兩份名單裡）
    for who, kind in ((TEACHER, "teacher"), (PARENT_A, "parent"), (PARENT_B, "parent"), (STAFF, "staff")):
        put("allowlist/" + key_of(who["email"]), {"kind": kind, "alias": who["alias"], "updatedAt": t})
    for who in (TEACHER, PARENT_A):
        put("private_allowlist/" + key_of(who["email"]), {"updatedAt": t})
    put("parent_child_map/" + key_of(PARENT_A["email"]),
        {"seats": ["01"], "kind": "parent", "active": True, "relation": "母", "label": "座號 01 家長", "updatedAt": t})
    put("parent_child_map/" + key_of(PARENT_B["email"]),
        {"seats": ["02"], "kind": "parent", "active": True, "relation": "父", "label": "座號 02 家長", "updatedAt": t})
    put("parent_child_map/" + key_of(STAFF["email"]),
        {"seats": ["03"], "kind": "staff", "active": True, "label": "座號 03 同仁", "updatedAt": t})
    put("roster/students", {"students": [{"seat": s, "name": "學生 " + c, "displayName": "學生 " + c}
                                         for s, c in (("01", "A"), ("02", "B"), ("03", "C"))], "updatedAt": t})
    put("roster/links", {"recordsKitUrl": "https://example.com/records", "classDocsIndexUrl": "", "updatedAt": t})
    put("ops/backup_status", {"nightly": {"lastRunAt": t, "ok": True}, "weekly": {"lastRunAt": t, "ok": True}})
    put("config/site", {"teacherDisplayName": "測試導師", "schoolName": "", "studentsCount": 3,
                        "calendarIcsUrl": "", "updatedAt": t})

    # 班級紀事：一篇可見（一張照片）、一篇下架
    pid1 = "a1b2c3d4e5f60001"
    photos("posts/" + D.post, [pid1])
    put("posts/" + D.post + "/content/main", {"blocks": [
        {"t": "p", "spans": [{"text": "冒煙測試的紀事正文。"}]},
        {"t": "img", "pid": pid1, "caption": "測試照片"},
        {"t": "video", "url": "https://www.youtube.com/watch?v=SMOKE000001", "title": "測試影片"},
    ], "updatedAt": t})
    put("posts/" + D.post, {"title": "冒煙測試：看得到的紀事", "date": ymd(2), "category": "班級生活",
                            "excerpt": "冒煙測試的摘要。", "coverPid": pid1, "coverThumb": None, "photoCount": 1,
                            "visible": True, "publishedAt": t, "updatedAt": t})
    put("posts/" + D.hidden + "/content/main", {"blocks": [{"t": "p", "spans": [{"text": "下架的正文。"}]}], "updatedAt": t})
    put("posts/" + D.hidden, {"title": "冒煙測試：已下架的紀事", "date": ymd(3), "category": "班級生活",
                              "excerpt": "下架。", "coverPid": None, "coverThumb": None, "photoCount": 0,
                              "visible": False, "publishedAt": t, "updatedAt": t})
    put("posts/" + D.post + "/comments/smokeComment0001", {
        "authorName": "B 的爸爸", "body": "學生 B 家長的留言。", "role": "parent", "authorAlias": PARENT_B["alias"],
        "status": "visible", "createdAt": t})

    # 相簿：兩張照片、一支影片連結
    photos("albums/" + D.album, ["a1b2c3d4e5f60002", "a1b2c3d4e5f60003"])
    put("albums/" + D.album, {"title": "冒煙測試相簿", "date": ymd(4), "order": 0, "description": "測試用。",
                              "coverPid": "a1b2c3d4e5f60002", "coverThumb": None, "photoCount": 2,
                              "videos": [{"title": "測試影片", "url": "https://www.youtube.com/watch?v=SMOKE000002"}],
                              "visible": True, "updatedAt": t})

    # 私密紀事
    put("private_posts/" + D.private, {"title": "冒煙測試：私密紀事", "date": ymd(5), "excerpt": "只有私密名單。",
                                       "blocks": [{"t": "p", "spans": [{"text": "私密紀事的正文。"}]}],
                                       "coverPid": None, "coverThumb": None, "photoCount": 0, "visible": True,
                                       "publishedAt": t, "updatedAt": t})

    # 單頁：首頁、關於我們、課程、課表
    put("pages/home", {"title": "首頁", "kind": "home", "order": 0, "visible": True, "updatedAt": t,
                       "data": {"bannerText": "冒煙測試的橫幅。"}})
    put("pages/about", {"title": "關於我們", "kind": "about", "order": 0, "visible": True, "updatedAt": t,
                        "blocks": [{"t": "p", "spans": [{"text": "關於我們的測試內容。"}]}]})
    put("pages/course-smoke", {"title": "測試課程", "kind": "course", "order": 0, "visible": True, "updatedAt": t,
                               "blocks": [{"t": "p", "spans": [{"text": "課程介紹。"}]}],
                               "data": {"videos": [{"title": "課程說明", "url": "https://www.youtube.com/watch?v=SMOKE000003"}],
                                        "cards": [{"title": "科目一", "text": "說明。", "url": "https://example.com/s1"}]}})
    put("pages/schedule-smoke", {"title": "課表", "kind": "schedule", "order": 1, "visible": True, "updatedAt": t,
                                 "data": {"rows": [{"cells": ["", "一"]}, {"cells": ["第一節", "科目"]}]}})

    # 部落格：三個座號
    for seat, letter in (("01", "A"), ("02", "B"), ("03", "C")):
        put("student_blogs/" + seat, {"seat": seat, "displayName": "學生 " + letter, "intro": "", "avatar": None,
                                      "updatedAt": t})
    put("student_blogs/01/entries/" + D.e_teacher01, {
        "title": "導師寫給 A 的文章", "body": "導師的文章。", "date": ymd(1), "author": "teacher",
        "authorAlias": TEACHER["alias"], "photos": [], "visible": True, "createdAt": t})
    put("student_blogs/01/entries/" + D.e_teacher01 + "/blog_comments/smokeBlogComment01", {
        "body": "A 的媽媽回覆老師。", "role": "parent", "authorAlias": PARENT_A["alias"], "status": "visible", "createdAt": t})
    put("student_blogs/02/entries/" + D.e_parent02, {
        "title": "B 家長寫的文章", "body": "B 家長的文章。", "date": ymd(2), "author": "parent",
        "authorAlias": PARENT_B["alias"], "photos": [], "visible": True, "createdAt": t})
    put("student_blogs/03/entries/" + D.e_teacher03, {
        "title": "導師寫給 C 的文章", "body": "同仁讀得到這篇。", "date": ymd(3), "author": "teacher",
        "authorAlias": TEACHER["alias"], "photos": [], "visible": True, "createdAt": t})
    put("student_blogs/03/entries/" + D.e_teacher03 + "/blog_comments/smokeBlogComment03", {
        "body": "同仁看不到這一則。", "role": "teacher", "authorAlias": TEACHER["alias"], "status": "visible", "createdAt": t})
    # v1.1：座位表、個人照＋家長合照（只有導師讀得到）、每日一詩（讀者讀得到）
    put("seating/" + D.plan, {"title": "冒煙測試座位", "date": D.plan, "note": "",
                              "rows": [{"seats": ["01", "02", "-", "03"]}, {"seats": ["", "-", "-"]}], "updatedAt": t})
    photos("personal_photos/01", [D.personal_pid])
    put("personal_photos/01", {"photoPids": [D.personal_pid], "updatedAt": t})
    photos("parent_photo_display/01", [D.parent_pid])
    put("parent_photo_display/01", {"relations": ["母"], "note": "冒煙測試備註", "photoPids": [D.parent_pid], "updatedAt": t})
    put("pages/poems-" + D.today[:7], {"title": "每日一詩", "kind": "poem", "order": 0, "visible": True, "updatedAt": t,
                                       "data": {"month": D.today[:7], "items": [
                                           {"date": D.today, "title": "冒煙測試的詩", "author": "示範文字",
                                            "text": "第一行\n  第二行"}]}})
    commit(docs)
    return D


# ── 瀏覽器 ─────────────────────────────────────────────────────────────

MAKE_PHOTO_JS = r"""(async () => {
  async function jpeg(w, h, q) {
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const x = c.getContext('2d');
    x.fillStyle = '#7a6010'; x.fillRect(0, 0, w, h);
    x.fillStyle = '#c4a03c'; x.beginPath(); x.arc(w * 0.7, h * 0.3, h * 0.15, 0, Math.PI * 2); x.fill();
    x.fillStyle = '#1f6f6b'; x.fillRect(0, h * 0.7, w, h * 0.3);
    const url = c.toDataURL('image/jpeg', q);
    return url.slice(url.indexOf(',') + 1);
  }
  return { thumb: [await jpeg(320, 240, 0.7), 320, 240], image: [await jpeg(1280, 960, 0.8), 1280, 960] };
})()"""


class Checks:
    def __init__(self, verbose=False):
        self.results = []
        self.verbose = verbose

    def ok(self, cond, label, detail=""):
        self.results.append((bool(cond), label, detail))
        mark = "✓" if cond else "✗"
        if not cond or self.verbose:
            print("  %s %s%s" % (mark, label, ("　→ " + str(detail)) if (detail and not cond) else ""))
        elif cond:
            print("  ✓ %s" % label)
        return bool(cond)

    def summary(self):
        n = len(self.results)
        good = sum(1 for r in self.results if r[0])
        return good, n


class Actor:
    """一個登入身分：自己的瀏覽器情境（不共用登入狀態與本機資料）＋一個分頁。"""

    def __init__(self, browser, base, name, who, checks, shots):
        import verify_site as vs
        self.vs = vs
        self.base = base
        self.name = name
        self.who = who
        self.C = checks
        self.shots = shots
        self.page = browser.new_page(isolated=True)
        for dom in ("Page", "Runtime", "Log", "Network"):
            self.page.send(dom + ".enable")
        self.page.send("Emulation.setDeviceMetricsOverride", vs.VIEWPORTS["mobile"])
        self.page.send("Emulation.setTouchEmulationEnabled", {"enabled": True})
        self.n = 0

    def ev(self, expr, timeout=30):
        return self.page.evaluate(expr, timeout=timeout)

    def wait(self, expr, timeout=20):
        return self.page.wait_for(expr, timeout=timeout)

    def errors(self):
        errs, _external, _fonts = self.vs.collect_problems(self.page.my_events(clear=True))
        return errs

    def open(self, rel, label=None, expect_ready=True):
        """開一頁 → 等畫完 → 驗零主控台錯誤＋手機寬沒有橫向溢出。回傳是否畫完。"""
        self.page.my_events(clear=True)
        self.vs.goto(self.page, self.base + rel)
        ready = self.vs.wait_ready(self.page, timeout=30)
        self.page.b.pump(0.4)
        label = label or rel
        if expect_ready:
            self.C.ok(ready, "%s｜%s：畫完" % (self.name, label))
        ov = self.ev(self.vs.overflow_js(self.vs.VIEWPORTS["mobile"]["width"])) or {}
        errs = self.errors()
        self.C.ok(not errs, "%s｜%s：零主控台錯誤" % (self.name, label), "；".join(errs[:3]))
        self.C.ok(not (ov.get("overflow") or ov.get("offenders")), "%s｜%s：手機寬沒有橫向溢出" % (self.name, label),
                  "、".join((ov.get("offenders") or [])[:3]))
        if self.shots:
            self.n += 1
            safe = "".join(ch if ch.isalnum() else "-" for ch in rel)[:60]
            self.page.screenshot(str(Path(self.shots) / ("%s__%02d__%s.png" % (self.name, self.n, safe))), full_page=True)
        return ready

    def sign_in(self):
        """用 Auth 模擬器接受的假 Google 憑證登入（跟正式站同一個 SDK 實例；登入狀態存在這個瀏覽器情境裡）。"""
        self.vs.goto(self.page, self.base + "index.html")
        self.wait("window.CMW && document.documentElement.getAttribute('data-cmw-ready') === '1' && !!document.querySelector('.gate')", 30)
        token = json.dumps({"sub": self.who["sub"], "email": self.who["email"], "email_verified": True})
        self.ev("CMW.getStore()._ready().then(sdk => sdk.AU.signInWithCredential(sdk.auth, "
                "sdk.AU.GoogleAuthProvider.credential(%s))).then(() => true)" % json.dumps(token), timeout=30)
        return self.wait("(() => { const s = CMW.getStore().getSession(); return s.state === 'ready' || s.state === 'denied'; })()"
                         " && document.documentElement.getAttribute('data-cmw-ready') === '1'", 30)

    def store_code(self, js):
        """在頁面裡直接呼叫 Store（驗規則：該被拒的就算畫面不發也要被拒）。回傳 'ok' 或 StoreError 的 code。"""
        r = self.ev("(async () => { try { await (%s); return 'ok'; } catch (e) { return (e && e.code) || String(e); } })()" % js)
        self.page.my_events(clear=True)   # 刻意製造的拒絕不算頁面錯誤
        return r


def popup_probe(browser, base, C):
    """點「用 Google 帳號登入」→ 真的開出 Auth 模擬器的登入視窗（signInWithPopup 走得通；被擋時退回整頁轉址也算）。"""
    page = browser.new_page(isolated=True)
    for dom in ("Page", "Runtime", "Log"):
        page.send(dom + ".enable")
    import verify_site as vs
    vs.goto(page, base + "index.html")
    page.wait_for("document.documentElement.getAttribute('data-cmw-ready') === '1' && !!document.querySelector('.btn--google')", 30)
    page.my_events(clear=True)
    page.send("Runtime.evaluate", {"expression": "document.querySelector('.btn--google').click()", "userGesture": True})
    opened = None
    deadline = time.time() + 20
    while time.time() < deadline and not opened:
        for t in browser.send("Target.getTargets").get("targetInfos", []):
            if t.get("type") == "page" and ":%d/emulator/auth/handler" % AUTH_PORT in (t.get("url") or ""):
                opened = t
                break
        if not opened:
            browser.pump(0.3)
    C.ok(opened is not None, "登入閘｜按「用 Google 帳號登入」會開出 Auth 模擬器的 Google 登入視窗（真的 SDK signInWithPopup）")
    if opened and opened.get("targetId") != page.tid:
        browser.send("Target.closeTarget", {"targetId": opened["targetId"]})
    browser.pump(1.0)
    errs, _e, _f = vs.collect_problems(page.my_events(clear=True))
    C.ok(not errs, "登入閘｜開登入視窗再關掉：零主控台錯誤", "；".join(errs[:3]))


def compose_with_exif(A, seat):
    """家長在網頁上發一篇附照片的文章：照片是當場做的、帶 EXIF（方向 6＋GPS 記號）的 JPEG。回傳新文章 id。"""
    fixture = FIXTURE_JS.read_text(encoding="utf-8")
    A.open("my-child.html#/new/" + seat, "寫一篇")
    A.ev(fixture)
    A.ev("""(async () => {
      const f = await CMWTestJpeg.makeFile(2000, 1500, 6);
      const input = document.getElementById('mc-photos');
      const dt = new DataTransfer(); dt.items.add(f); input.files = dt.files;
      input.dispatchEvent(new Event('change', { bubbles: true })); return true; })()""")
    A.C.ok(A.wait("!!document.querySelector('.photo-slot img')", 30), "%s｜選照片後在瀏覽器裡重新編碼、出現預覽" % A.name,
           A.ev("Array.from(document.querySelectorAll('.photo-slot')).map(x => x.textContent).join('｜')"))
    A.ev("""(() => { document.getElementById('mc-title').value = '冒煙測試：家長發的文';
      document.getElementById('mc-body').value = '第一行\\n\\n  第三行（前面兩個空白）';
      document.querySelector('.photo-slot input').value = '測試圖說';
      document.querySelector('.compose-form button[type=submit]').click(); return true; })()""")
    posted = A.wait("location.hash.indexOf('#/entry/%s/') === 0 && !!document.querySelector('.blog-post')"
                    " && document.documentElement.getAttribute('data-cmw-ready') === '1'" % seat, 30)
    A.C.ok(posted, "%s｜部落格發文（文章＋照片兩份，一個批次）成功並跳到文章頁" % A.name,
           A.ev("(document.querySelector('.compose-form .form-msg') || {}).textContent || ''"))
    if not posted:
        return None
    post_id = A.ev("location.hash.split('/')[3]")
    errs = A.errors()
    A.C.ok(not errs, "%s｜發文過程零主控台錯誤" % A.name, "；".join(errs[:3]))
    return post_id


def v11_teacher(T, C, D):
    """導師：座位表分頁、個人照（並排家長合照）、匯出 PDF（班級紀事、學生部落格全班）、每日一詩——全部走真 SDK＋真規則。"""
    ready = "document.documentElement.getAttribute('data-cmw-ready') === '1'"
    T.open("teacher.html#/seating", "座位表")
    C.ok(T.ev("document.querySelectorAll('.seating-svg .seat-card--seat').length === 3"
              " && document.querySelectorAll('.seating-svg .seat-card--empty').length === 1"
              " && document.querySelector('.seating-svg').textContent.indexOf('學生 A') >= 0"),
         "導師｜座位表（seating.all）：3 個座位＋1 個空位，名字由名冊（roster/students）補上")
    T.open("family-photos.html", "個人照")
    C.ok(T.wait("document.querySelectorAll('.fp-card').length === 3"
                " && document.querySelectorAll('.fp-card img[src^=\"data:image/jpeg;base64,\"]').length === 1", 15),
         "導師｜個人照（personalPhotos.all）：名冊 3 格、座號 01 的縮圖讀得到（MIME 寫死 image/jpeg）")
    T.ev("document.querySelector('.fp-card[data-seat=\"01\"]').click()")
    C.ok(T.wait("document.querySelectorAll('.fp-viewer .fp-pane img[src^=\"data:image/jpeg;base64,\"]').length === 2"
                " && document.querySelector('.fp-viewer-rel').textContent.indexOf('母') >= 0", 15),
         "導師｜點開：孩子的個人照與家長合照（parentPhotos.all）兩張顯示圖並排、稱謂「母」")
    T.page.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
    T.open("blog-print.html", "匯出 PDF（班級紀事）")
    C.ok(T.wait("document.querySelector('.export-count').textContent === '將匯出 1／2 篇'", 15),
         "導師｜匯出清單：可見的那篇預設勾、下架的預設不勾（posts.recent.teacher）",
         T.ev("(document.querySelector('.export-count') || {}).textContent"))
    T.ev("document.querySelector('.export-buttons .btn--primary').click()")
    C.ok(T.wait("!!document.querySelector('.print-doc.is-ready')", 20)
         and T.ev("document.querySelectorAll('.print-doc .print-item').length === 1"
                  " && document.querySelectorAll('.print-fig img[src^=\"data:image/jpeg;base64,\"]').length === 1"
                  " && !document.querySelector('.export-buttons .btn:not(.btn--primary)').disabled"),
         "導師｜產生列印版：正文（content/main）＋顯示圖載完才開放列印",
         T.ev("(document.querySelector('.export-status') || {}).textContent"))
    T.open("my-child-print.html", "匯出 PDF（學生部落格）")
    T.ev("(() => { const s = document.getElementById('ex-mode'); s.value = 'all'; s.dispatchEvent(new Event('change', {bubbles: true})); return true; })()")
    C.ok(T.wait("document.querySelectorAll('.export-group').length === 3", 15), "導師｜匯出部落格（全班）：3 個座號各一組（entries.bySeat.teacher）")
    T.ev("document.querySelector('.export-buttons .btn--primary').click()")
    C.ok(T.wait("!!document.querySelector('.print-doc.is-ready') && document.querySelectorAll('.print-doc .print-student').length === 3", 20),
         "導師｜全班一份：每位學生一段（列印時各從新的一頁開始）")
    T.open("poem.html", "每日一詩")
    C.ok(T.ev("document.querySelector('.poem-title').textContent === '冒煙測試的詩'"
              " && document.querySelector('.poem-text').textContent === '第一行\\n  第二行'"),
         "導師｜每日一詩：今天那一首、正文逐字（行首空白）")
    errs = T.errors()
    C.ok(not errs, "導師｜v1.1 頁面操作過程零主控台錯誤", "；".join(errs[:3]))


def v11_parent(A, C, D):
    """家長：導師限定的三頁只看到一句說明（畫面一個查詢都不發），規則也真的擋；每日一詩讀得到。"""
    for rel, label in (("teacher.html#/seating", "座位表"), ("family-photos.html", "個人照"),
                       ("blog-print.html", "匯出 PDF"), ("my-child-print.html", "匯出 PDF（部落格）")):
        A.open(rel, label + "（導師限定）")
        C.ok(A.ev("document.body.textContent.indexOf('這一頁只有導師能用') >= 0"
                  " && !document.querySelector('.fp-card, .seating-svg, .export-panel')"),
             "A家長｜%s：只看到「只有導師能用」" % label)
    C.ok(A.store_code("CMW.getStore().query('seating.all')") == "denied", "A家長｜規則：查座位表被拒")
    C.ok(A.store_code("CMW.getStore().query('personalPhotos.all')") == "denied"
         and A.store_code("CMW.getStore().get('personal_photos/01')") == "denied",
         "A家長｜規則：連自己孩子的個人照也讀不到（導師限定）")
    C.ok(A.store_code("CMW.getStore().get('personal_photos/01/thumbs/%s')" % D.personal_pid) == "denied"
         and A.store_code("CMW.getStore().get('parent_photo_display/01')") == "denied"
         and A.store_code("CMW.getStore().query('parentPhotos.all')") == "denied",
         "A家長｜規則：個人照的縮圖、家長合照（連自己的）都被拒")
    A.open("poem.html", "每日一詩")
    C.ok(A.ev("document.querySelector('.poem-title').textContent === '冒煙測試的詩'"), "A家長｜每日一詩讀得到（pages/poems-YYYY-MM）")


def run_inner(manifest_path):
    m = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        print("✗ 請用 python3 scripts/smoke_emulator.py 跑（它會啟動模擬器）。")
        return 2
    import verify_site as vs
    C = Checks(m.get("verbose"))
    shots = m.get("shots") or ""
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
    httpd, base = vs.serve(Path(m["www"]))
    browser = cdp.Browser(m["chrome"])
    try:
        # 0. 照片：在 Chrome 裡當場畫、轉成 JPEG（repo 裡不放任何圖檔）
        scratch = browser.new_page()
        photo = scratch.evaluate(MAKE_PHOTO_JS)
        D = seed(photo)
        print("✓ 已用管理身分種好測試資料（名單、紀事、相簿、私密紀事、單頁、3 個座號的部落格）")

        # 網頁用的 Firebase 程式庫從官方 CDN（www.gstatic.com）載入：載不下來，後面每一項都會壞，先講白話原因就停
        vs.goto(scratch, base + "index.html")
        scratch.wait_for("window.CMW && document.documentElement.getAttribute('data-cmw-ready') === '1'", 30)
        sdk = scratch.evaluate("(window.CMW ? CMW.getStore()._ready().then(() => 'ok', e => String((e && e.message) || e))"
                               " : Promise.resolve('網頁程式沒有載入'))", timeout=90)
        if sdk != "ok":
            print("✗ 瀏覽器載不到 Firebase 的網頁程式庫（%s）：%s" % (SDK_HOST, sdk))
            print("  → 冒煙測試要連網：這台電腦現在連不上 %s（網路斷了、公司或學校的防火牆、Proxy 擋住）。"
                  "連得上再跑一次；規則本身可以先跑 scripts/test_rules.py（不需要連網）。" % SDK_HOST)
            return 1
        print("✓ Firebase 網頁程式庫載得到（%s）" % SDK_HOST)

        print("\n=== 登入閘（真的 SDK） ===")
        popup_probe(browser, base, C)

        print("\n=== 導師：第一輪 ===")
        T = Actor(browser, base, "導師", TEACHER, C, shots)
        C.ok(T.sign_in(), "導師｜用 Google（模擬器）登入並解析出身分")
        s = T.ev("CMW.getStore().getSession()")
        C.ok(s["state"] == "ready" and s["roles"]["teacher"] and s["roles"]["privateReader"] and s["roles"]["alias"] == TEACHER["alias"],
             "導師｜Session：導師探針放行、名單 kind＝teacher、代號對", s["roles"])
        T.open("index.html", "首頁")
        C.ok(T.ev("!!document.querySelector('.teacher-fab') && !!document.querySelector('.nav-teacher')"), "導師｜首頁有導師浮鈕與「導師專用」分頁")
        T.open("blog.html", "紀事列表")
        C.ok(T.ev("document.body.textContent.indexOf('已下架的紀事') >= 0 && !!document.querySelector('.entry--private')"),
             "導師｜紀事列表看得到下架的紀事與私密紀事鎖頭卡")
        T.open("post.html?s=" + D.hidden, "下架的單篇")
        C.ok(T.ev("document.body.textContent.indexOf('已下架的紀事') >= 0 && !!document.querySelector('.chip--hidden')"),
             "導師｜下架的單篇照樣讀得到（標示已下架）")
        T.open("admin.html", "留言後台")
        C.ok(T.ev("document.querySelectorAll('.admin-item').length >= 1 && document.body.textContent.indexOf('座號 02') >= 0"),
             "導師｜留言後台（集合群組查詢）列出留言，代號對回座號")
        T.open("album.html?a=" + D.album, "單本相簿")
        C.ok(T.ev("document.querySelectorAll('.album-photos .thumb img[src^=\"data:image/jpeg;base64,\"]').length === 2"),
             "導師｜相簿格：2 張縮圖直接用查詢結果的 base64")
        T.ev("document.querySelector('.album-photos .thumb').click()")
        C.ok(T.wait("!!document.querySelector('.lightbox-stage img[src^=\"data:image/jpeg;base64,\"]')", 15),
             "導師｜燈箱讀顯示圖（photoSrc，MIME 寫死 image/jpeg）")
        T.ev("document.querySelector('.lightbox-close').click()")
        T.open("courses.html", "課程")
        C.ok(T.ev("document.querySelectorAll('.syllabus-card').length === 1 && document.querySelectorAll('.schedule').length === 1"),
             "導師｜課程頁：大綱卡與課表")
        T.ev("document.querySelector('.courses .blk-video-play').click()")
        C.ok(T.wait("!!document.querySelector('.courses iframe[src^=\"https://www.youtube-nocookie.com/embed/SMOKE000003\"]')", 5),
             "導師｜課程影片點了才建 youtube-nocookie 播放器")
        T.page.my_events(clear=True)   # 模擬器沒有網路也無所謂：只驗 iframe 的網址
        T.open("teacher.html", "導師專用")
        C.ok(T.ev("!!document.querySelector('.tool-card--records a[href=\"https://example.com/records\"]')"
                  " && document.querySelector('.tool-card--backup').textContent.indexOf('正常') >= 0"),
             "導師｜導師專用：紀錄入口讀 roster/links、備份狀態讀 ops/backup_status")
        T.open("page.html?id=about", "關於我們")
        v11_teacher(T, C, D)

        print("\n=== 學生 A 家長（座號 01，也是私密讀者） ===")
        A = Actor(browser, base, "A家長", PARENT_A, C, shots)
        C.ok(A.sign_in(), "A家長｜登入並解析出身分")
        s = A.ev("CMW.getStore().getSession()")
        C.ok(s["state"] == "ready" and not s["roles"]["teacher"] and s["roles"]["privateReader"]
             and s["roles"]["seats"] == ["01"] and s["roles"]["seatKind"] == "parent",
             "A家長｜Session：讀者＋私密讀者＋座號 01 家長（導師探針被拒）", s["roles"])
        A.open("index.html", "首頁")
        C.ok(A.ev("!document.querySelector('.teacher-fab') && !!document.querySelector('.nav-my-child')"), "A家長｜沒有導師工具、有「我的孩子」")
        A.open("blog.html", "紀事列表")
        C.ok(A.ev("!!document.querySelector('.entry--private') && document.body.textContent.indexOf('已下架的紀事') < 0"),
             "A家長｜紀事列表：私密紀事以鎖頭卡併入、看不到下架的")
        A.open("post.html?s=" + D.post, "單篇紀事")
        C.ok(A.wait("!!document.querySelector('.post-body .blk-photo img[src^=\"data:image/jpeg;base64,\"]')", 15),
             "A家長｜單篇正文的照片讀得到")
        A.ev("""(() => { document.getElementById('comment-name').value = 'A 的媽媽';
          document.getElementById('comment-body').value = '冒煙測試留言 <script>x</script>';
          document.querySelector('.comment-form button[type=submit]').click(); return true; })()""")
        C.ok(A.wait("Array.from(document.querySelectorAll('.comment-body')).some(p => p.textContent.indexOf('冒煙測試留言') >= 0)", 15),
             "A家長｜送出留言：即時出現在留言串（onSnapshot）")
        C.ok(A.ev("document.querySelectorAll('.comment-body script').length === 0"), "A家長｜留言裡的 <script> 只是文字")
        errs = A.errors()
        C.ok(not errs, "A家長｜留言過程零主控台錯誤", "；".join(errs[:3]))
        receipt = None
        for _ in range(20):
            receipt = read_doc("posts/%s/reads/%s" % (D.post, key_of(PARENT_A["email"])))
            if receipt:
                break
            time.sleep(0.5)
        C.ok(receipt and receipt.get("kind") == "parent" and receipt.get("readAt"), "A家長｜開過單篇＝已讀回條寫進資料庫（kind parent）", receipt)
        cm = [d for p, d in list_docs("posts/%s/comments" % D.post) if d.get("authorAlias") == PARENT_A["alias"]]
        C.ok(cm and cm[0].get("role") == "parent" and cm[0].get("status") == "visible", "A家長｜留言文件：role 與作者代號由規則驗過", cm[:1])
        A.open("post.html?s=" + D.hidden, "下架的單篇")
        C.ok(A.ev("!!document.querySelector('.notice') && document.body.textContent.indexOf('下架的正文') < 0"),
             "A家長｜下架的單篇：顯示「找不到」，內容讀不到")
        C.ok(A.store_code("CMW.getStore().get('posts/%s')" % D.hidden) == "denied", "A家長｜規則：get 下架的紀事被拒")
        A.open("post.html?s=2000-01-01-not-here", "不存在的單篇")
        C.ok(A.ev("!!document.querySelector('.notice')"), "A家長｜不存在的單篇：找不到")
        A.open("album.html?a=" + D.album, "單本相簿")
        A.ev("""(() => { document.getElementById('comment-name').value = 'A 的媽媽';
          document.getElementById('comment-body').value = '相簿留言';
          document.querySelector('.comment-form button[type=submit]').click(); return true; })()""")
        C.ok(A.wait("Array.from(document.querySelectorAll('.comment-body')).some(p => p.textContent.indexOf('相簿留言') >= 0)", 15),
             "A家長｜相簿留言送出並即時出現")
        A.errors()
        A.open("private.html", "私密紀事列表")
        A.open("private.html?p=" + D.private, "私密紀事單篇")
        C.ok(A.ev("document.body.textContent.indexOf('私密紀事的正文') >= 0 && document.title.indexOf('冒煙測試：') < 0"),
             "A家長｜私密紀事讀得到，分頁標題不露出文章標題")
        pr = None
        for _ in range(20):
            pr = read_doc("private_posts/%s/reads/%s" % (D.private, key_of(PARENT_A["email"])))
            if pr:
                break
            time.sleep(0.5)
        C.ok(pr and pr.get("kind") == "parent", "A家長｜私密紀事的已讀回條寫進資料庫", pr)
        A.open("my-child.html", "我的孩子")
        C.ok(A.ev("location.hash === '' && document.body.textContent.indexOf('學生 A 的部落格') >= 0"
                  " && document.body.textContent.indexOf('導師寫給 A 的文章') >= 0"),
             "A家長｜我的孩子：只有一個座號就直接看到座號 01 的文章")
        A.open("my-child.html#/entry/01/" + D.e_teacher01, "我的孩子單篇")
        C.ok(A.ev("document.body.textContent.indexOf('A 的媽媽回覆老師') >= 0"), "A家長｜對話串讀得到")
        post_id = compose_with_exif(A, "01")
        if post_id:
            entry = read_doc("student_blogs/01/entries/" + post_id)
            img = read_doc("student_blogs/01/entries/%s/images/0" % post_id)
            th = read_doc("student_blogs/01/entries/%s/thumbs/0" % post_id)
            C.ok(entry and entry.get("author") == "parent" and entry.get("authorAlias") == PARENT_A["alias"]
                 and entry.get("body") == "第一行\n\n  第三行（前面兩個空白）" and entry.get("photos") == [
                     {"pid": "0", "w": 960, "h": 1280, "caption": "測試圖說"}],
                 "A家長｜資料庫裡的文章：author parent、作者代號、內文逐字、照片清單（已轉正成直的）", entry)
            ok_img = False
            detail = ""
            if img and th:
                ib = base64.b64decode(img["data"])
                tb = base64.b64decode(th["data"])
                has_app1 = A.ev("(() => { const P = CMW.photoEncode, J = CMWTestJpeg;"
                                " const a = J.b64ToBytes(%s), b = J.b64ToBytes(%s);"
                                " return [P.hasMetadata(a), P.hasMetadata(b)]; })()" % (json.dumps(img["data"]), json.dumps(th["data"])))
                mark = b"CMW-EXIF-GPS-TEST"
                ok_img = (ib[:2] == b"\xff\xd8" and tb[:2] == b"\xff\xd8" and has_app1 == [False, False]
                          and mark not in ib and mark not in tb and (img["w"], img["h"], th["w"], th["h"]) == (960, 1280, 240, 320)
                          and th.get("order") == 0)
                detail = {"app1": has_app1, "size": (img["w"], img["h"], th["w"], th["h"])}
            C.ok(ok_img, "A家長｜上傳的照片：JPEG、沒有 APP1（EXIF）、沒有 GPS 記號、方向已轉正（960×1280／240×320）", detail)
            C.ok(A.store_code("CMW.getStore().batch([{ op: 'set', path: 'student_blogs/01/entries/%s', data: { title: 'x', body: 'x',"
                              " date: '%s', author: 'parent', authorAlias: '%s', photos: [], visible: true, createdAt: CMW.SERVER_TIME } }])"
                              % (post_id, ymd(0), PARENT_A["alias"])) == "denied",
                 "A家長｜規則：同一個文章編號重送（＝修改）被拒")
            # 對話串：留言 → 收起自己的那一則（兩段確認）
            A.ev("""(() => { document.getElementById('bc-body').value = '冒煙測試：家長的對話';
              document.querySelector('.blog-thread button[type=submit]').click(); return true; })()""")
            C.ok(A.wait("Array.from(document.querySelectorAll('.bc-item .comment-body')).some(p => p.textContent.indexOf('家長的對話') >= 0)", 15),
                 "A家長｜在自己的文章底下留言")
            A.ev("(() => { const b = Array.from(document.querySelectorAll('.bc-item.is-mine button')).find(x => x.textContent.indexOf('收起') === 0);"
                 " if (b) { b.click(); b.click(); } return !!b; })()")
            C.ok(A.wait("!Array.from(document.querySelectorAll('.bc-item .comment-body')).some(p => p.textContent.indexOf('家長的對話') >= 0)", 15),
                 "A家長｜收起自己的留言（收起後畫面上消失）")
            bc = [d for p, d in list_docs("student_blogs/01/entries/%s/blog_comments" % post_id)]
            C.ok(len(bc) == 1 and bc[0].get("status") == "hidden" and bc[0].get("role") == "parent",
                 "A家長｜資料庫裡那一則是 hidden（家長只能收起、不能刪）", bc)
            errs = A.errors()
            C.ok(not errs, "A家長｜對話串過程零主控台錯誤", "；".join(errs[:3]))
            last_bc = [p for p, d in list_docs("student_blogs/01/entries/%s/blog_comments" % post_id)]
            if last_bc:
                C.ok(A.store_code("CMW.getStore().update('%s', { status: 'visible' })" % last_bc[0]) == "denied",
                     "A家長｜規則：收起後不能自己改回顯示")
        A.open("my-child.html#/seat/02", "別人的座號")
        C.ok(A.ev("document.body.textContent.indexOf('不在你的帳號底下') >= 0 && document.body.textContent.indexOf('B 家長寫的文章') < 0"),
             "A家長｜打別人的座號：畫面只說不在你的帳號底下（不發查詢）")
        C.ok(A.store_code("CMW.getStore().get('student_blogs/02')") == "denied", "A家長｜規則：讀別人座號的部落格主頁被拒")
        C.ok(A.store_code("CMW.getStore().query('entries.bySeat', { seat: '02' })") == "denied", "A家長｜規則：查別人座號的文章被拒")
        C.ok(A.store_code("CMW.getStore().query('blogs.all')") == "denied", "A家長｜規則：列出全班部落格被拒")

        v11_parent(A, C, D)

        print("\n=== 學生 B 家長（座號 02，不是私密讀者） ===")
        B = Actor(browser, base, "B家長", PARENT_B, C, shots)
        C.ok(B.sign_in(), "B家長｜登入並解析出身分")
        s = B.ev("CMW.getStore().getSession()")
        C.ok(s["state"] == "ready" and not s["roles"]["privateReader"] and s["roles"]["seats"] == ["02"],
             "B家長｜Session：讀者、不是私密讀者、座號 02", s["roles"])
        B.open("blog.html", "紀事列表")
        C.ok(B.ev("!document.querySelector('.entry--private')"), "B家長｜紀事列表沒有任何私密紀事的痕跡")
        B.open("post.html?s=" + D.post, "單篇紀事")
        B.open("private.html?p=" + D.private, "私密紀事")
        C.ok(B.ev("document.body.textContent.indexOf('只給私密名單') >= 0 && document.body.textContent.indexOf('私密紀事的正文') < 0"),
             "B家長｜私密紀事頁只說「只給私密名單」")
        C.ok(B.store_code("CMW.getStore().query('private.list')") == "denied", "B家長｜規則：查私密紀事被拒")
        B.open("my-child.html", "我的孩子")
        C.ok(B.ev("document.body.textContent.indexOf('B 家長寫的文章') >= 0 && document.body.textContent.indexOf('導師寫給 A') < 0"),
             "B家長｜我的孩子：只看到自己孩子（座號 02）的文章")
        B.open("my-child.html#/entry/02/" + D.e_parent02, "我的孩子單篇")
        C.ok(B.ev("!!document.querySelector('.blog-thread form')"), "B家長｜自己孩子的文章底下有對話串")

        print("\n=== 同仁（座號 03 逐座號閱讀） ===")
        S = Actor(browser, base, "同仁", STAFF, C, shots)
        C.ok(S.sign_in(), "同仁｜登入並解析出身分")
        s = S.ev("CMW.getStore().getSession()")
        C.ok(s["state"] == "ready" and s["roles"]["seats"] == ["03"] and s["roles"]["seatKind"] == "staff",
             "同仁｜Session：座號 03、kind staff", s["roles"])
        S.open("my-child.html", "我的孩子")
        C.ok(S.ev("document.body.textContent.indexOf('導師寫給 C 的文章') >= 0 && !document.querySelector('a[href*=\"new/\"]')"),
             "同仁｜看得到座號 03 的文章、沒有寫文按鈕")
        S.open("my-child.html#/entry/03/" + D.e_teacher03, "我的孩子單篇")
        C.ok(S.ev("!document.querySelector('.blog-thread') && document.body.textContent.indexOf('同仁看不到這一則') < 0"),
             "同仁｜文章頁沒有對話串（連查都不查）")
        C.ok(S.store_code("CMW.getStore().query('blogComments.thread', { entry: 'student_blogs/03/entries/%s' })" % D.e_teacher03) == "denied",
             "同仁｜規則：讀對話串被拒")
        C.ok(S.store_code("CMW.getStore().get('parent_photo_display/01')") == "denied"
             and S.store_code("CMW.getStore().query('seating.all')") == "denied", "同仁｜規則：家長合照、座位表都被拒")

        print("\n=== 名單外的人 ===")
        O = Actor(browser, base, "名單外", OUTSIDER, C, shots)
        C.ok(O.sign_in(), "名單外｜登入（Google）")
        O.open("index.html", "首頁")
        C.ok(O.ev("CMW.getStore().getSession().state === 'denied' && document.body.textContent.indexOf('這個帳號還沒有開通') >= 0"
                  " && document.body.textContent.indexOf('%s') >= 0 && !document.querySelector('.primary-nav')" % OUTSIDER["email"]),
             "名單外｜看到「這個帳號還沒有開通」＋目前的信箱＋登出換帳號，沒有導覽與內容")
        C.ok(O.ev("!!Array.from(document.querySelectorAll('button')).find(b => b.textContent.indexOf('登出，換一個帳號') >= 0)"),
             "名單外｜有「登出，換一個帳號」")
        C.ok(O.store_code("CMW.getStore().query('posts.recent')") == "denied", "名單外｜規則：查紀事被拒")

        print("\n=== 導師：第二輪（家長的動作有沒有出現在導師端） ===")
        T.open("my-child.html#/admin", "我的孩子全班格")
        C.ok(T.ev("document.querySelectorAll('.mc-grid .mc-card').length === 3"), "導師｜全班格 3 格（blogs.all）")
        C.ok(T.ev("!!document.querySelector('.mc-card--new[data-seat=\"01\"]') && !!document.querySelector('.mc-card--new[data-seat=\"02\"]')"),
             "導師｜未讀：座號 01（家長剛發的文）與 02 亮起來（集合群組查詢當場算）")
        C.ok(T.ev("!document.querySelector('.mc-card--new[data-seat=\"03\"]')"), "導師｜座號 03 沒有家長動態，不亮")
        T.open("my-child.html#/seat/01", "座號 01")
        C.ok(T.ev("document.body.textContent.indexOf('冒煙測試：家長發的文') >= 0"
                  " && Array.from(document.querySelectorAll('.mc-identity')).some(x => x.textContent === '學生 A 家長（母）')"),
             "導師｜家長發的文出現在導師端，作者代號對回「學生 A 家長（母）」")
        C.ok(T.wait("!!document.querySelector('.blog-entry-media img[src^=\"data:image/jpeg;base64,\"]')", 15),
             "導師｜家長上傳的照片（縮圖）讀得到")
        T.open("my-child.html#/admin", "我的孩子全班格（看過之後）")
        C.ok(T.ev("!document.querySelector('.mc-card--new[data-seat=\"01\"]')"), "導師｜看過座號 01 之後未讀熄掉")
        if post_id:
            T.open("my-child.html#/entry/01/" + post_id, "家長的文章")
            C.ok(T.ev("document.body.textContent.indexOf('已收起') >= 0"), "導師｜看得到家長收起的那一則（標示已收起）")
            T.ev("(() => { const b = Array.from(document.querySelectorAll('.mc-teacher-tools button')).find(x => x.textContent.indexOf('下架') === 0);"
                 " if (b) b.click(); return !!b; })()")
            C.ok(T.wait("document.querySelector('.mc-teacher-tools .form-msg').textContent.indexOf('已下架') === 0", 15),
                 "導師｜下架家長的文章")
            e2 = read_doc("student_blogs/01/entries/" + post_id)
            C.ok(e2 and e2.get("visible") is False and e2.get("updatedAt"), "導師｜資料庫裡 visible＝false、updatedAt 是伺服器時間", e2)
            errs = T.errors()
            C.ok(not errs, "導師｜下架過程零主控台錯誤", "；".join(errs[:3]))
            C.ok(A.store_code("CMW.getStore().get('student_blogs/01/entries/%s')" % post_id) == "denied",
                 "A家長｜規則：下架之後家長讀不到那一篇")
        T.open("post.html?s=" + D.post, "單篇紀事（已讀）")
        C.ok(T.wait("document.querySelector('.read-panel-summary').textContent.indexOf('已讀 2/2') === 0", 15),
             "導師｜單篇的已讀 2/2（A、B 兩位家長的回條；同仁與導師不算）",
             T.ev("(document.querySelector('.read-panel-summary') || {}).textContent"))
        T.ev("(() => { const c = Array.from(document.querySelectorAll('.comment')).find(x => x.textContent.indexOf('冒煙測試留言') >= 0);"
             " const b = c && Array.from(c.querySelectorAll('button')).find(x => x.textContent === '收起'); if (b) b.click(); return !!b; })()")
        C.ok(T.wait("Array.from(document.querySelectorAll('.comment.is-hidden')).some(x => x.textContent.indexOf('冒煙測試留言') >= 0)", 15),
             "導師｜收起家長的留言（即時更新）")
        hidden = [d for p, d in list_docs("posts/%s/comments" % D.post) if d.get("authorAlias") == PARENT_A["alias"]]
        C.ok(hidden and hidden[0].get("status") == "hidden", "導師｜資料庫裡那則留言是 hidden")
        T.errors()
        T.open("private.html?p=" + D.private, "私密紀事（已讀）")
        C.ok(T.wait("document.querySelector('.read-panel-summary').textContent.indexOf('已讀 1/1') === 0", 15),
             "導師｜私密紀事的已讀 1/1（分母＝私密名單扣掉導師）",
             T.ev("(document.querySelector('.read-panel-summary') || {}).textContent"))
        A.open("post.html?s=" + D.post, "單篇紀事（被收起之後）")
        C.ok(A.ev("!Array.from(document.querySelectorAll('.comment-body')).some(p => p.textContent.indexOf('冒煙測試留言') >= 0)"),
             "A家長｜被導師收起的留言，家長看不到了")
    except cdp.CDPError as e:
        print("✗ 瀏覽器那一端出錯，冒煙測試停在這裡：%s" % e)
        print("  → 多半是 Chrome 被關掉、網頁卡住，或網路斷了（Firebase 程式庫要從 %s 載）。再跑一次看看。" % SDK_HOST)
        return 1
    finally:
        browser.close()
        httpd.shutdown()

    good, n = C.summary()
    print("\n%s %d/%d" % ("PASS" if good == n else "FAIL", good, n))
    for ok, label, detail in C.results:
        if not ok:
            print("  ✗ %s%s" % (label, ("　→ " + str(detail)) if detail else ""))
    if shots:
        print("截圖：%s" % shots)
    return 0 if good == n else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="模擬器冒煙測試：真的 Firebase JS SDK＋真的安全規則＋正式站模式（開發與 CI 用）")
    ap.add_argument("--shots", metavar="目錄", help="每一頁存一張手機寬截圖（預設不存；不要存在 repo 裡）")
    ap.add_argument("--require-chrome", action="store_true", help="找不到 Chrome 算失敗（CI 用）")
    ap.add_argument("--verbose", action="store_true", help="每一項都印出來")
    ap.add_argument("--inner", metavar="MANIFEST", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.inner:
        return run_inner(a.inner)
    return outer(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
