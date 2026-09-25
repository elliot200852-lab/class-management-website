#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""status.py — 代理每次開始工作先跑這支（AGENTS.md 鐵則）：有沒有東西在等你處理。

老師沒有別人的開工提醒，所以提醒內建在這裡。**唯讀、不連網、幾秒內跑完**：只看這台電腦上的
設定、data/、台帳，以及雲端硬碟同步夾在不在。每一項都說「要不要處理、怎麼處理、讀哪份劇本」。

安裝還沒做完（setup/progress.json 裡 0–10 步有還沒 done 的）→ 只印「安裝做到第 N 步，照 AGENTS.md 接著做」，
下面這些日常提醒一概不印（還沒部署就叫人備份、同步名單，只會把安裝順序打亂）。

檢查項目：
  · 學年封存之後還沒用新名單同步（data/ledgers/year-end.json，data_exit.py year-end 寫的）→ 最先提醒
  · config/class.json 填完了沒、data/ 在不在
  · 雲端硬碟同步夾與資料夾樹還在不在
  · 三條備份（資料庫、紀錄、部落格）幾天沒成功：7 天以上提醒、14 天以上加重語氣；上一次失敗也會說
  · data/inbox/ 有幾個檔等著歸檔；data/inbox/.archived/ 有沒有要清的
  · 名單檔（roster.csv、contacts.csv、parent-roles.yaml）在上次名單同步之後有沒有改過
  · 資料庫容量估算（上一份備份的照片與文件大小，對照免費方案 1 GiB；70% 以上提醒）
  · Pillow、gcloud、firebase 有沒有裝

用法：
  python3 scripts/status.py       （Windows：py -3 scripts/status.py）
exit code 一律 0（這支只報告，不擋任何事）。
"""
import sys
import json
import datetime
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, ledgers, hostos, images, progress  # noqa: E402
from lib import drivetree as dt  # noqa: E402
from lib.filesafe import human_size  # noqa: E402
from lib.hostos import PY  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

# 門檻的正本在 lib/thresholds.py（通知信模組的每日摘要用同一組數字）
from lib.thresholds import BACKUP_REMIND_DAYS as REMIND_DAYS, BACKUP_URGENT_DAYS as URGENT_DAYS  # noqa: E402
QUOTA_BYTES = 1024 ** 3
QUOTA_WARN = 0.70
QUOTA_URGENT = 0.90
NAME_FILES = ("roster.csv", "contacts.csv", "parent-roles.yaml")
BACKUP_LABELS = {"firestore": "網站資料庫備份", "records": "紀錄備份（名冊、母本、課程單元、課程紀錄）",
                 "blogs": "學生部落格備份"}

OK, INFO, WARN, URGENT = "ok", "info", "warn", "urgent"
MARK = {OK: "✓", INFO: "・", WARN: "！", URGENT: "‼"}


def item(level, title, todo="", playbook=""):
    return {"level": level, "title": title, "todo": todo, "playbook": playbook}


# ── 純函式：每一項判斷（測試直接呼叫）────────────────────────────────────

def backup_item(kind, rec, now):
    label = BACKUP_LABELS[kind]
    cmd = "%s scripts/backup.py %s" % (PY, kind)
    last = ledgers.parse_iso((rec or {}).get("last_ok"))
    fail = ledgers.parse_iso((rec or {}).get("last_fail"))
    failed_after = fail is not None and (last is None or fail > last)
    why = ("；上一次（%s）失敗：%s" % (fail.strftime("%m/%d %H:%M"), (rec or {}).get("last_error", ""))) if failed_after else ""
    if last is None:
        return item(WARN, "%s：還沒有成功過%s" % (label, why), "跑 %s（或一次跑完三條：%s scripts/backup.py all）" % (cmd, PY),
                    "playbooks/backup.md")
    days = (now - last).total_seconds() / 86400.0
    if days >= URGENT_DAYS:
        return item(URGENT, "%s：已經 %d 天沒有成功備份了%s" % (label, int(days), why),
                    "今天就跑 %s；電腦壞掉的話，這 %d 天的資料就只剩雲端上那一份" % (cmd, int(days)), "playbooks/backup.md")
    if days >= REMIND_DAYS:
        return item(WARN, "%s：%d 天沒有備份了%s" % (label, int(days), why), "跑 %s" % cmd, "playbooks/backup.md")
    if failed_after:
        return item(WARN, "%s：上一次成功是 %d 天前，但最近一次失敗了%s" % (label, int(days), why),
                    "照失敗訊息處理後再跑 %s" % cmd, "playbooks/backup.md")
    return item(OK, "%s：%s（%d 天前）" % (label, last.strftime("%Y-%m-%d %H:%M"), int(days)))


def names_item(mtimes, last_sync):
    """mtimes：{檔名: datetime}（不在的檔不放）；last_sync：上次名單同步成功的時間或 None。"""
    if not mtimes:
        return item(INFO, "還沒有名單檔（data/roster.csv 等）", "安裝步驟 6：匯入名單", "playbooks/sync-access.md")
    newest = max(mtimes.values())
    if last_sync is None:
        return item(WARN, "名單還沒有同步進網站過（或同步紀錄不見了）", "跑 %s scripts/access_sync.py 先預覽" % PY,
                    "playbooks/sync-access.md")
    if newest > last_sync:
        changed = sorted(n for n, t in mtimes.items() if t > last_sync)
        return item(WARN, "名單檔在上次同步（%s）之後改過：%s" % (last_sync.strftime("%m/%d %H:%M"), "、".join(changed)),
                    "跑 %s scripts/access_sync.py 看預覽，老師確認後再 --apply" % PY, "playbooks/sync-access.md")
    return item(OK, "名單：上次同步 %s 之後沒有改過" % last_sync.strftime("%Y-%m-%d %H:%M"))


def inbox_item(n_files, n_archived):
    out = []
    if n_files:
        out.append(item(WARN, "data/inbox/ 有 %d 個檔等著歸檔" % n_files,
                        "問老師這些是哪個課程單元的，照劇本歸檔（跑 %s scripts/archive_media.py 先看清單）" % PY,
                        "playbooks/archive-media.md"))
    if n_archived:
        out.append(item(INFO, "data/inbox/.archived/ 有 %d 個已經歸檔、但沒能放進垃圾桶的原檔" % n_archived,
                        "確認雲端硬碟上有了，請老師自己把那個資料夾清掉", "playbooks/archive-media.md"))
    if not out:
        out.append(item(OK, "data/inbox/ 是空的"))
    return out


def year_end_item(pending):
    """學年封存旗標（ledgers.year_end_pending() 的結果）；沒有旗標回 None。"""
    if not pending:
        return None
    day = str(pending.get("at", ""))[:10]
    return item(URGENT, "學年已封存（%s 跑過資料退場 year-end）：新學年的名單改好了嗎？" % day,
                "改好之前不要同步名單（會把上一屆的家長加回去）。請老師改好 roster.csv、contacts.csv、parent-roles.yaml，"
                "再跑 %s scripts/access_sync.py 預覽；老師確認後才 --apply --new-roster" % PY, "playbooks/year-end.md")


def capacity_item(est_bytes, snap_id=""):
    if est_bytes is None:
        return item(INFO, "資料庫容量：還沒有備份，估算不出來", "跑過一次資料庫備份後就會顯示", "playbooks/backup.md")
    pct = float(est_bytes) / QUOTA_BYTES
    text = "資料庫容量估計約 %s（免費方案上限 1 GiB 的 %d%%；依 %s 那份備份估算）" % (human_size(est_bytes), int(pct * 100),
                                                                     snap_id or "最近一份")
    todo = "學年結束照資料退場劇本清照片，或升級方案（docs/DATA-MODEL.md §5.4，不用改程式）"
    if pct >= QUOTA_URGENT:
        return item(URGENT, text, "快滿了：滿了以後發文、上傳、留言都會失敗。" + todo, "playbooks/year-end.md")
    if pct >= QUOTA_WARN:
        return item(WARN, text, todo, "playbooks/year-end.md")
    return item(OK, text)


def tools_items(have_pillow, have_gcloud, have_firebase):
    out = []
    for ok, name, why in ((have_pillow, "Pillow", "處理照片（紀事、相簿、部落格照片）"),
                          (have_gcloud, "gcloud", "發文、同步名單、備份（登入你的 Google 帳號）"),
                          (have_firebase, "firebase", "部署網站")):
        if not ok:
            out.append(item(INFO, "還沒裝 %s（%s要用）" % (name, why), "跑 %s scripts/doctor.py，照它給的官方連結請老師自己裝" % PY,
                            "playbooks/doctor.md"))
    if not out:
        out.append(item(OK, "Pillow、gcloud、firebase 都找得到"))
    return out


def estimate_bytes(snap_dir):
    """從一份本機快照估資料庫大小：文件 JSON 大小＋照片池檔大小（缺的用平均補）＋每份文件約 1.25 KB 的索引與名稱。"""
    snap_dir = Path(snap_dir)
    try:
        man = json.loads((snap_dir / "manifest.json").read_text(encoding="utf-8"))
        docs_bytes = (snap_dir / "documents.jsonl").stat().st_size
        rows = [json.loads(x) for x in (snap_dir / "photos.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return None
    pool = snap_dir.parent / "photos"
    sizes = []
    for r in rows:
        try:
            sizes.append((pool / (r["key"] + ".json")).stat().st_size)
        except (OSError, KeyError):
            pass
    photo_bytes = (sum(sizes) / len(sizes) * len(rows)) if sizes else 0
    counts = man.get("counts") or {}
    n = counts.get("documents", 0) + counts.get("photos", 0)
    return int(docs_bytes + photo_bytes + 1280 * n)


# ── 收集 ────────────────────────────────────────────────────────────────

def collect(now=None):
    now = now or datetime.datetime.now().astimezone()
    root = paths.root()
    data = paths.data_dir()
    out = []
    cfgp = root / "config" / "class.json"
    raw = None
    if not cfgp.exists():
        out.append(item(URGENT, "還沒有 config/class.json（還沒安裝，或裝到一半）", "照 AGENTS.md 的安裝步驟做", "AGENTS.md"))
    else:
        try:
            raw = json.loads(cfgp.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            out.append(item(URGENT, "config/class.json 讀不懂", "跑 %s scripts/build_config.py --check" % PY, "AGENTS.md"))
        if raw is not None:
            from lib import classcfg
            try:
                classcfg.load()
                out.append(item(OK, "設定檔 config/class.json 可以用"))
            except classcfg.ConfigError as e:
                out.append(item(WARN, "設定檔還沒填完：%s" % str(e).splitlines()[0],
                                "跑 %s scripts/build_config.py --check，照它說的補" % PY, "AGENTS.md"))
            if not (root / "firestore.rules").exists():
                out.append(item(INFO, "還沒產生安全規則（firestore.rules）", "跑 %s scripts/build_config.py" % PY, "AGENTS.md"))
    if not data.is_dir():
        out.append(item(URGENT, "找不到 data/（這個班的資料夾）", "跑 %s scripts/init_data.py" % PY, "AGENTS.md"))
        return out
    ye = year_end_item(ledgers.year_end_pending())
    if ye:
        out.insert(0, ye)
    tree = dt.DriveTree.from_config(raw or {})
    probs = tree.problems(tuple(k for k in dt.LOCATIONS if k != "root"))
    if probs:
        lines = probs[0].lines
        out.append(item(WARN, "雲端硬碟同步夾：" + lines[0], " ".join(x.lstrip("→ ") for x in lines[1:2]), "playbooks/backup.md"))
    else:
        out.append(item(OK, "雲端硬碟同步夾與資料夾樹都在（%s）" % tree.class_folder))
    state = ledgers.read_state()
    for kind in ledgers.BACKUP_KINDS:
        out.append(backup_item(kind, state.get(kind), now))
    inbox = data / "inbox"
    n_files = n_arch = 0
    if inbox.is_dir():
        n_files = sum(1 for p in inbox.iterdir() if p.is_file() and not p.name.startswith((".", "~cmw-tmp-"))
                      and p.name != "README.md")
        arch = inbox / ".archived"
        if arch.is_dir():
            n_arch = sum(1 for p in arch.iterdir() if p.is_file())
    out += inbox_item(n_files, n_arch)
    mt = {}
    for n in NAME_FILES:
        p = data / n
        if p.exists():
            mt[n] = datetime.datetime.fromtimestamp(p.stat().st_mtime).astimezone()
    out.append(names_item(mt, ledgers.last_access_sync()))
    snap_id, est = "", None
    fs_state = state.get("firestore") or {}
    if fs_state.get("snapshot"):
        snap_id = fs_state["snapshot"]
        est = estimate_bytes(data / "backups" / "firestore" / snap_id)
    out.append(capacity_item(est, snap_id))
    out += tools_items(images.have_pillow(), bool(hostos.find_exe_all("gcloud")), bool(hostos.find_exe_all("firebase")))
    return out


def report(items):
    order = {URGENT: 0, WARN: 1, INFO: 2, OK: 3}
    todo = [i for i in items if i["level"] != OK]
    fine = [i for i in items if i["level"] == OK]
    print("狀態檢查（唯讀、不連網）")
    if todo:
        print("\n要處理的事（%d 項，重要的在前）：" % len(todo))
        for i in sorted(todo, key=lambda x: order[x["level"]]):
            print("  %s %s" % (MARK[i["level"]], i["title"]))
            if i["todo"]:
                print("      怎麼處理：%s" % i["todo"])
            if i["playbook"]:
                print("      劇本：%s" % i["playbook"])
    if fine:
        print("\n沒問題的：")
        for i in fine:
            print("  %s %s" % (MARK[OK], i["title"]))
    if not todo:
        print("\n✓ 沒有要處理的事。")
    else:
        print("\n先跟老師說有哪幾件事在等（一句話），問他要不要現在處理；不要一口氣全做。")


def report_install(prog, n):
    """安裝還沒做完：只說做到第幾步，日常提醒全部不印。"""
    note = ""
    st = (prog.get("steps") or {}).get(str(n))
    if isinstance(st, dict) and st.get("note"):
        note = str(st["note"]).strip()
    print("狀態檢查（唯讀、不連網）")
    print("\n安裝做到第 %d 步，照 AGENTS.md 接著做（進度記在 setup/progress.json）。" % n)
    if note:
        print("  第 %d 步的紀錄：%s" % (n, note))
    print("日常提醒（備份、名單同步、容量……）等 0–10 步都做完再看；現在不用處理。")


def main(argv=None):
    ap = argparse.ArgumentParser(description="開工先跑：有沒有東西在等你處理（唯讀、不連網）")
    paths.add_root_arg(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    prog = progress.read()
    n = progress.first_open_step(prog)
    if n is not None:
        report_install(prog, n)
        return 0
    report(collect())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
