#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""firestore_rest.py — 管理腳本跟 Firestore 講話的唯一出入口（REST，只用標準庫）。

docs/ARCHITECTURE.md §5.4、§6：
  · 每個請求都帶 `Authorization: Bearer <權杖>` **和** `x-goog-user-project: <專案>`。
    用「使用者」的 gcloud 權杖呼叫 Google API 時，少了第二個標頭，請求會被算到別的專案、或直接被拒。
  · 權杖由 lib/gauth.py 給，只在記憶體；這支的任何訊息都不含權杖。
  · 401 → 重拿一次權杖再試一次；429／500／502／503／504／網路斷線 → 指數退避，最多重試 5 次；
    其他錯誤轉成白話（FirestoreError.plain()），連同伺服器的原始訊息一起印（不含權杖）。
  · 模擬器模式（`FIRESTORE_EMULATOR_HOST`、`CMW_EMULATOR=1` 或腳本的 --emulator）：網址改成
    http://127.0.0.1:<埠>，權杖是 "owner"（模擬器的管理身分），其他流程完全一樣。
  · 以 IAM 身分寫入**不受安全規則管**：寫入前一定先過 lib/schema.py（欄位白名單），這支只負責搬運。

值的型別轉換（Python ↔ Firestore typed value）：
  None→nullValue、bool→booleanValue、int→integerValue（字串）、float→doubleValue、str→stringValue、
  bytes→bytesValue、list→arrayValue、dict→mapValue、Timestamp→timestampValue；
  SERVER_TIME（只能放在最上層欄位）→ 寫入轉換 REQUEST_TIME（伺服器時間）。
"""
import os
import json
import time
import random
import socket
import base64
import urllib.error
import urllib.parse
import urllib.request

from . import gauth

API_ROOT = "https://firestore.googleapis.com/v1"
DEFAULT_EMULATOR_HOST = "127.0.0.1:8080"
RETRY_STATUS = (429, 500, 502, 503, 504)
MAX_RETRIES = 5

# 一次 commit 的上限：官方 500 個寫入、請求 10 MiB。照片文件很大，所以另外限制每批最多 10 張顯示圖，
# 位元組抓 9 MiB（JSON 編碼後的長度），留餘裕。
MAX_WRITES_PER_COMMIT = 500
MAX_IMAGES_PER_COMMIT = 10
MAX_COMMIT_BYTES = 9 * 1024 * 1024


# ── 型別 ──────────────────────────────────────────────────────────────────

class _ServerTime(object):
    """寫入資料裡代表「伺服器時間」的記號（REST 的 REQUEST_TIME 轉換）。"""

    def __repr__(self):
        return "SERVER_TIME"


SERVER_TIME = _ServerTime()


class Timestamp(str):
    """從 Firestore 讀回來的時間（RFC 3339 字串）。原樣寫回去仍是 timestampValue。"""


def encode_value(v):
    if v is SERVER_TIME:
        raise ValueError("SERVER_TIME 只能放在文件最上層的欄位")
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, Timestamp):
        return {"timestampValue": str(v)}
    if isinstance(v, str):
        return {"stringValue": v}
    if isinstance(v, (bytes, bytearray)):
        return {"bytesValue": base64.b64encode(bytes(v)).decode("ascii")}
    if isinstance(v, (list, tuple)):
        vals = []
        for x in v:
            if isinstance(x, (list, tuple)):
                raise ValueError("Firestore 的陣列裡不能直接放陣列（要包一層 map）")
            vals.append(encode_value(x))
        return {"arrayValue": {"values": vals}} if vals else {"arrayValue": {}}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {str(k): encode_value(x) for k, x in v.items()}}}
    raise ValueError("不支援的型別：%s" % type(v).__name__)


def decode_value(v):
    if "nullValue" in v:
        return None
    if "booleanValue" in v:
        return bool(v["booleanValue"])
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "timestampValue" in v:
        return Timestamp(v["timestampValue"])
    if "stringValue" in v:
        return v["stringValue"]
    if "bytesValue" in v:
        return base64.b64decode(v["bytesValue"])
    if "arrayValue" in v:
        return [decode_value(x) for x in (v["arrayValue"] or {}).get("values", [])]
    if "mapValue" in v:
        return decode_fields((v["mapValue"] or {}).get("fields", {}))
    if "referenceValue" in v:
        return v["referenceValue"]
    if "geoPointValue" in v:
        return dict(v["geoPointValue"])
    raise ValueError("看不懂的 Firestore 值：%s" % sorted(v))


def encode_fields(data):
    """dict → (fields, 伺服器時間欄位清單)。SERVER_TIME 只准出現在最上層。"""
    fields, transforms = {}, []
    for k, v in data.items():
        if v is SERVER_TIME:
            transforms.append(str(k))
        else:
            fields[str(k)] = encode_value(v)
    return fields, transforms


def decode_fields(fields):
    return {k: decode_value(v) for k, v in (fields or {}).items()}


class Doc(object):
    """讀回來的一份文件。path＝相對 documents/ 的路徑（例如 posts/2026-01-01-x）。"""

    __slots__ = ("path", "data", "update_time")

    def __init__(self, path, data, update_time=None):
        self.path = path
        self.data = data
        self.update_time = update_time

    @property
    def id(self):
        return self.path.rsplit("/", 1)[-1]

    def __repr__(self):
        return "Doc(%r)" % self.path


# ── 錯誤 ──────────────────────────────────────────────────────────────────

class FirestoreError(Exception):
    """一次失敗的請求。plain() 給老師與代理看：一句話發生什麼事＋下一步＋伺服器原始訊息（不含權杖）。"""

    def __init__(self, http_status, status, reason, message, title, hints, what=""):
        super().__init__(title)
        self.http_status = http_status
        self.status = status or ""
        self.reason = reason or ""
        self.server_message = message or ""
        self.title = title
        self.hints = list(hints)
        self.what = what

    def plain(self):
        lines = ["✗ " + self.title]
        if self.what:
            lines.append("  （在做的事：%s）" % self.what)
        lines += ["  → " + h for h in self.hints]
        if self.server_message:
            lines.append("  伺服器原始訊息（HTTP %s %s）：%s"
                         % (self.http_status or "-", self.status or "", self.server_message[:500]))
        return "\n".join(lines)


def explain(http_status, status, reason, message, emulator=False):
    """HTTP 狀態＋Google 錯誤碼 → (一句話, [下一步...])。"""
    low = (message or "").lower()
    if http_status is None:
        if emulator:
            return ("連不上本機的 Firestore 模擬器。", ["確認模擬器有在跑（firebase emulators:start 或 emulators:exec）。"])
        return ("連不上 Google 的伺服器。", ["檢查網路（能不能開網頁）；學校網路擋東西的話換手機熱點試試。",
                                        "網路恢復後再跑一次同一個指令就好（重跑是安全的）。"])
    if http_status == 401 or status == "UNAUTHENTICATED":
        return ("gcloud 的登入無效或過期了。", ["請老師在終端機跑：gcloud auth login（用開 Firebase 專案的那個 Google 帳號）。"])
    if http_status == 403 or status == "PERMISSION_DENIED":
        if reason in ("SERVICE_DISABLED", "API_DISABLED") or "has not been used in project" in low or "is disabled" in low:
            return ("這個專案還沒啟用 Firestore（或需要的 Google API）。",
                    ["到 Firebase 主控台 → 左邊「Firestore Database」→ 建立資料庫（地區選跟 config/class.json 的 region 一樣）。",
                     "如果已經建了，照下面伺服器原始訊息裡的網址按「啟用」，等 2–3 分鐘再跑一次。"])
        if reason in ("USER_PROJECT_DENIED",) or "serviceusage" in low or "user project" in low:
            return ("你登入 gcloud 的帳號不能使用這個專案。",
                    ["跑 gcloud auth list 看目前登入的是哪個帳號。",
                     "要用「開這個 Firebase 專案的那個 Google 帳號」：gcloud auth login，登入後再跑一次。",
                     "也確認 config/class.json 的 firebase.project_id 沒有打錯。"])
        return ("權限不足：gcloud 登入的帳號沒有這個專案的權限。",
                ["跑 gcloud auth list 看目前登入的帳號是不是開 Firebase 專案的那一個；不是就 gcloud auth login 換帳號。",
                 "確認 config/class.json 的 firebase.project_id 是你自己的專案。",
                 "學校帳號的話，可能是學校的管理員政策擋住了（見 AGENTS.md「學校帳號被鎖住怎麼判斷」）。"])
    if http_status == 404 or status == "NOT_FOUND":
        return ("找不到這個專案或資料庫。",
                ["確認 config/class.json 的 firebase.project_id 沒有打錯。",
                 "確認已經在 Firebase 主控台建立了 Firestore 資料庫（左邊「Firestore Database」）。"])
    if http_status == 429 or status == "RESOURCE_EXHAUSTED":
        return ("今天的免費額度用完了（或短時間內請求太多）。",
                ["Spark 免費方案每天寫入 20,000 次、讀取 50,000 次，台灣時間下午 4 點左右重置。",
                 "等額度恢復再跑同一個指令（重跑是安全的）；常常碰到的話可以升級方案（docs/DATA-MODEL.md §5.4）。"])
    if status == "FAILED_PRECONDITION" or http_status == 409 or status == "ALREADY_EXISTS" or status == "ABORTED":
        if "index" in low:
            return ("資料庫的索引還沒建好。", ["部署索引後要等幾分鐘；跑 python3 scripts/doctor.py --cloud 看索引狀態。"])
        return ("資料庫拒絕了這次寫入（文件的狀態跟預期不同，例如已經存在）。",
                ["多半是同一件事被跑了兩次；先確認網站上的內容，再決定要不要重跑。"])
    if http_status == 400 or status == "INVALID_ARGUMENT":
        return ("資料庫說資料格式不對（這多半是程式的問題，不是老師做錯）。",
                ["把這段訊息原樣回報給維護這份程式的人；不要自己改資料庫。"])
    if http_status in RETRY_STATUS:
        return ("Google 的伺服器暫時沒回應。", ["過幾分鐘再跑同一個指令（重跑是安全的）。"])
    return ("資料庫回了一個沒預期到的錯誤。", ["把這段訊息原樣回報；不要自己改資料庫。"])


def _parse_error(body_bytes):
    try:
        j = json.loads(body_bytes.decode("utf-8", "replace"))
    except ValueError:
        return "", "", (body_bytes or b"")[:300].decode("utf-8", "replace")
    if isinstance(j, list) and j:
        j = j[0]
    err = j.get("error", {}) if isinstance(j, dict) else {}
    reason = ""
    for d in err.get("details", []) or []:
        if isinstance(d, dict) and d.get("reason"):
            reason = d["reason"]
            break
    return err.get("status", ""), reason, err.get("message", "")


# ── 路徑 ─────────────────────────────────────────────────────────────────

def check_path(path, kind="doc"):
    """文件路徑（偶數段）或集合路徑（奇數段）；擋空段、.、..、斜線以外的怪東西。"""
    if not isinstance(path, str) or not path or path.startswith("/") or path.endswith("/"):
        raise ValueError("路徑格式不對：%r" % (path,))
    segs = path.split("/")
    for s in segs:
        if not s or s in (".", "..") or len(s.encode("utf-8")) > 1500 or "\n" in s:
            raise ValueError("路徑格式不對：%r" % (path,))
    if kind == "doc" and len(segs) % 2 != 0:
        raise ValueError("這不是文件路徑（段數要是偶數）：%r" % (path,))
    if kind == "collection" and len(segs) % 2 != 1:
        raise ValueError("這不是集合路徑（段數要是奇數）：%r" % (path,))
    return segs


def _quote_path(path):
    return "/".join(urllib.parse.quote(s, safe="") for s in path.split("/"))


# ── 分批 ─────────────────────────────────────────────────────────────────

def _is_image_write(w):
    name = (w.get("update") or {}).get("name") or w.get("delete") or ""
    return "/images/" in name and "update" in w


def split_writes(writes, max_writes=MAX_WRITES_PER_COMMIT, max_images=MAX_IMAGES_PER_COMMIT,
                 max_bytes=MAX_COMMIT_BYTES):
    """把寫入清單照順序切成好幾次 commit（順序不變）。單一寫入就超過位元組上限 → ValueError。"""
    batches, cur, cur_bytes, cur_images = [], [], 0, 0
    for w in writes:
        size = len(json.dumps(w, ensure_ascii=False).encode("utf-8")) + 2
        if size > max_bytes:
            raise ValueError("單一文件太大，一次請求放不下（%d 位元組）" % size)
        img = 1 if _is_image_write(w) else 0
        if cur and (len(cur) + 1 > max_writes or cur_bytes + size > max_bytes or cur_images + img > max_images):
            batches.append(cur)
            cur, cur_bytes, cur_images = [], 0, 0
        cur.append(w)
        cur_bytes += size
        cur_images += img
    if cur:
        batches.append(cur)
    return batches


# ── 用哪個目標（雲端或模擬器）──────────────────────────────────────────

def emulator_host_from_env(flag=False, environ=None):
    """回模擬器的 host:port；不是模擬器模式回 None。"""
    env = os.environ if environ is None else environ
    host = (env.get("FIRESTORE_EMULATOR_HOST") or "").strip()
    if host:
        return host
    if flag or (env.get("CMW_EMULATOR") or "").strip() in ("1", "true", "yes"):
        return DEFAULT_EMULATOR_HOST
    return None


def _is_local_host(host):
    h = host.rsplit(":", 1)[0].strip("[]").lower()
    return h in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


# ── HTTP 傳輸（單元測試換成假的）─────────────────────────────────────────

def urllib_transport(method, url, headers, body, timeout):
    """回 (http 狀態, 回應位元組)；連不上回 (None, 錯誤說明位元組)。"""
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        try:
            data = e.read()
        except (OSError, ValueError):
            data = b""
        return e.code, data
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
        return None, (type(e).__name__).encode("utf-8")


class Client(object):
    """Firestore REST 客戶端。

    project_id    老師自己的專案（config/class.json 的 firebase.project_id）
    emulator_host 模擬器 host:port；給了就走模擬器（權杖 "owner"），不給就走雲端
    tokens        gauth.TokenProvider（不給就自己建一個）
    transport     HTTP 傳輸（不給用 urllib）
    sleep         退避時用的等待函式（測試換成假的）
    """

    def __init__(self, project_id, emulator_host=None, tokens=None, transport=None, sleep=None,
                 timeout=120, max_retries=MAX_RETRIES, rng=None):
        if not project_id:
            raise ValueError("沒有專案 id")
        self.project_id = project_id
        self.emulator = bool(emulator_host)
        if self.emulator and not _is_local_host(emulator_host):
            raise ValueError("模擬器只准在這台電腦（127.0.0.1／localhost）：%s" % emulator_host)
        if not self.emulator and project_id.startswith("demo-"):
            raise ValueError("demo- 開頭的專案只存在模擬器裡；要測試請加 --emulator（或啟動模擬器）")
        self.emulator_host = emulator_host
        self.api_root = ("http://%s/v1" % emulator_host) if self.emulator else API_ROOT
        self.db = "projects/%s/databases/(default)" % project_id
        self.tokens = tokens or gauth.TokenProvider(emulator=self.emulator)
        self.transport = transport or urllib_transport
        self.sleep = sleep or time.sleep
        self.timeout = timeout
        self.max_retries = max_retries
        self.rng = rng or random.Random()
        self.request_count = 0

    def describe_target(self):
        if self.emulator:
            return "本機模擬器 %s（專案 %s；不會碰到雲端）" % (self.emulator_host, self.project_id)
        return "雲端 Firestore（專案 %s）" % self.project_id

    # ── 低階 ──
    def _headers(self):
        return {
            "Authorization": "Bearer " + self.tokens.token(),
            "x-goog-user-project": self.project_id,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        }

    def request(self, method, rel, body=None, params=None, what="", timeout=None, ok_404=False):
        """發一個請求。rel 是 v1/ 之後的路徑（已編碼）。回 (http 狀態, JSON)；404 且 ok_404 時回 (404, None)。"""
        url = "%s/%s" % (self.api_root, rel)
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        refreshed = False
        attempt = 0
        while True:
            self.request_count += 1
            status, raw = self.transport(method, url, self._headers(), data, timeout or self.timeout)
            if status is not None and 200 <= status < 300:
                if not raw:
                    return status, {}
                try:
                    return status, json.loads(raw.decode("utf-8"))
                except ValueError:
                    raise FirestoreError(status, "", "", "回應不是 JSON", "資料庫的回應看不懂。",
                                         ["過幾分鐘再試一次；一直這樣就回報。"], what)
            if status == 404 and ok_404:
                return 404, None
            if status == 401 and not refreshed and not self.emulator:
                refreshed = True
                self.tokens.refresh()
                continue
            if (status is None or status in RETRY_STATUS) and attempt < self.max_retries:
                delay = (2 ** attempt) * (1.0 + 0.25 * self.rng.random())
                attempt += 1
                self.sleep(delay)
                continue
            if status is None:
                gstatus, reason, message = "", "", (raw or b"").decode("utf-8", "replace")
            else:
                gstatus, reason, message = _parse_error(raw or b"")
            title, hints = explain(status, gstatus, reason, message, emulator=self.emulator)
            raise FirestoreError(status, gstatus, reason, message, title, hints, what)

    def name(self, path):
        check_path(path, "doc")
        return "%s/documents/%s" % (self.db, path)

    def _rel_docs(self, path=""):
        return "%s/documents%s" % (self.db, ("/" + _quote_path(path)) if path else "")

    def _doc_from(self, raw):
        prefix = self.db + "/documents/"
        name = raw.get("name", "")
        path = name[len(prefix):] if name.startswith(prefix) else name
        return Doc(path, decode_fields(raw.get("fields", {})), raw.get("updateTime"))

    # ── 讀 ──
    def get(self, path, mask=None):
        """讀一份文件；不存在回 None。mask＝只拿這幾個欄位（例如照片只拿 w、h，不下載 data）。"""
        check_path(path, "doc")
        params = [("mask.fieldPaths", f) for f in mask] if mask else None
        status, j = self.request("GET", self._rel_docs(path), params=params, what="讀 %s" % path, ok_404=True)
        if status == 404:
            return None
        return self._doc_from(j)

    def batch_get(self, paths, mask=None):
        """一次讀很多份：回 {path: Doc 或 None}。"""
        out = {}
        paths = list(paths)
        for i in range(0, len(paths), 100):
            chunk = paths[i:i + 100]
            body = {"documents": [self.name(p) for p in chunk]}
            if mask:
                body["mask"] = {"fieldPaths": list(mask)}
            _, j = self.request("POST", self._rel_docs() + ":batchGet", body=body, what="一次讀 %d 份文件" % len(chunk))
            prefix = self.db + "/documents/"
            for item in j if isinstance(j, list) else []:
                if "found" in item:
                    d = self._doc_from(item["found"])
                    out[d.path] = d
                elif "missing" in item:
                    n = item["missing"]
                    out[n[len(prefix):] if n.startswith(prefix) else n] = None
        for p in paths:
            out.setdefault(p, None)
        return out

    def list_docs(self, collection_path, mask=None, page_size=300):
        """列出一個集合底下所有文件（只含真的存在的）。"""
        check_path(collection_path, "collection")
        out, token = [], None
        while True:
            params = [("pageSize", str(page_size))]
            if token:
                params.append(("pageToken", token))
            if mask:
                params += [("mask.fieldPaths", f) for f in mask]
            _, j = self.request("GET", self._rel_docs(collection_path), params=params,
                                what="列出 %s" % collection_path)
            for raw in (j or {}).get("documents", []) or []:
                out.append(self._doc_from(raw))
            token = (j or {}).get("nextPageToken")
            if not token:
                return out

    def list_collection_ids(self, doc_path):
        check_path(doc_path, "doc")
        out, token = [], None
        while True:
            body = {"pageSize": 100}
            if token:
                body["pageToken"] = token
            _, j = self.request("POST", self._rel_docs(doc_path) + ":listCollectionIds", body=body,
                                what="列出 %s 底下的子集合" % doc_path)
            out += (j or {}).get("collectionIds", []) or []
            token = (j or {}).get("nextPageToken")
            if not token:
                return out

    def run_query(self, parent_path, collection_id, where=(), order_by=(), limit=None, all_descendants=False):
        """結構化查詢。where：[(欄位, '==', 值)]；order_by：[(欄位, 'asc'|'desc')]。parent_path 空字串＝根。"""
        if parent_path:
            check_path(parent_path, "doc")
        ops = {"==": "EQUAL", "<": "LESS_THAN", "<=": "LESS_THAN_OR_EQUAL", ">": "GREATER_THAN",
               ">=": "GREATER_THAN_OR_EQUAL"}
        q = {"from": [{"collectionId": collection_id, "allDescendants": bool(all_descendants)}]}
        filters = [{"fieldFilter": {"field": {"fieldPath": f}, "op": ops[op], "value": encode_value(v)}}
                   for f, op, v in where]
        if len(filters) == 1:
            q["where"] = filters[0]
        elif filters:
            q["where"] = {"compositeFilter": {"op": "AND", "filters": filters}}
        if order_by:
            q["orderBy"] = [{"field": {"fieldPath": f}, "direction": "DESCENDING" if d == "desc" else "ASCENDING"}
                            for f, d in order_by]
        if limit:
            q["limit"] = int(limit)
        _, j = self.request("POST", self._rel_docs(parent_path) + ":runQuery", body={"structuredQuery": q},
                            what="查詢 %s" % collection_id)
        return [self._doc_from(item["document"]) for item in (j or []) if isinstance(item, dict) and "document" in item]

    # ── 寫 ──
    def set_write(self, path, data, must_not_exist=False, mask_fields=None):
        """整份寫入（replace）；mask_fields＝只改這幾個欄位（其他欄位保留）。"""
        fields, transforms = encode_fields(data)
        w = {"update": {"name": self.name(path), "fields": fields}}
        if mask_fields is not None:
            w["updateMask"] = {"fieldPaths": [f for f in mask_fields if f not in transforms]}
        if transforms:
            w["updateTransforms"] = [{"fieldPath": f, "setToServerValue": "REQUEST_TIME"} for f in transforms]
        if must_not_exist:
            w["currentDocument"] = {"exists": False}
        return w

    def delete_write(self, path):
        return {"delete": self.name(path)}

    def commit(self, writes, what="寫入"):
        if not writes:
            return {}
        _, j = self.request("POST", self._rel_docs() + ":commit", body={"writes": list(writes)}, what=what,
                            timeout=max(self.timeout, 300))
        return j

    def commit_all(self, writes, what="寫入", progress=None):
        """照順序分批 commit。回 commit 次數。"""
        batches = split_writes(writes)
        for i, b in enumerate(batches):
            self.commit(b, what="%s（第 %d／%d 批，%d 個寫入）" % (what, i + 1, len(batches), len(b)))
            if progress:
                progress(i + 1, len(batches), len(b))
        return len(batches)

    def delete_recursive(self, doc_path, writes_out=None):
        """REST 沒有遞迴刪除：先列子集合逐層刪到底，再刪自己。回刪除的文件路徑清單（先子後父）。"""
        order = []
        for cid in self.list_collection_ids(doc_path):
            for d in self.list_docs(doc_path + "/" + cid, mask=["__name__"]):
                order += self.delete_recursive(d.path)
        order.append(doc_path)
        if writes_out is None:
            self.commit_all([self.delete_write(p) for p in order], what="刪除 %s" % doc_path)
        else:
            writes_out += [self.delete_write(p) for p in order]
        return order

    # ── 管理 API（唯讀；doctor.py --cloud、deploy.py 用）──
    def get_database(self):
        _, j = self.request("GET", self.db, what="讀資料庫設定")
        return j

    def list_indexes(self):
        out, token = [], None
        while True:
            params = [("pageSize", "200")] + ([("pageToken", token)] if token else [])
            _, j = self.request("GET", self.db + "/collectionGroups/-/indexes", params=params, what="列出索引")
            out += (j or {}).get("indexes", []) or []
            token = (j or {}).get("nextPageToken")
            if not token:
                return out

    def list_field_overrides(self):
        out, token = [], None
        while True:
            params = [("filter", "indexConfig.usesAncestorConfig:false"), ("pageSize", "200")]
            if token:
                params.append(("pageToken", token))
            _, j = self.request("GET", self.db + "/collectionGroups/-/fields", params=params, what="列出欄位索引設定")
            out += (j or {}).get("fields", []) or []
            token = (j or {}).get("nextPageToken")
            if not token:
                return out


def make_client(project_id, emulator_flag=False, environ=None, **kw):
    """依環境決定雲端或模擬器。"""
    host = emulator_host_from_env(emulator_flag, environ)
    return Client(project_id, emulator_host=host, **kw)


def strip_times(data, keys=("updatedAt", "publishedAt", "createdAt")):
    """比對內容時拿掉時間欄（每次寫都會變）。"""
    return {k: v for k, v in data.items() if k not in keys}
