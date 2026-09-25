#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""管理腳本測試共用的假資料（單元測試與 scripts/test_admin.py 的模擬器整合測試都用）。

全部是虛構的：學生 A～Y（座號 01–25）、家長「parent-a@example.com」這種信箱、同仁一位、私密讀者一位。
照片**不放任何圖檔在 repo 裡**：測試執行時用 Pillow 當場畫，並故意寫進 GPS 與「要轉 90 度」的 EXIF，
好驗證輸出真的把它們清掉、真的轉正。
"""
import json
from pathlib import Path

AT = "@"
DOMAIN = "example.com"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXY"
TEACHER = "class.teacher" + AT + DOMAIN
PROJECT = "demo-cmw"


def mail(local):
    return local + AT + DOMAIN


def parent_mail(i):
    return mail("parent-%s" % LETTERS[i].lower())


def config(project=PROJECT, teacher=TEACHER):
    return {
        "class_name": "示範班級",
        "school_name": "",
        "teacher": {"email": teacher, "display_name": "示範導師"},
        "students": {"count": 25},
        "seat_format": "兩位數字",
        "region": "asia-east1",
        "firebase": {"project_id": project, "api_key": "demo-api-key", "auth_domain": "", "app_id": "demo-app-id",
                     "messaging_sender_id": ""},
        "pages": {"home": True, "class_posts": True, "gallery": True, "my_child": True, "teacher_only": True,
                  "courses": True, "fun": True, "about": True},
        "categories": ["班級生活", "學習活動", "其他"],
        "calendar_ics_url": "",
        "drive": {"sync_root": ""},
        "notifications": {"enabled": False},
    }


def roster_csv(n=25):
    lines = ["座號,姓名,稱呼,備註"]
    for i in range(n):
        lines.append("%02d,學生 %s,%s," % (i + 1, LETTERS[i], LETTERS[i]))
    return "\n".join(lines) + "\n"


def contacts_csv(n=25, second_parent=(0, 1, 2), private=(0,), staff=True, drop=()):
    """每位學生一位「母」；second_parent 裡的座號多一位「父」。座號 01 的母是私密讀者。"""
    lines = ["座號,關係,姓名,Email,私密讀者,暫停,備註"]
    for i in range(n):
        if i in drop:
            continue
        lines.append("%02d,母,學生 %s 家長,%s,%s,," % (i + 1, LETTERS[i], parent_mail(i), "是" if i in private else ""))
        if i in second_parent:
            lines.append("%02d,父,學生 %s 家長2,%s,,," % (i + 1, LETTERS[i], mail("parent2-%s" % LETTERS[i].lower())))
    if staff:
        lines.append("01,同仁,示範同仁,%s,,," % mail("staff-1"))
        lines.append("03,同仁,示範同仁,%s,,," % mail("staff-1"))
    return "\n".join(lines) + "\n"


def roles_yaml(n=25, second_parent=(0, 1, 2)):
    lines = ["# 測試用"]
    for i in range(n):
        rels = ["母", "父"] if i in second_parent else ["母"]
        lines.append('"%02d": [%s]' % (i + 1, ", ".join(rels)))
    return "\n".join(lines) + "\n"


def make_jpeg(path, size=(1600, 1200), orientation=6, gps=True, seed=1):
    """畫一張有漸層與雜訊的照片，寫進 EXIF 方向與 GPS。需要 Pillow。"""
    from PIL import Image
    w, h = size
    grad = Image.linear_gradient("L").resize((w, h))
    grad2 = grad.rotate(90 * (seed % 4), expand=False).resize((w, h))
    noise = Image.effect_noise((w, h), 40 + seed)
    im = Image.merge("RGB", (grad, grad2, noise))
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x010F] = "TestCam"
    if gps:
        g = exif.get_ifd(0x8825)
        g[1] = "N"
        g[2] = (25.0, 2.0, 0.0)
        g[3] = "E"
        g[4] = (121.0, 30.0, 0.0)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    im.save(str(path), "JPEG", quality=92, exif=exif)
    return Path(path)


def write(p, text):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return p


POST_MD = """---
title: 秋天的散步
date: 2026-10-01
category: 班級生活
---
今天我們沿著學校後面的小路散步。
孩子們撿了很多落葉。

## 看到了什麼

- 紅色的葉子
- **黃色**的葉子
- 一隻*很慢*的蝸牛

![落葉堆](leaves.jpg)

> 老師說：慢慢走，才看得到。

[[video:https://www.youtube.com/watch?v=abcdefghijk|散步的影片]]

---

更多照片在[相簿](https://example.com/album)。<script>alert(1)</script>
"""

ALBUM_MD = """---
title: 運動會
date: 2026-10-02
videos:
  - 大隊接力 | https://www.youtube.com/watch?v=abcdefghijk
captions:
  - p1.jpg | 起跑
---
運動會當天的照片。
"""

BLOG_MD = """---
title: 今天的數學課
date: 2026-10-03
photos:
  - work.jpg | 作品
---
今天他在數學課上
  很專心。

謝謝！
"""

PRIVATE_MD = """---
title: 給私密讀者的說明
date: 2026-10-04
---
這一篇只有私密讀者看得到。
"""

ABOUT_MD = """---
title: 關於我們
---
我們是一個喜歡散步的班級。

## 我們的約定

1. 好好說話
2. 好好聽
"""

FUN_MD = """---
title: 專題活動
---
這裡放班上正在進行的專題活動。

## 落葉收集

大家一起收集了一百片葉子。

## 蝸牛賽跑

最慢的那隻贏了。
"""


def make_root(root, photos=True, n=25):
    """在 root 底下建一個完整的測試班級：config/class.json＋data/。回 root（Path）。"""
    root = Path(root)
    write(root / "config" / "class.json", json.dumps(config(), ensure_ascii=False, indent=2))
    d = root / "data"
    write(d / "roster.csv", roster_csv(n))
    write(d / "contacts.csv", contacts_csv(n))
    write(d / "parent-roles.yaml", roles_yaml(n))
    post = POST_MD if photos else POST_MD.replace("![落葉堆](leaves.jpg)\n", "")
    write(d / "class-posts" / "2026-10-01-autumn-walk.md", post)
    album = ALBUM_MD if photos else ALBUM_MD.replace("captions:\n  - p1.jpg | 起跑\n", "")
    write(d / "albums" / "2026-10-02-sports-day.md", album)
    blog = BLOG_MD if photos else BLOG_MD.replace("photos:\n  - work.jpg | 作品\n", "")
    write(d / "blog-drafts" / "01" / "math-day.md", blog)
    write(d / "private-posts" / "2026-10-04-note.md", PRIVATE_MD)
    write(d / "pages" / "about.md", ABOUT_MD)
    write(d / "pages" / "fun.md", FUN_MD)
    if photos:
        make_jpeg(d / "class-posts" / "2026-10-01-autumn-walk" / "leaves.jpg", seed=1)
        make_jpeg(d / "albums" / "2026-10-02-sports-day" / "p1.jpg", (1200, 900), orientation=1, seed=2)
        make_jpeg(d / "albums" / "2026-10-02-sports-day" / "p2.jpg", (900, 1200), orientation=3, seed=3)
        make_jpeg(d / "blog-drafts" / "01" / "math-day" / "work.jpg", (1000, 800), orientation=8, seed=4)
    return root
