#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""access_sync.py — 同步「誰進得了網站」：本機三個名單檔 → 資料庫的名單（docs/DATA-MODEL.md §0.5、§2.1–§2.5、§2.16）。

  讀：data/roster.csv、data/contacts.csv、data/parent-roles.yaml、config/class.json
  寫：allowlist（班網讀者＋作者代號）、private_allowlist（私密讀者）、parent_child_map（帳號對座號）、
      roster/students（導師限定的名冊）、config/site（導師稱呼、校名、人數、公開行事曆網址）

**預設只印計畫、不寫任何東西**；老師看過、說好，才加 --apply。

保證的事：
  · 導師（config/class.json 的 teacher.email）一定在 allowlist（kind teacher）與 private_allowlist。
  · private_allowlist ⊆ allowlist、parent_child_map 的帳號 ⊆ allowlist。
  · 作者代號（alias）已經有的**一律沿用**，只有新加入的人才產生新的 12 碼隨機代號。
  · 沒變的文件不重寫（跑第二次＝零變更）。
  · 寫完讀回來比對，對不上就 exit 1。

安全閘（任何一個不過就停，**一筆都不寫**，exit 2）：
  · 三個來源檔任何一個讀不到、是空的、格式錯 → 停（絕不把「讀不到」當成「全部刪除」）。
  · 下限：contacts.csv 裡有 email 的家長位置，少於 parent-roles.yaml 宣告的位置數減 3 → 停
    （下限來自 parent-roles.yaml，不是來自被保護的 contacts.csv 本身：CSV 被截斷時下限不會跟著縮）。
  （contacts.csv 出現 parent-roles.yaml 沒宣告的家長、同一個座號同一個稱謂有兩個信箱 → 不停，但預覽一定列出來給老師看。）
  · 這一次會讓超過 N 個人失去權限（預設 3，--max-deletes 調）→ 停。
  · 學年封存（data_exit.py year-end）之後還沒用新名單同步過：--apply 要多加 --new-roster（老師確認三個名單檔
    已經是新學年的）才寫，不然停——上一屆的名單檔一同步，上一屆的家長就全部回來了。預覽照常，只多一行警告。

輸出只用「座號＋關係」與遮住的信箱（p***@example.com），**不印姓名、不印完整 email**。

用法：
  python3 scripts/access_sync.py              # 預覽：印出會新增／更新／移除什麼
  python3 scripts/access_sync.py --apply      # 真的寫進資料庫
  python3 scripts/access_sync.py --check      # 只檢查資料庫上的名單包含關係（唯讀）
  python3 scripts/access_sync.py --apply --new-roster   # 學年封存之後第一次同步（新學年的名單改好了）
  （Windows：py -3 scripts/access_sync.py …）
"""
import sys
import json
import time
import secrets
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, schema, classcfg, gauth, ledgers  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib.sources import load_roster, load_contacts, load_roles, SourceError  # noqa: E402
from lib.console import setup_utf8  # noqa: E402
from lib.hostos import PY  # noqa: E402

setup_utf8()

SLACK = 3
DEFAULT_MAX_DELETES = 3
EXIT_STOPPED = 2


def mask_email(key):
    """p***@example.com：看得出是哪一位，但不把整個信箱印進紀錄。"""
    if not key or "@" not in key:
        return "（沒有信箱）"
    local, domain = key.split("@", 1)
    return "%s***@%s" % (local[:1], domain)


def new_alias(taken, token=None):
    token = token or (lambda: secrets.token_hex(6))
    for _ in range(100):
        a = token()
        if schema.ALIAS_RE.match(a) and a not in taken:
            taken.add(a)
            return a
    raise RuntimeError("產生不出不重複的代號")


# ── 來源 → 應該長什麼樣 ───────────────────────────────────────────────────

def source_gates(roster, contacts, roles, slack=SLACK):
    """回 (report 行, problems, notes)。problems 非空＝停。"""
    problems, notes = [], []
    roster_seats = {s.seat for s in roster}
    for seat in sorted(roles):
        if seat not in roster_seats:
            problems.append("parent-roles.yaml 宣告了座號 %s，但名冊（roster.csv）裡沒有這個座號" % seat)
    for seat in sorted(roster_seats - set(roles)):
        notes.append("名冊有座號 %s，但 parent-roles.yaml 沒寫它（這位孩子的家長不會被算進下限）" % seat)
    declared = {(seat, rel) for seat, rels in roles.items() for rel in rels}
    filled, undeclared, slot_lines = set(), [], {}
    for c in contacts:
        if c.staff:
            if c.seat and c.seat not in roster_seats:
                problems.append("contacts.csv 第 %d 列：同仁授權的座號 %s 不在名冊裡" % (c.line, c.seat))
            continue
        if c.seat not in roster_seats:
            problems.append("contacts.csv 第 %d 列：座號 %s 不在名冊裡" % (c.line, c.seat))
            continue
        if not c.key:
            continue
        slot_lines.setdefault((c.seat, c.relation), {}).setdefault(c.key, c.line)
        if (c.seat, c.relation) not in declared:
            undeclared.append(c)
            continue
        filled.add((c.seat, c.relation))
    # 沒宣告的家長照樣會加進名單（老師寫進 contacts.csv 就是要給權限），但預覽時一定要讓老師看見：
    # 多半是稱謂寫法不一樣（「媽媽」對「母」），或新轉入的孩子還沒寫進 parent-roles.yaml。
    for c in undeclared:
        notes.append("contacts.csv 第 %d 列：座號 %s 的「%s」沒有寫在 parent-roles.yaml（那個座號宣告的是：%s），"
                     "不算進下限；確認不是打錯字" % (c.line, c.seat, c.relation, "、".join(roles.get(c.seat, [])) or "（沒有）"))
    # 同一個座號、同一個稱謂出現兩個不同的信箱：最常見的原因是座號打錯（會讓家長看到別人孩子的部落格）
    for (seat, rel), keys in sorted(slot_lines.items()):
        if len(keys) > 1:
            notes.append("座號 %s 的「%s」有 %d 個不同的信箱（contacts.csv 第 %s 列）：確認沒有打錯座號"
                         % (seat, rel, len(keys), "、".join(str(x) for x in sorted(keys.values()))))
    floor = max(0, len(declared) - slack)
    if not declared:
        problems.append("parent-roles.yaml 一個家長位置都沒宣告")
    elif len(filled) < floor:
        problems.append("contacts.csv 只有 %d 個家長位置有 email，低於下限 %d（parent-roles.yaml 宣告 %d 個、容許缺 %d 個）："
                        "contacts.csv 可能被截斷或存壞了。先確認這個檔，真的有很多家長還沒給信箱的話，"
                        "先把 parent-roles.yaml 裡還沒有帳號的稱謂拿掉。" % (len(filled), floor, len(declared), slack))
    missing = sorted(declared - filled)
    if missing:
        shown = "、".join("座號 %s %s" % m for m in missing[:12]) + ("…" if len(missing) > 12 else "")
        notes.append("還沒有 email 的家長位置 %d 個：%s" % (len(missing), shown))
    report = ["家長位置：%d／%d 有 email（下限 %d）" % (len(filled), len(declared), floor)]
    return report, problems, notes


def build_desired(cfg, roster, contacts):
    """回 (desired, problems)。desired 的 key 都是 email 鍵。"""
    problems = []
    teacher = cfg.teacher_key
    people = {}
    for c in contacts:
        if not c.key:
            continue
        if c.key == teacher:
            problems.append("contacts.csv 第 %d 列：這是導師自己的信箱（導師會自動加入，不要寫在 contacts.csv）" % c.line)
            continue
        p = people.setdefault(c.key, {"staff": c.staff, "seats": [], "relation": "", "private": False,
                                      "paused": None, "lines": []})
        if p["staff"] != c.staff:
            problems.append("contacts.csv 第 %s 列與第 %d 列：同一個信箱不能同時是家長和同仁，請擇一"
                            % (p["lines"][0], c.line))
            continue
        if p["paused"] is not None and p["paused"] != c.paused:
            problems.append("contacts.csv 第 %s 列與第 %d 列：同一個信箱的「暫停」寫得不一樣"
                            % (p["lines"][0], c.line))
            continue
        p["paused"] = c.paused
        p["lines"].append(c.line)
        if c.seat and c.seat not in p["seats"]:
            p["seats"].append(c.seat)
        if not p["relation"] and c.relation:
            p["relation"] = c.relation
        p["private"] = p["private"] or c.private
    allow = {teacher: {"kind": "teacher"}}
    private = {teacher}
    cmap, who = {}, {teacher: "導師"}
    for key, p in people.items():
        kind = "staff" if p["staff"] else "parent"
        allow[key] = {"kind": kind}
        if p["private"]:
            private.add(key)
        seats = sorted(p["seats"])
        if len(seats) > 3:
            problems.append("contacts.csv 第 %s 列：一個信箱最多對應 3 個座號" % "、".join(str(x) for x in p["lines"]))
            continue
        if kind == "parent":
            who[key] = "座號 %s %s" % ("、".join(seats), p["relation"])
        else:
            who[key] = "同仁" + ("（座號 %s）" % "、".join(seats) if seats else "")
        if seats:
            doc = {"seats": seats, "kind": kind, "active": not p["paused"],
                   "label": "座號 %s %s" % ("、".join(seats), "家長" if kind == "parent" else "同仁")}
            if kind == "parent" and p["relation"]:
                doc["relation"] = p["relation"]
            cmap[key] = doc
    students = [{"seat": s.seat, "name": s.name, "displayName": s.display} for s in roster]
    site = {"teacherDisplayName": cfg.teacher_display_name, "schoolName": cfg.school_name,
            "studentsCount": cfg.students_count, "calendarIcsUrl": cfg.calendar_ics_url}
    desired = {"allow": allow, "private": private, "map": cmap, "roster": {"students": students},
               "site": site, "who": who}
    # 寫入前先驗一次形狀（alias 還沒配，用假值驗其他欄位）
    for key, d in allow.items():
        for x in schema.problems("allowlist", dict(d, alias="a" * 12, updatedAt=fr.SERVER_TIME)):
            problems.append("allowlist（%s）：%s" % (who.get(key, mask_email(key)), x))
    for key, d in cmap.items():
        for x in schema.problems("parent_child_map", dict(d, updatedAt=fr.SERVER_TIME)):
            problems.append("parent_child_map（%s）：%s" % (who.get(key, mask_email(key)), x))
    for x in schema.problems("roster_students", dict(desired["roster"], updatedAt=fr.SERVER_TIME)):
        problems.append("roster/students：" + x)
    for x in schema.problems("config_site", dict(site, updatedAt=fr.SERVER_TIME)):
        problems.append("config/site（來自 config/class.json）：" + x)
    return desired, problems


# ── 對帳 ─────────────────────────────────────────────────────────────────

def read_current(client):
    return {
        "allow": {d.id: d.data for d in client.list_docs("allowlist")},
        "private": {d.id: d.data for d in client.list_docs("private_allowlist")},
        "map": {d.id: d.data for d in client.list_docs("parent_child_map")},
        "roster": (client.get("roster/students") or fr.Doc("", None)).data,
        "site": (client.get("config/site") or fr.Doc("", None)).data,
    }


def diff(desired, current, token=None):
    """回 plan：每個集合的 create／update／delete 與 same 數量；roster、site 是 None／'create'／'update'。"""
    taken = {d.get("alias") for d in current["allow"].values() if isinstance(d.get("alias"), str)}
    plan = {"allow": {"create": {}, "update": {}, "delete": {}, "same": 0},
            "private": {"create": {}, "update": {}, "delete": {}, "same": 0},
            "map": {"create": {}, "update": {}, "delete": {}, "same": 0}}
    for key, want in sorted(desired["allow"].items()):
        cur = current["allow"].get(key)
        alias = cur.get("alias") if cur and isinstance(cur.get("alias"), str) and schema.ALIAS_RE.match(cur["alias"]) else None
        new = dict(want, alias=alias or new_alias(taken, token))
        if cur is None:
            plan["allow"]["create"][key] = new
        elif fr.strip_times(cur) == new:
            plan["allow"]["same"] += 1
        else:
            plan["allow"]["update"][key] = (cur, new)
    for key in sorted(set(current["allow"]) - set(desired["allow"])):
        plan["allow"]["delete"][key] = current["allow"][key]
    for key in sorted(desired["private"]):
        cur = current["private"].get(key)
        if cur is None:
            plan["private"]["create"][key] = {}
        elif fr.strip_times(cur) == {}:
            plan["private"]["same"] += 1
        else:
            plan["private"]["update"][key] = (cur, {})
    for key in sorted(set(current["private"]) - set(desired["private"])):
        plan["private"]["delete"][key] = current["private"][key]
    for key, want in sorted(desired["map"].items()):
        cur = current["map"].get(key)
        if cur is None:
            plan["map"]["create"][key] = want
        elif fr.strip_times(cur) == want:
            plan["map"]["same"] += 1
        else:
            plan["map"]["update"][key] = (cur, want)
    for key in sorted(set(current["map"]) - set(desired["map"])):
        plan["map"]["delete"][key] = current["map"][key]
    cur_roster = current["roster"]
    plan["roster"] = ("create" if cur_roster is None else
                      (None if fr.strip_times(cur_roster) == desired["roster"] else "update"))
    cur_site = current["site"]
    plan["site"] = ("create" if cur_site is None else
                    (None if fr.strip_times(cur_site) == desired["site"] else "update"))
    return plan


def change_count(plan):
    n = 0
    for c in ("allow", "private", "map"):
        n += len(plan[c]["create"]) + len(plan[c]["update"]) + len(plan[c]["delete"])
    return n + (1 if plan["roster"] else 0) + (1 if plan["site"] else 0)


def losing_access(plan):
    """這次會失去某種權限的人（email 鍵集合）：從任何一份名單被移除的都算。"""
    out = set()
    for c in ("allow", "private", "map"):
        out |= set(plan[c]["delete"])
    return out


def plan_writes(client, desired, plan):
    """照「先加再減」的順序排寫入：加的時候 allowlist 先，減的時候 allowlist 最後（包含關係隨時成立）。"""
    w = []
    ts = {"updatedAt": fr.SERVER_TIME}
    for key, new in plan["allow"]["create"].items():
        w.append(client.set_write("allowlist/" + key, dict(new, **ts)))
    for key, (_, new) in plan["allow"]["update"].items():
        w.append(client.set_write("allowlist/" + key, dict(new, **ts)))
    for key in list(plan["private"]["create"]) + list(plan["private"]["update"]):
        w.append(client.set_write("private_allowlist/" + key, dict(ts)))
    for key, new in plan["map"]["create"].items():
        w.append(client.set_write("parent_child_map/" + key, dict(new, **ts)))
    for key, (_, new) in plan["map"]["update"].items():
        w.append(client.set_write("parent_child_map/" + key, dict(new, **ts)))
    if plan["roster"]:
        w.append(client.set_write("roster/students", dict(desired["roster"], **ts)))
    if plan["site"]:
        w.append(client.set_write("config/site", dict(desired["site"], **ts)))
    for key in plan["map"]["delete"]:
        w.append(client.delete_write("parent_child_map/" + key))
    for key in plan["private"]["delete"]:
        w.append(client.delete_write("private_allowlist/" + key))
    for key in plan["allow"]["delete"]:
        w.append(client.delete_write("allowlist/" + key))
    return w


def inclusion_problems(current, teacher_key):
    """資料庫上的名單包含關係（--check）。"""
    p = []
    t = current["allow"].get(teacher_key)
    if not t or t.get("kind") != "teacher":
        p.append("導師不在 allowlist，或 kind 不是 teacher")
    if teacher_key not in current["private"]:
        p.append("導師不在 private_allowlist")
    for key in current["private"]:
        if key not in current["allow"]:
            p.append("有私密讀者不在 allowlist（%s）" % mask_email(key))
    for key, d in current["map"].items():
        if key not in current["allow"]:
            p.append("有座號對應的帳號不在 allowlist（%s）" % mask_email(key))
        if schema.problems("parent_child_map", d):
            p.append("parent_child_map 有一份格式不對（%s）" % mask_email(key))
    for key, d in current["allow"].items():
        if schema.problems("allowlist", d):
            p.append("allowlist 有一份格式不對（%s）" % mask_email(key))
        elif d.get("kind") == "teacher" and key != teacher_key:
            p.append("allowlist 有一個不是導師的帳號被標成 teacher（%s）" % mask_email(key))
    aliases = [d.get("alias") for d in current["allow"].values()]
    if len(aliases) != len(set(aliases)):
        p.append("allowlist 裡有兩個人的作者代號一樣")
    return p


# ── 印 ───────────────────────────────────────────────────────────────────

def _who(key, desired, current):
    if key in desired["who"]:
        return desired["who"][key]
    m = current["map"].get(key) or {}
    if m.get("label"):
        return m["label"] + ("（%s）" % m["relation"] if m.get("relation") else "")
    a = current["allow"].get(key) or {}
    return {"teacher": "導師", "staff": "同仁", "parent": "家長"}.get(a.get("kind"), "名單上的一位")


def _changed_fields(old, new):
    old = fr.strip_times(old or {})
    keys = sorted(set(old) | set(new))
    return "、".join(k for k in keys if old.get(k) != new.get(k))


def print_plan(plan, desired, current, limit=40):
    names = (("allow", "班網讀者名單（allowlist）"), ("private", "私密讀者名單（private_allowlist）"),
             ("map", "家長／同仁對座號（parent_child_map）"))
    for c, title in names:
        p = plan[c]
        print("%s：新增 %d、更新 %d、移除 %d、不變 %d"
              % (title, len(p["create"]), len(p["update"]), len(p["delete"]), p["same"]))
        lines = []
        for key in p["create"]:
            lines.append("  ＋ %s（%s）" % (_who(key, desired, current), mask_email(key)))
        for key, (old, new) in p["update"].items():
            lines.append("  ～ %s（%s）：%s" % (_who(key, desired, current), mask_email(key), _changed_fields(old, new)))
        for key in p["delete"]:
            lines.append("  － %s（%s）" % (_who(key, desired, current), mask_email(key)))
        for ln in lines[:limit]:
            print(ln)
        if len(lines) > limit:
            print("  …還有 %d 筆" % (len(lines) - limit))
    print("名冊（roster/students，只有導師看得到）：%s"
          % {None: "不變", "create": "新建", "update": "更新"}[plan["roster"]])
    print("站台資訊（config/site）：%s" % {None: "不變", "create": "新建", "update": "更新"}[plan["site"]])


def append_alias_history(plan):
    """被移除的人的代號記進本機台帳（之後資料退場要靠它找這個人寫過的留言）。"""
    removed = plan["allow"]["delete"]
    if not removed:
        return
    p = paths.rpath("data", "ledgers", "alias-history.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        for key, old in removed.items():
            f.write(json.dumps({"at": now, "emailKey": key, "alias": old.get("alias"), "event": "removed"},
                               ensure_ascii=False) + "\n")


# ── 主程式 ───────────────────────────────────────────────────────────────

def load_sources():
    data = paths.data_dir()
    notes = []
    problems = []
    roster = contacts = roles = None
    try:
        roster, n = load_roster(data / "roster.csv")
        notes += n
    except SourceError as e:
        problems += e.problems
    try:
        contacts, n = load_contacts(data / "contacts.csv")
        notes += n
    except SourceError as e:
        problems += e.problems
    try:
        roles = load_roles(data / "parent-roles.yaml")
    except SourceError as e:
        problems += e.problems
    return roster, contacts, roles, problems, notes


def stop(problems, header="名單同步停下來了，一筆都沒有寫："):
    print("✗ " + header)
    for p in problems:
        print("  ✗ " + p)
    print("  → 修好上面這些再跑一次。這些檔只有老師能打開（Excel／Numbers），代理不要自己讀它們。")
    return EXIT_STOPPED


def main(argv=None):
    ap = argparse.ArgumentParser(description="同步名單：data/ 的三個名單檔 → 資料庫（預設只預覽，--apply 才寫）")
    ap.add_argument("--apply", action="store_true", help="真的寫進資料庫（先不加，看過計畫再加）")
    ap.add_argument("--check", action="store_true", help="只檢查資料庫上的名單包含關係（唯讀）")
    ap.add_argument("--max-deletes", type=int, default=DEFAULT_MAX_DELETES, metavar="N",
                    help="一次最多讓幾個人失去權限（預設 %d；學生轉出、家長換信箱時老師確認過才調高）" % DEFAULT_MAX_DELETES)
    ap.add_argument("--new-roster", action="store_true",
                    help="學年封存（data_exit.py year-end）之後第一次同步：老師確認三個名單檔已經改成新學年的名單，才加這個")
    ap.add_argument("--emulator", action="store_true", help="寫到本機模擬器（測試用）")
    paths.add_root_arg(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    again = paths.rerun_flags(a)

    try:
        cfg = classcfg.load()
    except classcfg.ConfigError as e:
        print("✗ %s" % e)
        return EXIT_STOPPED

    year_end = ledgers.year_end_pending()
    if year_end:
        print("！ 學年已封存（%s 跑過資料退場 year-end）：名單改好了嗎？" % str(year_end.get("at", ""))[:10])
        print("  本機的 roster.csv、contacts.csv、parent-roles.yaml 還是上一屆的話，同步會把上一屆的家長全部加回網站。")
        if a.apply and not a.new_roster:
            return stop(["學年封存之後的第一次同步，要老師明講「三個名單檔都改成新學年的了」才寫。",
                         "先不加 --apply 預覽、請老師看過；確認是新名單，再加 --apply --new-roster。"],
                        "學年封存的安全閘擋下來了，一筆都沒有寫：")

    try:
        client = fr.make_client(cfg.project_id, emulator_flag=a.emulator)
    except ValueError as e:
        print("✗ %s" % e)
        return EXIT_STOPPED

    if a.check:
        print("名單檢查（唯讀）：%s" % client.describe_target())
        try:
            current = read_current(client)
        except (fr.FirestoreError, gauth.AuthError) as e:
            print(e.plain())
            return 1
        probs = inclusion_problems(current, cfg.teacher_key)
        print("allowlist %d 人、private_allowlist %d 人、parent_child_map %d 份"
              % (len(current["allow"]), len(current["private"]), len(current["map"])))
        roster, contacts, roles, sp, _ = load_sources()
        if not sp:
            desired, dp = build_desired(cfg, roster, contacts)
            if not dp:
                n = change_count(diff(desired, current))
                print("跟本機名單比：%s" % ("一致" if n == 0 else "有 %d 處待同步（跑 access_sync.py 看細節）" % n))
        if probs:
            for p in probs:
                print("  ✗ " + p)
            print("✗ 名單的包含關係有問題 → 跑 %s scripts/access_sync.py%s 看計畫，再加 --apply 修正。" % (PY, again))
            return 1
        print("✓ 名單的包含關係成立（導師在兩份名單、私密讀者與座號對應都在班網名單裡）。")
        return 0

    roster, contacts, roles, problems, notes = load_sources()
    if problems:
        return stop(problems)
    report, gp, gnotes = source_gates(roster, contacts, roles)
    if gp:
        return stop(gp, "安全閘擋下來了，一筆都沒有寫：")
    desired, dp = build_desired(cfg, roster, contacts)
    if dp:
        return stop(dp)

    print("名單同步%s：%s" % ("" if a.apply else "（預覽，不會寫任何東西）", client.describe_target()))
    for n in notes + gnotes:
        print("  提醒：" + n)
    print("來源：名冊 %d 位學生｜contacts.csv %d 列｜班網讀者應有 %d 人（含導師）、私密讀者 %d 人、座號對應 %d 份"
          % (len(roster), len(contacts), len(desired["allow"]), len(desired["private"]), len(desired["map"])))
    for r in report:
        print("  ✓ " + r)

    try:
        for note in getattr(client.tokens, "notes", []):
            print("  提醒：" + note)
        current = read_current(client)
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        return 1
    plan = diff(desired, current)
    losing = losing_access(plan)
    if len(losing) > a.max_deletes:
        print_plan(plan, desired, current)
        return stop(["這次會讓 %d 個人失去權限，超過上限 %d。確認真的要移除（例如學生轉出、學年結束）再加 --max-deletes %d。"
                     "學年結束請改走資料退場劇本。" % (len(losing), a.max_deletes, len(losing))],
                    "安全閘擋下來了，一筆都沒有寫：")
    print("  ✓ 這次失去權限的人：%d（上限 %d）" % (len(losing), a.max_deletes))
    print_plan(plan, desired, current)
    total = change_count(plan)
    if total == 0:
        print("✓ 資料庫上的名單已經跟本機一致，沒有要改的。")
        ledgers.mark_access_sync()
        if year_end and a.apply and a.new_roster:
            ledgers.clear_year_end()
        return 0
    if not a.apply:
        print("\n這只是預覽，什麼都還沒寫。老師確認上面的變動沒問題後，再跑：")
        print("  %s scripts/access_sync.py --apply%s%s%s"
              % (PY, (" --max-deletes %d" % a.max_deletes) if a.max_deletes != DEFAULT_MAX_DELETES else "",
                 " --new-roster" if year_end else "", again))
        if year_end:
            print("  （學年封存之後：老師確認上面是新學年的名單，才加 --new-roster）")
        return 0

    writes = plan_writes(client, desired, plan)
    try:
        n = client.commit_all(writes, what="同步名單")
        append_alias_history(plan)
        after = read_current(client)
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        print("  → 寫到一半停下來也沒關係：修好問題後再跑一次 --apply，會從目前的狀態接著對帳。")
        return 1
    left = change_count(diff(desired, after))
    probs = inclusion_problems(after, cfg.teacher_key)
    if left or probs:
        print("✗ 寫完讀回來比對不一致（還差 %d 處）%s" % (left, "；" + "；".join(probs) if probs else ""))
        return 1
    print("✓ 已寫入 %d 筆（%d 次送出），讀回比對一致。" % (len(writes), n))
    ledgers.mark_access_sync()
    if year_end:
        ledgers.clear_year_end()
        print("  學年封存的安全閘收起來了：之後名單同步照平常的兩段式就好。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
