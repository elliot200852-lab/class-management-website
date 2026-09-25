#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_site.py — 導師專用頁的兩個入口網址（資料庫 roster/links；只有導師讀得到，docs/DATA-MODEL.md §2.16）。

  --records-kit <網址>   「學生觀察與課程紀錄」卡片的按鈕：teacher-records-kit 裝好後它的網站網址
  --class-docs <網址>    「班級文件」卡片的按鈕：雲端硬碟網頁版打開 index.md 之後的網址（scripts/docs_index.py 產生那份）
  給空字串 "" ＝拿掉那個按鈕。只改你給的那一欄，另一欄不動。
  網址一律要 https:// 開頭、500 字以內；這兩個網址只有導師讀得到，但還是不要貼含孩子名字的網址。

  （config/site 那幾個值——導師稱呼、校名、人數、行事曆——由 scripts/access_sync.py 在同步名單時一起寫，不歸這支。）

用法（Windows 把 python3 換成 py -3）：
  python3 scripts/publish_site.py                                  看現在設定了什麼（唯讀）
  python3 scripts/publish_site.py --class-docs "https://…"         預覽
  python3 scripts/publish_site.py --class-docs "https://…" --apply 真的寫
exit：0＝成功（或只是看／預覽）；2＝輸入不對、什麼都沒寫；1＝寫入或讀回比對出錯。
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, gauth  # noqa: E402
from lib import blocks as blk  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

DOC = "roster/links"
FIELDS = {"records_kit": ("recordsKitUrl", "學生觀察與課程紀錄（teacher-records-kit）"),
          "class_docs": ("classDocsIndexUrl", "班級文件索引")}


def check_url(v):
    """回問題字串，沒問題回 None。空字串＝拿掉按鈕，合法。"""
    if v == "":
        return None
    if not blk.is_https(v, 500):
        return "網址要是 https:// 開頭、500 字以內、不能有空白"
    return None


def plan(current, wants):
    """回 (要寫的欄位, 問題)。current＝roster/links 現在的內容（沒有就 None）。"""
    cur = current or {}
    fields, problems = {}, []
    for opt, v in wants.items():
        if v is None:
            continue
        key, label = FIELDS[opt]
        why = check_url(v.strip())
        if why:
            problems.append("%s：%s" % (label, why))
            continue
        if cur.get(key) != v.strip() or key not in cur:
            fields[key] = v.strip()
    if fields:
        for key, _ in FIELDS.values():
            if key not in fields and key not in cur:
                fields[key] = ""
        fields["updatedAt"] = fr.SERVER_TIME
    return fields, problems


def main(argv=None):
    ap = argparse.ArgumentParser(description="導師專用頁的兩個入口網址（roster/links）；不加 --apply 只看、只預覽")
    ap.add_argument("--records-kit", metavar="網址", help="teacher-records-kit 的網站網址（\"\"＝拿掉）")
    ap.add_argument("--class-docs", metavar="網址", help="班級文件索引 index.md 在雲端硬碟網頁版的網址（\"\"＝拿掉）")
    ap.add_argument("--apply", action="store_true", help="真的寫進資料庫（老師點頭之後才加）")
    ap.add_argument("--emulator", action="store_true", help="連本機模擬器（測試用）")
    paths.add_root_arg(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        cfg = classcfg.load()
        client = fr.make_client(cfg.project_id, emulator_flag=a.emulator)
    except (classcfg.ConfigError, ValueError) as e:
        print("✗ %s" % e)
        return 2
    wants = {"records_kit": a.records_kit, "class_docs": a.class_docs}
    try:
        cur_doc = client.get(DOC)
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        return 1
    cur = cur_doc.data if cur_doc else {}
    print("導師專用頁的入口網址（只有導師看得到）：")
    for key, label in FIELDS.values():
        print("  %s：%s" % (label, cur.get(key) or "（沒有設定）"))
    if all(v is None for v in wants.values()):
        return 0
    fields, problems = plan(cur_doc.data if cur_doc else None, wants)
    if problems:
        print("✗ 什麼都沒寫：")
        for p in problems:
            print("  → " + p)
        return 2
    if not fields:
        print("已經是這樣了，不用改。")
        return 0
    print("會這樣改：")
    for key, label in FIELDS.values():
        if key in fields:
            print("  · %s → %s" % (label, fields[key] or "（拿掉按鈕）"))
    if not a.apply:
        print("\n這只是預覽，還沒寫。老師同意後再加 --apply。")
        return 0
    try:
        client.commit([client.set_write(DOC, fields, mask_fields=list(fields))], what="寫 roster/links")
        back = client.get(DOC)
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        return 1
    wrong = [k for k, v in fields.items() if v is not fr.SERVER_TIME and (back is None or back.data.get(k) != v)]
    if wrong:
        print("✗ 寫完讀回來對不上：%s。重跑同一個指令（重跑是安全的）。" % "、".join(wrong))
        return 1
    print("✓ 已寫入，讀回比對一致。導師專用頁重新整理就看得到按鈕（不用重新部署）。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
