# 劇本：每學年結束

老師會說：「學年結束了」「這學期結束要怎麼收」「網站要關掉了」「空間快滿了」（`status.py` 說資料庫容量超過 70% 也走這份）。

腳本：`scripts/backup.py`、`scripts/data_exit.py year-end`、`scripts/drive_init.py`。

免費方案的資料庫只有 1 GiB，一學年的照片大約用掉一半到四分之三，**第二學年累積就會滿**。所以每學年結束要選一條路：

| 選擇 | 做什麼 | 適合 |
|---|---|---|
| 封存 `archive` | 撤掉所有家長與同仁的權限（只留導師），資料留在網站上，只有你看得到 | 下學年還是帶同一班、容量還夠 |
| 只清照片 `photos` | 撤權限，再刪掉網站上的所有照片（文字留著）。原圖本來就在你的電腦與雲端硬碟，部落格照片在部落格歸檔 | 下學年繼續用同一個網站，空出容量 |
| 清空 `wipe` | 撤權限，再刪掉所有內容（紀事、相簿、部落格、名冊……） | 換班、網站要重新開始 |
| 整個專案刪除 | 在 Firebase 主控台刪專案（30 天內可以反悔） | 不再使用這個網站 |

另一條路是升級付費方案（不用改任何程式，見 `docs/DATA-MODEL.md` §5.4），那是老師自己的決定。

## 1. 代理要問什麼（一次一題）

1. 「下學年還會用這個網站嗎？是帶同一班，還是新的班？」
2. 依回答推薦一條路（上表），問「這樣可以嗎？」——**一定要老師自己選**。
3. 「學校對學生資料的保存有沒有規定幾年？」（決定這台電腦與雲端硬碟裡的備份要留多久；程式不會自動刪）

## 2. 老師去哪裡拿

- 學校的資料保存規定：問學校行政（教務處或資訊組）。
- 不用拿其他東西。

## 3. 代理要做什麼

1. 先跑一次完整備份：`python3 scripts/backup.py all`，確認三條都成功（`playbooks/backup.md`）。
   （`data_exit.py year-end --apply` 自己還會再備份一次；這一步是讓老師先看到「備份好了」再決定。）
2. 預覽（唯讀）：`python3 scripts/data_exit.py year-end --mode <archive|photos|wipe>`，把「會撤掉幾個人、會刪幾份」講給老師聽。
3. 說清楚「做完以後，家長和同仁就都進不了網站了（你自己還可以）」，老師點頭後加 `--apply`。
4. 選 `wipe` 的話，陪老師到 Firebase 主控台刪掉導師以外的所有登入帳號（`python3 scripts/where.py --open console-users`）。
5. 新學年開始：
   - `python3 scripts/drive_init.py --apply`：補建新學年的資料夾（已經有的不動）。
   - 請老師改好 `data/roster.csv`、`data/contacts.csv`、`data/parent-roles.yaml`，再照 `playbooks/sync-access.md` 同步名單。
     **在改好之前不要跑 `access_sync.py`**：它會把舊名單加回去。
   - 名單同步已經上鎖：`data_exit.py year-end --apply` 撤權限之前會立一支「學年已封存」旗標（`data/ledgers/year-end.json`）。
     旗標還在的時候，`status.py` 第一條就是「學年已封存：新學年的名單改好了嗎？」，`access_sync.py` 預覽也會先警告；
     `--apply` 要多加 `--new-roster` 才會寫。**只有老師親口確認三個名單檔都是新學年的了**，才用
     `python3 scripts/access_sync.py --apply --new-roster`；寫成功旗標就自己收掉，之後照平常的兩段式。
   - 新的課程單元照 `playbooks/new-block.md` 開。學校的學期或開學月份改了，先改 `config/class.json` 的
     `school_year`（`config/README.md`），再跑上面那一行 `drive_init.py --apply`。

## 4. 怎麼驗證＋失敗怎麼辦

- 成功：「✓ 完成：撤權限 N 份…」。跑 `python3 scripts/status.py`，容量那一行會在下一次資料庫備份後更新。
- 請老師用手機以家長帳號試登入：應該進不去。
- exit 2「備份沒有成功」：先修好備份，一筆都還沒刪。
- exit 1 或做到一半停下來：修好後再跑同一個 `--apply`，會接著做。清空一學年的照片大約要刪 3,500 份，免費方案一天可以刪 20,000 份。
- 選錯了想反悔：照 `playbooks/restore.md` 從學年結束前那一份快照還原（先預覽）。
