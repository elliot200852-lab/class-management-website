# 劇本：個人照相簿（只有導師看得到）

老師會說：「上傳個人照」「放全班的大頭照」「換 5 號的個人照」「把 5 號的個人照拿掉」。

腳本：`scripts/publish_personal_photos.py`。照片放 `data/personal-photos/`，**一位學生一張、檔名只用座號**（`01.jpg`、`7.png`）。
寫法說明：`data/personal-photos/README.md`。放上網站後在「個人照」（導師浮鈕 →「個人照」），**只有導師看得到**，
家長與同仁一律讀不到（連自己孩子的都讀不到）。**兩段式**：預覽 → 老師說好才 `--publish`。

## 1. 代理要問什麼（一次一題）

1. 「照片準備好了嗎？一位孩子一張，檔名改成座號（01.jpg、02.jpg……），放進我幫你打開的資料夾。」
2. 放好以後：「全部都放好了嗎？還是先放一部分？」

**孩子的照片你不打開、不看**（這台電腦上的照片就是孩子的臉）。你的設定擋住了 `data/personal-photos/` 與預覽檔所在的
`exports/`（`.claude/settings.json`、`.geminiignore`、`.aiexclude` 三處）；有些代理的設定只擋得住讀檔工具，所以終端機指令、
看圖工具也一樣不要用。照片對不對、方向對不對，由老師在**他的**螢幕上看預覽檔確認。

## 2. 老師去哪裡拿

- 照片：手機或相機傳到電腦。建議直式、只有那位孩子一個人。
- 改檔名：Mac 在 Finder 點一下檔名按 Enter；Windows 在檔案總管按右鍵 →「重新命名」。**不要用孩子的名字當檔名。**
- 資料夾：你幫他打開 `data/personal-photos/`（Mac `python3 scripts/where.py --open data/personal-photos`；
  Windows `py -3 scripts/where.py --open data/personal-photos`，斜線照寫 `/`）。

## 3. 代理要做什麼

1. 預覽（唯讀，直接跑；照片多的話要一兩分鐘）：`python3 scripts/publish_personal_photos.py --open`。
   跟他確認：幾位、哪幾號還沒有照片（腳本會列座號），請他看預覽檔裡每張的方向與是不是對的孩子。
2. 他說好：「我接下來把個人照放上網站，只有你看得到，家長和同仁都看不到」，他點頭才跑
   `python3 scripts/publish_personal_photos.py --publish`。已經上過、照片一樣的會略過。
3. 換某一位的照片：請他直接換掉那個檔（檔名一樣），預覽 → 腳本會說那一號「已經在網站上、內容不一樣」→ 他同意後
   `--publish --update`（舊的那張會從網站刪掉）。只處理一位可以加 `--seat 5`。
4. 拿掉某一位（例如轉出）：`python3 scripts/publish_personal_photos.py --remove 5` 看網站上有沒有，他點頭才加 `--publish`；
   本機那張照片請他自己移到垃圾桶（學生轉出走 `playbooks/data-exit.md` 會一起處理）。

## 4. 怎麼驗證＋失敗怎麼辦

- 成功：「✓ 已上線 N 位……讀回比對一致」。請他打開「個人照」：每位孩子一格，點一位看大圖，旁邊並排家長合照
  （還沒有家長合照就是空框；家長合照走 `playbooks/parent-photo.md`）。
- exit 2：
  - 「有 N 個照片檔的檔名不是座號」→ 請他自己打開資料夾把那幾個檔改名（腳本故意不印檔名，因為可能是孩子的名字）。
  - 「座號 N 有兩張照片」→ 留一張。
  - 「座號 N 不在名冊裡」→ 檔名打錯，或那位同學已經轉出。
  - 「需要 Pillow」→ 把官方連結與那一行安裝指令給他自己貼（`AGENTS.md` 步驟 1-6）。
  - 「已經在網站上、內容不一樣」→ 問他要不要換，同意才 `--update`。
- exit 1：照「→」處理後重跑同一個指令（已經上去而且一樣的會略過）。
