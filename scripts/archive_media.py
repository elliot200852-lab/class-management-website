#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""archive_media.py — 課堂的照片、影片、音檔、文件歸檔：data/inbox/ → 同步夾「課堂檔案」。

只有導師看得到：落點是 01_機密（只有導師）/課堂檔案/<學年>/<單元>/，**從不設定任何分享**。
（要給家長看的照片走相簿 playbooks/album.md，不是這支。）

檔名一律：YYYYMMDD-<單元>-<類型>-<說明>.<原副檔名>
  · 類型只准五個：板書｜作業本｜課堂活動｜教材｜其他（鎖死，免得每次長出新說法，十年後查不到）。
  · 說明寫「內容」，**不寫人**：作業本封面常有姓名欄，一律寫成「作業本-主題」。
    說明與單元名稱會拿 data/roster.csv 的姓名、稱呼比對，撞到就擋下（只印座號，不印名字）。
  · 日期：老師指定的 → 照片的拍攝日期（EXIF，要有 Pillow）→ 檔案修改時間（會提醒）。
  · 課程單元要先用 scripts/new_block.py 開好（data/units/<單元>/ 存在），打錯字不會多出一個夾。
  · 學年照 config/class.json 的 school_year.start_month 算（依學校；沒寫是 8 月）。

流程（每個檔）：算 md5 → 台帳裡有同 md5 就跳過（老師刪掉過的也不重傳＝墓碑）→ 複製到同步夾 →
**讀回來比 md5** → 寫台帳 data/ledgers/media-ledger.jsonl → **最後**才把 inbox 的原檔移到系統垃圾桶
（Mac 垃圾桶、Windows 資源回收筒；做不到就搬到 data/inbox/.archived/，請老師之後自己清）。先驗後刪，永不顛倒。
影片一次只處理一支（大檔複製久，一次一支比較不會半途而廢）。

墓碑：每次 --apply 開頭先對帳——台帳記著、但同步夾裡已經不見的檔，記成「老師刪掉了」；之後同一個檔
再丟進 inbox 也不會重傳。老師從雲端硬碟垃圾桶救回來，下次對帳自動撤銷墓碑。

用法（Windows 把 python3 換成 py -3）：
  python3 scripts/archive_media.py
      列出 data/inbox/ 的檔（唯讀）：類型、大小、推得出的日期、是不是已經歸檔過
  python3 scripts/archive_media.py --block 範例單元 --file IMG_0012.jpg --type 板書 --desc 單元重點
      預覽一個檔（不動任何東西）；加 --date 20310303 指定日期
  python3 scripts/archive_media.py --block 範例單元 --manifest data/exports/歸檔清單.json
      預覽一批：清單是 [{"file": "IMG_0012.jpg", "type": "板書", "desc": "單元重點", "date": "20310303"}, …]
  以上兩種加 --apply 才真的歸檔。
  python3 scripts/archive_media.py --reconcile     只做墓碑對帳（寫台帳，不動 inbox）

exit code：0 成功；2 停下來了（輸入、名字、同步夾的問題，什麼都沒做）；1 做到一半失敗（已完成的檔已記台帳，重跑會跳過）。
"""
import re
import sys
import json
import argparse
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, ledgers  # noqa: E402
from lib.drivetree import (DriveTree, DriveTreeError, ensure_below, name_problem, school_year, to_date,  # noqa: E402
                           DEFAULT_START_MONTH)
from lib.filesafe import (md5_file, copy_verified, CopyError, media_kind, move_to_trash, RunLock, LockBusy,  # noqa: E402
                          human_size)
from lib import namecheck  # noqa: E402
from lib.hostos import PY  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

EXIT_STOPPED = 2
TYPES = ledgers.MEDIA_TYPES
DESC_MAX = 40
INBOX_SKIP = ("README.md",)
MASS_MISSING_MIN = 3


class Stop(Exception):
    pass


# ── 命名 ─────────────────────────────────────────────────────────────────

def build_name(date8, block, typ, desc, ext):
    """YYYYMMDD-單元-類型-說明.副檔名；任何一段不合規就丟 Stop（白話原因）。"""
    if typ not in TYPES:
        raise Stop("類型只能是：%s（收到「%s」）" % ("、".join(TYPES), typ))
    d = (desc or "").strip()
    if not d:
        raise Stop("說明是空的：寫這張是什麼內容（例如「單元重點」），不寫人")
    if len(d) > DESC_MAX:
        raise Stop("說明太長（最多 %d 字）：%s…" % (DESC_MAX, d[:10]))
    prob = name_problem(d, "說明", max_len=DESC_MAX)
    if prob:
        raise Stop(prob)
    if not re.match(r"^\d{8}$", date8 or ""):
        raise Stop("日期要寫成 YYYYMMDD（例如 20310303）")
    try:
        to_date(date8)
    except ValueError:
        raise Stop("日期不存在：%s" % date8)
    name = "%s-%s-%s-%s%s" % (date8, block, typ, d, ext.lower())
    prob = name_problem(name, "檔名", max_len=150)
    if prob:
        raise Stop(prob)
    return name


def exif_date(path):
    """照片的拍攝日期（YYYYMMDD）；沒有 Pillow、不是照片、沒有 EXIF → None。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(str(path)) as im:
            ex = im.getexif()
            v = None
            try:
                v = ex.get_ifd(0x8769).get(36867)
            except (AttributeError, KeyError, TypeError):
                v = None
            v = v or ex.get(306)
    except Exception:  # noqa: BLE001  Pillow 對壞檔會丟各種例外；推不出日期就算了
        return None
    m = re.match(r"^(\d{4}):(\d{2}):(\d{2})", str(v or ""))
    if not m:
        return None
    s = "".join(m.groups())
    try:
        to_date(s)
    except ValueError:
        return None
    return s


def guess_date(path, given=None):
    """回 (YYYYMMDD, 來源說明)。"""
    if given:
        return str(given).replace("-", ""), "老師指定"
    if media_kind(path.name) == "photo":
        d = exif_date(path)
        if d:
            return d, "照片的拍攝日期"
    try:
        t = datetime.date.fromtimestamp(path.stat().st_mtime)
        return t.strftime("%Y%m%d"), "檔案修改時間（可能是轉傳的日期，不一定是上課那天）"
    except OSError:
        return datetime.date.today().strftime("%Y%m%d"), "今天"


# ── inbox 與區塊 ─────────────────────────────────────────────────────────

def inbox_files(inbox):
    if not inbox.is_dir():
        return []
    return sorted(p for p in inbox.iterdir()
                  if p.is_file() and not p.name.startswith(".") and p.name not in INBOX_SKIP
                  and not p.name.startswith("~cmw-tmp-"))


def blocks(data):
    base = data / "units"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def check_block(data, block, needles):
    prob = name_problem(block, "單元名稱", max_len=30)
    if prob:
        raise Stop(prob)
    if needles and namecheck.find(block, needles):
        raise Stop("單元名稱裡有學生的名字（座號 %s），換一個" % "、".join(namecheck.find(block, needles)))
    have = blocks(data)
    if block not in have:
        raise Stop("還沒有「%s」這個課程單元（data/units/ 裡有：%s）。\n"
                   "  → 打錯字就改；真的是新的單元，先問老師，再跑 %s scripts/new_block.py \"%s\""
                   % (block, "、".join(have) or "（還沒有任何單元）", PY, block))


# ── 墓碑對帳 ─────────────────────────────────────────────────────────────

def reconcile(state, media_root):
    """台帳 vs 同步夾：回 (事件清單, 提醒清單)。**不寫檔**，呼叫端決定要不要寫。

    判定「老師刪掉了」的條件：那個課程夾本身還在（整個夾不見＝沒掛上或被搬走，不下結論），
    而且不是整夾一起消失（同一夾 3 個以上全部不見＝多半是同步還沒下來，也不下結論）。"""
    events, notes = [], []
    by_folder = {}
    for md5, rec in state.items():
        if not rec.get("year") or not rec.get("block") or not rec.get("name"):
            continue
        by_folder.setdefault((rec["year"], rec["block"]), []).append((md5, rec))
    now = ledgers.now_iso()
    for (year, block), items in sorted(by_folder.items()):
        folder = Path(media_root) / year / block
        if not folder.is_dir():
            if any(r["status"] == "active" for _, r in items):
                notes.append("課程夾 %s/%s 整個不見了（沒有同步下來，或被搬走），這一夾先不對帳" % (year, block))
            continue
        active = [(m, r) for m, r in items if r["status"] == "active"]
        gone = [(m, r) for m, r in active if not (folder / r["name"]).exists()]
        if len(active) >= MASS_MISSING_MIN and len(gone) == len(active):
            notes.append("課程夾 %s/%s 裡的 %d 個檔全部不見了（多半是雲端硬碟還沒同步下來），這一夾先不對帳"
                         % (year, block, len(active)))
            gone = []
        for m, r in gone:
            events.append({"event": "removed", "md5": m, "at": now, "name": r["name"]})
        for m, r in items:
            if r["status"] == "removed" and (folder / r["name"]).exists():
                events.append({"event": "restored", "md5": m, "at": now, "name": r["name"]})
    return events, notes


# ── 計畫 ─────────────────────────────────────────────────────────────────

class Item(object):
    def __init__(self, src, typ, desc, date):
        self.src, self.typ, self.desc, self.date = src, typ, desc, date
        self.kind = media_kind(src.name)
        self.md5 = None
        self.name = None
        self.date_note = ""
        self.skip = ""


def read_manifest(path, inbox):
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = paths.root() / path
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise Stop("歸檔清單讀不懂（%s）：要是 JSON 陣列 [{\"file\", \"type\", \"desc\", \"date\"}]" % type(e).__name__)
    if isinstance(raw, dict):
        raw = raw.get("items")
    if not isinstance(raw, list) or not raw:
        raise Stop("歸檔清單要是一個非空的陣列")
    out = []
    for i, r in enumerate(raw, start=1):
        if not isinstance(r, dict) or not r.get("file"):
            raise Stop("歸檔清單第 %d 項少了 file" % i)
        out.append((r["file"], r.get("type", ""), r.get("desc", ""), r.get("date")))
    return out


def plan(data, block, rows, state, needles):
    inbox = data / "inbox"
    items, seen = [], {}
    videos = 0
    for fname, typ, desc, date in rows:
        if "/" in fname or "\\" in fname:
            raise Stop("清單裡的 file 只寫 inbox 裡的檔名：%s" % fname)
        src = inbox / fname
        if not src.is_file():
            raise Stop("data/inbox/ 裡沒有 %s" % fname)
        it = Item(src, typ, desc, date)
        if it.kind is None:
            raise Stop("%s 的格式不認得（照片、影片、音檔、文件才收）" % fname)
        if it.kind == "video":
            videos += 1
        if needles is not None:
            hit = namecheck.find(desc or "", needles)
            if hit:
                raise Stop("%s 的說明裡有學生的名字（座號 %s）：說明寫內容、不寫人" % (fname, "、".join(hit)))
        d8, note = guess_date(src, date)
        it.date_note = note
        it.name = build_name(d8, block, typ, desc, src.suffix)
        it.md5 = md5_file(src)
        rec = state.get(it.md5)
        if rec and rec["status"] == "active":
            it.skip = "已經歸檔過（%s）" % rec.get("name")
        elif rec and rec["status"] == "removed":
            it.skip = "老師之前在雲端硬碟刪掉了這個檔（%s），不重傳；真的要重新歸檔，請老師明講" % rec.get("name")
        elif it.md5 in seen:
            it.skip = "跟 %s 是同一個檔" % seen[it.md5]
        seen.setdefault(it.md5, fname)
        items.append(it)
    if videos > 1:
        raise Stop("一次只處理一支影片（這批有 %d 支）：請把清單拆開，一支一支跑" % videos)
    return items


def list_inbox(data, state):
    files = inbox_files(data / "inbox")
    if not files:
        print("data/inbox/ 是空的，沒有要歸檔的檔。")
        return 0
    print("data/inbox/ 有 %d 個檔：" % len(files))
    for p in files:
        kind = media_kind(p.name)
        md5 = md5_file(p)
        rec = state.get(md5)
        st = ""
        if rec and rec["status"] == "active":
            st = "｜已經歸檔過：%s" % rec.get("name")
        elif rec:
            st = "｜老師刪掉過（不重傳）"
        d8, note = guess_date(p)
        print("  %s｜%s｜%s｜日期 %s（%s）%s" % (p.name, {"photo": "照片", "video": "影片", "audio": "音檔", "doc": "文件"}
                                           .get(kind, "不認得的格式"), human_size(p.stat().st_size), d8, note, st))
    print("\n課程單元（data/units/）：%s" % ("、".join(blocks(data)) or "（還沒有；先跑 new_block.py）"))
    print("類型只能是：%s" % "、".join(TYPES))
    print("下一步：看過每個檔的內容，問老師是哪個單元，照說明（寫內容不寫人）組清單，再跑 --block … --manifest …（先預覽）")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="課堂照片／影片／音檔／文件 → 同步夾的課堂檔案（只有導師看得到）")
    paths.add_root_arg(ap)
    ap.add_argument("--block", help="課程單元（data/units/ 裡的資料夾名）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--manifest", help="歸檔清單（JSON）")
    g.add_argument("--file", help="inbox 裡的一個檔名")
    ap.add_argument("--type", help="類型：%s" % "／".join(TYPES))
    ap.add_argument("--desc", help="說明（寫內容，不寫人）")
    ap.add_argument("--date", help="日期 YYYYMMDD（不給就用拍攝日期或檔案時間）")
    ap.add_argument("--apply", action="store_true", help="真的歸檔（先不加，看預覽）")
    ap.add_argument("--reconcile", action="store_true", help="只做墓碑對帳")
    a = ap.parse_args(argv)
    paths.apply_root(a)
    data = paths.data_dir()
    events, bad = ledgers.read_media_events()
    state = ledgers.fold_media(events)
    if bad:
        print("！ 台帳裡有 %d 行讀不懂，已略過（data/ledgers/media-ledger.jsonl）" % bad)

    if not a.block and not a.reconcile:
        if a.manifest or a.file:
            print("✗ 要加 --block <單元>")
            return EXIT_STOPPED
        return list_inbox(data, state)

    try:
        cfg = classcfg.load()
    except classcfg.ConfigError as e:
        print("✗ %s" % e)
        return EXIT_STOPPED
    tree = DriveTree.from_config(cfg.raw)
    try:
        media_root = tree.require("media")["media"]
    except DriveTreeError as e:
        print(e.plain())
        return EXIT_STOPPED

    if a.reconcile:
        evs, notes = reconcile(state, media_root)
        for n in notes:
            print("！ " + n)
        ledgers.append_media_events(evs)
        print("✓ 對帳完成：記成「老師刪掉了」%d 個、救回來 %d 個。"
              % (sum(e["event"] == "removed" for e in evs), sum(e["event"] == "restored" for e in evs)))
        return 0

    needles = namecheck.load(data)
    try:
        check_block(data, a.block, needles)
        if a.manifest:
            rows = read_manifest(a.manifest, data / "inbox")
        elif a.file:
            rows = [(a.file, a.type or "", a.desc or "", a.date)]
        else:
            raise Stop("要給 --file（一個檔）或 --manifest（一批）；不知道有哪些檔就先不加參數跑一次")
        items = plan(data, a.block, rows, state, needles)
    except Stop as e:
        print("✗ %s" % e)
        return EXIT_STOPPED
    if needles is None:
        print("！ 沒有 data/roster.csv 可以比對姓名：請自己再確認一次說明裡沒有學生的名字。")

    todo = [it for it in items if not it.skip]
    print("課堂檔案歸檔%s：單元「%s」→ 01_機密（只有導師）/課堂檔案/<學年>/%s/"
          % ("" if a.apply else "（預覽，不會動任何東西）", a.block, a.block))
    for it in items:
        if it.skip:
            print("  － %s：跳過（%s）" % (it.src.name, it.skip))
        else:
            print("  ＋ %s → %s/%s（日期來源：%s）" % (it.src.name, tree.school_year(it.name[:8]), it.name, it.date_note))
    if not a.apply:
        if todo:
            print("\n這只是預覽。老師確認檔名與單元都對，再加 --apply（歸檔後 inbox 的原檔會移到垃圾桶）。")
        return 0

    try:
        with RunLock(data / "backups" / ".lock"):
            evs, notes = reconcile(state, media_root)
            for n in notes:
                print("！ " + n)
            if evs:
                ledgers.append_media_events(evs)
                removed = {e["md5"] for e in evs if e["event"] == "removed"}
                print("  對帳：%d 個檔已經不在雲端硬碟的課程夾（記成老師刪掉了，不會重傳）" % len(removed))
                for it in todo:
                    if it.md5 in removed:
                        it.skip = "老師之前在雲端硬碟刪掉了這個檔，不重傳"
                todo = [it for it in todo if not it.skip]
            return archive(data, a.block, todo, media_root, tree.start_month)
    except LockBusy as e:
        print("✗ %s" % e)
        return EXIT_STOPPED


def archive(data, block, todo, media_root, start_month=DEFAULT_START_MONTH):
    done, failed, fallback = [], [], []
    for it in todo:
        try:
            year = school_year(it.name[:8], start_month)
            folder = ensure_below(media_root, year, block)
            dst = folder / it.name
            n = 2
            while dst.exists() and md5_file(dst) != it.md5:
                stem, suf = it.name.rsplit(".", 1) if "." in it.name else (it.name, "")
                dst = folder / ("%s-%d%s" % (stem, n, ("." + suf) if suf else ""))
                n += 1
            copy_verified(it.src, dst, expected_md5=it.md5)
            ledgers.append_media_events([{"event": "archived", "md5": it.md5, "at": ledgers.now_iso(), "name": dst.name,
                                          "block": block, "year": year, "date": it.name[:8], "type": it.typ,
                                          "desc": it.desc, "orig_name": it.src.name, "size": it.src.stat().st_size}])
            where, info = move_to_trash(it.src, data / "inbox" / ".archived")
            if where == "fallback":
                fallback.append(it.src.name)
            done.append((it.src.name, dst.name))
            print("  ✓ %s → %s/%s/%s（md5 已比對）" % (it.src.name, year, block, dst.name))
        except (CopyError, DriveTreeError, OSError) as e:
            failed.append((it.src.name, str(e)))
            print("  ✗ %s：%s（沒有寫台帳、原檔沒動）" % (it.src.name, e))
    print("\n歸檔 %d 個、失敗 %d 個。" % (len(done), len(failed)))
    if fallback:
        print("！ 有 %d 個原檔沒辦法放進系統垃圾桶，已搬到 data/inbox/.archived/：確認雲端硬碟上有了，請老師自己把那個資料夾清掉。"
              % len(fallback))
    if done:
        print("  原檔已移到垃圾桶（反悔可以從垃圾桶拿回來）。雲端硬碟程式會自己上傳；圖示顯示「已是最新狀態」才算傳完。")
    if failed:
        print("  → 失敗的檔還在 data/inbox/，修好問題後再跑同一個指令（已經歸檔的會自動跳過）。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
