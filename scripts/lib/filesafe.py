#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""filesafe.py — 備份與歸檔共用的檔案動作：md5、驗過才算數的複製、原子寫檔、執行鎖、移到垃圾桶。

原則：
  · 複製＝先寫到同一個資料夾裡的暫存名，再一次改名成正式檔名，**改名後重新讀檔算 md5**，
    跟來源一樣才算成功（copy_verified）。對不上就刪掉那份壞的、丟 CopyError。
    寫進雲端硬碟同步夾時，這個 md5 驗的是「這台電腦上的那一份」；上傳到雲端是雲端硬碟程式的事
    （劇本教老師看右上角圖示確認「已是最新狀態」）。
  · 台帳、設定一律原子寫（先寫暫存檔再 os.replace），寫到一半斷電也不會留下半個檔。
  · 本機原檔「驗過才移走」，而且是移到系統垃圾桶（反悔還拿得回來），不直接刪。
    Mac：~/.Trash；Windows：資源回收筒（標準庫 ctypes 呼叫 SHFileOperationW）；
    Linux：freedesktop 規格的 ~/.local/share/Trash（files＋info，檔案管理員可以還原）；
    做不到（沒權限）就搬到呼叫端指定的備援資料夾，請老師之後自己清。
"""
import os
import sys
import json
import time
import errno
import shutil
import random
import hashlib
from pathlib import Path

TMP_PREFIX = "~cmw-tmp-"


PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif", ".tif", ".tiff", ".bmp")
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp", ".webm", ".mts")
AUDIO_EXT = (".m4a", ".mp3", ".wav", ".aac", ".ogg", ".flac", ".amr", ".opus")
DOC_EXT = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".odp", ".ods", ".txt", ".md",
           ".key", ".pages", ".numbers", ".rtf", ".csv")


def media_kind(name):
    """副檔名 → 'photo'／'video'／'audio'／'doc'；不認得回 None。"""
    n = str(name).lower()
    for kind, exts in (("photo", PHOTO_EXT), ("video", VIDEO_EXT), ("audio", AUDIO_EXT), ("doc", DOC_EXT)):
        if n.endswith(exts):
            return kind
    return None


class CopyError(Exception):
    pass


def md5_file(path, chunk=1024 * 1024):
    h = hashlib.md5()
    with open(str(path), "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def md5_bytes(data):
    return hashlib.md5(data).hexdigest()


def _replace(src, dst, tries=5, sleep=time.sleep):
    """os.replace，碰到「檔案正被別的程式開著」（Windows 上雲端硬碟程式正在上傳那個檔）就等一下再試。"""
    for i in range(tries):
        try:
            os.replace(str(src), str(dst))
            return
        except PermissionError:
            if i == tries - 1:
                raise
            sleep(1.0 + i)


def _tmp_name(dst):
    return dst.parent / ("%s%06d-%s" % (TMP_PREFIX, random.randint(0, 999999), dst.name))


def write_bytes_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_name(path)
    try:
        with open(str(tmp), "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        _replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return path


def write_text_atomic(path, text):
    return write_bytes_atomic(path, text.encode("utf-8"))


def write_json_atomic(path, obj):
    return write_text_atomic(path, json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def read_json(path, default=None):
    """讀 JSON；檔案不在回 default。讀不懂 → 把壞檔改名保留（.corrupt-<時間>），回 default。"""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bad = path.with_name(path.name + ".corrupt-" + time.strftime("%Y%m%d-%H%M%S"))
        try:
            os.replace(str(path), str(bad))
        except OSError:
            pass
        return default


def copy_verified(src, dst, expected_md5=None, overwrite=False):
    """把 src 複製到 dst，讀回來比 md5。回 (md5, 這次有沒有真的複製)。

    · dst 已經存在且 md5 一樣 → 不複製（冪等）。
    · dst 已經存在但內容不同 → overwrite=False 時丟 CopyError（不蓋掉別人的檔）；True 時整份換掉。
    · expected_md5：來源應該是這個 md5（台帳記的）；對不上表示來源本身壞了 → CopyError。
    """
    src, dst = Path(src), Path(dst)
    src_md5 = md5_file(src)
    if expected_md5 and src_md5 != expected_md5:
        raise CopyError("來源檔的內容跟台帳記的不一樣（可能壞了）：%s" % src.name)
    if dst.exists():
        if dst.is_file() and md5_file(dst) == src_md5:
            return src_md5, False
        if not overwrite:
            raise CopyError("目的地已經有一個同名但內容不同的檔：%s（不會蓋掉它）" % dst.name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_name(dst)
    try:
        shutil.copyfile(str(src), str(tmp))
        _replace(tmp, dst)
    except OSError as e:
        raise CopyError("複製 %s 失敗（%s）" % (src.name, e.strerror or type(e).__name__))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    got = md5_file(dst)
    if got != src_md5:
        try:
            dst.unlink()
        except OSError:
            pass
        raise CopyError("複製後讀回來的 md5 對不上：%s（已刪掉壞的那一份）" % dst.name)
    return src_md5, True


class Mirror(object):
    """增量鏡像：本機檔 → 同步夾，只複製新的或改過的（台帳記每個相對路徑上次複製的 md5）。
    只增不刪：本機刪掉的檔，同步夾那份留著（備份的意思就是這樣）；要刪走資料退場。"""

    def __init__(self, ledger_path):
        self.ledger_path = Path(ledger_path)
        led = read_json(self.ledger_path, default={})
        self.led = led if isinstance(led, dict) else {}
        self.copied = 0
        self.checked = 0

    def sync(self, src, dst, rel):
        src, dst = Path(src), Path(dst)
        st = src.stat()
        rec = self.led.get(rel) or {}
        self.checked += 1
        if rec.get("size") == st.st_size and rec.get("mtime") == int(st.st_mtime) and rec.get("dst") == str(dst) \
                and dst.exists():
            return False
        md5, did = copy_verified(src, dst, overwrite=True)
        self.led[rel] = {"md5": md5, "size": st.st_size, "mtime": int(st.st_mtime), "dst": str(dst)}
        if did:
            self.copied += 1
        return did

    def save(self):
        write_json_atomic(self.ledger_path, self.led)


def clean_tmp(folder):
    """清掉上一次中斷留下的暫存檔（只清我們自己的暫存名）。"""
    try:
        for p in Path(folder).iterdir():
            if p.name.startswith(TMP_PREFIX) and p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass
    except OSError:
        pass


def dir_size(folder):
    total = 0
    for dirpath, _, files in os.walk(str(folder)):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return "%.1f GB" % n


# ── 執行鎖（同一個班同時只能有一個備份／歸檔在跑）─────────────────────────

class LockBusy(Exception):
    pass


class RunLock(object):
    """with RunLock(path): …   已經有人拿著鎖 → LockBusy。超過 stale_hours 的鎖當成上次當掉留下的，收回。"""

    def __init__(self, path, stale_hours=6):
        self.path = Path(path)
        self.stale = stale_hours * 3600
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, ("%d %s\n" % (os.getpid(), time.strftime("%Y-%m-%d %H:%M:%S"))).encode("ascii"))
                return self
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise
                try:
                    age = time.time() - self.path.stat().st_mtime
                except OSError:
                    continue
                if age > self.stale:
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                raise LockBusy("另一個備份或歸檔正在跑（%s 已經存在，%d 分鐘前開始）。等它跑完再試；"
                               "確定沒有別的在跑，刪掉這個檔再試。" % (self.path.name, int(age // 60)))
        raise LockBusy("拿不到執行鎖：%s" % self.path)

    def __exit__(self, *exc):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        try:
            self.path.unlink()
        except OSError:
            pass
        return False


# ── 移到垃圾桶 ─────────────────────────────────────────────────────────────

FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400


def windows_trash_flags():
    """SHFileOperationW 的旗標：可復原（進資源回收筒）、不跳確認、不跳錯誤視窗、不顯示進度。"""
    return FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI


def windows_from_field(path):
    """pFrom 要兩個 \\0 結尾（ctypes 的字串自己會補一個，這裡再補一個）。"""
    return str(path) + "\0"


def _trash_windows(path):
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = windows_from_field(os.path.abspath(str(path)))
    op.pTo = None
    op.fFlags = windows_trash_flags()
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted:
        raise OSError("SHFileOperationW 回 %s" % rc)


def _unique(dst):
    if not dst.exists():
        return dst
    stem, suf = dst.stem, dst.suffix
    stamp = time.strftime("%H%M%S")
    for i in range(1, 1000):
        cand = dst.with_name("%s %s-%d%s" % (stem, stamp, i, suf))
        if not cand.exists():
            return cand
    raise OSError("找不到可用的檔名：%s" % dst.name)


# 測試專用：設了這個環境變數，三個平台都改把檔案搬進這個資料夾（整合測試在 Windows 上也絕不碰真的資源回收筒）。
TRASH_DIR_ENV = "CMW_TRASH_DIR"


def freedesktop_trash(home=None, environ=None):
    """Linux 桌面的家目錄垃圾桶（freedesktop.org Trash 規格）：$XDG_DATA_HOME/Trash，預設 ~/.local/share/Trash。
    給 home＝一律用 <home>/.local/share/Trash（測試用假的 HOME）。"""
    env = os.environ if environ is None else environ
    if home is None:
        xdg = (env.get("XDG_DATA_HOME") or "").strip()
        base = Path(xdg) if xdg and os.path.isabs(xdg) else Path(os.path.expanduser("~")) / ".local" / "share"
    else:
        base = Path(home) / ".local" / "share"
    return base / "Trash"


def trash_files_dir(os_name, home=None, environ=None):
    """移到垃圾桶之後，檔案實際會在哪個資料夾（測試用來確認；Windows 的資源回收筒不是一般資料夾，回 None）。"""
    env = os.environ if environ is None else environ
    if (env.get(TRASH_DIR_ENV) or "").strip():
        return Path(env[TRASH_DIR_ENV])
    if os_name == "mac":
        return Path(home or os.path.expanduser("~")) / ".Trash"
    if os_name == "linux":
        return freedesktop_trash(home, env) / "files"
    return None


def trashinfo_text(abs_path, when=None):
    """freedesktop 規格的 .trashinfo 內容：Path 是 URL 編碼的絕對路徑，DeletionDate 是本地時間 YYYY-MM-DDThh:mm:ss。"""
    from urllib.parse import quote
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(when))
    return "[Trash Info]\nPath=%s\nDeletionDate=%s\n" % (quote(str(abs_path), safe="/"), stamp)


def _trash_freedesktop(path, trash):
    """照 freedesktop 規格搬進 <trash>/files，並在 <trash>/info 留一份 .trashinfo（檔案管理員的「還原」靠它）。
    先用 O_EXCL 建 .trashinfo 佔住名字，再搬檔；搬失敗就把 .trashinfo 收回。回垃圾桶裡的新路徑。"""
    files, info = trash / "files", trash / "info"
    files.mkdir(parents=True, exist_ok=True)
    info.mkdir(parents=True, exist_ok=True)
    abs_path = Path(os.path.abspath(str(path)))
    stem, suf = (path.name, "") if path.is_dir() else (path.stem, path.suffix)
    for i in range(1000):
        cand = path.name if i == 0 else "%s.%d%s" % (stem, i, suf)
        info_path = info / (cand + ".trashinfo")
        try:
            fd = os.open(str(info_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        if (files / cand).exists() or os.path.islink(str(files / cand)):
            os.close(fd)
            os.unlink(str(info_path))
            continue
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(trashinfo_text(abs_path))
            shutil.move(str(path), str(files / cand))
        except BaseException:
            try:
                os.unlink(str(info_path))
            except OSError:
                pass
            raise
        return files / cand
    raise OSError("垃圾桶裡找不到可用的檔名：%s" % path.name)


def move_to_trash(path, fallback_dir, os_name=None, home=None, environ=None):
    """把檔案（或資料夾）移到系統垃圾桶。回 ("trash", 位置說明) 或 ("fallback", 備援資料夾裡的新路徑)。

    Mac：~/.Trash；Linux：freedesktop 規格的 ~/.local/share/Trash（files＋info）；Windows：資源回收筒。
    fallback_dir：放不進垃圾桶時搬去的地方（例如 data/inbox/.archived/）；呼叫端要提醒老師之後自己清。
                  給 None＝放不進垃圾桶就丟 OSError（由呼叫端決定怎麼辦）。
    環境變數 CMW_TRASH_DIR（只給測試）：改搬進那個資料夾，不碰任何真的垃圾桶。
    """
    from . import hostos
    env = os.environ if environ is None else environ
    path = Path(path)
    osn = os_name or hostos.OS
    try:
        override = (env.get(TRASH_DIR_ENV) or "").strip()
        if override:
            box = Path(override)
            box.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(_unique(box / path.name)))
            return "trash", "測試用垃圾桶"
        if osn == "mac":
            trash = Path(home or os.path.expanduser("~")) / ".Trash"
            if trash.is_dir():
                dst = _unique(trash / path.name)
                shutil.move(str(path), str(dst))
                return "trash", "垃圾桶"
        elif osn == "linux":
            _trash_freedesktop(path, freedesktop_trash(home, env))
            return "trash", "垃圾桶"
        elif osn == "win" and sys.platform.startswith("win"):
            _trash_windows(path)
            if not path.exists():
                return "trash", "資源回收筒"
    except (OSError, AttributeError, ValueError):
        pass
    if fallback_dir is None:
        raise OSError("放不進系統垃圾桶")
    fb = Path(fallback_dir)
    fb.mkdir(parents=True, exist_ok=True)
    dst = _unique(fb / path.name)
    shutil.move(str(path), str(dst))
    return "fallback", dst
