# config/class.json 逐欄說明

這份檔是這個班網站的「總開關」。**這個檔不會進 git**（已被 `.gitignore` 擋住），只存在你自己的電腦上。

第一次安裝：把 `class.example.json` 複製一份改名成 `class.json`，照下面逐欄填好，
再跑 `python3 scripts/build_config.py`（Windows：`py -3 scripts/build_config.py`）。
不知道某一欄要填什麼就先留著範本值，跑 `--check` 會告訴你哪些還沒填（範本裡的 `teacher@example.com`、`your-project-id`
這類佔位值一定要換掉，留著就過不了）。

## 每一欄最後會跑到哪裡

同一份 `class.json` 裡的值，去處不一樣。「公開」的意思是：網站部署以後，**任何人**（不用登入）
都抓得到。

| 去處 | 哪些欄位 | 誰看得到 |
|---|---|---|
| **公開**網站設定檔 `site/js/site-config.js` | `class_name`、`firebase.*`（網頁設定）、`pages`、`categories`，以及程式自己算出來的網站正式網址 | 任何人 |
| 安全規則（只給資料庫看） | `teacher.email`（轉成「email 鍵」後才放進去） | 只有 Firebase 自己；網頁抓不到 |
| 資料庫 `config/site`（登入後才讀得到） | `school_name`、`teacher.display_name`、`students.count`、`calendar_ics_url` | 名單上的家長與同仁、你 |
| 只留在你的電腦 | `region`、`school_year.*`、`drive.sync_root`、`drive.class_folder`、`notifications.*` | 只有你 |
| 通知信模組（v1.1 選配，裝了才有） | `functions/cmw.generated.json`：專案、`region`、網址、`notifications.time_zone`、`digest_hour`（**沒有信箱**）；資料庫 `config/notify`（`scripts/notify_config.py` 寫）：`teacher.email`、`notifications.gmail_address`、`sender_name`、`signature`、`class_name` | Functions、你（導師）；網頁上的家長讀不到 |

寫進資料庫 `config/site` 的是名單同步 `scripts/access_sync.py`（先預覽，再 `--apply`）：它讀這份檔、寫進資料庫；
改了這幾欄要再跑一次它，網站上才會變（不用重新部署）。`build_config.py` **不會**把這幾欄寫進任何公開的檔。

## 逐欄

| 欄位 | 意思 | 去哪裡拿 |
|---|---|---|
| `class_name` | 班級顯示名稱，會出現在網站標題與各個頁面（**公開**）。 | 自己取；不知道要取什麼就先留著「我的班級」。不想被外人從名字認出是哪一班，就取一個不含校名的名字。 |
| `school_name` | 學校名稱（選填）。登入後才看得到。 | 不想寫就留空字串 `""`。 |
| `teacher.email` | 你要用來登入這個網站後台的 Google 信箱。只會被寫進安全規則，**不會**出現在公開的網站設定檔。 | 你自己的 Gmail 或學校配發的 Google 帳號（學校帳號可能被鎖住、開不了專案：看 `AGENTS.md` 步驟 2 第 2 題）。**範本裡的 `teacher@example.com` 一定要換掉**：`example.com` 是佔位用的假網域，`build_config.py` 會把它當成「還沒填」擋下來。 |
| `teacher.display_name` | 家長會看到的稱呼。登入後才看得到。 | 例如「王老師」。 |
| `students.count` | 班上人數（1–40）。登入後導師頁面用。 | 你自己數一下班級人數。 |
| `seat_format` | 固定說明文字，**不要修改這一欄**。 | 座號一律是兩位數字字串（01–40），程式全部統一用這個寫法。 |
| `region` | 你建 Firestore 資料庫時選的地區。只給檢查工具比對用。 | 不知道要填什麼就用 `asia-east1`（離台灣近），建資料庫時也選同一個——資料庫建好以後地區**不能改**。 |
| `firebase.project_id` | 你自己開的 Firebase 專案代號。 | Firebase Console → 專案設定（齒輪圖示）→ 一般 → 「專案 ID」。 |
| `firebase.api_key` | 網頁連線用的金鑰。這把金鑰本來就是公開的（每個 Firebase 網站都一樣），真正擋人的是安全規則。 | Firebase Console → 專案設定 → 一般 → 「你的應用程式」→（沒有應用程式就先「新增應用程式」選網頁）→ SDK 設定與配置，裡面的 `apiKey`。 |
| `firebase.auth_domain` | 登入功能用的網域。**留空字串 `""` 就好**，程式會自動用 `<專案 ID>.firebaseapp.com`——這也是你網站的正式網址。 | 不用拿。填了別的（例如 `.web.app` 結尾）會被擋下來：網站網址和登入網域不同的話，部分手機瀏覽器會登入失敗。 |
| `firebase.app_id` | 這個網頁應用程式的代號。 | 同 `api_key`，SDK 設定與配置裡的 `appId`。 |
| `firebase.messaging_sender_id` | Firebase 內部用的數字代號（選填）。 | 同上，`messagingSenderId`；不確定就留空字串。 |
| `pages` | 每一頁要不要開（`true`／`false`）。沒寫的頁面＝開。 | 想關掉某一頁（例如還沒準備好相簿）就把那一項改成 `false`；不用「每日一詩」就加 `"poem": false`（導覽列就不會出現）。 |
| `categories` | 班級紀事的分類清單，會出現在分類選單裡（**公開**）。 | 預設是「班級生活」「學習活動」「戶外與參訪」「藝術與作品」「公告」。可以整組換成你們學校習慣的說法（例如學校有自己的課程名稱、活動名稱，就用那些字），三到六個最好找。 |
| `school_year.start_month` | 學年從幾月開始（1–12 的整數）。雲端硬碟裡「學年」資料夾的名字照這個算。 | **依學校**：看學校行事曆的開學月。預設 `8`（8 月 1 日換學年，資料夾叫 `2030-2031` 這樣）；學年就是日曆年的學校填 `1`（資料夾只寫年份）。 |
| `school_year.terms` | 一學年分成哪幾個學期（清單，1–6 個）。雲端硬碟「班級文件」的每個學年底下，每個學期會建一個資料夾。 | **依學校**：預設 `["上學期", "下學期"]`。分三個學期的學校就寫 `["第一學期", "第二學期", "第三學期"]`。名稱會變成資料夾名，只用一般文字。改了以後跑 `scripts/drive_init.py --apply` 補建新的資料夾（舊的不會被刪）。 |
| `school_year.term_aliases` | （選填）學期資料夾的別名：班級文件索引看到這些名字的資料夾，也算成對應的學期。**不會**多建資料夾。 | 通常不用填，預設 `{}`。老師以前自己建的資料夾用別的叫法時才加，例如設定是上學期／下學期、舊資料夾叫第一學期／第二學期：`{"上學期": ["第一學期"], "下學期": ["第二學期"]}`。鍵一定要是 `terms` 裡的學期名稱；每個學期最多 5 個別名，同一個別名只能對到一個學期。 |
| `calendar_ics_url` | 行事曆訂閱網址（選填），首頁「訂閱行事曆」按鈕會用到。登入後才看得到。**只可填公開日曆網址，不可貼私人 iCal 網址。** | Google 日曆 → 設定 → 你的班級日曆 → 先勾「公開這個日曆」→ 複製「iCal 格式的公開網址」（`https://` 開頭、`/public/basic.ics` 結尾）。**「iCal 格式的私人網址」（網址裡有 `private-`）絕對不要貼**：拿到那串網址的人不用登入就能看到整本日曆，`build_config.py` 會擋。不用就留空字串 `""`。 |
| `drive.sync_root` | Google 雲端硬碟桌面版同步夾的路徑（選填），備份與課程歸檔會寫到這裡。 | 不用自己填：跑 `scripts/drive_init.py`，它會找到同步夾、問你選哪一個，再寫進來（`playbooks/backup.md`）。 |
| `drive.class_folder` | 同步夾裡這個班的資料夾名稱（「<班名> 班級網站」）。 | 由 `scripts/drive_init.py` 寫；建好後固定，之後改班名也不會跟著變（備份才找得到原來那個資料夾）。 |
| `notifications.enabled` | v1.1 選配的通知信模組要不要裝（`true`／`false`）。**預設 `false`**；裝之前一定要先看 `playbooks/notify.md`（要 Blaze 付費方案、一個寄信用的 Gmail）。 | 老師同意裝了，代理才改成 `true`；`build_config.py` 會產生 `functions/cmw.generated.json`（沒有任何信箱）。 |
| `notifications.sender_name` | 通知信的寄件人名稱（選填，≤ 40 字，一行）。 | 空字串＝「〈稱呼〉（〈班名〉）」。不要放學校全名與孩子的名字。 |
| `notifications.signature` | 寄給家長的信的信尾署名（選填，≤ 300 字，可以換行）。 | 空字串＝「〈班名〉 〈稱呼〉」。 |
| `notifications.gmail_address` | 寄通知信的 Gmail 帳號（選填）：就是產生「應用程式密碼」的那個帳號。 | 空字串＝用 `teacher.email`。學校帳號不能產生應用程式密碼時，另開一個個人 Gmail 填在這裡；家長回信會回到 `teacher.email`。 |
| `notifications.time_zone` | 每日摘要與排程用的時區。 | 台灣就是 `Asia/Taipei`（預設）。 |
| `notifications.digest_hour` | 每日摘要幾點寄（0–23 的整數）。 | 預設 `7`（早上 7 點）。改了要重新部署（`deploy.py --only functions --yes`）。 |

Firebase 主控台給你的 SDK 設定裡如果有 `storageBucket`，**不用抄進來**：這一版不用 Cloud Storage，
照片直接存在資料庫裡。舊的 `class.json` 裡留著 `storage_bucket` 也沒關係，程式只會提醒你可以刪掉。

## 安全規則

- **這個檔手改沒關係，但改完一定要重跑 `python3 scripts/build_config.py`**，網站的設定與
  安全規則才會跟著更新。
- `email` 欄位請直接貼你 Google 帳號的信箱，不要加引號、不要加任何符號——`build_config.py`
  會擋掉看起來不像信箱的內容（這是防止有人把奇怪的字串偷渡進安全規則）。
  Gmail 信箱裡的點號與大小寫不影響比對（`scripts/lib/emailkey.py` 會統一成同一種寫法）。
- 這個檔含有你的真實資訊，**絕對不要**把它傳到任何公開的地方（GitHub、聊天室截圖……）。
