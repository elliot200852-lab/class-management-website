#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notify_setup.py — v1.1 選配通知信模組的安裝檢查表：一項一項看裝到哪裡，印出「下一步」。**只看不改**。

通知信模組是選配：裝了才有「新留言寄信給導師」「導師發文 30 分鐘後寄給那個孩子的家長」「每日摘要」。
它要把程式（Cloud Functions）部署到老師自己的 Firebase 專案，所以一定要 **Blaze（隨用隨付）方案**。
一個班的用量通常落在免費額度內，但 Blaze 要綁信用卡、預算警示只會寄信不會封頂——這些要照實跟老師說（playbooks/notify.md）。

檢查表（照順序；第一個沒過的就是下一步）：
  本機（不連網）
    1. config/class.json 的 notifications.enabled 是 true（老師同意裝了，代理才改）
    2. notifications 其他欄位合法（寄件人名稱、署名、寄件 Gmail、時區、摘要時間）
    3. functions/cmw.generated.json 是這個專案的（build_config.py 產生）
    4. functions/ 的套件裝好了（老師自己在終端機打一行 npm ci；版本照 package-lock.json 釘死）
    5. 找得到 Firebase CLI
  雲端（加 --cloud；全部是讀取，不改任何東西）
    6. 專案是 Blaze
    7. Secret Manager 裡有 Gmail 應用程式密碼（CMW_GMAIL_APP_PASSWORD；只看「有沒有」，**不讀密碼本身**）
    8. 七支 Functions 都部署在 region（跟資料庫同一區）
    9. 映像檔清理政策設好了（Artifact Registry 的 gcf-artifacts 倉庫）
   10. config/notify 建了、排程有心跳（ops/notify_status）、每日摘要有心跳（ops/digest_status）

用法（Windows 把 python3 換成 py -3）：
  python3 scripts/notify_setup.py            本機那幾項
  python3 scripts/notify_setup.py --cloud    再加雲端那幾項
部署本身只走 deploy.py（python3 scripts/deploy.py --only functions --yes）；開關只走 notify_config.py。
"""
import sys
import argparse
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, cloudcheck, gauth, hostos, notify  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib.hostos import PY  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

SECRETS_API = "https://secretmanager.googleapis.com/v1"
FUNCTIONS_API = "https://cloudfunctions.googleapis.com/v2"
ARTIFACTS_API = "https://artifactregistry.googleapis.com/v1"
BLAZE_URL = "https://firebase.google.com/docs/projects/billing/firebase-pricing-plans"
APP_PASSWORD_URL = "https://support.google.com/accounts/answer/185833"


def item(ok, label, todo=""):
    return {"ok": ok, "label": label, "todo": todo}


# ── 本機 ────────────────────────────────────────────────────────────────────

def local_items(cfg):
    raw = cfg.raw
    out = []
    en = notify.enabled(raw)
    out.append(item(en, "config/class.json 的 notifications.enabled 是 true",
                    "老師看過 playbooks/notify.md 第 0 節（要 Blaze、費用、寄件帳號）並同意裝之後，代理把 notifications.enabled 改成 true，"
                    "再跑 %s scripts/build_config.py。" % PY))
    probs = notify.validate(raw)
    out.append(item(not probs, "notifications 的其他欄位合法",
                    "；".join("%s → %s" % (m, f) for m, f in probs)))
    gen = notify.read_generated()
    gen_ok = bool(gen) and gen.get("projectId") == cfg.project_id and gen.get("region") == cfg.region \
        and gen.get("timeZone") == notify.time_zone(raw) and gen.get("digestHour") == notify.digest_hour(raw)
    out.append(item(gen_ok, "functions/cmw.generated.json 是這個專案、這份設定的",
                    "跑 %s scripts/build_config.py（會重新產生；不要手寫）。" % PY))
    out.append(item(notify.installed_ok(), "functions/ 的套件裝好了（firebase-functions、firebase-admin、nodemailer）",
                    "請老師在他自己的終端機打這一行（代理不跑安裝指令）：%s ，看到 added … packages 就好。"
                    % notify.npm_ci_command()))
    fb = hostos.find_exe_all("firebase")
    out.append(item(bool(fb), "找得到 Firebase CLI", "照 AGENTS.md 步驟 1-4 請老師自己安裝。"))
    return out


# ── 雲端（唯讀）─────────────────────────────────────────────────────────────

def eval_secret(status, j):
    label = "Secret Manager 裡有 Gmail 應用程式密碼（%s；只看有沒有，不讀內容）" % notify.SECRET_NAME
    todo = ("請老師自己在他的終端機打：firebase functions:secrets:set %s --project <專案 ID> ，"
            "畫面問值的時候貼上 16 個字母的應用程式密碼（打字時畫面不會顯示）。**不要貼給 AI 代理**。"
            "密碼怎麼產生：playbooks/notify.md 第 2 節。" % notify.SECRET_NAME)
    if status == 404:
        return item(False, label, todo)
    if status != 200 or not isinstance(j, dict):
        return item(None, label, "讀不到（HTTP %s）：Secret Manager API 可能還沒啟用（第一次部署時會自動啟用），或登錯帳號。" % status)
    versions = [v for v in (j.get("versions") or []) if v.get("state") == "ENABLED"]
    return item(bool(versions), label, "" if versions else todo)


def eval_functions(status, j, region):
    label = "七支 Functions 都部署在 %s（跟資料庫同一區）" % region
    if status != 200 or not isinstance(j, dict):
        return item(None if status != 404 else False, label,
                    "讀不到 Functions 清單（HTTP %s）：還沒部署過的話跑 %s scripts/deploy.py --only functions --yes。" % (status, PY))
    have = {str(f.get("name", "")).rsplit("/", 1)[-1].lower() for f in (j.get("functions") or [])}
    missing = [n for n in notify.FUNCTION_IDS if n.lower() not in have]
    return item(not missing, label, ("還沒部署：%s → 跑 %s scripts/deploy.py --only functions --yes。"
                                     % ("、".join(missing), PY)) if missing else "")


def eval_cleanup(status, j):
    label = "映像檔清理政策設好了（舊的程式映像檔會自動刪，不會一直累積費用）"
    todo = "跑 %s scripts/deploy.py --only functions --yes（它會補設，不加 --force）。" % PY
    if status == 404:
        return item(False, label, "還沒部署過 Functions：" + todo)
    if status != 200 or not isinstance(j, dict):
        return item(None, label, "讀不到（HTTP %s）。" % status)
    return item(bool(j.get("cleanupPolicies")), label, "" if j.get("cleanupPolicies") else todo)


def eval_heartbeats(cfg_doc, notify_doc, digest_doc, now):
    out = []
    if not cfg_doc:
        out.append(item(False, "config/notify 建好了", "跑 %s scripts/notify_config.py --phase dryrun（預覽）→ 老師點頭 → 加 --apply。" % PY))
        return out
    phase = cfg_doc.get("phase")
    out.append(item(True, "config/notify 建好了（階段 %s）" % phase))
    if phase in ("dryrun", "live") and cfg_doc.get("parentMail", True):
        t = _parse(notify_doc.get("lastRunAt"))
        fresh = t is not None and (now - t).total_seconds() <= notify.SWEEP_STALE_MINUTES * 60
        out.append(item(fresh, "家長通知排程在動（60 分鐘內跑過）",
                        "部署完要等 10 分鐘；超過一小時還沒有，看 Firebase 主控台 → Functions → cmwNotifySweep 的紀錄。"))
    if phase in ("dryrun", "live") and cfg_doc.get("digest", True):
        t = _parse(digest_doc.get("lastRunAt"))
        fresh = t is not None and (now - t).total_seconds() <= 26 * 3600
        out.append(item(fresh or None, "每日摘要一天內跑過", "剛打開的話等到明天摘要時間再看（沒事的日子不寄信，但這裡會有紀錄）。"))
    return out


def _parse(v):
    if not v:
        return None
    try:
        return datetime.datetime.strptime(str(v)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def cloud_items(cfg, client):
    out = []
    s, j, m = cloudcheck.api_get(client, "%s/projects/%s/billingInfo" % (cloudcheck.BILLING, cfg.project_id))
    blaze = bool(isinstance(j, dict) and j.get("billingEnabled")) if s == 200 else None
    out.append(item(blaze, "專案是 Blaze（隨用隨付）方案",
                    "照 AGENTS.md「免費方案的額度與升級」升 Blaze，**馬上設預算警示**（警示只寄信、不會封頂）。說明：%s" % BLAZE_URL))
    s, j, m = cloudcheck.api_get(client, "%s/projects/%s/secrets/%s/versions?filter=state:ENABLED"
                                 % (SECRETS_API, cfg.project_id, notify.SECRET_NAME))
    out.append(eval_secret(s, j))
    s, j, m = cloudcheck.api_get(client, "%s/projects/%s/locations/%s/functions" % (FUNCTIONS_API, cfg.project_id, cfg.region))
    out.append(eval_functions(s, j, cfg.region))
    s, j, m = cloudcheck.api_get(client, "%s/projects/%s/locations/%s/repositories/gcf-artifacts"
                                 % (ARTIFACTS_API, cfg.project_id, cfg.region))
    out.append(eval_cleanup(s, j))
    got = client.batch_get(["config/notify", "ops/notify_status", "ops/digest_status"])
    doc = lambda p: got.get(p).data if got.get(p) else {}  # noqa: E731
    out += eval_heartbeats(doc("config/notify") or None, doc("ops/notify_status"), doc("ops/digest_status"),
                           datetime.datetime.now(datetime.timezone.utc))
    return out


def print_items(items):
    nxt = None
    for it in items:
        mark = {True: "✓", False: "✗", None: "！"}[it["ok"]]
        print("%s %s" % (mark, it["label"]))
        if it["ok"] is not True and it["todo"]:
            print("   → %s" % it["todo"])
            if nxt is None and it["ok"] is False:
                nxt = it
    return nxt


def main(argv=None):
    ap = argparse.ArgumentParser(description="通知信模組（v1.1 選配）的安裝檢查表；只看不改")
    ap.add_argument("--cloud", action="store_true", help="另外查雲端（唯讀）：方案、密碼有沒有放、Functions、清理政策、心跳")
    paths.add_root_arg(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        cfg = classcfg.load()
    except classcfg.ConfigError as e:
        print("✗ %s" % e)
        return 2
    print("=" * 60)
    print("通知信模組（v1.1 選配）安裝檢查表：專案 %s、地區 %s" % (cfg.project_id, cfg.region))
    print("=" * 60)
    items = local_items(cfg)
    if a.cloud:
        try:
            client = fr.make_client(cfg.project_id)
            items += cloud_items(cfg, client)
        except (fr.FirestoreError, gauth.AuthError, ValueError) as e:
            print(getattr(e, "plain", lambda: "✗ %s" % e)())
            return 1
    nxt = print_items(items)
    print("=" * 60)
    if nxt:
        print("下一步：%s" % nxt["todo"])
        return 1
    if not a.cloud:
        print("本機這幾項都好了。部署：%s scripts/deploy.py --only functions --yes（老師點頭後）；部署完跑 --cloud 再看一次。" % PY)
    else:
        print("通知信模組裝好了。開關：%s scripts/notify_config.py（看現況）。" % PY)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
