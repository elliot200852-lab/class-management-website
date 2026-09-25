# 劇本：部署網站

老師會說：「部署網站」「網站更新一下」「我改了設定（班名、分類、要開哪些頁）要上線」「換了導師信箱」。

腳本：`scripts/deploy.py`。順序寫死：檢查 → 產生設定 → 安全規則 → 索引（等全部建好）→ 網站 → 部署後檢查。
**部署不動任何資料**（紀事、相簿、名單都不變）。發文、上傳相簿、同步名單**不需要**部署。

## 1. 代理要問什麼（一次一題）

1. 「這次改了什麼？」——確認真的需要部署：改了 `config/class.json`（班名、分類、頁面開關、導師信箱、Firebase 設定）、
   更新了這份程式（`git pull` 之後）才需要。只是發文就不用。
2. 部署前把計畫講給他聽（第 3 段第 2 步），問：「我可以開始部署嗎？大概要 5–15 分鐘。」

## 2. 老師去哪裡拿

- 需要兩個登入（第一次安裝時做過）：`gcloud auth login` 與 `firebase login`，**兩個都用開 Firebase 專案、也是導師信箱的那個 Google 帳號**。
- Firebase CLI、gcloud 沒裝：跑 `python3 scripts/doctor.py`，照它印的官方連結請他自己裝（不要替他裝）。

## 3. 代理要做什麼

1. 唯讀健檢（直接跑）：`python3 scripts/doctor.py --cloud`。「部署前就要過」的項目有 ✗ 就先照說明處理。
2. 印計畫（不做事，直接跑）：`python3 scripts/deploy.py`，把列出的步驟念給他聽。
3. 他同意後：
   ```
   python3 scripts/deploy.py --yes
   ```
   等索引那一步會每 20 秒回報一次，最多等 20 分鐘；這段時間什麼都不用做。
4. **任何時候都不要加 `--force`**（會刪掉線上的索引）；腳本本身也不會加。
5. 改了導師信箱：部署完接著跑名單同步（`sync-access.md`），新信箱才會進名單、舊的才會移除。

## 4. 怎麼驗證＋失敗怎麼辦

- 成功：最後「✓ 部署完成。網站：https://<專案>.firebaseapp.com」，第 5 步的檢查全部 ✓。
- 某一步失敗：腳本會停在那一步、印出指令、最後幾行輸出和「→」的可能原因。常見：
  - 「Firebase CLI 還沒登入」→ 請他跑 `firebase login`（用同一個帳號）。
  - 「權限不足」→ `firebase login:list`、`gcloud auth list` 看登入的是不是開專案的帳號。
  - 「需要的 Google API 還沒啟用」→ 照輸出裡的網址按「啟用」，等 2–3 分鐘。
  - 「等了 20 分鐘索引還沒建好」→ 索引在雲端繼續建；過一陣子跑 `python3 scripts/deploy.py --only indexes --yes` 接著等，
    READY 之後 `python3 scripts/deploy.py --only hosting --yes`。
- 單獨重跑某一步：`--only check|build|rules|indexes|functions|hosting|verify --yes`（`functions` 是選配的通知信模組；
  沒開就印「略過」）。重跑是安全的。
- 部署完請老師用手機（最好從 LINE 點網站連結 → 改用瀏覽器開）以家長帳號登入一次，確認看得到紀事與照片。
