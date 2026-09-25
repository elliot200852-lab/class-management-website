# data/courses/

三種東西：

1. **課程紀錄**：`data/courses/<單元>/records.md`（**子資料夾**），每上完一堂記一段（今天實際上了什麼、孩子整體的反應、下一堂要調整什麼）。
   開新課程單元時由 `scripts/new_block.py` 從範本（`templates/course-records.md`）建好。
   - 記的是「課」，不是「某一個孩子」：個別孩子的觀察寫在 teacher-records-kit；真的要提到孩子只寫座號、不寫名字。
   - **只留在這台電腦與備份**，不會上網站（`scripts/publish_courses.py` 只讀這一層的 md 與它同名的照片資料夾，不讀課程紀錄）。
2. **課程頁與課表**：這一層的 `courses.md`、`courses-<英數>.md`（例如 `courses-term.md`）、`schedule.md`；照片放同名資料夾。
   由 `scripts/publish_courses.py <檔名>` 預覽、`--publish` 上網站的「課程」頁。寫法見 `playbooks/courses.md`。內容不含學生個資。
3. **科任大綱的文字檔**：`syllabi/<學年>-<科目>.md`，科任老師原文逐字（個人聯絡資料、帳號資訊、學生名字一律不進來）。只留在這台電腦與備份，
   給導師與代理備課時查；家長看的是雲端硬碟 `02_分享給家長/科任課程大綱/` 的 PDF 與課程頁的卡片（`playbooks/subject-syllabus.md`）。

- **誰寫**：老師（或老師的 AI 代理照老師口述整理）。
- **備份**：`python3 scripts/backup.py records` 會把整個 `data/courses/` 備份到雲端硬碟 `01_機密（只有導師）/紀錄備份/`。
