#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""open_blogs.py — 開學生部落格（「我的孩子」）的主頁：名冊裡每個座號一份 student_blogs/<座號>（docs/DATA-MODEL.md §2.13）。

  讀：data/roster.csv（座號、稱呼）；頭像選用：data/avatars/<座號>.jpg（或 .png 等，檔名只准座號）
  寫：student_blogs/<座號>  { seat, displayName（只放名、不放姓）, avatar（null 或內嵌小圖）, updatedAt }

  · 還沒開的就開；已經開的只在「稱呼」或頭像改了時更新（intro 等其他欄位保留）。
  · **從不刪部落格**：名冊裡沒有了的座號只提醒（要刪走資料退場劇本）。
  · 預設只印計畫；加 --apply 才寫。
  · 輸出只印座號，不印孩子的名字。

用法：
  python3 scripts/open_blogs.py                  # 預覽全班
  python3 scripts/open_blogs.py --apply          # 開全班
  python3 scripts/open_blogs.py --seat 3 --apply # 只開（或更新）3 號；可以給好幾次 --seat
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, schema, images, gauth  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib.seats import parse_seat  # noqa: E402
from lib.sources import load_roster, SourceError  # noqa: E402
from lib.console import setup_utf8  # noqa: E402
from lib.hostos import PY  # noqa: E402

setup_utf8()
EXIT_STOPPED = 2


def find_avatar(seat):
    d = paths.data_dir() / "avatars"
    if not d.is_dir():
        return None
    for p in sorted(d.iterdir()):
        if p.is_file() and p.stem == seat and images.is_photo_file(p):
            return p
    return None


def build_wanted(students, seats_filter):
    """回 ({座號: 資料（avatar 先放檔案路徑）}, problems)。"""
    wanted, problems = {}, []
    roster_seats = {s.seat for s in students}
    for s in seats_filter or []:
        if s not in roster_seats:
            problems.append("座號 %s 不在名冊（data/roster.csv）裡" % s)
    for st in students:
        if seats_filter and st.seat not in seats_filter:
            continue
        wanted[st.seat] = {"seat": st.seat, "displayName": st.display, "avatar": find_avatar(st.seat)}
    return wanted, problems


def plan(wanted, current, encode_avatar):
    """回 [(座號, 'create'|'update', 資料, 改了什麼)]；encode_avatar(path) → 內嵌小圖 dict。"""
    out = []
    for seat, w in sorted(wanted.items()):
        cur = current.get(seat)
        avatar = encode_avatar(w["avatar"]) if w["avatar"] else None
        data = {"seat": seat, "displayName": w["displayName"]}
        if cur is None:
            data["avatar"] = avatar
            out.append((seat, "create", data, "新開"))
            continue
        changed = []
        if cur.get("displayName") != w["displayName"]:
            changed.append("稱呼")
        if w["avatar"] and cur.get("avatar") != avatar:
            changed.append("頭像")
        if cur.get("seat") != seat:
            changed.append("座號欄")
        if changed:
            data["avatar"] = avatar if w["avatar"] else cur.get("avatar")
            out.append((seat, "update", data, "、".join(changed)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="開學生部落格主頁（預設只預覽；--apply 才寫）")
    ap.add_argument("--seat", action="append", default=[], metavar="座號", help="只處理這個座號（可給好幾次）")
    ap.add_argument("--apply", action="store_true", help="真的寫進資料庫")
    ap.add_argument("--emulator", action="store_true", help="寫到本機模擬器（測試用）")
    paths.add_root_arg(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        cfg = classcfg.load()
        students, notes = load_roster(paths.data_dir() / "roster.csv")
        seats_filter = [parse_seat(s) for s in a.seat]
    except classcfg.ConfigError as e:
        print("✗ %s" % e)
        return EXIT_STOPPED
    except SourceError as e:
        print("✗ 名冊讀不了，什麼都沒寫：")
        for p in e.problems:
            print("  ✗ " + p)
        return EXIT_STOPPED
    except ValueError:
        print("✗ --seat 要是 1–40 的數字")
        return EXIT_STOPPED
    wanted, problems = build_wanted(students, seats_filter)
    if problems:
        for p in problems:
            print("✗ " + p)
        return EXIT_STOPPED
    if any(w["avatar"] for w in wanted.values()) and not images.have_pillow():
        print(images.pillow_help())
        return EXIT_STOPPED

    cache = {}

    def encode_avatar(p):
        if p not in cache:
            try:
                cache[p] = images.process(p, "座號 %s 的頭像" % p.stem).inline()
            except images.ImageError as e:
                raise SystemExit(str(e))
        return cache[p]

    try:
        client = fr.make_client(cfg.project_id, emulator_flag=a.emulator)
        print("學生部落格%s：%s" % ("" if a.apply else "（預覽，不會寫任何東西）", client.describe_target()))
        for n in notes:
            print("  提醒：" + n)
        current = {d.id: d.data for d in client.list_docs("student_blogs")}
    except ValueError as e:
        print("✗ %s" % e)
        return EXIT_STOPPED
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        return 1
    steps = plan(wanted, current, encode_avatar)
    roster_seats = {s.seat for s in students}
    orphans = sorted(set(current) - roster_seats)
    creates = [s for s in steps if s[1] == "create"]
    updates = [s for s in steps if s[1] == "update"]
    print("名冊 %d 位｜這次處理 %d 個座號｜要新開 %d、要更新 %d、不變 %d"
          % (len(students), len(wanted), len(creates), len(updates), len(wanted) - len(creates) - len(updates)))
    if creates:
        print("  ＋ 新開：座號 %s" % "、".join(s[0] for s in creates))
    for seat, _, _, what in updates:
        print("  ～ 座號 %s：%s" % (seat, what))
    if orphans:
        print("  提醒：資料庫裡還有名冊沒有的座號部落格：%s（不會刪；學生轉出請走資料退場劇本）" % "、".join(orphans))
    for seat, _, data, _ in steps:
        full = dict(data, updatedAt=fr.SERVER_TIME)
        probs = schema.problems("student_blog", full)
        if probs:
            print("✗ 座號 %s 的資料格式不對：%s" % (seat, "；".join(probs)))
            return EXIT_STOPPED
    if not steps:
        print("✓ 部落格都開好了，沒有要改的。")
        return 0
    if not a.apply:
        print("\n這只是預覽，什麼都還沒寫。老師說好之後再跑：")
        print("  %s scripts/open_blogs.py%s --apply%s" % (PY, "".join(" --seat %s" % s for s in seats_filter),
                                                   paths.rerun_flags(a)))
        return 0
    writes = []
    for seat, kind, data, _ in steps:
        full = dict(data, updatedAt=fr.SERVER_TIME)
        if kind == "create":
            writes.append(client.set_write("student_blogs/" + seat, full, must_not_exist=True))
        else:
            writes.append(client.set_write("student_blogs/" + seat, full,
                                           mask_fields=["seat", "displayName", "avatar", "updatedAt"]))
    try:
        client.commit_all(writes, what="開部落格")
        after = {d.id: d.data for d in client.list_docs("student_blogs")}
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        print("  → 修好後再跑一次同一個指令就好（已經開好的不會重開）。")
        return 1
    left = plan(wanted, after, encode_avatar)
    if left:
        print("✗ 寫完讀回來還有 %d 個座號對不上" % len(left))
        return 1
    print("✓ 已寫入 %d 個座號的部落格主頁，讀回比對一致。" % len(steps))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
