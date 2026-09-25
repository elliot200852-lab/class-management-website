#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_parent_photo.py — 家長合照＋稱謂（個人照相簿點開時跟孩子的照片並排；docs/DATA-MODEL.md §2.18）。

只有導師看得到（安全規則）。雲端只存照片（清掉 EXIF 與定位、壓縮過）與**稱謂**（母、父、祖母……），不存家長姓名；
稱謂預設取 data/parent-roles.yaml 裡那個座號的宣告，照片裡只有其中幾位就用 --who 指定。

照片從哪裡來（二選一）：
  --from-file <照片檔>        本機的一張照片（建議放 data/parent-photos/<座號>.jpg；原始檔名不會上網）
  --from-blog <文章編號>      那位孩子部落格裡、家長或導師已經發過的一篇文章裡的照片（--photo 0／1／2 選第幾張，預設 0）；
                              這個來源在預覽時就要連上網站讀照片（只讀，不寫）

用法：
  python3 scripts/publish_parent_photo.py --seat 4 --from-file data/parent-photos/04.jpg            # 預覽
  python3 scripts/publish_parent_photo.py --seat 4 --from-blog 2026-10-03-ab12cd34 --photo 1        # 預覽
  python3 scripts/publish_parent_photo.py --seat 4 --from-file data/parent-photos/04.jpg --publish  # 上線
      （座號 04 已經有家長合照、要換一張：多加 --update）
  可以加：--who 母（照片裡只有媽媽）、--note "一段只有導師看得到的備註（≤ 200 字）"
  python3 scripts/publish_parent_photo.py --remove 4 [--publish]     # 從網站拿掉座號 04 的家長合照
"""
import sys
import base64
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, images, schema, gauth  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib import preview as pv  # noqa: E402
from lib import publishing as pub  # noqa: E402
from lib import multipub as mp  # noqa: E402
from lib.seats import parse_seat  # noqa: E402
from lib.firestore_rest import SERVER_TIME  # noqa: E402
from lib.hostos import PY  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()


def relations_for(seat, who):
    """稱謂：parent-roles.yaml 那個座號的宣告；--who 指定時只能從宣告裡挑（擋打錯字）。"""
    roles = mp.parent_roles()
    declared = roles.get(seat) if roles is not None else None
    if who:
        picked = [x.strip() for x in who.replace("，", ",").replace("、", ",").split(",") if x.strip()]
        if len(set(picked)) != len(picked) or not (1 <= len(picked) <= 4) or \
                any(not (1 <= len(x) <= 10) for x in picked):
            raise pub.PublishError("--who 要是 1–4 個不重複的稱謂，用逗號分開（例如 --who 母,父）")
        if declared is not None and any(x not in declared for x in picked):
            raise pub.PublishError("--who 寫的稱謂不在 data/parent-roles.yaml 座號 %s 的宣告裡（宣告的是：%s）"
                                   % (seat, "、".join(declared) or "沒有"))
        return picked
    if declared is None:
        raise pub.PublishError(["找不到 data/parent-roles.yaml（或裡面沒有座號 %s），不知道照片裡是誰。" % seat,
                                "請老師說照片裡是誰，用 --who 指定（例如 --who 母,父）。"])
    if not declared:
        raise pub.PublishError(["data/parent-roles.yaml 裡座號 %s 沒有宣告任何家長稱謂。" % seat,
                                "請老師說照片裡是誰，用 --who 指定（例如 --who 母）。"])
    return list(declared[:4])


def photo_from_file(path_str):
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = paths.root() / p
    if not p.is_file():
        raise pub.PublishError("找不到照片檔：%s" % path_str)
    if not images.is_photo_file(p):
        raise pub.PublishError("這個檔不是支援的照片格式（jpg、png、webp、heic…）")
    if not images.have_pillow():
        raise pub.PublishError(images.pillow_help().splitlines())
    try:
        return images.process(p, "家長合照")
    except images.ImageError as e:
        raise pub.PublishError(str(e).splitlines())


def photo_from_blog(client, seat, post_id, which):
    """從那位孩子的部落格文章讀一張照片（只讀），重新處理成家長合照（再清一次中繼資料、重新壓縮）。"""
    if not schema.POST_ID_RE.match(post_id or ""):
        raise pub.PublishError("文章編號格式不對（像 2026-10-03-ab12cd34；在網站那篇文章的網址最後面）")
    if which not in ("0", "1", "2"):
        raise pub.PublishError("--photo 只能是 0、1、2（那篇文章的第 1、2、3 張照片）")
    entry = "student_blogs/%s/entries/%s" % (seat, post_id)
    doc = client.get(entry)
    if doc is None:
        raise pub.PublishError("座號 %s 的部落格裡找不到文章 %s（座號對嗎？）" % (seat, post_id))
    have = [str(x.get("pid")) for x in (doc.data.get("photos") or []) if isinstance(x, dict)]
    if which not in have:
        raise pub.PublishError("那篇文章沒有第 %d 張照片（它有 %d 張；--photo 從 0 開始數）" % (int(which) + 1, len(have)))
    img = client.get(entry + "/images/" + which)
    data = img.data.get("data") if img is not None else None
    if not isinstance(data, str) or not data:
        raise pub.PublishError("讀不到那張照片的內容")
    if not images.have_pillow():
        raise pub.PublishError(images.pillow_help().splitlines())
    try:
        raw = base64.b64decode(data, validate=True)
        return images.process_bytes(raw, "部落格文章 %s 的第 %d 張照片" % (post_id, int(which) + 1))
    except (ValueError, images.ImageError) as e:
        raise pub.PublishError(str(e).splitlines() if isinstance(e, images.ImageError) else "那張照片的資料壞掉了")


def build(seat, ph, relations, note, source_label):
    owner = "parent_photo_display/" + seat
    ph.order = 0
    doc = {"relations": relations, "note": note, "photoPids": [ph.pid], "updatedAt": SERVER_TIME}
    summary = ["座號 %s 的家長合照（%s）" % (seat, source_label),
               "稱謂：%s" % ("、".join(relations) if relations else "（沒有）"),
               "備註：%s" % (note or "（沒有）"),
               "上線後誰看得到：只有導師（家長與同仁讀不到）", pub.photo_summary([ph])]
    body = '<figure><img src="%s" alt=""><figcaption>座號 %s・%s</figcaption></figure>' % (
        pv.esc(pv.data_uri(ph.image.data)), pv.esc(seat), pv.esc("、".join(relations)))
    html = pv.page("預覽：家長合照", "座號 %s 的家長合照" % seat, ["只有導師看得到"], summary, body)
    return pub.Draft("parent-photo", seat, owner, [ph], [(owner, doc, "parent_photo_display")], summary, html)


def main(argv=None):
    ap = argparse.ArgumentParser(description="家長合照＋稱謂（導師限定；預設只預覽）")
    ap.add_argument("--seat", help="座號")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--from-file", metavar="照片檔", help="本機的一張照片")
    src.add_argument("--from-blog", metavar="文章編號", help="這位孩子部落格裡某篇文章的照片")
    ap.add_argument("--photo", default="0", help="--from-blog 用：第幾張（0、1、2；預設 0）")
    ap.add_argument("--who", help="照片裡是哪幾位（稱謂，逗號分開）；不寫＝parent-roles.yaml 裡這個座號的全部")
    ap.add_argument("--note", default="", help="只有導師看得到的備註（≤ 200 字）")
    ap.add_argument("--remove", metavar="座號", help="從網站拿掉這個座號的家長合照（搭 --publish 才真的刪）")
    pub.add_common_args(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        cfg = classcfg.load()
    except classcfg.ConfigError as e:
        return pub.fail([str(e)])
    try:
        rm = parse_seat(a.remove) if a.remove else None
        seat = parse_seat(a.seat) if a.seat else None
    except ValueError:
        return pub.fail("座號格式不對：1–40 的數字")
    if rm:
        return mp.remove("parent_photo_display/" + rm, a, cfg, "座號 %s 的家長合照" % rm,
                         "%s scripts/publish_parent_photo.py --remove %s%s" % (PY, rm, paths.rerun_flags(a)))
    if not seat or not (a.from_file or a.from_blog):
        return pub.fail(["要寫座號與照片來源，例如：",
                         "%s scripts/publish_parent_photo.py --seat 4 --from-file data/parent-photos/04.jpg" % PY])
    note = (a.note or "").strip()
    if len(note) > 200:
        return pub.fail("--note 最多 200 字")
    roster = mp.roster_seats()
    if roster is not None and seat not in roster:
        return pub.fail("座號 %s 不在名冊（data/roster.csv）裡" % seat)
    client = None
    try:
        relations = relations_for(seat, a.who)
        if a.from_blog:
            client = mp.connect(cfg, a)
            ph = photo_from_blog(client, seat, a.from_blog.strip(), str(a.photo).strip())
            label = "取自部落格文章 %s 的第 %d 張" % (a.from_blog.strip(), int(a.photo) + 1)
        else:
            ph = photo_from_file(a.from_file)
            label = "取自本機照片"
        draft = build(seat, ph, relations, note, label)
        draft.validate()
    except ValueError as e:
        return pub.fail([str(e)])
    except (fr.FirestoreError, gauth.AuthError) as e:
        print(e.plain())
        return 1
    except pub.PublishError as e:
        return pub.fail(e.lines)
    for line in draft.summary:
        print("  " + line)
    p = pub.write_preview(draft, a.open)
    print("  預覽檔：%s" % p)
    parts = ["%s scripts/publish_parent_photo.py --seat %s" % (PY, seat)]
    parts.append(("--from-blog %s --photo %s" % (a.from_blog.strip(), a.photo)) if a.from_blog
                 else "--from-file \"%s\"" % a.from_file)
    if a.who:
        parts.append("--who %s" % a.who)
    if note:
        parts.append("--note \"%s\"" % note.replace('"', "'"))
    cmd = " ".join(parts) + paths.rerun_flags(a)
    if not a.publish:
        print("\n這只是預覽，還沒上線。請老師先看預覽檔（是不是對的照片、稱謂對不對）；確認沒問題、說「上傳」之後再跑：")
        print("  %s --publish" % cmd)
        return 0
    return mp.publish_all([(draft, draft.owner)], a, cfg, cmd, noun="張")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
