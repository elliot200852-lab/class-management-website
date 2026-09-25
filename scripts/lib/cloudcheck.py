#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cloudcheck.py — `doctor.py --cloud` 與 `deploy.py` 用的雲端唯讀檢查（docs/ARCHITECTURE.md §7.4）。

這些項目**只有真雲端才會壞**（模擬器驗不到）：兩邊登入的帳號、資料庫的地區與模式、登入網域與網址、
Auth 的登入方式、索引有沒有建好、規則是不是本機這份、方案、網站有沒有上線。

  · 全部是讀取（GET），每個請求都帶 x-goog-user-project；**不改任何東西**。
  · 查不到、回 403 時原樣印出伺服器的訊息，並說可能的原因（API 沒啟用、登錯帳號、學校組織政策）。
  · 判斷邏輯（eval_*）都是純函式：單元測試用假的回應餵它，不連網。
    API 的確切網址與回應形狀照官方 REST 參考寫；作者沒有真雲端測試專案，這一層只在老師的專案上跑得到。

每一項：key、label、ok（True／False／None＝無法判斷）、phase（pre＝部署前就要過；post＝部署後才要過；info＝只提醒）、
detail、hints。
"""
import re
import json
import urllib.error
import urllib.request

from . import gauth, paths, hostos
from .emailkey import email_key

FIRESTORE = "https://firestore.googleapis.com/v1"
FIREBASE_MGMT = "https://firebase.googleapis.com/v1beta1"
IDTK = "https://identitytoolkit.googleapis.com/admin/v2"
RULES_API = "https://firebaserules.googleapis.com/v1"
BILLING = "https://cloudbilling.googleapis.com/v1"
FIREBASE_CLI_URL = "https://firebase.google.com/docs/cli"


class Item(object):
    __slots__ = ("key", "label", "ok", "phase", "detail", "hints")

    def __init__(self, key, label, ok, phase, detail="", hints=()):
        self.key, self.label, self.ok, self.phase = key, label, ok, phase
        self.detail, self.hints = detail, list(hints)

    def mark(self):
        return {True: "✓", False: "✗", None: "！"}[self.ok]


# ── 取資料（真的連網的部分）────────────────────────────────────────────

def api_get(client, url):
    """帶管理端權杖＋x-goog-user-project 的 GET。回 (http 狀態或 None, JSON 或 None, 錯誤訊息)。"""
    refreshed = False
    while True:
        status, raw = client.transport("GET", url, client._headers(), None, 60)
        if status == 401 and not refreshed:
            refreshed = True
            client.tokens.refresh()
            continue
        break
    if status is None:
        return None, None, "連不上（%s）" % (raw or b"").decode("utf-8", "replace")
    try:
        j = json.loads((raw or b"{}").decode("utf-8"))
    except ValueError:
        j = None
    if 200 <= status < 300:
        return status, j, ""
    msg = ""
    if isinstance(j, dict):
        msg = (j.get("error") or {}).get("message", "")
    return status, None, msg or (raw or b"")[:300].decode("utf-8", "replace")


def public_get(url, timeout=30):
    """不帶任何身分的 GET（檢查網站本身）。回 (狀態或 None, 標頭 dict（小寫鍵）, 內文字串)。"""
    req = urllib.request.Request(url, headers={"User-Agent": "class-management-website-doctor"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, ""
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, {}, type(e).__name__


def firebase_exe():
    found = hostos.find_exe_all("firebase")
    return found[0][0] if found else None


def firebase_accounts(runner=None):
    """firebase CLI 登入的帳號清單；找不到 CLI 回 None。"""
    import subprocess
    exe = firebase_exe()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "login:list", "--json"], capture_output=True, text=True, timeout=90,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    out = []
    try:
        j = json.loads(r.stdout or "{}")
        for u in j.get("result") or []:
            em = ((u or {}).get("user") or {}).get("email")
            if em:
                out.append(em)
    except ValueError:
        out = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", r.stdout or "")
    return out


# ── 判斷（純函式）────────────────────────────────────────────────────

def _key(e):
    try:
        return email_key(e)
    except (ValueError, TypeError):
        return None


def mask(e):
    if not e or "@" not in e:
        return "（沒有）"
    a, b = e.split("@", 1)
    return "%s***@%s" % (a[:1], b)


def eval_accounts(teacher_email, gcloud_account, firebase_list):
    tk = _key(teacher_email)
    g = _key(gcloud_account) if gcloud_account else None
    hints = []
    if not gcloud_account:
        return Item("accounts", "gcloud 與 firebase 登入同一個帳號（＝導師 email）", False, "pre",
                    "gcloud 沒有登入的帳號", ["請老師跑：gcloud auth login（用開 Firebase 專案、也是導師 email 的那個帳號）"])
    if firebase_list is None:
        return Item("accounts", "gcloud 與 firebase 登入同一個帳號（＝導師 email）", False, "pre",
                    "找不到 Firebase CLI", ["照官方說明自己安裝：%s ，裝完重開終端機，跑 firebase login" % FIREBASE_CLI_URL])
    fks = {_key(x) for x in firebase_list}
    ok = g == tk and tk in fks
    if g != tk:
        hints.append("gcloud 登入的是 %s，不是導師 email（config/class.json 的 teacher.email）：gcloud auth login 換帳號"
                     % mask(gcloud_account))
    if tk not in fks:
        hints.append("firebase CLI 沒有用導師 email 登入：跑 firebase login（已經登入別的帳號就先 firebase logout）")
    detail = "gcloud：%s｜firebase：%s" % (mask(gcloud_account), "、".join(mask(x) for x in firebase_list) or "沒有登入")
    return Item("accounts", "gcloud 與 firebase 登入同一個帳號（＝導師 email）", ok, "pre", detail, hints)


def _denied_hints(status, msg):
    if status == 403:
        return ["伺服器拒絕（403）。可能是：API 沒啟用（訊息裡有啟用網址就按它）、gcloud 登錯帳號、學校組織政策擋住。",
                "伺服器原始訊息：%s" % (msg or "（沒有）")[:300]]
    if status == 404:
        return ["找不到（404）：確認 config/class.json 的 project_id；Firestore 資料庫要先在主控台建立。",
                "伺服器原始訊息：%s" % (msg or "（沒有）")[:300]]
    if status is None:
        return ["連不上 Google：檢查網路。"]
    return ["伺服器回 %s：%s" % (status, (msg or "")[:300])]


def eval_database(status, j, msg, region):
    items = []
    if status != 200 or not isinstance(j, dict):
        items.append(Item("database", "資料庫存在而且讀得到", False, "pre", "HTTP %s" % status, _denied_hints(status, msg)))
        items.append(Item("location", "資料庫地區＝config 的 region、模式是 Native", None, "pre", "讀不到資料庫，無法判斷"))
        return items
    items.append(Item("database", "資料庫存在而且讀得到", True, "pre", "(default)"))
    loc, typ = j.get("locationId", ""), j.get("type", "")
    # 版本（edition）：Standard 才是這個網站測過、Spark 免費額度適用的那一種。舊專案的資料庫沒有這一欄、
    # 或是 DATABASE_EDITION_UNSPECIFIED，都等於 Standard。Enterprise 版的計費與功能不同，這個網站沒測過。
    edition = str(j.get("databaseEdition") or "").upper()
    edition_ok = edition in ("", "STANDARD", "DATABASE_EDITION_UNSPECIFIED")
    ok = loc == region and typ == "FIRESTORE_NATIVE" and edition_ok
    hints = []
    if loc != region:
        hints.append("資料庫建在 %s，但 config/class.json 的 region 是 %s。資料庫的地區建好就不能改："
                     "把 region 改成 %s 就好（v1 只有檢查工具用到這一欄）。" % (loc, region, loc))
    if typ != "FIRESTORE_NATIVE":
        hints.append("資料庫模式是 %s，這個網站要 Native 模式：請在 Firebase 主控台用 Native 模式重新建立。" % (typ or "未知"))
    if not edition_ok:
        hints.append("資料庫是 %s 版，這個網站要 Standard（標準版）：Enterprise 版的計費方式不同、免費額度不適用，"
                     "這個網站也沒在上面測過。資料庫還是空的話，請老師在 Firebase 主控台 → Firestore 刪掉它、"
                     "照 AGENTS.md 步驟 2 第 3 題重建（版本選 Standard）；找不到刪除鈕就開一個新專案重來（空專案沒有損失）。"
                     % edition.capitalize())
    items.append(Item("location", "資料庫地區＝config 的 region、模式是 Native、版本是 Standard", ok, "pre",
                      "地區 %s、模式 %s、版本 %s" % (loc or "?", typ or "?", (edition or "STANDARD").capitalize()), hints))
    return items


def eval_webapp(status, j, msg, cfg):
    label = "登入網域＝網站網址（<專案>.firebaseapp.com）、網頁設定跟 class.json 一樣"
    if not cfg.app_id:
        return Item("webapp", label, False, "pre", "class.json 沒有 firebase.app_id",
                    ["到 Firebase 主控台 → 專案設定 → 你的應用程式 → SDK 設定，把 appId 填進 config/class.json。"])
    if status != 200 or not isinstance(j, dict):
        return Item("webapp", label, False, "pre", "讀不到網頁應用程式設定（HTTP %s）" % status, _denied_hints(status, msg))
    expected = "%s.firebaseapp.com" % cfg.project_id
    site_host = cfg.site_url.replace("https://", "").split("/")[0]
    hints = []
    if j.get("authDomain") != expected:
        hints.append("線上的 authDomain 是 %s，應該是 %s" % (j.get("authDomain"), expected))
    if site_host != expected:
        hints.append("網站網址的主機是 %s，應該是 %s（config/class.json 的 auth_domain 留空）" % (site_host, expected))
    if j.get("apiKey") != cfg.api_key:
        hints.append("config/class.json 的 api_key 跟 Firebase 主控台的不一樣：重新從 SDK 設定複製。")
    if j.get("appId") and j.get("appId") != cfg.app_id:
        hints.append("config/class.json 的 app_id 跟 Firebase 主控台的不一樣。")
    return Item("webapp", label, not hints, "pre", "authDomain %s" % j.get("authDomain"), hints)


def eval_auth(status, j, msg, g_status, g, g_msg, project_id):
    label = "登入方式：Google 已開、電子郵件連結（不用密碼）已開、授權網域有網站網址"
    if status != 200 or not isinstance(j, dict):
        return Item("auth", label, False, "pre", "讀不到 Authentication 設定（HTTP %s）" % status,
                    _denied_hints(status, msg) + ["還沒開過 Authentication 的話：Firebase 主控台 → Authentication → 開始使用。"])
    hints = []
    email = ((j.get("signIn") or {}).get("email") or {})
    if not email.get("enabled"):
        hints.append("電子郵件登入沒開：Authentication → 登入方式 → 電子郵件／密碼 → 啟用，並打開「電子郵件連結（無密碼登入）」。")
    elif email.get("passwordRequired", True):
        hints.append("電子郵件登入要打開「電子郵件連結（無密碼登入）」（現在是要密碼的模式）。")
    domains = j.get("authorizedDomains") or []
    if "%s.firebaseapp.com" % project_id not in domains:
        hints.append("授權網域裡沒有 %s.firebaseapp.com：Authentication → 設定 → 授權網域 → 新增。" % project_id)
    if g_status != 200 or not isinstance(g, dict) or not g.get("enabled"):
        hints.append("Google 登入沒開：Authentication → 登入方式 → Google → 啟用（支援電子郵件選你自己的信箱）。")
    detail = "Google %s｜email 連結 %s" % ("開" if (g or {}).get("enabled") else "沒開",
                                          "開" if email.get("enabled") and not email.get("passwordRequired", True) else "沒開")
    return Item("auth", label, not hints, "pre", detail, hints)


def _norm_index(cg, scope, fields):
    fs = []
    for f in fields or []:
        if f.get("fieldPath") == "__name__":
            continue
        fs.append((f.get("fieldPath"), f.get("order") or ("CONTAINS" if f.get("arrayConfig") else "")))
    return (cg, scope or "COLLECTION", tuple(fs))


def _cg_of(name, kind):
    m = re.search(r"/collectionGroups/([^/]+)/%s/(.+)$" % kind, name or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def index_status(local, remote_indexes, remote_fields):
    """回 {'missing': [...], 'building': [...], 'bad': [...], 'extra': [...]}（都是人看得懂的字串）。"""
    out = {"missing": [], "building": [], "bad": [], "extra": []}
    rem = {}
    for r in remote_indexes or []:
        cg, _ = _cg_of(r.get("name"), "indexes")
        rem[_norm_index(cg, r.get("queryScope"), r.get("fields"))] = r.get("state", "")
    want = set()
    for i in local.get("indexes", []):
        k = _norm_index(i.get("collectionGroup"), i.get("queryScope"), i.get("fields"))
        want.add(k)
        label = "%s（%s）" % (k[0], "、".join("%s %s" % f for f in k[2]))
        st = rem.get(k)
        if st is None:
            out["missing"].append(label)
        elif st == "CREATING":
            out["building"].append(label)
        elif st != "READY":
            out["bad"].append("%s：%s" % (label, st))
    for k in rem:
        if k not in want:
            out["extra"].append("%s（%s）" % (k[0], "、".join("%s %s" % f for f in k[2])))
    fields = {}
    for f in remote_fields or []:
        cg, fp = _cg_of(f.get("name"), "fields")
        if cg:
            fields[(cg, fp)] = (f.get("indexConfig") or {}).get("indexes") or []
    for fo in local.get("fieldOverrides", []):
        k = (fo.get("collectionGroup"), fo.get("fieldPath"))
        label = "欄位設定 %s.%s" % k
        if k not in fields:
            out["missing"].append(label)
            continue
        got = fields[k]
        want_set = {(x.get("queryScope"), x.get("order") or x.get("arrayConfig")) for x in fo.get("indexes", [])}
        got_set = {(x.get("queryScope"), x.get("order") or x.get("arrayConfig")) for x in got}
        if want_set != got_set:
            out["missing"].append(label)
        elif any(x.get("state") == "CREATING" for x in got):
            out["building"].append(label)
        elif any(x.get("state") not in (None, "READY") for x in got):
            out["bad"].append("%s：%s" % (label, ",".join(sorted({x.get("state", "") for x in got}))))
    return out


def eval_indexes(local, remote_indexes, remote_fields, err=None):
    label = "索引已部署而且都建好了（READY）"
    if err:
        return Item("indexes", label, None, "post", "讀不到索引清單", err)
    st = index_status(local, remote_indexes, remote_fields)
    hints = []
    if st["missing"]:
        hints.append("還沒部署（%d）：%s → 跑 deploy.py" % (len(st["missing"]), "；".join(st["missing"][:5])))
    if st["building"]:
        hints.append("還在建（%d）：等幾分鐘再看" % len(st["building"]))
    if st["bad"]:
        hints.append("狀態不正常：%s → 到 Firebase 主控台 → Firestore → 索引 看錯誤" % "；".join(st["bad"][:5]))
    if st["extra"]:
        hints.append("線上多了 %d 個本機沒有的索引（不影響網站；部署時不會刪，也不要加 --force）" % len(st["extra"]))
    ok = not (st["missing"] or st["building"] or st["bad"])
    return Item("indexes", label, ok, "post", "本機 %d 個複合索引、%d 個欄位設定"
                % (len(local.get("indexes", [])), len(local.get("fieldOverrides", []))), hints)


def _norm_rules(s):
    return "\n".join(line.rstrip() for line in (s or "").replace("\r\n", "\n").strip().split("\n"))


def eval_rules(local_text, remote_text, err=None):
    label = "線上的安全規則＝本機產生的 firestore.rules"
    if local_text is None:
        return Item("rules", label, None, "post", "本機還沒有 firestore.rules", ["先跑 build_config.py"])
    if err:
        return Item("rules", label, None, "post", "讀不到線上的規則", err)
    if remote_text is None:
        return Item("rules", label, False, "post", "線上還沒有規則", ["跑 deploy.py 部署"])
    ok = _norm_rules(local_text) == _norm_rules(remote_text)
    return Item("rules", label, ok, "post", "一致" if ok else "不一樣",
                [] if ok else ["本機改過設定還沒部署：跑 deploy.py（或 deploy.py --only rules）"])


def eval_billing(status, j, msg):
    label = "專案方案"
    if status != 200 or not isinstance(j, dict):
        return Item("billing", label, None, "info", "無法判斷（HTTP %s）" % status,
                    ["讀不到帳單資訊不算失敗：可能是 Cloud Billing API 沒開。Firebase 主控台左下角看得到方案名稱。"])
    if j.get("billingEnabled"):
        return Item("billing", label, True, "info", "Blaze（隨用隨付）",
                    ["記得在 Google Cloud 主控台 → 帳單 → 預算與快訊 設一個預算警示（警示只通知、不會封頂）。"])
    return Item("billing", label, True, "info", "Spark（免費）",
                ["Spark 的 email 連結登入信全專案每天只有 5 封；家長以 Google 帳號登入為主。"])


def eval_site(site_url, project_id, robots, config_js):
    label = "網站上線（robots.txt 200、不被搜尋引擎收錄、設定檔是這個專案）"
    rs, rh, _ = robots
    cs, _, ctext = config_js
    hints = []
    if rs != 200:
        hints.append("%s/robots.txt 回 %s：網站還沒部署或網址不對" % (site_url, rs))
    elif "noindex" not in (rh.get("x-robots-tag") or ""):
        hints.append("回應沒有 X-Robots-Tag: noindex：firebase.json 的標頭沒部署到")
    if cs != 200:
        hints.append("%s/js/site-config.js 回 %s" % (site_url, cs))
    elif ('"%s"' % project_id) not in (ctext or ""):
        hints.append("線上的 site-config.js 不是這個專案的設定：重跑 build_config.py 再部署網站")
    return Item("site", label, not hints, "post", site_url, hints)


# ── 全部跑一次 ─────────────────────────────────────────────────────────

def local_indexes():
    p = paths.pkg_path("firestore.indexes.json")
    return json.loads(p.read_text(encoding="utf-8"))


def local_rules():
    p = paths.rpath("firestore.rules")
    return p.read_text(encoding="utf-8") if p.exists() else None


def run(cfg, client, phases=("pre", "post", "info"), include_site=True, include_access=True):
    items = []
    p = cfg.project_id
    if "pre" in phases:
        items.append(eval_accounts(cfg.teacher_email, gauth.active_account(), firebase_accounts()))
        s, j, m = api_get(client, "%s/projects/%s/databases/(default)" % (FIRESTORE, p))
        items += eval_database(s, j, m, cfg.region)
        if cfg.app_id:
            s, j, m = api_get(client, "%s/projects/%s/webApps/%s/config" % (FIREBASE_MGMT, p, cfg.app_id))
        else:
            s, j, m = None, None, ""
        items.append(eval_webapp(s, j, m, cfg))
        s, j, m = api_get(client, "%s/projects/%s/config" % (IDTK, p))
        gs, g, gm = api_get(client, "%s/projects/%s/defaultSupportedIdpConfigs/google.com" % (IDTK, p))
        items.append(eval_auth(s, j, m, gs, g, gm, p))
    if "post" in phases:
        try:
            items.append(eval_indexes(local_indexes(), client.list_indexes(), client.list_field_overrides()))
        except Exception as e:  # FirestoreError 或網路問題：原樣說明，不當成通過
            items.append(eval_indexes({}, [], [], err=[getattr(e, "plain", lambda: str(e))()]))
        s, j, m = api_get(client, "%s/projects/%s/releases/cloud.firestore" % (RULES_API, p))
        if s == 200 and isinstance(j, dict) and j.get("rulesetName"):
            s2, j2, m2 = api_get(client, "%s/%s" % (RULES_API, j["rulesetName"]))
            files = ((j2 or {}).get("source") or {}).get("files") or []
            remote = files[0].get("content") if files else None
            items.append(eval_rules(local_rules(), remote, None if s2 == 200 else _denied_hints(s2, m2)))
        elif s == 404:
            items.append(eval_rules(local_rules(), None))
        else:
            items.append(eval_rules(local_rules(), None, _denied_hints(s, m)))
        if include_site and cfg.site_url:
            items.append(eval_site(cfg.site_url, p, public_get(cfg.site_url + "/robots.txt"),
                                   public_get(cfg.site_url + "/js/site-config.js")))
        if include_access:
            items.append(access_item(cfg, client))
    if "info" in phases:
        s, j, m = api_get(client, "%s/projects/%s/billingInfo" % (BILLING, p))
        items.append(eval_billing(s, j, m))
    return items


def access_item(cfg, client):
    import access_sync  # scripts/ 已在 sys.path（doctor.py、deploy.py 都從 scripts/ 跑）
    label = "名單包含關係（導師在兩份名單、私密讀者與座號對應都在班網名單裡）"
    try:
        cur = access_sync.read_current(client)
    except Exception as e:
        return Item("access", label, None, "post", "讀不到名單", [getattr(e, "plain", lambda: str(e))()])
    probs = access_sync.inclusion_problems(cur, cfg.teacher_key)
    return Item("access", label, not probs, "post", "班網讀者 %d 人" % len(cur["allow"]),
                probs + (["跑 access_sync.py（先預覽，再 --apply）"] if probs else []))


def print_items(items):
    names = {"pre": "部署前就要過", "post": "部署後要過", "info": "提醒"}
    for it in items:
        print("%s %s — %s%s" % (it.mark(), it.label, it.detail, "" if it.ok is not False else "（%s）" % names[it.phase]))
        for h in it.hints:
            print("   → %s" % h)
