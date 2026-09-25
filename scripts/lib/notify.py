#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notify.py — v1.1 選配通知信模組的 Python 端共用：class.json 的 notifications 欄位、config/notify 的形狀、
Functions 的名字與部署指令。build_config.py、notify_config.py、notify_setup.py、deploy.py 都用這一份。

分工（docs/ARCHITECTURE.md §10）：
  · config/class.json 的 notifications.*   → 只留在老師電腦：要不要裝、寄件名稱與署名、寄件 Gmail、時區、摘要幾點寄
  · functions/cmw.generated.json          → build_config.py 產生（部署時用）：專案、地區、網址、時區、摘要時間、備份門檻。
                                            **裡面沒有任何信箱**
  · 資料庫 config/notify                   → notify_config.py 寫（網頁寫不進去）：階段 off／dryrun／live、三個開關、
                                            通知起始線、收件與寄件信箱、署名。改了不用重新部署
Gmail 應用程式密碼只在 Google 的 Secret Manager（老師自己在終端機貼），這台電腦與 AI 代理都不經手。
"""
import re

from .emailkey import EMAIL_RE, email_key

PHASES = ("off", "dryrun", "live")
SECRET_NAME = "CMW_GMAIL_APP_PASSWORD"
FUNCTION_IDS = ("cmwCommentPost", "cmwCommentAlbum", "cmwCommentPrivate", "cmwBlogEntry", "cmwBlogComment",
                "cmwNotifySweep", "cmwDailyDigest")
TOGGLES = {"teacher-mail": "teacherMail", "parent-mail": "parentMail", "digest": "digest"}
DEFAULT_TZ = "Asia/Taipei"
DEFAULT_DIGEST_HOUR = 7
SWEEP_STALE_MINUTES = 60          # 與 functions/lib/pure.js 的 SWEEP_STALE_MS 一致：排程每 10 分鐘一輪
TZ_RE = re.compile(r"^[A-Za-z_]+(/[A-Za-z0-9_+-]+)*$")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")

GENERATED_REL = ("functions", "cmw.generated.json")


def section(raw):
    n = (raw or {}).get("notifications")
    return n if isinstance(n, dict) else {}


def enabled(raw):
    return section(raw).get("enabled") is True


def time_zone(raw):
    return str(section(raw).get("time_zone") or "").strip() or DEFAULT_TZ


def digest_hour(raw):
    h = section(raw).get("digest_hour")
    return DEFAULT_DIGEST_HOUR if h is None or h == "" else h


def validate(raw):
    """class.json 的 notifications 欄位。回 [(問題, 怎麼修)]（空清單＝沒問題）。欄位全部選填。"""
    n = section(raw)
    out = []
    if "enabled" in n and not isinstance(n.get("enabled"), bool):
        out.append(("notifications.enabled 要是 true 或 false", "不知道要不要開通知信就先填 false。"))
    for key, mx, what in (("sender_name", 40, "寄件人名稱"), ("signature", 300, "信尾署名")):
        v = n.get(key)
        if v is None:
            continue
        if not isinstance(v, str):
            out.append(("notifications.%s 要是文字" % key, "填%s，或留空字串 \"\"（用預設）。" % what))
        elif len(v) > mx:
            out.append(("notifications.%s 太長（最多 %d 字）" % (key, mx), "縮短一點。"))
        elif key == "sender_name" and _CTRL_RE.search(v):
            out.append(("notifications.sender_name 不能換行或有控制字元", "寫成一行。"))
    g = n.get("gmail_address")
    if g not in (None, ""):
        if not isinstance(g, str) or not EMAIL_RE.match(g.strip()):
            out.append(("notifications.gmail_address 看起來不是信箱", "填寄通知信用的 Gmail（就是放應用程式密碼的那個帳號），或留空（用 teacher.email）。"))
    tz = n.get("time_zone")
    if tz not in (None, "") and (not isinstance(tz, str) or not TZ_RE.match(tz.strip()) or len(tz) > 64):
        out.append(("notifications.time_zone 格式不對", "填時區名稱，例如 Asia/Taipei；不確定就留空。"))
    h = n.get("digest_hour")
    if h not in (None, "") and (not isinstance(h, int) or isinstance(h, bool) or not 0 <= h <= 23):
        out.append(("notifications.digest_hour 要是 0–23 的整數", "每日摘要幾點寄，例如 7（早上 7 點）。"))
    return out


def identity(raw):
    """config/notify 裡跟「誰寄、寄給誰、怎麼署名」有關的欄位（從 class.json 算出來；notify_config.py 寫進資料庫）。"""
    raw = raw or {}
    n = section(raw)
    teacher = raw.get("teacher") or {}
    t_email = str(teacher.get("email") or "").strip()
    from_email = str(n.get("gmail_address") or "").strip() or t_email
    display = str(teacher.get("display_name") or "").strip() or "老師"
    class_name = str(raw.get("class_name") or "").strip() or "我的班級"
    sender = _CTRL_RE.sub(" ", str(n.get("sender_name") or "").strip()) or ("%s（%s）" % (display, class_name))
    signature = str(n.get("signature") or "").strip() or ("%s %s" % (class_name, display))
    return {
        "teacherEmail": t_email,
        "teacherKey": email_key(t_email),
        "fromEmail": from_email,
        "senderName": sender[:40],
        "signature": signature[:300],
        "className": class_name[:40],
    }


def functions_values(raw):
    """functions/cmw.generated.json 用的非公開值（build_config.py 的樣板 functions-config.json.tmpl）。沒有任何信箱。"""
    from .thresholds import BACKUP_REMIND_DAYS, BACKUP_URGENT_DAYS
    return {
        "NOTIFY_TIME_ZONE": time_zone(raw),
        "NOTIFY_DIGEST_HOUR": digest_hour(raw) if isinstance(digest_hour(raw), int) else DEFAULT_DIGEST_HOUR,
        "BACKUP_REMIND_DAYS": BACKUP_REMIND_DAYS,
        "BACKUP_URGENT_DAYS": BACKUP_URGENT_DAYS,
    }


def mask(e):
    if not e or "@" not in e:
        return "（沒有）"
    a, b = e.split("@", 1)
    return "%s***@%s" % (a[:1], b)


# ── 部署指令（deploy.py 的 functions 那一步用）：**任何一條都不准帶 --force** ─────────────

def _no_force(argv):
    if "--force" in argv or "-f" in argv:
        raise RuntimeError("通知信模組的指令不准帶 --force")
    return argv


def deploy_argv(firebase, project_id):
    return _no_force([firebase, "deploy", "--only", "functions", "--project", project_id, "--non-interactive"])


def setpolicy_argv(firebase, project_id, region):
    """Functions 的容器映像檔清理政策（預設留 1 天）。非互動模式下它的確認題預設「是」，所以不需要 --force。
    第一次部署前 Artifact Registry 的倉庫還不存在，這條只會印「先部署」然後 exit 0。"""
    return _no_force([firebase, "functions:artifacts:setpolicy", "--location", region, "--project", project_id,
                      "--non-interactive"])


CLEANUP_POLICY_MISSING = "could not set up cleanup policy"

DEPLOY_HINTS = (
    (("secret", "cmw_gmail_app_password"),
     "Gmail 應用程式密碼還沒放進 Secret Manager（或名稱不對）：照 playbooks/notify.md 第 4 步，請老師自己在他的終端機跑 "
     "firebase functions:secrets:set %s（AI 代理不經手密碼），再重跑這一步。" % SECRET_NAME),
    (("eventarc", "service agent", "may take a few minutes", "propagat"),
     "第一次部署時 Google 要幾分鐘開好內部權限：等 5 分鐘，再跑 deploy.py --only functions --yes（重跑是安全的）。"),
    (("found in your project but do not exist", "would you like to proceed with deletion", "deletion"),
     "線上有這份程式碼裡沒有的 Functions（可能是別的工具部署的）：部署不會刪它們，也**不要加 --force**。"
     "請老師到 Firebase 主控台 → Functions 看是哪幾支，確定不要了再自己在主控台刪。"),
    (("blaze", "billing account", "billing is not enabled", "pay-as-you-go"),
     "通知信模組要 Blaze（隨用隨付）方案：照 AGENTS.md「免費方案的額度與升級」一節升級並設預算警示，再重跑。"),
    (("cannot find module", "npm ci", "node_modules"),
     "functions 資料夾的套件還沒裝：照 notify_setup.py 印的那一行，請老師自己在終端機跑一次，再重跑。"),
)


def deploy_hint(lines):
    text = "\n".join(lines).lower()
    for keys, hint in DEPLOY_HINTS:
        if any(k in text for k in keys):
            return hint
    return None


# ── 本機準備好了沒（deploy.py 的 functions 那一步、notify_setup.py 都用）──────────────────

def functions_dir():
    from . import paths
    return paths.pkg_path("functions")


def npm_ci_command():
    """老師**自己**在終端機打的那一行（鐵則 10：代理不跑任何安裝指令）。版本照 functions/package-lock.json 釘死。"""
    return 'npm ci --prefix "%s"' % functions_dir()


def installed_ok():
    """functions/node_modules 裝好了沒（只看官方的三個套件在不在）。"""
    d = functions_dir() / "node_modules"
    return all((d / name / "package.json").is_file() for name in ("firebase-functions", "firebase-admin", "nodemailer"))


def read_generated():
    import json
    from . import paths
    p = paths.rpath(*GENERATED_REL)
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def functions_not_ready(project_id):
    """部署 Functions 之前本機要先好的兩件事。回白話原因（字串），都好了回 None。"""
    from .hostos import PY
    if not installed_ok():
        return ("functions 資料夾的套件還沒裝。請老師在他自己的終端機打這一行（版本照 package-lock.json 釘死，"
                "官方的 Firebase 套件＋寄信用的 nodemailer）：%s ，看到 added … packages 再跑 deploy.py --only functions --yes。"
                % npm_ci_command())
    gen = read_generated()
    if not gen or gen.get("projectId") != project_id:
        return "functions/cmw.generated.json 不在或不是這個專案的：先跑 %s scripts/deploy.py --only build --yes（會重新產生）。" % PY
    return None
