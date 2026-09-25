# data/blog-drafts/

導師替某位孩子發的部落格文章（「我的孩子」）的草稿：`<座號>/<草稿名>.md`，照片放 `<座號>/<草稿名>/`。
由 `scripts/publish_blog.py --seat <座號> <草稿名>` 發出去。家長自己發的文章在網站上直接發，不經過這裡。

```
data/blog-drafts/03/2026-10-03-math.md
data/blog-drafts/03/2026-10-03-math/work.jpg
```

## 檔頭與正文

```
---
title: 今天的數學課          必填，1–200 字
date: 2026-10-03            選填，預設今天
photos:                     選填：最多 3 張（請老師自己挑，不要替他選）
  - work.jpg | 作品          「檔名 | 圖說」；沒有圖說就只寫檔名，不要替老師編
---
正文逐字保留：空白、換行照原樣，不轉 Markdown（1–10,000 字）。
```

- 發過的草稿記在 `data/ledgers/blog-posts.jsonl`；同一份草稿不能再發一次（避免同一篇出現兩次）。
- 發完要改字：改好草稿後 `--publish --update`（只改標題與正文；照片發了就不能換）。
- 座號的部落格要先開（`scripts/open_blogs.py`），名單要先同步（`scripts/access_sync.py`）。
