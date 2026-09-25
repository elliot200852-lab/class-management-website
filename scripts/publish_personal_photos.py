#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_personal_photos.py — 導師限定的個人照相簿（family-photos.html；docs/DATA-MODEL.md §2.18）。

  來源：data/personal-photos/<座號>.<副檔名>，一位學生一張，**檔名只用座號**（01.jpg、7.png 都可以；
        不要用名字當檔名）。照片處理跟相簿同一套：依拍攝方向轉正、清掉 EXIF 與定位資訊、壓成顯示圖與縮圖兩份。
  寫到：personal_photos/<座號>（＋底下的 thumbs、images）。只有導師讀得到（安全規則），家長與同仁一律讀不到。
        原始檔名、原圖都不會上網。

用法：
  python3 scripts/publish_personal_photos.py                       # 預覽整個資料夾
  python3 scripts/publish_personal_photos.py --seat 4              # 只預覽座號 04
  python3 scripts/publish_personal_photos.py --publish             # 上線（網站上已經有、照片換過的要多加 --update）
  python3 scripts/publish_personal_photos.py --remove 4            # 看網站上有沒有座號 04 的個人照
  python3 scripts/publish_personal_photos.py --remove 4 --publish  # 從網站拿掉（本機的照片不動）
"""
import re
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, images  # noqa: E402
from lib import preview as pv  # noqa: E402
from lib import publishing as pub  # noqa: E402
from lib import multipub as mp  # noqa: E402
from lib.seats import parse_seat  # noqa: E402
from lib.firestore_rest import SERVER_TIME  # noqa: E402
from lib.hostos import PY  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

NAME_RE = re.compile(r"^(\d{1,2})\.([A-Za-z]+)$")


def folder():
    return paths.data_dir() / "personal-photos"


def scan(only_seat=None):
    """→ ({座號: 檔案}, 問題清單)。檔名不是座號的**不印檔名**（可能是孩子的名字），只說第幾個檔。"""
    d = folder()
    if not d.is_dir():
        raise pub.PublishError(["找不到 data/personal-photos/（跑一次 %s scripts/init_data.py 就會建好）" % PY])
    files = sorted((p for p in d.iterdir() if p.is_file() and images.is_photo_file(p)), key=lambda p: p.name.lower())
    found, problems, odd = {}, [], []
    for i, p in enumerate(files, 1):
        m = NAME_RE.match(p.name)
        seat = None
        if m:
            try:
                seat = parse_seat(m.group(1))
            except ValueError:
                seat = None
        if seat is None:
            odd.append(i)
            continue
        if seat in found:
            problems.append("座號 %s 有兩張照片（%s 與 %s）：留一張就好" % (seat, found[seat].name, p.name))
            continue
        found[seat] = p
    if odd:
        problems.append("有 %d 個照片檔的檔名不是座號（依檔名排序的第 %s 個）：請老師自己打開 data/personal-photos/，"
                        "把它們改名成座號（例如 07.jpg），或移出這個資料夾" % (len(odd), "、".join(str(i) for i in odd)))
    if only_seat:
        found = {k: v for k, v in found.items() if k == only_seat}
        if not found and not problems:
            problems.append("data/personal-photos/ 裡沒有座號 %s 的照片（檔名要是 %s.jpg 之類）" % (only_seat, only_seat))
    return found, problems


def build(only_seat=None):
    found, problems = scan(only_seat)
    roster = mp.roster_seats()
    if roster is not None:
        outside = [s for s in found if s not in roster]
        if outside:
            problems.append("座號 %s 不在名冊（data/roster.csv）裡：檔名打錯了，還是那位同學已經轉出？" % mp.seat_list(outside))
    if problems:
        raise pub.PublishError(problems)
    if not found:
        raise pub.PublishError(["data/personal-photos/ 裡還沒有照片。",
                                "一位學生一張，檔名只用座號（例如 01.jpg、02.jpg），放進 data/personal-photos/。"])
    if not images.have_pillow():
        raise pub.PublishError(images.pillow_help().splitlines())
    items, cells = [], []
    names = mp.roster_display()
    seats = sorted(found)
    for i, seat in enumerate(seats, 1):
        print("  處理照片 %d／%d：座號 %s" % (i, len(seats), seat))
        sys.stdout.flush()
        try:
            ph = images.process(found[seat], "座號 %s 的個人照" % seat)
        except images.ImageError as e:
            raise pub.PublishError(str(e).splitlines())
        ph.order = 0
        owner = "personal_photos/" + seat
        doc = {"photoPids": [ph.pid], "updatedAt": SERVER_TIME}
        summary = ["座號 %s：顯示圖 %s、縮圖 %s" % (seat, pub.kb(len(ph.image.data)), pub.kb(len(ph.thumb.data)))]
        items.append((pub.Draft("personal-photo", seat, owner, [ph], [(owner, doc, "personal_photos")], summary, ""),
                      owner))
        cells.append((pv.data_uri(ph.thumb.data), "座號 %s %s" % (seat, names.get(seat, ""))))
    missing = sorted(roster - set(found)) if (roster is not None and not only_seat) else []
    lines = ["個人照 %d 張：座號 %s" % (len(items), mp.seat_list(found)),
             "上線後誰看得到：只有導師（家長與同仁讀不到）", pub.photo_summary([d.photos[0] for d, _ in items])]
    if missing:
        lines.append("名冊上還沒有個人照的座號：%s" % mp.seat_list(missing))
    html = pv.page("預覽：個人照", "個人照（導師限定）", ["只有導師看得到"], lines, pv.grid_html(cells))
    return items, lines, html


def main(argv=None):
    ap = argparse.ArgumentParser(description="導師限定個人照：data/personal-photos/<座號>.jpg → 網站（預設只預覽）")
    ap.add_argument("--seat", help="只處理這個座號")
    ap.add_argument("--remove", metavar="座號", help="從網站拿掉這個座號的個人照（搭 --publish 才真的刪）")
    pub.add_common_args(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        cfg = classcfg.load()
    except classcfg.ConfigError as e:
        return pub.fail([str(e)])
    try:
        seat = parse_seat(a.seat) if a.seat else None
        rm = parse_seat(a.remove) if a.remove else None
    except ValueError:
        return pub.fail("座號格式不對：1–40 的數字")
    if rm:
        return mp.remove("personal_photos/" + rm, a, cfg, "座號 %s 的個人照" % rm,
                         "%s scripts/publish_personal_photos.py --remove %s%s" % (PY, rm, paths.rerun_flags(a)))
    try:
        items, lines, html = build(seat)
        for draft, _ in items:
            draft.validate()
    except pub.PublishError as e:
        return pub.fail(e.lines)
    for line in lines:
        print("  " + line)
    p = pub.write_preview(mp.PseudoDraft("personal-photos", seat or "all", html), a.open)
    print("  預覽檔：%s" % p)
    cmd = "%s scripts/publish_personal_photos.py%s%s" % (PY, (" --seat " + seat) if seat else "", paths.rerun_flags(a))
    if not a.publish:
        print("\n這只是預覽，還沒上線。請老師先看預覽檔（照片方向、是不是對的孩子）；確認沒問題、說「上傳」之後再跑：")
        print("  %s --publish" % cmd)
        return 0
    return mp.publish_all(items, a, cfg, cmd, noun="位")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
