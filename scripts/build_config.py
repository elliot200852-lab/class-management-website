#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_config.py — 唯一的設定產生器：config/class.json 進，網站設定、.firebaserc 與安全規則出。

  讀：config/class.json（沒有就退回 config/class.example.json，只用來驗形狀）
      templates/manifest.json（樣板 → 輸出路徑的對照表）
      templates/*.tmpl

  產：site/js/site-config.js   window.SITE_CONFIG = {...}（**公開**：部署後任何人都抓得到）
      .firebaserc               repo 根目錄；Firebase CLI 部署要用
      functions/cmw.generated.json  v1.1 選配通知信模組部署時讀的設定（不公開、沒有信箱；沒開模組也照樣產生，用不到而已）
      firestore.rules           安全規則（templates/firestore.rules.tmpl）：導師的 email 鍵只會出現在這裡，
                                不會出現在公開設定檔。規則測試：python3 scripts/test_rules.py

  這幾個輸出檔都被 .gitignore 擋住，而且**永遠由這支腳本產生**——AI 代理不准手寫。
  手寫的話班名、email、Firebase 設定隨便一個打錯，網站就連不上資料庫。

  公開與不公開的分界（docs/ARCHITECTURE.md §7.1）：
    · 公開設定檔只放 PUBLIC_KEYS：Firebase 網頁設定、網站正式網址、班名、頁面開關、分類、版本。
      manifest 裡標 "public": true 的樣板多用任何一個別的欄位，這支就拒跑。
    · 導師 email → 只以 email 鍵（TEACHER_EMAIL_KEY）插進安全規則。
    · 學校名、學生人數、行事曆網址、導師稱呼 → 不經過這支的樣板；由 scripts/publish_site.py（P4）
      寫進資料庫 config/site，登入後網頁才讀得到。
    · 通知信模組（v1.1 選配）→ functions/cmw.generated.json 只放專案、地區、網址、時區、摘要時間、備份門檻，
      **不放任何信箱**；收件與寄件信箱在資料庫 config/notify（scripts/notify_config.py 寫）。

  firestore.indexes.json 不歸這支管：它跟班級設定無關，由 scripts/build_indexes.py 產生並進 git。

用法：
  python3 scripts/build_config.py                 # 產生設定
  python3 scripts/build_config.py --check          # 只檢查設定合不合法，不寫任何檔
  python3 scripts/build_config.py --allow-placeholders   # 範本值降成提醒（測試／示範用）
  python3 scripts/build_config.py --root DIR        # 指定資料根目錄（測試用）
  python3 scripts/build_config.py --root DIR --emulator
      # 模擬器用（冒煙測試 scripts/smoke_emulator.py、先試玩 scripts/try_emulator.py）：專案 id 換成 demo- 開頭、網站設定加 emulator: true
      # （前端改連本機的 Auth／Firestore 模擬器）。一定要搭 --root 指到暫存資料夾，不准寫進這份 repo。

設定裡還留著範本值（teacher@example.com、your-project-id、還沒填的 apiKey……）時，
這支**直接 exit 1**——產得出檔卻連不上你的資料庫、規則鎖的是別人的信箱，那不算裝好了。
"""
import re
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths
from lib.console import setup_utf8
# 嚴格的信箱字元集與 email 鍵正規化只有一份正本（lib/emailkey.py）。**不要在這裡另寫一個**：
# 導師的 email 鍵會被插進安全規則的字串字面值裡，寬鬆的 pattern 會讓「是不是老師本人」的
# 條件可能被改寫成恆真。
from lib.emailkey import EMAIL_RE, email_key
from lib import notify
from lib.drivetree import school_year_problems

setup_utf8()

# Google Cloud／Firebase 專案 ID 的合法格式：小寫英文字母開頭，其餘小寫英數字與 -，6–30 字。
PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{5,29}$")

# Firestore 資料庫常見地區（regional，不是 multi-region）。v1 只有 Firestore 用得到這一欄
# （doctor.py --cloud 比對資料庫實際地區）；v1.1 的選配通知信模組也部署在同一區。
# 這份清單是依 2026 年初的認知整理，不保證跟 Firebase 官方清單逐字一致；
# 真的要用不在清單裡的地區，到 Firebase Console 確認後直接把它加進來即可。
REGION_WHITELIST = {
    "asia-east1", "asia-east2", "asia-northeast1", "asia-northeast2", "asia-northeast3",
    "asia-south1", "asia-south2", "asia-southeast1", "asia-southeast2",
    "australia-southeast1", "australia-southeast2",
    "europe-central2", "europe-north1", "europe-southwest1",
    "europe-west1", "europe-west2", "europe-west3", "europe-west4", "europe-west6",
    "europe-west8", "europe-west9", "europe-west12",
    "me-central1", "me-west1",
    "northamerica-northeast1", "northamerica-northeast2",
    "southamerica-east1", "southamerica-west1",
    "us-central1", "us-east1", "us-east4", "us-east5", "us-south1",
    "us-west1", "us-west2", "us-west3", "us-west4",
}

PLACEHOLDER_EXACT = {"your-project-id", "teacher@example.com"}
PLACEHOLDER_MIN_STUDENTS, PLACEHOLDER_MAX_STUDENTS = 1, 40

# 公開設定檔（manifest 標 "public": true 的樣板）只准用這幾個欄位。
# 要加欄位之前先想：這個值被全世界看到可以嗎？不行就放進資料庫 config/site（登入後才讀得到）。
PUBLIC_KEYS = frozenset({
    "CLASS_NAME", "SITE_URL", "VERSION",
    "FIREBASE_PROJECT_ID", "FIREBASE_API_KEY", "FIREBASE_AUTH_DOMAIN",
    "FIREBASE_APP_ID", "FIREBASE_MESSAGING_SENDER_ID",
    "PAGES", "CATEGORIES",
    "EMULATOR",
})

# --emulator：模擬器用的專案 id 一律 demo- 開頭（Firebase 保證 demo- 專案只連本機模擬器、碰不到任何真的雲端資源）
EMULATOR_PROJECT_ID = "demo-cmw"

# Google 日曆「私人網址（iCal 格式）」的路徑長這樣：.../ical/<日曆>/private-<金鑰>/basic.ics。
# 拿到這個網址的人不用登入就能看到整本日曆（含私人行程），而且這個欄位會被寫進資料庫給全班讀者看，
# 所以一律拒收；公開網址是 .../public/basic.ics。
PRIVATE_ICAL_RE = re.compile(r"/private-[^/]*/", re.IGNORECASE)


def is_placeholder(value):
    """這個字串是不是還沒被換成真的值（範本值、空白、「請填入」開頭、「your-」開頭）。"""
    v = (value or "").strip()
    if not v:
        return True
    if v in PLACEHOLDER_EXACT:
        return True
    if v.startswith("your-"):
        return True
    if "請填入" in v:
        return True
    return False


def _load_json(path):
    # utf-8-sig：Windows 記事本（與部分編輯器）存 UTF-8 時會在檔頭加 BOM；照 utf-8 讀會變成「不是合法的 JSON」。
    # 與 scripts/lib/classcfg.py、status.py 的讀法一致（沒有 BOM 的檔讀起來完全一樣）。
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        print("✗ 找不到設定檔：%s" % path)
        print("  → 從 config/class.example.json 複製一份改名成 config/class.json，"
              "照 config/README.md 逐欄填。")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print("✗ %s 不是合法的 JSON（第 %d 行第 %d 欄：%s）" % (path, e.lineno, e.colno, e.msg))
        print("  → 看上面說的那一行附近：有沒有漏逗號、少括號、最後一項後面多了一個逗號；"
              "引號要用直的英文引號 \"，不能是中文輸入法的彎引號「“」「”」（Word、備忘錄、LINE 複製過來常會變成彎的）。")
        sys.exit(1)


def _load_config():
    """讀 config/class.json；沒有就退回 config/class.example.json（只用來驗形狀）。
    回傳 (來源說明字串, 設定 dict)。"""
    real = paths.rpath("config", "class.json")
    if real.exists():
        return "config/class.json", _load_json(real)
    example = paths.pkg_path("config", "class.example.json")
    return ("config/class.example.json（找不到 config/class.json，先用範本檔驗形狀）",
            _load_json(example))


def validate(cfg, problems, notes, allow_placeholders=False):
    """檢查設定的形狀。真正的錯誤進 problems（會 exit 1），可以先放著的進 notes。

    範本值預設算錯誤：產得出檔、印一行「下一步」然後 exit 0，會讓老師以為裝好了，
    實際上網頁連不上任何資料庫。測試與示範模式才加 --allow-placeholders 把它降成提醒。
    """
    def ph(msg, fix):
        if allow_placeholders:
            notes.append(msg)
        else:
            problems.append((msg, fix))

    class_name = str(cfg.get("class_name") or "").strip()
    if not class_name:
        problems.append(("class.json 沒有 class_name（班級顯示名稱）",
                          "填班級名稱；不知道要取什麼就先用「我的班級」。"))

    school_name = cfg.get("school_name")
    if school_name is not None and not isinstance(school_name, str):
        problems.append(("school_name 要是文字（可以是空字串）", '寫成 "" 或學校名稱。'))

    teacher = cfg.get("teacher") or {}
    email = str(teacher.get("email") or "").strip().lower()
    if not email:
        problems.append(("class.json 的 teacher.email 是空的", "填你要用來登入的 Google 信箱。"))
    elif not EMAIL_RE.match(email):
        problems.append(("teacher.email 看起來不是信箱：%r" % email,
                          "格式要像 someone@example.com（只能有英數與 . _ % + -，不能有引號或其他符號）。"))
    elif not _email_key_ok(email):
        problems.append(("teacher.email 轉不成 email 鍵",
                          "檢查 @ 前後有沒有打錯（gmail 信箱的 @ 前面不能只有點號）。"))
    elif is_placeholder(email):
        ph("teacher.email 還是範本值（%s）。" % email,
           "換成你要用來登入的 Google 信箱（測試或示範模式才加 --allow-placeholders）。")

    display_name = str(teacher.get("display_name") or "").strip()
    if not display_name:
        problems.append(("teacher.display_name 是空的", "填一個給家長看的稱呼，例如「王老師」。"))

    students = cfg.get("students") or {}
    count = students.get("count")
    if not isinstance(count, int) or isinstance(count, bool):
        problems.append(("students.count 要是整數", "填班上實際的學生人數（1–40）。"))
    elif not (PLACEHOLDER_MIN_STUDENTS <= count <= PLACEHOLDER_MAX_STUDENTS):
        problems.append(("students.count 超出範圍：%r（只能 1–40）" % (count,),
                          "這個框架目前只支援 1–40 人的班級。"))

    region = str(cfg.get("region") or "").strip()
    if not region:
        problems.append(("region 是空的", "不知道要填什麼就用 asia-east1（要跟你建 Firestore 資料庫時選的地區一樣）。"))
    elif region not in REGION_WHITELIST:
        problems.append(("region 不是常見的 Firebase 地區：%r" % region,
                          "填你建 Firestore 資料庫時選的地區（例如 asia-east1）。確定這個地區存在的話，"
                          "可以直接把它加進 scripts/build_config.py 的 REGION_WHITELIST。"))

    fb = cfg.get("firebase") or {}
    project_id = str(fb.get("project_id") or "").strip()
    if not project_id:
        problems.append(("firebase.project_id 是空的", "到 Firebase Console → 專案設定 → 一般，複製「專案 ID」。"))
    elif is_placeholder(project_id):
        ph("firebase.project_id 還是範本值（%s）。" % project_id, "換成你自己 Firebase 專案的 project id。")
    elif not PROJECT_ID_RE.match(project_id):
        problems.append(("firebase.project_id 格式不對：%r" % project_id,
                          "只能是小寫英數字與 -，6–30 字，開頭要是英文字母，例如 my-class-2026。"))

    for key in ("api_key", "app_id"):
        v = str(fb.get(key) if fb.get(key) is not None else "").strip()
        if not v:
            ph("firebase.%s 還沒填。" % key,
               "到 Firebase Console → 專案設定 → 一般 → 你的應用程式 → SDK 設定與配置去複製。")
        elif is_placeholder(v):
            ph("firebase.%s 還是範本值。" % key, "換成 Firebase Console 給你的實際值。")

    msid = fb.get("messaging_sender_id")
    if msid is not None and not isinstance(msid, (str, int)):
        problems.append(("firebase.messaging_sender_id 要是文字或數字（可以留空）",
                          "照 SDK 設定與配置裡的 messagingSenderId 貼；不確定就留空字串。"))

    if "storage_bucket" in fb:
        notes.append("firebase.storage_bucket 不會被用到：v1 不用 Cloud Storage（照片存在資料庫裡）。"
                     "這一欄可以直接刪掉。")

    auth_domain = str(fb.get("auth_domain") or "").strip().lower()
    expected_domain = _default_auth_domain(project_id)
    if auth_domain and is_placeholder(auth_domain):
        ph("firebase.auth_domain 還是範本值。", "留空字串，程式會自動用 <project_id>.firebaseapp.com。")
    elif auth_domain and expected_domain and auth_domain != expected_domain:
        problems.append(("firebase.auth_domain 必須是 %s（網站正式網址與登入網域要同一個）" % expected_domain,
                          "留空字串讓程式自動補；不要填 .web.app 或自訂網域（v1 不支援，"
                          "登入會在部分手機瀏覽器失敗）。"))

    pages = cfg.get("pages")
    if pages is not None and not isinstance(pages, dict):
        problems.append(("pages 要是物件（開關表）", '格式是 {"home": true, "gallery": false, ...}。'))

    categories = cfg.get("categories")
    if categories is not None and not isinstance(categories, list):
        problems.append(("categories 要是清單（陣列）", '格式是 ["班級生活", "學習活動", ...]。'))
    elif not categories:
        notes.append("categories 是空的——班級紀事會沒有分類可選。")

    problems.extend(school_year_problems(cfg.get("school_year")))

    ics = str(cfg.get("calendar_ics_url") or "").strip()
    if ics and not ics.lower().startswith("https://"):
        problems.append(("calendar_ics_url 要是 https:// 開頭的公開日曆網址",
                          "webcal:// 開頭的把前面改成 https://；不用行事曆就留空字串。"))
    elif ics and PRIVATE_ICAL_RE.search(ics):
        problems.append(("calendar_ics_url 是日曆的「私人網址」，不能用",
                          "私人網址不用登入就看得到整本日曆（含私人行程），而且會被全班讀者看到。"
                          "請到 Google 日曆 → 設定 → 你的班級日曆 → 先「公開這個日曆」，"
                          "再複製「iCal 格式的公開網址」（結尾是 /public/basic.ics）；不用就留空字串。"))

    drive = cfg.get("drive") or {}
    sync_root = drive.get("sync_root")
    if sync_root is not None and not isinstance(sync_root, str):
        problems.append(("drive.sync_root 要是文字路徑（可以是空字串）",
                          "填 Google 雲端硬碟桌面版同步夾的路徑；不確定就先留空。"))

    notif = cfg.get("notifications")
    if notif is not None and not isinstance(notif, dict):
        problems.append(("notifications 要是物件", '格式是 {"enabled": false, ...}；不用通知信就寫 {"enabled": false}。'))
    else:
        problems.extend(notify.validate(cfg))
        if notify.enabled(cfg):
            notes.append("通知信模組（v1.1 選配）開著：要 Blaze 方案，照 playbooks/notify.md 裝；"
                         "deploy.py 會多一步部署 Functions，開關在 scripts/notify_config.py。")


def _email_key_ok(email):
    try:
        email_key(email)
        return True
    except ValueError:
        return False


def _default_auth_domain(project_id):
    """網站正式網址與登入網域統一用 <project_id>.firebaseapp.com（docs/ARCHITECTURE.md §3.4）。"""
    return ("%s.firebaseapp.com" % project_id) if project_id else ""


def _read_version():
    try:
        return paths.pkg_root().joinpath("VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def compute_values(cfg, emulator=False):
    """設定 dict → 樣板要代換的原始值（還沒 JSON 編碼）。

    公開樣板只准用 PUBLIC_KEYS；其餘兩個（TEACHER_EMAIL_KEY、REGION）只給不公開的產生檔
    （安全規則、v1.1 Functions 設定）。學校名、學生人數、行事曆網址、導師稱呼刻意**不在這裡**：
    它們不進任何樣板，由 scripts/publish_site.py 直接從 class.json 寫進資料庫 config/site。

    emulator=True（--emulator，只給冒煙測試）：專案 id 不是 demo- 開頭就換成 EMULATOR_PROJECT_ID，
    apiKey／appId 是空的或範本值就換成假值（模擬器不驗），網站設定多一個 emulator: true。
    """
    teacher = cfg.get("teacher") or {}
    fb = dict(cfg.get("firebase") or {})
    if emulator:
        if not str(fb.get("project_id") or "").strip().startswith("demo-"):
            fb["project_id"] = EMULATOR_PROJECT_ID
        for key, fake in (("api_key", "demo-api-key"), ("app_id", "demo-app-id")):
            if is_placeholder(str(fb.get(key) or "")):
                fb[key] = fake
        fb["auth_domain"] = ""
    project_id = str(fb.get("project_id") or "").strip()
    raw_email = str(teacher.get("email") or "").strip()
    try:
        teacher_key = email_key(raw_email)
    except ValueError:
        teacher_key = ""
    auth_domain = str(fb.get("auth_domain") or "").strip().lower() or _default_auth_domain(project_id)
    return {
        # ── 公開（PUBLIC_KEYS）
        "CLASS_NAME": cfg.get("class_name") or "我的班級",
        "SITE_URL": ("https://%s" % auth_domain) if auth_domain else "",
        "VERSION": _read_version(),
        "FIREBASE_PROJECT_ID": project_id,
        "FIREBASE_API_KEY": fb.get("api_key") or "",
        "FIREBASE_AUTH_DOMAIN": auth_domain,
        "FIREBASE_APP_ID": fb.get("app_id") or "",
        "FIREBASE_MESSAGING_SENDER_ID": str(fb.get("messaging_sender_id") or ""),
        "PAGES": cfg.get("pages") or {},
        "CATEGORIES": cfg.get("categories") or [],
        "EMULATOR": bool(emulator),
        # ── 不公開（只給安全規則／v1.1 Functions 設定這類不部署成公開檔的樣板）
        "TEACHER_EMAIL_KEY": teacher_key,
        "REGION": cfg.get("region") or "",
        # v1.1 通知信模組（functions/cmw.generated.json）：時區、摘要時間、備份門檻（lib/thresholds.py）。沒有信箱。
        **notify.functions_values(cfg),
    }


def check_public_templates(manifest, read_template):
    """manifest 裡標 public 的樣板只准用 PUBLIC_KEYS。回傳問題清單 [(樣板名, 多用的欄位清單)]。"""
    bad = []
    for entry in manifest.get("templates", []):
        if not entry.get("public"):
            continue
        text = read_template(entry["src"])
        used = {t[2:-2] for t in _PLACEHOLDER_TOKEN_RE.findall(text)}
        extra = sorted(used - PUBLIC_KEYS)
        if extra:
            bad.append((entry["src"], extra))
    return bad


_PLACEHOLDER_TOKEN_RE = re.compile(r"\{\{[A-Z_]+\}\}")


def render_template(tmpl_text, values_json):
    """把樣板裡的 {{KEY}} 換成 values_json[KEY]（已經是 JSON 編碼過的字面值）。
    代換完還留著沒吃到的 {{...}}，代表樣板用到一個對照表沒有的鍵，直接報錯而不是產出半殘的檔。"""
    out = tmpl_text
    for key, jval in values_json.items():
        out = out.replace("{{%s}}" % key, jval)
    remaining = _PLACEHOLDER_TOKEN_RE.findall(out)
    if remaining:
        raise SystemExit("✗ 樣板裡還有沒被代換到的欄位：%s（樣板或 compute_values() 對不上，回報這個訊息）"
                          % remaining)
    return out


def main():
    ap = argparse.ArgumentParser(
        description="從 config/class.json 產生網站設定（site/js/site-config.js）、.firebaserc 與安全規則（firestore.rules）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="產生的檔：site/js/site-config.js、.firebaserc、firestore.rules（都被 .gitignore 擋住）")
    ap.add_argument("--check", action="store_true", help="只檢查設定合不合法，不寫任何檔")
    ap.add_argument("--allow-placeholders", action="store_true",
                     help="範本值降成提醒，不當成錯誤（測試或示範模式用；正式安裝不要加）")
    ap.add_argument("--emulator", action="store_true",
                     help="模擬器用（冒煙測試、先試玩）：專案 id 換成 demo- 開頭、網站改連本機模擬器（一定要搭 --root 暫存資料夾）")
    paths.add_root_arg(ap)
    a = ap.parse_args()
    paths.apply_root(a)

    if a.emulator:
        # 產生檔的位置就是正式網站的位置（site/js/site-config.js、.firebaserc）：寫進 repo 本身的話，
        # 下一次部署會把「連本機模擬器」的設定送上線。所以只准寫進別的資料夾。
        if paths.root().resolve() == paths.pkg_root().resolve():
            print("✗ --emulator 只給測試用，一定要搭 --root 指到暫存資料夾（不然會蓋掉這份 repo 的正式網站設定）。")
            sys.exit(1)
        a.allow_placeholders = True

    source_label, cfg = _load_config()

    problems, notes = [], []
    validate(cfg, problems, notes, allow_placeholders=a.allow_placeholders)

    if problems:
        print("✗ 設定還不能用（來源：%s）" % source_label)
        for msg, fix in problems:
            print("  ✗ %s" % msg)
            print("    → %s" % fix)
        sys.exit(1)

    if a.check:
        print("✓ 設定檢查通過（來源：%s）" % source_label)
        for n in notes:
            print("  提醒：%s" % n)
        return

    values = compute_values(cfg, emulator=a.emulator)
    values_json = {k: json.dumps(v, ensure_ascii=False) for k, v in values.items()}

    manifest_path = paths.pkg_path("templates", "manifest.json")
    manifest = _load_json(manifest_path)

    def read_template(name):
        tmpl_path = paths.pkg_path("templates", name)
        if not tmpl_path.exists():
            print("✗ 找不到樣板：%s" % tmpl_path)
            sys.exit(1)
        return tmpl_path.read_text(encoding="utf-8")

    leaks = check_public_templates(manifest, read_template)
    if leaks:
        print("✗ 公開樣板用了不准公開的欄位（這些值部署後全世界都抓得到）：")
        for name, extra in leaks:
            print("  ✗ %s：%s" % (name, "、".join(extra)))
        print("  → 把那幾個欄位從樣板拿掉；登入後才需要的值請放進資料庫 config/site"
              "（見 docs/ARCHITECTURE.md §7.1）。")
        sys.exit(1)

    written = []
    for entry in manifest.get("templates", []):
        tmpl_text = read_template(entry["src"])
        rendered = render_template(tmpl_text, values_json)
        out_path = paths.rpath(*entry["dest"].split("/"))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Path.write_text(newline=) 要 Python 3.10+；用 open() 才能支援 3.9
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(rendered)
        written.append(out_path)

    print("✓ 已產生（來源：%s）：" % source_label)
    for p in written:
        try:
            print("  - %s" % p.relative_to(paths.root()))
        except ValueError:
            print("  - %s" % p)
    for n in notes:
        print("提醒：%s" % n)


if __name__ == "__main__":
    main()
