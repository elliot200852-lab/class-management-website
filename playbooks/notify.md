# 劇本：通知信（v1.1 選配模組）——新留言寄給你、老師發文 30 分鐘後寄給家長、每日摘要

老師會說：「有人留言要通知我」「家長發文我想馬上知道」「我發部落格要寄信給家長」「每日摘要」「通知信先停」「通知信健檢」。

腳本：`scripts/notify_setup.py`（安裝檢查表，只看不改）、`scripts/deploy.py --only functions`（部署）、
`scripts/notify_config.py`（開關，資料庫 `config/notify`）。程式在 `functions/`（Cloud Functions 第 2 代，Node.js 22）。

## 0. 先講清楚（第一次裝之前，一定要照這一節念給老師聽，他同意了才往下）

- **這是選配**：不裝，網站照常運作；只是沒有通知信。
- **會寄什麼**：
  1. 有人在紀事、相簿、私密紀事留言 → 馬上寄一封給你（你自己的留言不寄）。
  2. 家長在「我的孩子」發文、在文章底下回話 → 馬上寄一封給你。
  3. 你（導師）在某個孩子的部落格發文或回覆 → **等 30 分鐘**才寄給那個孩子的家長，一位家長一封。這 30 分鐘是你的反悔時間：
     文章下架、刪掉、回覆收起，就整筆取消，家長什麼都不會收到。
  4. 每天早上一封摘要：昨天的新留言、家長發的文與對話、要處理的事（名單對不起來、備份太久沒做、通知寄不出去）。沒事的日子不寄。
- **信裡只有座號、標題、連結**，不夾留言與文章內容、不寫孩子姓名；家長要登入網站才看得到內容。
  但標題是你自己取的：標題裡有孩子名字，信裡就會有。信一旦寄出就不受網站的規定保護。
- **只寄給用 Google 帳號對到座號的家長**（也就是看得到「我的孩子」的那些人）；用信箱連結登入的家長收不到部落格通知。
- **要升級成 Blaze（隨用隨付）方案、綁信用卡**。通知信要把程式放到 Google 的伺服器上跑，免費的 Spark 方案不能放。
  一個班的用量通常落在免費額度內（2026 年的官方價目：Cloud Functions 每月 200 萬次呼叫免費、Cloud Scheduler 每個帳單帳戶
  3 個排程免費——這裡用 2 個、Secret Manager 6 個密碼版本免費、Artifact Registry 0.5 GB 免費；**以官方頁為準**：
  <https://firebase.google.com/pricing>、<https://cloud.google.com/functions/pricing>、<https://cloud.google.com/scheduler/pricing>）。
  **一定要設預算警示**；警示只會寄信提醒，**不會自動停止收費**。
- **寄件帳號**：用一個 Gmail 帳號加上「應用程式密碼」寄信。學校配發的帳號常被管理員關掉兩步驟驗證或應用程式密碼，
  那就請老師另外開一個專門寄班級通知的個人 Gmail。一般 Gmail 一天大約可以寄 500 封。
- 這套程式**依現狀提供**，作者沒有在真的雲端上跑過它（只在模擬器裡驗過），第一次打開要先用「預演」模式（dryrun）試一兩天。

## 1. 代理要問什麼（一次一題）

1. 念完第 0 節：「要裝通知信嗎？要的話，第一步是把專案升級成 Blaze 並設預算警示。」
2. 「通知信要用哪一個 Gmail 寄？就是等一下要產生應用程式密碼的那個帳號。」（跟導師信箱一樣就不用填；不一樣就寫進
   `notifications.gmail_address`，家長回信會回到導師信箱。）
3. 「家長收到的信，寄件人要顯示什麼名字？信尾要怎麼署名？」（不填：寄件人「〈稱呼〉（〈班名〉）」、署名「〈班名〉 〈稱呼〉」。
   不要放學校全名與孩子的名字。）
4. 「每日摘要要幾點寄？」（預設早上 7 點，台灣時間。）

## 2. 老師去哪裡拿

- **升級 Blaze＋預算警示**：照 `AGENTS.md`「免費方案的額度與升級」一節（主控台左下角「升級」→ Blaze；再到
  <https://console.cloud.google.com/billing> 設預算，例如每月 US$5）。
- **應用程式密碼**（官方說明 <https://support.google.com/accounts/answer/185833>）：
  1. 用寄件的那個 Gmail 登入 <https://myaccount.google.com/signinoptions/two-step-verification>，先打開「兩步驟驗證」。
  2. 到 <https://myaccount.google.com/apppasswords>，名稱打「班級網站通知」，按「建立」，畫面會出現 16 個字母（四組）。
  3. **這串字不要貼給 AI 代理、不要存在任何檔案裡**；下一步直接貼進 Google 的 Secret Manager。
  4. 看不到「應用程式密碼」→ 兩步驟驗證沒開，或學校管理員關掉了：改用個人 Gmail。
- **把密碼放進 Secret Manager**（老師**自己**在他的終端機打；Mac「終端機」、Windows「命令提示字元」）：
  ```
  firebase functions:secrets:set CMW_GMAIL_APP_PASSWORD --project <專案 ID>
  ```
  問要不要啟用 Secret Manager API → 打 y；問值（Enter a value）→ 貼上那 16 個字母（畫面不會顯示）→ Enter。
  以後換密碼（例如改了 Gmail 密碼，應用程式密碼會失效）就重打一次這一行，再部署一次。
- **裝 functions 的套件**（老師**自己**在他的終端機打；`notify_setup.py` 會印出這一行、含完整路徑）：
  `npm ci --prefix "<這個資料夾>/functions"`，看到 `added … packages` 就好。版本照 `functions/package-lock.json` 釘死
  （官方的 Firebase 套件，加上寄信用的 nodemailer）。最後幾行如果有黃字的 `npm warn`（例如說有新版 npm、某個套件已經不維護）
  可以不理：只要有 `added … packages`、沒有紅字的 `npm error`，就是裝好了。

## 3. 代理要做什麼

**裝**（每一步做完跑一次 `python3 scripts/notify_setup.py`，照它的「下一步」走；Windows 用 `py -3`）：

1. 老師同意後改 `config/class.json` 的 `notifications`：`enabled: true`，第 1 節問到的 `gmail_address`、`sender_name`、
   `signature`、`digest_hour`（`time_zone` 保持 `Asia/Taipei`）→ `build_config.py --check` → `build_config.py`
   （會產生 `functions/cmw.generated.json`，裡面沒有任何信箱）。
2. 請老師做第 2 節的三件事：升 Blaze、放應用程式密碼、裝套件。做完跑 `notify_setup.py --cloud`（唯讀），前 3 項雲端檢查
   （Blaze、密碼有放、……）要過；「Functions 部署了沒」現在 ✗ 是正常的。
3. 部署：`python3 scripts/deploy.py --only functions`（印計畫）→ 跟老師說「我要把通知信程式放上你的 Firebase 專案，
   第一次大約 5–10 分鐘」→ 他點頭 → `python3 scripts/deploy.py --only functions --yes`。
   - 第一次部署會自動啟用幾個 Google 服務（Cloud Functions、Cloud Build、Artifact Registry、Cloud Run、Eventarc、Pub/Sub、
     Cloud Scheduler、Secret Manager），要等幾分鐘。
   - 它會在最後說「could not set up cleanup policy」：**這是第一次部署一定會遇到的**，腳本會接著自動補設清理政策
     （舊的程式映像檔留 1 天就刪，不會一直累積費用）。**任何指令都不加 `--force`**。
4. `notify_setup.py --cloud`：Functions 七支都在、清理政策設好了。
5. 打開預演：`python3 scripts/notify_config.py --phase dryrun`（預覽）→ 老師點頭 → 加 `--apply`。
   預演＝給你自己的信照寄、給家長的信**只記錄不寄**。打開那一刻之前建立的留言、文章一律不寄（通知起始線）。
6. 試一次：請老師用家長測試帳號在一篇紀事底下留一句話 → 一兩分鐘內導師信箱收到「新留言」的信（可能在垃圾郵件，
   請他標成「不是垃圾郵件」）。10 分鐘後跑 `notify_config.py`（唯讀），看得到「家長通知排程：最後一輪 幾分鐘前」。
7. 預演一兩天、每日摘要也收到了、沒有「需要處理」→ 問老師「要開始真的寄給家長了嗎？」→ 點頭 →
   `notify_config.py --phase live --apply`。它會檢查排程真的在跑，才准切。

**日常**：

- 「通知信健檢」「怎麼沒收到信」→ `notify_setup.py --cloud` ＋ `notify_config.py`（都唯讀），照「→」處理。
- 「先別寄給家長」→ `notify_config.py --parent-mail off --apply`；「全部先停」→ `--phase off --apply`（緊急煞車：
  排隊中的家長通知 10 分鐘內全部取消，之後打開也不會補寄）。恢復：`--phase dryrun` 或 `--parent-mail on`。
- 「每日摘要不要了」→ `--digest off --apply`。「改寄件人名稱／署名」→ 改 `config/class.json` → `notify_config.py --sync --apply`
  （不用重新部署）。
- 要還原備份（`playbooks/restore.md`）之前：先 `--phase off --apply`，還原完再打開（程式也會擋掉舊內容，這是雙重保險）。
- 升級程式之後：`deploy.py --yes` 會連通知信一起重新部署（第 4 步）。

**移除**（老師說「不要通知信了」）：

1. `notify_config.py --phase off --apply`。
2. 刪掉雲端上的 7 支 Functions：請老師到 Firebase 主控台 → 左邊「Functions」→ 每一支右邊「⋮」→ 刪除
   （`cmwCommentPost`、`cmwCommentAlbum`、`cmwCommentPrivate`、`cmwBlogEntry`、`cmwBlogComment`、`cmwNotifySweep`、`cmwDailyDigest`）。
   代理不跑刪除指令（非互動刪除一定要 `--force`，這個專案不用它）。
3. 刪密碼：Google Cloud 主控台 → Secret Manager → `CMW_GMAIL_APP_PASSWORD` → 刪除；Gmail 的應用程式密碼頁也把它撤銷。
4. `config/class.json` 的 `notifications.enabled` 改回 `false`。想回到免費方案，再照主控台把方案改回 Spark。

## 4. 怎麼驗證＋失敗怎麼辦

- 裝好：`notify_setup.py --cloud` 最後是「通知信模組裝好了」；老師收得到測試留言的信與每日摘要。
- `deploy.py --only functions` 失敗，照它印的「→」：
  - 提到 secret／`CMW_GMAIL_APP_PASSWORD` → 密碼還沒放：第 2 節請老師自己打那一行。
  - 提到 Eventarc、Service Agent、權限還在開 → 第一次部署常見：等 5 分鐘再跑同一行。
  - 提到線上有程式碼裡沒有的 Functions → 可能是別的工具部署的：不要刪、不要 `--force`，請老師到主控台看是哪幾支。
  - 提到 billing／Blaze → 還沒升級，或帳單帳戶被停用。
  - 「functions 資料夾的套件還沒裝」→ 請老師打 `notify_setup.py` 印的那一行 `npm ci`。
- 導師收不到信：先看垃圾郵件；`notify_config.py` 有「即時信最近一次寄不出去」→ 多半是應用程式密碼錯了或被撤銷
  （Gmail 回「Username and Password not accepted」）：重新產生、重打 `secrets:set`、再 `deploy.py --only functions --yes`。
- 家長說沒收到：只有 Google 帳號對到座號的家長會收到；`notify_config.py` 看階段是不是 `live`、給家長的信是不是「開」；
  那篇是不是在 30 分鐘內被下架；家長的垃圾郵件。每日摘要會列出「寄不出去」的筆數。
- 每日摘要說「給家長的通知排程 N 小時沒跑了」→ `notify_setup.py --cloud` 看 Functions 還在不在；在的話請老師到
  Firebase 主控台 → Functions → `cmwNotifySweep` → 紀錄，把最後幾行錯誤念給你。
- `notify_config.py --phase live` 被擋「要先在 dryrun 跑過」「排程還沒在動」→ 照它說的：先 dryrun、等排程跑過一輪（10 分鐘）。
