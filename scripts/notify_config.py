#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notify_config.py — v1.1 選配通知信模組的開關（資料庫 config/notify）。網頁寫不進去，只有這支改得動。

  階段（--phase）：
    off     全部不寄。也是緊急煞車：排隊中的家長通知，下一輪（10 分鐘內）一律取消，不會累積到下次打開時補寄
    dryrun  給導師自己的信照寄（新留言、家長發文、每日摘要）；給家長的信**只記錄、不寄**（先試跑用）
    live    給家長的信也真的寄：導師發文／回覆 30 分鐘後，一位家長一封
  三個開關（--teacher-mail／--parent-mail／--digest on|off）：各自關掉其中一種信。

  規矩（寫死在這支裡）：
    · 從 off 打開（dryrun 或 live）時寫下「通知起始線」notifyFloor＝伺服器現在的時間：這之前建立的內容一律不寄
      （還原備份、補發舊文都不會讓家長突然收到一堆信）
    · 切 live 之前一定要先在 dryrun，而且排程在 60 分鐘內跑過（ops/notify_status 有心跳）＝Functions 真的部署好、在動
    · dryrun 期間排進去的通知，事後切 live 也不會補寄
    · 寄件人、署名、收件（導師）信箱從 config/class.json 來（notifications.*、teacher.*）；每次寫入都一起更新

用法（Windows 把 python3 換成 py -3；斜線照寫）：
  python3 scripts/notify_config.py                       看現況（唯讀：開關、心跳、佇列、每日摘要）
  python3 scripts/notify_config.py --phase dryrun        預覽會怎麼改（不寫）
  python3 scripts/notify_config.py --phase dryrun --apply   真的寫
  python3 scripts/notify_config.py --phase live --apply
  python3 scripts/notify_config.py --phase off --apply      緊急煞車
  python3 scripts/notify_config.py --parent-mail off --apply
  python3 scripts/notify_config.py --sync --apply           只更新寄件人、署名、信箱（改了 class.json 之後）

exit：0＝成功（或只是看／預覽）；2＝被規矩擋下、什麼都沒寫；1＝寫入或讀回比對出錯。
"""
import sys
import argparse
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, gauth, notify  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib.hostos import PY  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

CONFIG = "config/notify"
PHASE_TEXT = {
    "off": "off（全部不寄）",
    "dryrun": "dryrun（給家長的信只記錄、不寄；給你自己的信照寄）",
    "live": "live（給家長的信也真的寄）",
}
IDENTITY_FIELDS = ("teacherEmail", "teacherKey", "fromEmail", "senderName", "signature", "className")


def parse_ts(v):
    if not v:
        return None
    try:
        return datetime.datetime.strptime(str(v)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def ago(ts, now):
    t = parse_ts(ts)
    if t is None:
        return None
    return (now - t).total_seconds() / 60.0


def fmt_ago(minutes):
    if minutes is None:
        return "從來沒有"
    if minutes < 60:
        return "%d 分鐘前" % max(0, int(minutes))
    if minutes < 48 * 60:
        return "%d 小時前" % int(minutes // 60)
    return "%d 天前" % int(minutes // 1440)


def local_time(ts):
    t = parse_ts(ts)
    return t.astimezone().strftime("%Y-%m-%d %H:%M") if t else "（沒有）"


# ── 規矩（純函式，測試直接呼叫）────────────────────────────────────────────────

def plan_changes(current, args, identity, sweep_minutes_ago):
    """回 (要寫的欄位 dict, 問題清單)。問題非空＝不准寫。current＝config/notify 現在的內容（沒有就 None）。"""
    cur = current or {}
    cur_phase = cur.get("phase") if cur.get("phase") in notify.PHASES else "off"
    fields, problems = {}, []
    if args.get("phase"):
        new = args["phase"]
        if new == "live":
            if cur_phase != "dryrun":
                problems.append("要先在 dryrun 跑過才能切 live（現在是 %s）：先 --phase dryrun --apply，"
                                "確認每日摘要與你自己的通知信都收得到，再切 live。" % cur_phase)
            elif sweep_minutes_ago is None or sweep_minutes_ago > notify.SWEEP_STALE_MINUTES:
                problems.append("給家長的通知排程還沒在動（ops/notify_status 最後一輪：%s；正常每 10 分鐘一次）：通知信模組可能"
                                "還沒部署好。先跑 %s scripts/notify_setup.py --cloud 看哪裡沒好。" % (fmt_ago(sweep_minutes_ago), PY))
        if new != cur_phase:
            fields["phase"] = new
        if new != "off" and cur_phase == "off":
            fields["notifyFloor"] = fr.SERVER_TIME
    for opt, key in notify.TOGGLES.items():
        v = args.get(opt)
        if v is not None:
            want = v == "on"
            if cur.get(key, True) is not want or key not in cur:
                fields[key] = want
    if current is None:
        for key in notify.TOGGLES.values():
            fields.setdefault(key, True)
        fields.setdefault("phase", "off")
    if fields or args.get("sync"):
        for k in IDENTITY_FIELDS:
            if cur.get(k) != identity[k]:
                fields[k] = identity[k]
    if fields:
        fields["updatedAt"] = fr.SERVER_TIME
    return fields, problems


def validate_doc(d):
    """寫進去之後整份 config/notify 的形狀（跟 functions/lib/pure.js 的 normalizeSettings 讀法一致）。"""
    p = []
    allowed = set(IDENTITY_FIELDS) | set(notify.TOGGLES.values()) | {"phase", "notifyFloor", "updatedAt"}
    extra = set(d) - allowed
    if extra:
        p.append("多了不認得的欄位：%s" % "、".join(sorted(extra)))
    if d.get("phase") not in notify.PHASES:
        p.append("phase 要是 off／dryrun／live")
    for key in notify.TOGGLES.values():
        if key in d and not isinstance(d[key], bool):
            p.append("%s 要是 true／false" % key)
    for key in ("teacherEmail", "fromEmail"):
        if not isinstance(d.get(key), str) or not notify.EMAIL_RE.match(d.get(key, "")):
            p.append("%s 不是合法的信箱" % key)
    for key, mx in (("senderName", 40), ("signature", 300), ("className", 40)):
        v = d.get(key)
        if not isinstance(v, str) or not (1 <= len(v) <= mx):
            p.append("%s 要是 1–%d 字" % (key, mx))
    if d.get("phase") in ("dryrun", "live") and not d.get("notifyFloor"):
        p.append("打開時一定要有通知起始線（notifyFloor）")
    return p


# ── 讀現況 ─────────────────────────────────────────────────────────────────

def read_state(client):
    got = client.batch_get([CONFIG, "ops/notify_status", "ops/digest_status"])
    cfg = got.get(CONFIG)
    queue = {"pending": 0, "failed": 0}
    for state in queue:
        try:
            queue[state] = len(client.run_query("", "blog_notify_queue", where=[("state", "==", state)], limit=500))
        except fr.FirestoreError:
            queue[state] = None
    return {
        "config": cfg.data if cfg else None,
        "notify": got.get("ops/notify_status").data if got.get("ops/notify_status") else {},
        "digest": got.get("ops/digest_status").data if got.get("ops/digest_status") else {},
        "queue": queue,
    }


def show(state, now, again=""):
    c = state["config"]
    n = state["notify"]
    dg = state["digest"]
    print("通知信（v1.1 選配）現況")
    if not c:
        print("  config/notify 還沒建：Functions 就算部署了也一封都不寄。")
        print("  → 模組裝好後，第一次打開：%s scripts/notify_config.py --phase dryrun%s（預覽）→ 老師點頭 → 加 --apply"
              % (PY, again))
    else:
        print("  階段：%s" % PHASE_TEXT.get(c.get("phase"), "%s（看不懂，當成 off）" % c.get("phase")))
        onoff = lambda k: "開" if c.get(k, True) else "關"  # noqa: E731
        print("  給你的即時信：%s｜給家長的信：%s｜每日摘要：%s" % (onoff("teacherMail"), onoff("parentMail"), onoff("digest")))
        print("  寄件：「%s」<%s>｜收件（你）：%s" % (c.get("senderName", ""), notify.mask(c.get("fromEmail")),
                                                notify.mask(c.get("teacherEmail"))))
        print("  通知起始線：%s（這之前建立的內容一律不寄）" % local_time(c.get("notifyFloor")))
    m = ago(n.get("lastRunAt"), now)
    print("  家長通知排程：最後一輪 %s（正常每 10 分鐘一次）｜排隊中 %s｜寄不出去 %s"
          % (fmt_ago(m), state["queue"]["pending"] if state["queue"]["pending"] is not None else "？",
             state["queue"]["failed"] if state["queue"]["failed"] is not None else "？"))
    if n.get("lastError"):
        print("  ！ 排程上一輪的錯誤：%s" % n["lastError"])
    if n.get("lastInstantError"):
        print("  ！ 即時信最近一次寄不出去（%s）：%s" % (local_time(n.get("lastInstantErrorAt")), n["lastInstantError"]))
    d = ago(dg.get("lastRunAt"), now)
    sent = "有寄出" if dg.get("sent") else ("關著沒寄" if dg.get("skipped") else "沒有新東西、沒寄")
    print("  每日摘要：最後一次 %s（%s）%s" % (fmt_ago(d), sent if dg else "—",
                                           "；錯誤：%s" % dg["lastError"] if dg.get("lastError") else ""))
    return m


def describe(fields):
    out = []
    for k, v in fields.items():
        if k == "updatedAt":
            continue
        if k == "phase":
            out.append("階段 → %s" % PHASE_TEXT[v])
        elif k == "notifyFloor":
            out.append("通知起始線 → 寫入的那一刻（這之前建立的內容一律不寄）")
        elif k in notify.TOGGLES.values():
            name = {"teacherMail": "給你的即時信", "parentMail": "給家長的信", "digest": "每日摘要"}[k]
            out.append("%s → %s" % (name, "開" if v else "關"))
        elif k in ("teacherEmail", "fromEmail", "teacherKey"):
            out.append("%s → %s" % ({"teacherEmail": "收件（你）", "fromEmail": "寄件 Gmail", "teacherKey": "導師 email 鍵"}[k],
                                     notify.mask(v)))
        else:
            out.append("%s → %s" % ({"senderName": "寄件人名稱", "signature": "信尾署名", "className": "班名"}[k],
                                     v.replace("\n", " ／ ")))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="通知信模組的開關（資料庫 config/notify）；不加 --apply 只看、只預覽")
    ap.add_argument("--phase", choices=notify.PHASES, help="off／dryrun／live")
    for opt in notify.TOGGLES:
        ap.add_argument("--" + opt, choices=("on", "off"), help="%s開或關" % {"teacher-mail": "給導師的即時信",
                                                                              "parent-mail": "給家長的信",
                                                                              "digest": "每日摘要"}[opt])
    ap.add_argument("--sync", action="store_true", help="從 config/class.json 更新寄件人、署名、信箱")
    ap.add_argument("--apply", action="store_true", help="真的寫進資料庫（老師點頭之後才加）")
    ap.add_argument("--emulator", action="store_true", help="連本機模擬器（測試用）")
    paths.add_root_arg(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        cfg = classcfg.load()
    except classcfg.ConfigError as e:
        print("✗ %s" % e)
        return 2
    probs = notify.validate(cfg.raw)
    if probs:
        print("✗ config/class.json 的 notifications 有問題：")
        for msg, fix in probs:
            print("  ✗ %s\n    → %s" % (msg, fix))
        return 2
    wants = {"phase": a.phase, "sync": a.sync}
    wants.update({opt: getattr(a, opt.replace("-", "_")) for opt in notify.TOGGLES})
    changing = any(v for v in wants.values())
    if changing and a.phase in ("dryrun", "live") and not notify.enabled(cfg.raw):
        print("✗ config/class.json 的 notifications.enabled 不是 true：通知信模組還沒裝（playbooks/notify.md）。什麼都沒寫。")
        return 2
    try:
        client = fr.make_client(cfg.project_id, emulator_flag=a.emulator)
    except ValueError as e:
        print("✗ %s" % e)
        return 2
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        state = read_state(client)
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        return 1
    sweep_ago = show(state, now, paths.rerun_flags(a))
    if not changing:
        return 0
    fields, problems = plan_changes(state["config"], wants, notify.identity(cfg.raw), sweep_ago)
    if problems:
        print("\n✗ 不能這樣改（什麼都沒寫）：")
        for p in problems:
            print("  → " + p)
        return 2
    if not fields:
        print("\n已經是這樣了，不用改。")
        return 0
    merged = dict(state["config"] or {})
    merged.update({k: ("(伺服器時間)" if v is fr.SERVER_TIME else v) for k, v in fields.items()})
    bad = validate_doc(merged)
    if bad:
        print("\n✗ 改完的設定不合法（什麼都沒寫）：")
        for p in bad:
            print("  → " + p)
        print("  → 多半是 config/class.json 的 teacher.email、notifications.gmail_address 沒填好：先跑 %s scripts/build_config.py --check。" % PY)
        return 2
    print("\n會這樣改：")
    for line in describe(fields):
        print("  · " + line)
    if not a.apply:
        print("\n這只是預覽，還沒寫。老師同意後再加 --apply。")
        return 0
    try:
        client.commit([client.set_write(CONFIG, fields, mask_fields=list(fields))], what="寫 config/notify")
        back = client.get(CONFIG)
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        return 1
    wrong = [k for k, v in fields.items() if v is not fr.SERVER_TIME and (back is None or back.data.get(k) != v)]
    wrong += [k for k, v in fields.items() if v is fr.SERVER_TIME and (back is None or not isinstance(back.data.get(k), fr.Timestamp))]
    if wrong:
        print("✗ 寫完讀回來對不上：%s。重跑同一個指令（重跑是安全的）。" % "、".join(wrong))
        return 1
    print("✓ 已寫入 config/notify，讀回比對一致。Functions 下一次觸發就用新的設定（不用重新部署）。")
    if fields.get("phase") == "off":
        print("  排隊中的家長通知會在下一輪（10 分鐘內）全部取消。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
