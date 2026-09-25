# data/units/

課程單元資料：一個單元一個資料夾，`data/units/<單元>/`。

**開新的單元用 `python3 scripts/new_block.py <單元>`**（`playbooks/new-block.md`），它從範本
（`templates/unit/`）建好下面這些，已經有的檔不覆蓋：

```
data/units/<單元>/
  大綱.md          單元大綱（目標、每週安排、準備、參考資料）
  session.yaml     基本資料（名稱、學年、起訖日、上課時段、預計堂數）
  lessons/         逐堂教案：01-主題.md、02-主題.md……（開頭兩位數字＝第幾堂）
  texts/           學生文本：詩、故事、閱讀單、學習單（要印的 PDF、Word 也可以放）
```

同一個單元的**課程紀錄**在 `data/courses/<單元>/records.md`（見那個目錄的說明）。

- **誰寫**：老師（或老師的 AI 代理照老師口述整理）。
- **內容不放學生個資**：這裡是課程設計本身。個別孩子的觀察寫在老師自己的紀錄工具（`data/records/` 的說明）。
- **資料夾名稱**也是課堂檔案歸檔（`scripts/archive_media.py --block <單元>`）的資料夾名：只用一般文字，
  不能有 `/ \ : * ? " < > |`，不能有學生名字。
- **會不會上雲**：不上網站。`python3 scripts/backup.py records` 把整個資料夾備份到雲端硬碟
  `01_機密（只有導師）/紀錄備份/`（文字進壓縮檔；照片、影片、20 MB 以上的大檔另外一份一份複製）。
