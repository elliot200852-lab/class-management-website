# playbooks/ — 日常操作劇本

老師跟你（AI 代理）說一句話，你找到對應的劇本、照著做。對照表在 `AGENTS.md` 的「老師說什麼 → 讀哪份劇本」。

每份劇本固定四段：**代理要問什麼**、**老師去哪裡拿**、**代理要做什麼**、**怎麼驗證＋失敗怎麼辦**。

所有劇本共通的規矩（跟 `AGENTS.md` 的鐵則一起守）：

1. 開始前先跑 `python3 scripts/status.py`（Windows：`py -3 scripts/status.py`）。
2. **一次只問一題**，問完等他回答。
3. **有副作用的指令（`--apply`、`--publish`、`--update`、`deploy.py --yes`）一定先講一句「我接下來要做 X，做完會變成 Y」，等他點頭。**
   預覽、`--check`、`doctor.py` 這類唯讀的直接跑。
4. **不要自己打開 `data/roster.csv`、`data/contacts.csv`**（有學生真名與家長信箱；你的設定也擋住了）。
   要改名單就請老師自己用 Excel／Numbers 打開改；腳本的輸出只會出現座號、稱謂與遮住的信箱（`p***@gmail.com`），可以放心轉述。
5. 腳本的 exit code：`0`＝成功；`2`＝被安全閘或輸入問題擋下（**一筆都沒寫**）；`1`＝寫到一半出錯或讀回比對不一致。
   非 0 就停，把腳本印的「→」那幾行用白話轉述給老師，不要自己想辦法繞過（不要刪台帳、不要加大 `--max-deletes`、不要改腳本）。
6. 要給老師看的預覽檔或資料夾：在指令後面加 `--open`，或用 `python3 scripts/where.py --open <名稱或路徑>`
   （Windows `py -3 …`；Mac、命令提示字元、PowerShell、Git Bash 都是同一個寫法，路徑照寫 `/`，例如 `exports/preview/post-x.html`、
   `data/personal-photos`）。預覽檔（`exports/`、`data/exports/`）你自己不讀：腳本印的摘要就夠，檔案是給老師看的。
7. 老師改過的 md 檔以**磁碟上的檔案**為準：上傳前不要用你記憶裡的版本覆蓋回去。
8. 指令在 Windows 一律把 `python3` 換成 `py -3`，**斜線照寫 `/`**（例如 `py -3 scripts/status.py`）：PowerShell、命令提示字元、
   Git Bash 都看得懂 `/`；改成反斜線 `\` 在 Git Bash 裡會被吃掉。跟 `AGENTS.md` 的「平台對照」同一個寫法。

| 劇本 | 老師會說 |
|---|---|
| [sync-access.md](sync-access.md) | 同步家長名單、加一位家長、家長換信箱、學生轉出 |
| [class-post.md](class-post.md) | 發班級紀事、上傳這篇、改那篇、下架 |
| [album.md](album.md) | 上傳相簿、相簿加照片、加影片連結 |
| [private-post.md](private-post.md) | 發私密紀事、誰看得到私密紀事 |
| [open-blogs.md](open-blogs.md) | 開部落格、幫 3 號開部落格、換頭像 |
| [blog-post.md](blog-post.md) | 幫 3 號發部落格、改那篇部落格 |
| [page.md](page.md) | 改關於我們、改專題活動、改首頁那句話、做一個獨立頁面 |
| [courses.md](courses.md) | 更新課程頁、放課表、課程頁加影片或大綱卡 |
| [subject-syllabus.md](subject-syllabus.md) | 科任大綱入檔（文字檔、分享給家長的 PDF、課程頁的卡片） |
| [class-docs.md](class-docs.md) | 把文件放進班級文件、更新班級文件索引 |
| [parent-note.md](parent-note.md) | 寄給某號的家長（只在老師明講時；不寄信，只用郵件程式打開） |
| [seating.md](seating.md) | 排座位、上傳座位表（導師限定） |
| [personal-photos.md](personal-photos.md) | 上傳或更換學生個人照（導師限定） |
| [parent-photo.md](parent-photo.md) | 家長合照與稱謂（導師限定） |
| [export-pdf.md](export-pdf.md) | 把班級紀事或部落格匯出成 PDF |
| [poem.md](poem.md) | 每日一詩：選詩草稿、確認後上線 |
| [notify.md](notify.md) | 通知信（選配，要 Blaze）：留言通知、寄信給家長、每日摘要、先停 |
| [deploy.md](deploy.md) | 部署網站、網站更新、改了設定要上線 |
| [doctor.md](doctor.md) | 健檢、網站怪怪的、登入不了 |
| [backup.md](backup.md) | 備份、設定雲端硬碟、備份多久沒跑了 |
| [restore.md](restore.md) | 那篇不見了、救回來、換電腦、硬碟壞了 |
| [archive-media.md](archive-media.md) | 課程歸檔、把今天的板書照片收起來 |
| [new-block.md](new-block.md) | 開一個新的課程單元 |
| [where.md](where.md) | 我的資料在哪、打開某個資料夾 |
| [data-exit.md](data-exit.md) | 學生轉出、家長要求刪除自己的資料 |
| [year-end.md](year-end.md) | 學年結束、空間快滿了 |
| [try.md](try.md) | 先試玩、給我看看長什麼樣（模擬器，不用任何帳號） |
