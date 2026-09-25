#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multipub.py — 一次送好幾份「只有導師看得到」的內容（座位表方案、全班個人照……）的共用流程。

跟 publishing.run() 同一套兩段式與寫入順序（顯示圖 → 縮圖 → 文件 → 讀回比對 → 最後刪舊照片），
差別只在「一次好幾份」：
  · 雲端上已經一模一樣的那幾份直接略過（重跑是安全的、不多花寫入次數）；
  · 雲端上已經有、內容不一樣的那幾份＝要改已上線的內容，沒加 --update 就一份都不寫、全部列出來；
  · 每一份各自寫、各自讀回比對，中途斷掉就修好後重跑同一個指令。

本機學生名冊只拿來比對「座號在不在班上」，**輸出只印座號，不印名字**（代理的對話紀錄會看到這些輸出）。
"""
import sys
import time

from . import paths, gauth
from . import firestore_rest as fr
from . import publishing as pub
from .sources import load_roster, load_roles, SourceError


def roster_seats():
    """data/roster.csv 裡的座號集合；沒有名冊或讀不懂回 None（呼叫端只提醒，不擋）。"""
    p = paths.data_dir() / "roster.csv"
    if not p.exists():
        return None
    try:
        students, _ = load_roster(p)
    except SourceError:
        return None
    return {s.seat for s in students}


def roster_display():
    """{座號: 稱呼}（只給本機預覽頁用；不印到主控台）。讀不到回 {}。"""
    p = paths.data_dir() / "roster.csv"
    if not p.exists():
        return {}
    try:
        students, _ = load_roster(p)
    except SourceError:
        return {}
    return {s.seat: s.display for s in students}


def parent_roles():
    """data/parent-roles.yaml → {座號: [稱謂]}；沒有檔回 None。檔案壞掉丟 PublishError（照它的說明修）。"""
    p = paths.data_dir() / "parent-roles.yaml"
    if not p.exists():
        return None
    try:
        return load_roles(p)
    except SourceError as e:
        raise pub.PublishError(e.problems)


def seat_list(seats):
    return "、".join(sorted(seats))


def same_content(cur, draft, summary_path):
    """雲端那一份（fr.Doc 或 None）跟準備要寫的內容一樣嗎（時間欄不算）。"""
    if cur is None:
        return False
    for path, data, _ in draft.docs:
        if path == summary_path:
            return fr.strip_times(cur.data) == fr.strip_times(data)
    return False


class PseudoDraft(object):
    """只為了寫一份合併的預覽頁（publishing.write_preview 只看這三個屬性）。"""

    def __init__(self, kind, ident, html):
        self.kind = kind
        self.ident = ident
        self.preview_html = html


def connect(cfg, a):
    client = fr.make_client(cfg.project_id, emulator_flag=a.emulator)
    print("上線目標：%s" % client.describe_target())
    return client


def publish_all(items, a, cfg, rerun_cmd, noun="份"):
    """items：[(draft, summary_path)]。預覽已經印過了；這裡只做 --publish 那一段。回 exit code。"""
    try:
        client = connect(cfg, a)
    except ValueError as e:
        return pub.fail([str(e)])
    try:
        got = client.batch_get([sp for _, sp in items])
        for note in getattr(client.tokens, "notes", []):
            print("  提醒：" + note)
        todo, same, blocked = [], [], []
        for draft, sp in items:
            cur = got.get(sp)
            if cur is None:
                todo.append((draft, "publish"))
            elif same_content(cur, draft, sp):
                same.append(draft)
            elif a.update:
                todo.append((draft, "update"))
            else:
                blocked.append(draft)
        if blocked:
            return pub.fail(["這幾%s已經在網站上、內容不一樣：%s" % (noun, "、".join(d.ident for d in blocked)),
                             "要改已上線的內容，老師確認過後加 --update 再跑一次：",
                             rerun_cmd + " --publish --update"], "沒有覆蓋已上線的內容（一%s都沒寫）：" % noun)
        n_w = n_s = 0
        for draft, action in todo:
            w, s = pub.publish(client, draft, progress=False)
            n_w += w
            n_s += s
            extra = {}
            for path, data, _ in draft.docs:
                if path.count("/") == 1:
                    extra = {k: data[k] for k in ("title", "date") if k in data}
            pub.record_publish(draft, action, extra)
            print("  ✓ %s（%s）" % (draft.ident, "更新" if action == "update" else "新發布"))
            sys.stdout.flush()
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        print("  → 修好後再跑同一個指令就好：已經寫進去而且一樣的會略過。")
        return 1
    except pub.PublishError as e:
        return pub.fail(e.lines, "上線後檢查沒過：")
    if same:
        print("  （%d %s跟網站上一模一樣，略過：%s）" % (len(same), noun, "、".join(d.ident for d in same)))
    if not todo:
        print("✓ 網站上已經是最新的，這次沒有寫任何東西。")
        return 0
    print("✓ 已上線 %d %s：寫入 %d 份文件%s，讀回比對一致。網站重新整理就看得到，不用重新部署。"
          % (len(todo), noun, n_w, ("、刪掉舊照片 %d 張" % n_s) if n_s else ""))
    return 0


def remove(owner, a, cfg, what, rerun_cmd):
    """從網站拿掉一份（連同底下的照片）。預設只預覽；--publish 才刪。本機檔不動。回 exit code。"""
    try:
        client = connect(cfg, a)
    except ValueError as e:
        return pub.fail([str(e)])
    try:
        cur = client.get(owner)
        if cur is None:
            print("網站上沒有%s（%s），不用拿掉。" % (what, owner))
            return 0
        if not a.publish:
            print("網站上有%s（%s）。確認要拿掉的話（本機的檔不會動），老師說好之後跑：" % (what, owner))
            print("  " + rerun_cmd + " --publish")
            return 0
        order = client.delete_recursive(owner)
        if client.get(owner) is not None:
            return pub.fail("刪完讀回來還在：%s" % owner, "拿掉後檢查沒過：")
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        print("  → 修好後再跑同一個指令就好。")
        return 1
    pub.ledger_append("published.jsonl", [{"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": what, "id": owner,
                                           "action": "remove"}])
    print("✓ 已從網站拿掉%s（刪除 %d 份文件）。本機的檔沒有動。" % (what, len(order)))
    return 0
