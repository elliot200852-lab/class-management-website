#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ledgers.py — 本機台帳（data/ledgers/）：備份狀態、課堂檔案歸檔台帳。

  backup-state.json   每一條備份線最後一次**成功**的時間與摘要；失敗只記在 last_fail，
                      **不動 last_ok**——status.py 看 last_ok 算幾天沒備份，失敗的話提醒會一直叫。
  media-ledger.jsonl  課堂檔案歸檔的事件（只增不改）：archived／removed（老師刪掉了＝墓碑）／restored。
                      目前狀態＝把事件依序疊起來（fold_media）。一行一個 JSON，壞掉的行略過並回報。
"""
import json
import datetime
from pathlib import Path

from . import paths
from .filesafe import write_json_atomic, read_json

BACKUP_KINDS = ("firestore", "records", "blogs")
MEDIA_TYPES = ("板書", "作業本", "課堂活動", "教材", "其他")


def now_iso():
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def parse_iso(s):
    try:
        d = datetime.datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        d = d.astimezone()
    return d


def state_path():
    return paths.data_dir() / "ledgers" / "backup-state.json"


def read_state():
    st = read_json(state_path(), default={})
    return st if isinstance(st, dict) else {}


def mark_ok(kind, **info):
    st = read_state()
    cur = dict(st.get(kind) or {})
    cur.update(info)
    cur["last_ok"] = now_iso()
    cur.pop("last_error", None)
    st[kind] = cur
    write_json_atomic(state_path(), st)
    return cur


def mark_fail(kind, error):
    st = read_state()
    cur = dict(st.get(kind) or {})
    cur["last_fail"] = now_iso()
    cur["last_error"] = str(error)[:300]
    st[kind] = cur
    write_json_atomic(state_path(), st)
    return cur


def access_sync_path():
    return paths.data_dir() / "ledgers" / "access-sync.json"


def mark_access_sync():
    """access_sync.py 寫完（或確認已經一致）時記一筆：status.py 拿名單檔的修改時間跟它比。"""
    write_json_atomic(access_sync_path(), {"last_ok": now_iso()})


def last_access_sync():
    st = read_json(access_sync_path(), default={})
    return parse_iso(st.get("last_ok")) if isinstance(st, dict) else None


# ── 學年封存旗標（data_exit.py year-end 寫；access_sync.py、status.py 看）────────────
# 學年結束撤掉全部權限之後，本機三個名單檔多半還是舊的一班：這時照平常跑名單同步，就會把上一屆的家長全部加回去。
# 所以 year-end 在動手之前先立這支旗標；旗標還在的時候，access_sync.py --apply 要老師明講「名單改好了」
# （--new-roster）才放行，寫成功才收旗標。

def year_end_path():
    return paths.data_dir() / "ledgers" / "year-end.json"


def mark_year_end(mode):
    write_json_atomic(year_end_path(), {"at": now_iso(), "mode": str(mode)})


def year_end_pending():
    """學年封存之後還沒用新名單同步過 → {"at": …, "mode": …}；沒有旗標（或已經收掉）→ None。"""
    st = read_json(year_end_path(), default={})
    if isinstance(st, dict) and st.get("at") and not st.get("cleared_at"):
        return st
    return None


def clear_year_end():
    st = read_json(year_end_path(), default={})
    if isinstance(st, dict) and st.get("at") and not st.get("cleared_at"):
        st["cleared_at"] = now_iso()
        write_json_atomic(year_end_path(), st)


# ── 資料退場台帳（data_exit.py --apply 寫；backup.py restore firestore 看）──────────────
# 整庫還原會把退場前的快照寫回去：轉出學生的部落格、家長的留言與回條都會「復活」。所以退場時記一筆：
# 誰（座號；email 鍵與作者代號只存 SHA-256 前 32 碼，不存信箱）、什麼時候。還原時比快照的建立時間，
# 快照比退場早、又碰到這些人的資料，就停下來（除非老師明講 --include-exited）。只增不改。

def exit_ledger_path():
    return paths.data_dir() / "ledgers" / "data-exit.jsonl"


def exit_hash(s):
    """跟通知信台帳 blog_notify_queue/*/sent/{hash} 同一種算法：SHA-256 前 32 碼。"""
    import hashlib
    return hashlib.sha256(str(s).encode("utf-8")).hexdigest()[:32]


def record_exit(kind, seats=(), keys=(), aliases=(), mode=None, path=None):
    rec = {"at": now_iso(), "kind": str(kind), "seats": sorted(set(seats)),
           "keyHashes": sorted({exit_hash(k) for k in keys if k}),
           "aliasHashes": sorted({exit_hash(a) for a in aliases if a})}
    if mode:
        rec["mode"] = str(mode)
    p = Path(path or exit_ledger_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(str(p), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush()
    return rec


def read_exits(path=None):
    """退場紀錄（壞掉的行略過）。"""
    p = Path(path or exit_ledger_path())
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("at") and rec.get("kind"):
            out.append(rec)
    return out


# ── 課堂檔案台帳 ─────────────────────────────────────────────────────────

def media_ledger_path():
    return paths.data_dir() / "ledgers" / "media-ledger.jsonl"


def read_media_events(path=None):
    """回 (事件清單, 壞掉的行數)。"""
    p = Path(path or media_ledger_path())
    if not p.exists():
        return [], 0
    events, bad = [], 0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(ev, dict) and ev.get("md5") and ev.get("event") in ("archived", "removed", "restored"):
            events.append(ev)
        else:
            bad += 1
    return events, bad


def fold_media(events):
    """事件 → {md5: 目前狀態}。狀態欄：status（'active'／'removed'）、name、block、year、date、type、desc、
    orig_name、size、archived_at、removed_at。同一個 md5 第二次 archived（不該發生）以第一次為準。"""
    out = {}
    for ev in events:
        m = ev["md5"]
        kind = ev["event"]
        if kind == "archived":
            if m in out:
                continue
            rec = {k: ev.get(k) for k in ("name", "block", "year", "date", "type", "desc", "orig_name", "size")}
            rec["archived_at"] = ev.get("at")
            rec["status"] = "active"
            out[m] = rec
        elif m in out:
            if kind == "removed":
                out[m]["status"] = "removed"
                out[m]["removed_at"] = ev.get("at")
            elif kind == "restored":
                out[m]["status"] = "active"
                out[m].pop("removed_at", None)
    return out


def append_media_events(events, path=None):
    """加事件（只增不改）。一次寫一整批：整批組好再 append，減少寫到一半的機會。"""
    if not events:
        return
    p = Path(path or media_ledger_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\n" for ev in events)
    with open(str(p), "a", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
