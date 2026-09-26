#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fsbackup.py — 把整個 Firestore 匯出成 JSON（保留型別）、存成快照、照片增量、寫回去。

**保留型別**：匯出的是 REST 回傳的原始欄位（stringValue、integerValue、timestampValue、geoPointValue、
referenceValue、bytesValue……原樣），寫回去也原樣送出，所以還原後逐欄相等（模擬器整合測試驗）。

怎麼走遍整個資料庫（只用有文件的 REST 方法，不用集合群組或無種類查詢）：
  1. 根目錄 listCollectionIds → 最上層集合。
  2. 每個集合 listDocuments（showMissing=true：底下有子集合、但本身已被刪掉的「空殼文件」也列得到，
     才不會漏掉它底下的資料）。
  3. 每份文件再 listCollectionIds 往下走。**例外**：DATA-MODEL 規定沒有子集合的「葉子集合」
     （LEAF_COLLECTIONS：照片、正文、留言、回條、對話串）不再往下問——這幾種文件佔了資料庫的大半，
     每份都問一次會多出上萬個請求。規則的預設拒絕保證瀏覽器寫不出新的子集合；新增集合要先改 DATA-MODEL，
     那時也要回來檢查這張表。

照片增量（DATA-MODEL §5.2：1 GB 的資料庫每天全抓一次，一個月就是 30 GiB 流量）：
  · 照片文件（thumbs、images）只列「名稱＋更新時間」（mask），**只有新的或改過的才下載**。
  · 下載的照片存進「照片池」：一份照片文件一個 JSON 檔，檔名＝sha256(路徑)[:32]-sha256(更新時間)[:8]。
    路徑一樣、內容改過（更新時間不同）就是新檔；舊檔不動。
  · 照片池**只增不減**（不自動清）：自動清理算錯一次就是永久少一張照片。資料退場時才照路徑精準刪
    （purge_pool_paths）。一學年的照片池大約就是資料庫裡照片的大小（DATA-MODEL §5.2：幾百 MB）。
  · 每份快照只有：documents.jsonl（照片以外的全部文件）、photos.jsonl（照片的路徑、池裡的檔名、md5）、
    manifest.json（工具標記、專案、各檔 md5）。
"""
import os
import re
import json
import time
import shutil
import hashlib
from pathlib import Path

from . import firestore_rest as fr
from .filesafe import (write_bytes_atomic, md5_file, md5_bytes, copy_verified, CopyError, clean_tmp)

PHOTO_COLLECTIONS = frozenset(("thumbs", "images"))
LEAF_COLLECTIONS = frozenset(("thumbs", "images", "content", "comments", "reads", "blog_comments", "sent"))
TOOL_TAG = "class-management-website backup.py firestore v1"
SNAP_RE = re.compile(r"^\d{8}-\d{6}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
POOL_RE = re.compile(r"^[0-9a-f]{32}-[0-9a-f]{8}\.json$")
DOCS_FILE = "documents.jsonl"
PHOTOS_FILE = "photos.jsonl"
MANIFEST = "manifest.json"
SNAP_FILES = (DOCS_FILE, PHOTOS_FILE, MANIFEST)


class SnapshotError(Exception):
    pass


def snapshot_id(t=None):
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(t))


def free_snapshot_id(taken, t=None):
    """還沒被用掉的代號（同一秒內跑兩次時往後推一秒）。taken(代號) → 是否已經有了。"""
    t = time.time() if t is None else t
    while True:
        sid = snapshot_id(t)
        if not taken(sid):
            return sid
        t += 1


def month_of(snap_id):
    return "%s-%s" % (snap_id[0:4], snap_id[4:6])


def pool_prefix(path):
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:32]


def pool_key(path, update_time):
    return pool_prefix(path) + "-" + hashlib.sha256(str(update_time or "").encode("utf-8")).hexdigest()[:8]


def is_photo_path(path):
    segs = path.split("/")
    return len(segs) >= 4 and len(segs) % 2 == 0 and segs[-2] in PHOTO_COLLECTIONS


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def mask_path(path):
    """印給老師或代理看的文件路徑：名單、回條的 doc id 是 email 鍵，遮成 p***@example.com。"""
    out = []
    for s in str(path).split("/"):
        if "@" in s:
            local, _, dom = s.partition("@")
            s = "%s***@%s" % (local[:1], dom)
        out.append(s)
    return "/".join(out)


# ── 走遍資料庫 ─────────────────────────────────────────────────────────────

class Export(object):
    def __init__(self):
        self.docs = []        # [{"path","fields","createTime","updateTime"}]（照片以外）
        self.photos = []      # [{"path","updateTime","createTime"}]（照片：只有名稱與時間）
        self.phantoms = []    # 本身不存在、底下有子集合的路徑

    def doc_map(self):
        return {d["path"]: d for d in self.docs}


class Walker(object):
    def __init__(self, client, progress=None):
        self.c = client
        self.progress = progress
        self.prefix = client.db + "/documents/"

    def _rel(self, name):
        return name[len(self.prefix):] if name.startswith(self.prefix) else name

    def root_collections(self):
        out, token = [], None
        while True:
            body = {"pageSize": 300}
            if token:
                body["pageToken"] = token
            _, j = self.c.request("POST", self.c._rel_docs() + ":listCollectionIds", body=body, what="列出最上層的集合")
            out += (j or {}).get("collectionIds", []) or []
            token = (j or {}).get("nextPageToken")
            if not token:
                return sorted(out)

    def collection_ids(self, doc_path):
        return sorted(self.c.list_collection_ids(doc_path))

    def list_raw(self, coll, mask=None, show_missing=False, page_size=300):
        fr.check_path(coll, "collection")
        out, token = [], None
        while True:
            params = [("pageSize", str(page_size))]
            if token:
                params.append(("pageToken", token))
            if mask:
                params += [("mask.fieldPaths", f) for f in mask]
            if show_missing:
                params.append(("showMissing", "true"))
            _, j = self.c.request("GET", self.c._rel_docs(coll), params=params, what="列出 %s" % coll)
            out += (j or {}).get("documents", []) or []
            token = (j or {}).get("nextPageToken")
            if not token:
                return out

    def walk(self, roots=None, names_only=False):
        """回 Export。roots＝只走這幾個集合路徑（例如只要 student_blogs）；None＝全部。
        names_only＝只要路徑不要內容（資料退場列「要刪哪些」用，讀取次數一樣、流量小很多）。"""
        ex = Export()
        queue = list(roots) if roots is not None else self.root_collections()
        n = 0
        while queue:
            coll = queue.pop(0)
            cid = coll.rsplit("/", 1)[-1]
            if cid in PHOTO_COLLECTIONS:
                for raw in self.list_raw(coll, mask=["__name__"]):
                    ex.photos.append({"path": self._rel(raw["name"]), "updateTime": raw.get("updateTime", ""),
                                      "createTime": raw.get("createTime", "")})
                continue
            leaf = cid in LEAF_COLLECTIONS
            for raw in self.list_raw(coll, mask=["__name__"] if names_only else None, show_missing=not leaf):
                path = self._rel(raw["name"])
                if "createTime" in raw:
                    ex.docs.append({"path": path, "fields": raw.get("fields", {}) or {},
                                    "createTime": raw.get("createTime", ""), "updateTime": raw.get("updateTime", "")})
                else:
                    ex.phantoms.append(path)
                if not leaf:
                    for sub in self.collection_ids(path):
                        queue.append(path + "/" + sub)
                n += 1
                if self.progress and n % 500 == 0:
                    self.progress(n)
        ex.docs.sort(key=lambda d: d["path"])
        ex.photos.sort(key=lambda d: d["path"])
        return ex


def batch_get_raw(client, paths_):
    """一次讀幾份文件的原始欄位：{路徑: 原始文件或 None}。"""
    prefix = client.db + "/documents/"
    out = {}
    body = {"documents": [client.name(p) for p in paths_]}
    _, j = client.request("POST", client._rel_docs() + ":batchGet", body=body, what="讀 %d 份照片文件" % len(paths_))
    for item in j if isinstance(j, list) else []:
        if "found" in item:
            n = item["found"]["name"]
            out[n[len(prefix):] if n.startswith(prefix) else n] = item["found"]
        elif "missing" in item:
            n = item["missing"]
            out[n[len(prefix):] if n.startswith(prefix) else n] = None
    for p in paths_:
        out.setdefault(p, None)
    return out


# ── 照片池 ────────────────────────────────────────────────────────────────

class Pool(object):
    """照片池：local（本機 data/backups/firestore/photos/）＋ sync（同步夾 05_全站備份/firestore/photos/，可以沒有）。"""

    def __init__(self, local_dir, sync_dir=None):
        self.local = Path(local_dir)
        self.sync = Path(sync_dir) if sync_dir else None
        self._sync_names = None

    def sync_names(self):
        if self._sync_names is None:
            self._sync_names = set()
            if self.sync is not None and self.sync.is_dir():
                try:
                    self._sync_names = {n for n in os.listdir(str(self.sync)) if POOL_RE.match(n)}
                except OSError:
                    self._sync_names = set()
        return self._sync_names

    def local_file(self, key):
        return self.local / (key + ".json")

    def has(self, key):
        return self.local_file(key).exists() or (key + ".json") in self.sync_names()

    def save(self, raw, key):
        data = _dumps({"path": raw["path"], "createTime": raw.get("createTime", ""),
                       "updateTime": raw.get("updateTime", ""), "fields": raw.get("fields", {}) or {}}).encode("utf-8")
        write_bytes_atomic(self.local_file(key), data)
        return md5_bytes(data)

    def find(self, key):
        p = self.local_file(key)
        if p.exists():
            return p
        if self.sync is not None:
            q = self.sync / (key + ".json")
            if q.exists():
                return q
        return None

    def load(self, key):
        p = self.find(key)
        if p is None:
            raise SnapshotError("照片池裡找不到 %s（本機與同步夾都沒有）" % key)
        return json.loads(p.read_text(encoding="utf-8"))

    def md5(self, key):
        p = self.find(key)
        return md5_file(p) if p else None

    def push(self, key, md5=None):
        """本機池 → 同步夾池（驗 md5）。同步夾已經有 → 不動。回 True＝這次有複製。"""
        name = key + ".json"
        if self.sync is None:
            return False
        if name in self.sync_names():
            return False
        src = self.local_file(key)
        if not src.exists():
            raise CopyError("本機照片池少了 %s，同步夾也沒有：這張照片沒辦法備份" % name)
        copy_verified(src, self.sync / name, expected_md5=md5)
        self.sync_names().add(name)
        return True


def fetch_photos(client, refs, pool, known_md5=None, progress=None):
    """照片增量：池裡沒有的才下載。回照片列 [{"path","updateTime","key","md5"}]（下載途中被刪掉的照片略過）。"""
    known = dict(known_md5 or {})
    rows, todo = [], []
    for r in refs:
        key = pool_key(r["path"], r["updateTime"])
        if pool.has(key):
            rows.append({"path": r["path"], "updateTime": r["updateTime"], "key": key, "md5": known.get(key) or pool.md5(key)})
        else:
            todo.append(r)
    done = 0
    for kind, size in (("images", 8), ("thumbs", 50)):
        part = [r for r in todo if r["path"].split("/")[-2] == kind]
        for i in range(0, len(part), size):
            chunk = part[i:i + size]
            got = batch_get_raw(client, [r["path"] for r in chunk])
            for r in chunk:
                raw = got.get(r["path"])
                if raw is None:
                    continue
                raw = dict(raw, path=r["path"])
                ut = raw.get("updateTime", r["updateTime"])
                key = pool_key(r["path"], ut)
                md5 = pool.save(raw, key)
                rows.append({"path": r["path"], "updateTime": ut, "key": key, "md5": md5})
            done += len(chunk)
            if progress:
                progress(done, len(todo))
    rows.sort(key=lambda x: x["path"])
    return rows, len(todo)


# ── 快照 ────────────────────────────────────────────────────────────────

def write_snapshot(base_dir, snap_id, project, export, photo_rows, kind="regular", created=""):
    """寫一份本機快照 base_dir/<id>/（先寫 <id>.partial 再改名，寫到一半不會留下像樣的快照）。"""
    base_dir = Path(base_dir)
    final = base_dir / snap_id
    tmp = base_dir / (snap_id + ".partial")
    if final.exists():
        raise SnapshotError("快照 %s 已經存在" % snap_id)
    if tmp.exists():
        shutil.rmtree(str(tmp))
    tmp.mkdir(parents=True)
    docs_text = "".join(_dumps(d) + "\n" for d in export.docs)
    photos_text = "".join(_dumps(r) + "\n" for r in photo_rows)
    (tmp / DOCS_FILE).write_bytes(docs_text.encode("utf-8"))
    (tmp / PHOTOS_FILE).write_bytes(photos_text.encode("utf-8"))
    manifest = {
        "tool": TOOL_TAG, "id": snap_id, "project": project, "kind": kind, "created": created,
        "counts": {"documents": len(export.docs), "photos": len(photo_rows), "phantoms": len(export.phantoms)},
        "files": {DOCS_FILE: md5_bytes(docs_text.encode("utf-8")), PHOTOS_FILE: md5_bytes(photos_text.encode("utf-8"))},
        "phantoms": export.phantoms[:200],
    }
    (tmp / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")
    os.replace(str(tmp), str(final))
    return final, manifest


def read_manifest(snap_dir):
    p = Path(snap_dir) / MANIFEST
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict) or m.get("tool") != TOOL_TAG:
        return None
    return m


def load_snapshot(snap_dir):
    """回 (manifest, 文件清單, 照片列清單)。各檔 md5 對不上 → SnapshotError。"""
    snap_dir = Path(snap_dir)
    m = read_manifest(snap_dir)
    if m is None:
        raise SnapshotError("%s 不是這個工具做的快照（沒有 manifest.json 或標記不對）" % snap_dir.name)
    out = {}
    for name in (DOCS_FILE, PHOTOS_FILE):
        p = snap_dir / name
        if not p.exists():
            raise SnapshotError("快照 %s 少了 %s" % (snap_dir.name, name))
        data = p.read_bytes()
        if md5_bytes(data) != (m.get("files") or {}).get(name):
            raise SnapshotError("快照 %s 的 %s 內容跟 manifest 記的 md5 不一樣（檔案壞了）" % (snap_dir.name, name))
        out[name] = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    return m, out[DOCS_FILE], out[PHOTOS_FILE]


def list_snapshots(base_dir):
    """本機快照：[(id, 路徑)]，舊的在前。只認名字對、manifest 有本工具標記的（別人的資料夾不碰）。"""
    base_dir = Path(base_dir)
    out = []
    if not base_dir.is_dir():
        return out
    for p in sorted(base_dir.iterdir()):
        if p.is_dir() and SNAP_RE.match(p.name) and read_manifest(p) is not None:
            out.append((p.name, p))
    return out


def list_sync_snapshots(snap_root):
    """同步夾 snapshots/YYYY-MM/<id>/：[(id, 路徑)]，舊的在前。"""
    snap_root = Path(snap_root)
    out = []
    if not snap_root.is_dir():
        return out
    for month in sorted(snap_root.iterdir()):
        if not (month.is_dir() and MONTH_RE.match(month.name)):
            continue
        for p in sorted(month.iterdir()):
            if p.is_dir() and SNAP_RE.match(p.name) and read_manifest(p) is not None:
                out.append((p.name, p))
    out.sort(key=lambda x: x[0])
    return out


def prune(entries, keep):
    """entries＝list_snapshots／list_sync_snapshots 的結果（只含本工具的快照）。留最新 keep 份，刪其餘。
    回刪掉的 id。空掉的 YYYY-MM 夾順手收掉（裡面還有別的東西就不動）。"""
    if keep < 1:
        raise ValueError("至少要留 1 份")
    doomed = entries[:-keep] if len(entries) > keep else []
    gone = []
    for sid, p in doomed:
        shutil.rmtree(str(p))
        gone.append(sid)
        parent = p.parent
        if MONTH_RE.match(parent.name):
            try:
                parent.rmdir()
            except OSError:
                pass
    return gone


def clean_partials(base_dir):
    base_dir = Path(base_dir)
    if not base_dir.is_dir():
        return
    for p in base_dir.iterdir():
        if p.is_dir() and p.name.endswith(".partial") and SNAP_RE.match(p.name[:-8]):
            shutil.rmtree(str(p), ignore_errors=True)


def push_snapshot(snap_dir, sync_snap_root, sync_latest):
    """本機快照 → 同步夾 snapshots/YYYY-MM/<id>/ 與 latest/（每個檔驗 md5；manifest 最後寫）。"""
    from .drivetree import ensure_below
    snap_dir = Path(snap_dir)
    sid = snap_dir.name
    dst = ensure_below(sync_snap_root, month_of(sid), sid)
    clean_tmp(dst)
    for name in SNAP_FILES:
        copy_verified(snap_dir / name, dst / name, overwrite=True)
    clean_tmp(sync_latest)
    for name in (DOCS_FILE, PHOTOS_FILE, MANIFEST):
        copy_verified(snap_dir / name, Path(sync_latest) / name, overwrite=True)
    return dst


def find_snapshot(ident, local_base, sync_snap_root=None, sync_latest=None):
    """找快照：'latest'＝本機最新（沒有就同步夾 latest/），或指定 id（本機先、同步夾後）。回路徑或 None。"""
    local = list_snapshots(local_base)
    regular = [(i, p) for i, p in local if (read_manifest(p) or {}).get("kind") == "regular"]
    if ident == "latest":
        if regular:
            return regular[-1][1]
        if sync_latest and read_manifest(sync_latest) is not None:
            return Path(sync_latest)
        return None
    for i, p in local:
        if i == ident:
            return p
    if sync_snap_root:
        for i, p in list_sync_snapshots(sync_snap_root):
            if i == ident:
                return p
    return None


# ── 還原 ────────────────────────────────────────────────────────────────

def select_paths(paths_, only=()):
    """only＝路徑前綴（例如 posts/2026-10-01-x）；那份文件本身與它底下全部都算。"""
    if not only:
        return list(paths_)
    pre = [o.strip("/") for o in only if o.strip("/")]
    return [p for p in paths_ if any(p == o or p.startswith(o + "/") for o in pre)]


LIST_COLLECTIONS = frozenset(("allowlist", "private_allowlist", "parent_child_map"))
VIS_FIELDS = ("visible", "status")


def is_list_path(path):
    """名單類文件（誰進得了網站）：還原預設不寫，名單一律由 access_sync.py 照本機名單檔對帳。"""
    return str(path).split("/", 1)[0] in LIST_COLLECTIONS


def is_hidden(fields):
    """原始欄位（REST 格式）：下架（visible:false）或收起（status:'hidden'）。"""
    f = fields or {}
    return f.get("visible") == {"booleanValue": False} or f.get("status") == {"stringValue": "hidden"}


def keep_visibility(snap_fields, cur_fields):
    """覆蓋既有文件時，visible／status 留現在的值（快照之後才下架、收起的，還原不會自動重新上架）。"""
    out = dict(snap_fields or {})
    for f in VIS_FIELDS:
        if f in (cur_fields or {}):
            out[f] = cur_fields[f]
    return out


def restore_writes(client, snap_docs, snap_photos, pool, current_docs, current_photos, only=(),
                   include_lists=False, restore_visibility=False):
    """算出還原要寫哪些文件：只寫「現在不在」或「內容不同」的；**不刪任何文件**（快照之後新增的保留原樣）。
    名單類（LIST_COLLECTIONS）預設不寫（include_lists 才寫）；覆蓋既有文件時 visible／status 留現在的值
    （restore_visibility 才照快照）。
    回 (寫入清單, {'create', 'overwrite', 'same', 'lists'（沒寫的名單類）, 'kept_hidden'（留著下架的）,
    'revealed'（會重新變可見的）})。寫入順序：深的先（照片、正文、留言），
    摘要文件最後（跟發文一樣：列表上看得到的時候，底下的東西一定都在）。"""
    snap = {d["path"]: d["fields"] for d in snap_docs}
    snap_ph = {r["path"]: r["key"] for r in snap_photos}
    cur = {d["path"]: d["fields"] for d in current_docs}
    cur_ph = {r["path"]: r["key"] for r in current_photos}
    chosen = set(select_paths(list(snap) + list(snap_ph), only))
    lists = sorted(p for p in chosen if is_list_path(p))
    if not include_lists:
        chosen -= set(lists)
        skipped_lists = lists
    else:
        skipped_lists = []
    create, overwrite, same = [], [], 0
    kept_hidden, revealed = [], []
    fields_of = {}
    for p in chosen:
        if p in snap:
            want = snap[p]
            if p in cur:
                if not restore_visibility:
                    want = keep_visibility(snap[p], cur[p])
                if is_hidden(cur[p]) and not is_hidden(snap[p]):
                    (revealed if restore_visibility else kept_hidden).append(p)
            if p not in cur and p not in cur_ph:
                create.append(p)
            elif cur.get(p) != want:
                overwrite.append(p)
            else:
                same += 1
                continue
            fields_of[p] = want
        else:
            key = snap_ph[p]
            if p in cur_ph and cur_ph[p] == key:
                same += 1
                continue
            doc = pool.load(key)
            if p in cur_ph:
                try:
                    now = pool.load(cur_ph[p])
                except SnapshotError:
                    now = None
                if now is not None and now.get("fields") == doc.get("fields"):
                    same += 1
                    continue
                overwrite.append(p)
            else:
                create.append(p)
            fields_of[p] = doc.get("fields", {}) or {}
    order = sorted(fields_of, key=lambda p: (-p.count("/"), p))
    writes = [{"update": {"name": client.name(p), "fields": fields_of[p]}} for p in order]
    return writes, {"create": sorted(create), "overwrite": sorted(overwrite), "same": same, "lists": skipped_lists,
                    "kept_hidden": sorted(kept_hidden), "revealed": sorted(revealed)}


EXIT_SEAT_OWNERS = ("student_blogs", "parent_photo_display", "personal_photos")


def _seat_in_fields(path, fields):
    """名冊、座位表這兩種「一份文件放全班」的文件裡有沒有列到某些座號：回列到的座號集合。"""
    segs = path.split("/")
    d = fr.decode_fields(fields or {})
    found = set()
    if path == "roster/students":
        found = {str((s or {}).get("seat")) for s in d.get("students") or [] if isinstance(s, dict)}
    elif segs[0] == "seating" and len(segs) == 2:
        for r in d.get("rows") or []:
            if isinstance(r, dict):
                found |= {str(s) for s in r.get("seats") or []}
    return found


def exit_hits(snap_docs, snap_photos, chosen, exits):
    """快照裡、這次選中要還原的路徑，有哪些屬於已退場的人（ledgers.read_exits() 的紀錄，呼叫端先挑出比快照晚的）：
    座號（部落格、個人照、家長合照、通知佇列、名冊與座位表裡的那一格）、email 鍵（路徑裡的 reads/{key}、名單、
    sent/{hash}）、作者代號（留言、部落格文章與對話的 authorAlias）。year-end 紀錄＝全部都算。回排序好的路徑清單。"""
    chosen = set(chosen)
    if not exits or not chosen:
        return []
    if any(e.get("kind") == "year-end" for e in exits):
        return sorted(chosen)
    from .ledgers import exit_hash
    seats = set()
    keys, aliases = set(), set()
    for e in exits:
        seats |= set(e.get("seats") or [])
        keys |= set(e.get("keyHashes") or [])
        aliases |= set(e.get("aliasHashes") or [])
    hits = set()
    fields = {d["path"]: d.get("fields") or {} for d in snap_docs if d["path"] in chosen}
    # 全部快照文件（不只這次選中的）：作者代號屬於退場的人的文件路徑。文章底下的照片（thumbs／images）、
    # 對話串本身不帶作者代號，要靠「祖先文件是他寫的」才認得出來（--only 只挑照片子路徑也一樣擋）。
    owned = set()
    if aliases:
        for d in snap_docs:
            alias = ((d.get("fields") or {}).get("authorAlias") or {}).get("stringValue")
            if alias and exit_hash(alias) in aliases:
                owned.add(d["path"])

    def by_exited_author(path):
        segs = path.split("/")
        return any("/".join(segs[:i]) in owned for i in range(2, len(segs) + 1, 2))
    for p in chosen:
        segs = p.split("/")
        if len(segs) >= 2 and segs[0] in EXIT_SEAT_OWNERS and segs[1] in seats:
            hits.add(p)
        elif len(segs) >= 2 and segs[0] == "blog_notify_queue" and segs[1].split("__", 1)[0] in seats:
            hits.add(p)
        elif keys and any(s in keys or exit_hash(s) in keys for s in segs[1::2]):
            hits.add(p)
        elif owned and by_exited_author(p):
            hits.add(p)
        elif p in fields and seats and (_seat_in_fields(p, fields[p]) & seats):
            hits.add(p)
    return sorted(hits)


# ── 孤兒照片（部落格文章底下、文章 photos 清單沒列到的照片文件）──────────────────────
# 規則為了存取次數預算，照片寫入不檢查「同一批真的有那篇文章」（DATA-MODEL §1.6）：家長可以在自己座號底下
# 寫出沒有文章、或文章 photos 清單沒列到的照片文件。網頁上看不到，只佔容量；正常使用（整批一次成功或一次失敗）
# 不會產生，所以出現了多半是有人繞過網頁直接寫。

def blog_photo_owner(path):
    """student_blogs/{seat}/entries/{postId}/{thumbs|images}/{pid} → (座號, postId, 文章路徑, pid)；不是就 None。"""
    segs = str(path).split("/")
    if len(segs) == 6 and segs[0] == "student_blogs" and segs[2] == "entries" and segs[4] in PHOTO_COLLECTIONS:
        return segs[1], segs[3], "/".join(segs[:4]), segs[5]
    return None


def entry_pids(photos):
    """文章的 photos 欄位（已解碼的 list）→ 列到的 pid 集合。"""
    return {str((ph or {}).get("pid")) for ph in (photos or []) if isinstance(ph, dict) and ph.get("pid") is not None}


def find_orphan_photos(entries, photo_paths):
    """entries＝{文章路徑: 列到的 pid 集合}（只放真的存在的文章）；photo_paths＝照片文件路徑。
    回孤兒照片路徑（排序好）：文章不存在，或 pid 不在文章的 photos 清單裡。"""
    out = []
    for p in photo_paths:
        o = blog_photo_owner(p)
        if o is None:
            continue
        _, _, entry, pid = o
        if entry not in entries or pid not in entries[entry]:
            out.append(p)
    return sorted(out)


def entries_from_docs(docs):
    """快照或匯出的文件（原始欄位）→ find_orphan_photos 要的 {文章路徑: pid 集合}。"""
    out = {}
    for d in docs:
        segs = d["path"].split("/")
        if len(segs) == 4 and segs[0] == "student_blogs" and segs[2] == "entries":
            out[d["path"]] = entry_pids(fr.decode_fields(d.get("fields") or {}).get("photos"))
    return out


def mask_post_id(post_id):
    """印給人看的 postId：日期留著，後面的隨機碼只留第一個字。"""
    s = str(post_id)
    return s[:12] + "***" if len(s) > 12 else s


def orphan_summary(orphans, size_of=None):
    """孤兒照片統計（只有座號、數量、估算大小、遮住的 postId；不含內容）：
    {"count", "bytes", "seats": {座號: {"count", "bytes", "posts": [遮住的 postId…（最多 3 個）]}}}。
    size_of(路徑) → 位元組數或 None（例如照片池裡那個檔的大小）。"""
    seats = {}
    total = 0
    for p in orphans:
        seat, post_id, _, _ = blog_photo_owner(p)
        n = (size_of(p) if size_of else None) or 0
        s = seats.setdefault(seat, {"count": 0, "bytes": 0, "posts": []})
        s["count"] += 1
        s["bytes"] += n
        total += n
        m = mask_post_id(post_id)
        if m not in s["posts"] and len(s["posts"]) < 3:
            s["posts"].append(m)
    return {"count": len(orphans), "bytes": total, "seats": seats}


def purge_pool_paths(pool_dirs, doc_paths):
    """資料退場：把照片池裡這些照片文件的**所有版本**刪掉（本機與同步夾）。回刪掉的檔數。"""
    prefixes = {pool_prefix(p) for p in doc_paths if is_photo_path(p)}
    n = 0
    for d in pool_dirs:
        if d is None or not Path(d).is_dir():
            continue
        for name in os.listdir(str(d)):
            if POOL_RE.match(name) and name[:32] in prefixes:
                try:
                    (Path(d) / name).unlink()
                    n += 1
                except OSError:
                    pass
    return n
