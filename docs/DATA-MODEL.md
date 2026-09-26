# 資料模型與權限（DATA-MODEL）v2

> 這份是**正本**。前台（`site/js/`）、安全規則（`templates/firestore.rules.tmpl`）、管理腳本（`scripts/`）
> 三邊都照這份寫，**不准各自解讀**。要改集合名、欄位、ID 格式、誰能讀寫、查詢形狀，先改這份
> （查詢改 `templates/queries.json` 再跑 `python3 scripts/build_indexes.py`），再改程式與規則測試，同一個 commit。
>
> 讀者：寫前台（P2）、寫規則（P3）、寫腳本（P4）的人或 AI 代理。老師不必讀這份。
> 網站分層、Store 介面、正文區塊格式、發文流程、部署順序在 `docs/ARCHITECTURE.md`；兩份衝突以這份為準。
>
> **v2 與 v1 的差別**（架構複審後的定案；各項的理由寫在下面對應的章節）：v1 只用 Firestore＋Auth＋Hosting，**預設 Spark 免費方案**；
> 照片以 base64 存進 Firestore（縮圖文件＋顯示文件兩份），影片一律外部連結；正文存結構化區塊，不存 HTML；
> 拿掉 uid 對 email 的身分表，改用規則驗過的 email 鍵與作者代號；email 鍵正規化；
> 部落格文章子集合叫 `entries`；網站正式網址＝`<專案>.firebaseapp.com`；每個查詢形狀都登記、索引由程式產生。

---

## 0. 約定

### 0.1 v1 用到哪些服務

| 服務 | 用途 | 方案 |
|---|---|---|
| **Cloud Firestore**（`(default)` 資料庫，只用這一個） | 名單、所有內容、照片、留言、回條 | Spark 免費額度內（§5） |
| **Firebase Authentication** | Google 登入、email 連結登入 | Spark（email 連結每天 5 封，§5.1） |
| **Firebase Hosting** | 網站空殼（`site/`），正式網址 `https://<專案>.firebaseapp.com` | Spark |

就這三個。v1 不部署任何伺服器端程式，所以**沒有任何東西會在背景幫你改資料**：計數、未讀、權限標記
一律由規則當場判斷、或由導師端網頁即時查。選配的通知信模組是 v1.1，另外需要付費方案（ARCHITECTURE §10）。

老師不必綁信用卡；Spark 方案用量到頂就是暫停，不會收費（§5.3）。

### 0.2 三種存取者

| 存取者 | 怎麼連線 | 受不受安全規則管 |
|---|---|---|
| **瀏覽器**（家長、同仁、導師在網頁上操作） | Firebase JS SDK，帶 Firebase Auth 的 ID token | **受規則管**。本文件每張權限表講的都是這一種 |
| **管理腳本**（`scripts/*.py`，在導師自己電腦上跑） | Firestore REST，帶導師本人 `gcloud` 登入的存取權杖，一律加 `x-goog-user-project: <專案>` 標頭（ARCHITECTURE §6） | **不受規則管**，走 IAM。規則對「只有腳本寫」的集合寫 `allow write: if false`，腳本照樣寫得進去 |
| 規則測試（模擬器，`demo-cmw` 專案，`tests/rules/`） | 官方 `@firebase/rules-unit-testing`＋Firebase JS SDK，連本機模擬器 | 各角色的請求受規則管；種資料用「關掉規則」的管理身分（等同管理腳本） |

「規則寫 `if false`」不等於「沒人能寫」，而是「只有管理腳本能寫」。權限表的「腳本」欄就是在講這件事。
腳本不受規則管，所以腳本寫入前**一定**先過 `scripts/lib/schema.py`（本文件欄位白名單的 Python 版），不合就不寫。

### 0.3 email 鍵（`emailKey`）正規化

名單的 doc id、規則裡的比對、前端讀自己的名單文件，三邊一律先把 email 轉成同一個「email 鍵」再比。
不統一的話，家長明明在名單裡卻被擋，畫面上看不出原因（Google 登入拿到的寫法常跟通訊錄不一樣）。

| 步驟 | 規則 |
|---|---|
| 1 | 前後空白去掉，全部轉小寫 |
| 2 | 一定剛好一個 `@`，前後都不能是空的，字元集照 `EMAIL_RE`（規則端：`verified()` 用同一個正規式比對，另外擋「gmail 去掉點號後是空的」；三邊拒收的是同一批，向量檔的 `invalid` 驗） |
| 3 | 網域是 `gmail.com` 或 `googlemail.com`：`@` 前面的點號**全部**拿掉，網域統一寫成 `gmail.com` |
| 4 | 其他網域（含學校的 Workspace 網域）：點號照留 |
| 5 | `+` 後綴不處理，照原樣保留 |

三個實作、一套測試向量：

| 實作 | 位置 | 誰寫 |
|---|---|---|
| Python | `scripts/lib/emailkey.py` 的 `email_key()`（另外用 `EMAIL_RE` 擋引號、反斜線、空白、非 ASCII） | 已完成（P1） |
| 安全規則 | §1.4 的 `emailKey()`（`trim()`＋`lower()`，與 Python 同樣去掉前後空白、tab、換行） | 已完成（P3；`tests/rules/` 用共用向量驗） |
| 前端 | `site/js/core/emailkey.js`（`CMW.emailKey()`，給讀自己名單文件、回條 doc id 用） | P2 |
| 共用測試向量 | `tests/fixtures/emailkey_vectors.json`（email 拆成 `[@ 前, @ 後]` 兩段存，避開 privacy_scan） | 三邊的測試都要讀它；規則測試用它造登入身分 |

規則端注意：`replace()` 的第一個參數是 **RE2 正規式**，所以點號要寫 `'[.]'`；寫成 `'.'` 會把每個字都換掉
（例如 `'foo@example.com'.replace('.', '-')` 得到 15 個 `-`；官方參考頁也舉了同樣的例子）。

### 0.4 ID 與欄位格式（程式、規則、路徑、測試同一套）

| 東西 | 格式 | 正規式 | 備註 |
|---|---|---|---|
| 座號 `seat` | 兩位數字字串 `"01"`–`"40"` | `^(0[1-9]\|[1-3][0-9]\|40)$` | Python 一律經 `scripts/lib/seats.py`；前端一律經 `CMW.seats.key()`。**不准**出現 `"1"`、`"座01"` |
| email 鍵 | §0.3 | — | 當 `allowlist`、`private_allowlist`、`parent_child_map`、`reads` 的 doc id |
| 作者代號 `alias` | 12 碼小寫英數，隨機 | `^[a-z0-9]{12}$` | §0.5。放在讀者看得到的文件（留言、部落格）上代表「誰寫的」，**不是 email** |
| 紀事／相簿／私密紀事 `slug` | 日期開頭的小寫英數與連字號 | `^[0-9]{4}-[0-9]{2}-[0-9]{2}(-[a-z0-9]+)+$`，總長 ≤ 80 | 只准 ASCII（網址參數與 doc id 都乾淨） |
| 部落格文章 `postId` | 日期＋8 碼小寫英數，隨機 | `^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]{8}$` | 瀏覽器用 `crypto.getRandomValues` 產生；**每次送出（含重試）都換新的**（§2.14） |
| 照片 `pid` | 腳本：顯示檔 JPEG 位元組 SHA-256 的前 16 碼十六進位；瀏覽器（部落格）：`"0"`、`"1"`、`"2"` | `^([0-9a-f]{16}\|[0-2])$` | 腳本那種是「內容定址」：同一張照片重發得到同一個 pid、不同照片不可能同名覆寫 |
| 單頁 `pageId` | 小寫英數與連字號 | `^[a-z][a-z0-9-]{0,39}$` | 例：`home`、`about`、`fun`、`calendar`、`courses-term` |
| 日期欄 `date` | `YYYY-MM-DD` 字串（老師所在時區的日期） | `^[0-9]{4}-[0-9]{2}-[0-9]{2}$` | 排序用字串比較 |
| 時間欄 `createdAt` 等 | Firestore Timestamp | — | 瀏覽器寫的一律 `serverTimestamp()`，規則驗 `== request.time`；腳本寫的用 REST 的 `REQUEST_TIME` 轉換 |
| 網址欄（影片、外部連結、行事曆） | `https://` 開頭 | 規則不驗（腳本寫）；`schema.py` 驗；前端渲染再驗一次（ARCHITECTURE §4.3） | 長度 ≤ 500 |

### 0.5 名單、包含關係、作者代號

- **名單三份**：`allowlist`（能進班網的人）、`private_allowlist`（能看私密紀事的人）、
  `parent_child_map`（誰對應哪幾個座號）。三份都是**資料**，由 `scripts/access_sync.py`（P4）從本機
  `data/contacts.csv`、`data/parent-roles.yaml` 對帳寫入。改名單＝跑那支腳本，**不需要重新部署規則**。
- **包含關係由 `access_sync.py` 保證**：`private_allowlist ⊆ allowlist`、`parent_child_map 的 email ⊆ allowlist`、
  導師的 email 一定同時在 `allowlist`（`kind: 'teacher'`）與 `private_allowlist`。`access_sync.py --check`
  發現破了就 exit 1（`doctor.py --cloud` 也會檢查；`status.py` 不連網，只提醒名單檔在上次同步之後有沒有改過）。規則仍然**各自再查一次**（座號家長一律同時要求是讀者，§1.1），
  包含關係只是讓資料乾淨，不是安全邊界。
- **作者代號 `alias`**：每個 `allowlist` 文件帶一個 12 碼隨機代號。留言、部落格文章、對話串存的是
  **規則驗過的 `authorAlias`**（規則：`== get(allowlist/{自己}).data.alias`），導師端再用 `allowlist`
  （導師可讀）對回 email，用 `parent_child_map` 對出座號與稱謂，用 `roster/students` 對出「A（母）」。
  - 為什麼不直接存 email 鍵：紀事與相簿的留言**全班讀者都讀得到**（Firestore 沒有欄位層級的讀取權限），
    存 email 等於把每位留言家長的信箱公開給全班。只有導師讀得到的文件（回條 `reads`）才直接用 email 鍵。
  - `access_sync.py` 產生代號時先讀現有的 `allowlist` 文件，**沿用舊代號**；只有新加入的人才產生新的
    （`secrets.token_hex(6)`）。同一個人從名單移除再加回來會拿到新代號，舊留言在導師端顯示「（已不在名單）」。
  - 這個設計取代 v1 的 uid 對 email 身分表：不需要本人第一次登入時寫一次、沒有 set-once 錯誤碼的問題。
- **角色標籤**：留言的 `role` 由規則強制等於 `allowlist` 的 `kind`（`teacher`／`parent`／`staff`），
  前端固定在顯示名稱旁畫「導師／家長／同仁」標籤。顯示名稱是本人自填的，可以亂寫（例如家長 A 署名「B 的媽媽」），但標籤假冒不了。
  所以留言卡另外畫**作者代號的前 4 碼**（`#ab12`；`authorAlias` 由規則綁名單，冒用不了）：兩則署名一樣、短碼不一樣＝不是同一個帳號寫的。
  要知道是哪一位，導師在留言後台用 `allowlist` 對回。

### 0.6 可見旗標與「規則不是過濾器」

- 腳本寫入的內容（紀事、相簿、私密紀事、單頁）與部落格文章都有 `visible`。**下架＝改成 `false`，不刪**。
  留言與對話串用 `status: 'visible' | 'hidden'`。
- 非導師的**查詢**必須自己帶 `where('visible','==',true)`（或 `where('status','==','visible')`），
  否則整個查詢被規則拒絕——規則不會幫你過濾，只會整批拒絕。每個查詢該帶什麼，登記在 §4，程式驗證。
- **單筆讀取**（get）不用帶條件：規則直接看那一份文件。

### 0.7 權限表怎麼讀

每個集合一張表：列＝操作，欄＝角色。每一欄是**持有該角色的典型帳號的實際權限**
（座號家長、同仁、私密讀者一定也是讀者，會繼承讀者那一欄）。「未登入」欄同時代表「登入了但不在名單」；
只有 §2.1、§2.2 兩張名單表把它拆成「未登入」與「登入但不在名單」兩欄（登入但不在名單的人能 get 自己那份、拿到「找不到」）。
「讀者」欄＝Google 登入的讀者；**email 連結登入的讀者只有讀公開內容那幾格**（紀事、相簿、單頁與它們的照片、讀留言），
凡是寫入（留言、回條）與私密內容都要 Google 登入（§1.1）。「腳本」欄＝管理腳本（IAM，不受規則管）。

符號：✓ 允許｜✗ 拒絕｜條件寫在格子裡。「get」＝讀單一份、「list」＝查詢（含 count）。

---

## 1. 角色與規則共用函式

### 1.1 角色總表

| 角色 | 誰 | 伺服器端判定（規則函式，§1.4） |
|---|---|---|
| **未登入** | 任何人 | `request.auth == null` |
| （已登入但不在名單） | 登入了但不在 `allowlist` | `isReader()` 為假 |
| **班網讀者** | 家長與同仁（含 email 連結登入的人） | `isReader()`：email 已驗證 **且** `allowlist/{emailKey}` 存在。**寫入（留言、回條）另外要 `isGoogle()`** |
| **座號家長** | 對應到自己孩子座號的家長 | `isParentOf(seat)`：**同時是讀者**＋Google 登入＋`parent_child_map/{emailKey}` 存在、`active == true`、`kind == 'parent'`、`seats` 含該座號 |
| **同仁逐座號閱讀** | 導師授權可讀某幾個座號部落格的同仁 | `isSeatReaderOf(seat)` 裡 `kind == 'staff'` 的那一半；同樣要求同時是讀者＋Google 登入 |
| **私密讀者** | 能看私密紀事的少數人 | `isPrivateReader()`：導師，或（讀者 **且** Google 登入 **且** `private_allowlist/{emailKey}` 存在） |
| **導師**（1 位） | 班級導師本人 | `isTeacher()`：email 已驗證＋**Google 登入**＋`emailKey() == {{TEACHER_EMAIL_KEY}}` |

- 導師的 email 鍵由 `scripts/build_config.py` 以 `{{TEACHER_EMAIL_KEY}}` 插進規則產生檔（渲染結果是**含雙引號**的
  JSON 字串，規則裡直接寫 `emailKey() == {{TEACHER_EMAIL_KEY}}`，不要自己加引號）。插進去之前已經過
  `EMAIL_RE`＋`email_key()`，擋掉引號與反斜線。導師 email **不會**出現在公開的 `site/js/site-config.js`（P1 已改）。
- **座號家長、同仁、私密讀者必須是 Google 登入；留言與已讀回條也要 Google 登入**。email 連結登入的帳號只能讀公開內容
  （紀事、相簿、單頁、讀留言），前端對這種身分顯示「此登入方式只能閱讀，留言與私密內容請用 Google 登入。」
- **為什麼（帳號預先註冊）**：email 連結登入要先在 Firebase 打開「電子郵件/密碼」，這個 provider 同時開放**密碼註冊**
  （網頁的 apiKey 是公開的，任何人都能呼叫註冊 API）。攻擊者拿一位**還沒登入過班網**的家長信箱註冊密碼帳號、觸發驗證信，
  家長一點「驗證信箱」，這個帳號就是 `email_verified == true`，而且 email 鍵對得上名單。規則分不出這個帳號和真的 email 連結登入：
  兩者 token 的 `sign_in_provider` **都是 `'password'`**。所以規則只信 Google 登入（Google 帳號在本人手上）：
  password 登入的人最多讀到全班讀者本來就讀得到的公開內容，冒不了名留言、簽不了回條、讀不到私密紀事與部落格。
  非 Google 家長多、又要讓他們留言的班，要升 Blaze 並加 blocking function（`beforeUserCreated` 擋 `password` 註冊），
  或乾脆不開 email 連結（INSTALL 第 2 節、AGENTS 第 2 步）。
- 沒有匿名登入。Firebase Auth 只開 Google 與「電子郵件/密碼」（只為了其中的「電子郵件連結（無密碼）」；密碼註冊關不掉，見上一條）。
- 導師的規則判定不看名單（`isTeacher()` 只比 email 鍵），但導師**要留言**時規則會讀導師自己的
  `allowlist` 文件拿 `kind` 與 `alias`，所以 `access_sync.py` 一定把導師放進名單。

### 1.2 前端怎麼知道自己的角色（Session 解析）

登入後，前端同時發最多四個單筆讀取（ARCHITECTURE §2.3 的 `onSession`）：

| 讀取 | 規則 | 結果怎麼解讀 |
|---|---|---|
| `allowlist/{自己的 emailKey}` | 本人可讀自己那份（不存在就回「找不到」） | 有文件＝讀者，順便拿到 `kind`、`alias`；找不到＝「尚未授權」畫面 |
| `private_allowlist/{自己的 emailKey}` | 同上 | 有文件＝私密讀者（還要同時是讀者、而且 Google 登入）；**不是 Google 登入就不發這個請求** |
| `parent_child_map/{自己的 emailKey}` | 讀者＋Google 登入才可讀自己那份 | 有文件且 `active`＝座號清單與 `kind`；**不是 Google 登入就不發這個請求** |
| `site_access/teacher`（探針，文件不存在） | 只有 `isTeacher()` 放行 | 放行（回「找不到」）＝導師；被拒＝不是導師；**不是 Google 登入就不發** |

「是不是 Google 登入」前端讀 ID token 的 `claims.firebase.sign_in_provider`（`getIdTokenResult()`），跟規則的 `isGoogle()` 同一個來源；
不看 `providerData`（同一個信箱連結了 Google 與 email 連結時，`providerData` 有 `google.com`，但這一次可能是用 email 連結登入的）。

前端的角色判斷**只拿來決定畫面長什麼樣，不是安全邊界**；真正的邊界永遠是規則。Session 可以暫存在
`sessionStorage`（每個分頁第一次載入、之後每 30 分鐘、或登入狀態改變時才重新解析），省讀取次數。

### 1.3 規則語言能做什麼（查證過的限制）

| 項目 | 事實 | 對本專案的意義 |
|---|---|---|
| 字串方法 | `lower()`、`upper()`、`trim()`、`size()`、`split(re)`（回清單）、`replace(re, sub)`（**全部**符合的都換）、`matches(re)`（**整串**比對）、`toUtf8()`；可用 `s[i]`、`s[i:j]`；`re` 一律是 RE2 | email 鍵正規化在規則裡做得到（§1.4）；點號要寫 `'[.]'` |
| `get()`／`getAfter()` | 文件不存在時回 `null`（不是丟錯） | 可以寫 `get(p) != null && get(p).data.x == …` |
| 三元運算子 | 支援 `a ? b : c` | `emailKey()` 用它 |
| `let` | 每個函式最多 10 個 | — |
| 函式 | 參數最多 7 個、呼叫深度最多 20、不准遞迴 | — |
| **文件存取次數**（`exists`／`get`／`getAfter`） | **單次請求或查詢：10 次；批次寫入與交易：整批 20 次**（每個寫入各自仍受 10 次限制）；同一份文件被快取的呼叫不計 | 見 §1.6 預算表；瀏覽器批次一律 ≤ 7 個寫入。**模擬器對查詢量到的上限是 20**（比正式環境寬），所以查詢的次數只能靠靜態檢查（`scripts/lib/rules_budget.py`） |
| 每次請求可評估的運算式 | 1,000 個 | 不要在規則裡對大陣列逐項檢查 |
| 規則檔大小 | 原始碼 256 KB、編譯後 250 KB | 只給很多集合共用的函式放最外層，集合專屬的函式放進該 `match` 裡（官方建議，避免編譯爆掉） |
| 計費 | 規則裡每讀一份文件算一次讀取；同一請求裡同一份文件只算一次 | §5.2 的讀取估算已含這一項 |

### 1.4 共用函式（放在 `match /databases/{database}/documents` 最上層；原文在附錄 §A）

附錄 A 是 `templates/firestore.rules.tmpl` 的逐字複本（`tests/test_rules_template.py` 比對），這裡只列每個函式的意思，
不另抄一份程式碼（三份會對不齊）。

| 函式 | 意思 | 讀幾份文件 |
|---|---|---|
| `signedIn()` | `request.auth != null` | 0 |
| `verified()` | 已登入＋`email_verified == true`＋email（去掉前後空白後）符合 `EMAIL_RE`＋gmail 去掉點號後不是空的。`emailKey()` 只准在它為真之後呼叫 | 0 |
| `isGoogle()` | `sign_in_provider == 'google.com'`（email 連結與密碼登入都是 `'password'`，分不出來，§1.1；用 `.get()` 取值，token 少欄位也不會出錯） | 0 |
| `emailKey()` | §0.3：`trim().lower()`；gmail／googlemail 去掉 `@` 前面的點號（`replace('[.]', '')`）並統一 `gmail.com` | 0 |
| `isTeacher()` | `verified() && isGoogle() && emailKey() == {{TEACHER_EMAIL_KEY}}` | 0 |
| `allowDoc()` | 自己的 `allowlist` 文件（不在名單＝`null`） | 1 |
| `isReader()` | `verified() && allowDoc() != null` | 1 |
| `isPrivateReader()` | `isTeacher() \|\|（isReader() && isGoogle() && private_allowlist 有自己）` | 2 |
| `hasSeat(seat, kinds)` → `isParentOf(seat)`、`isSeatReaderOf(seat)` | `isReader() && isGoogle()`＋自己的 `parent_child_map` 存在、`active == true`、`kind` 在 `kinds` 裡、`seats` 含該座號（取欄位一律 `.get(欄位, 預設)`） | 2 |
| `validSeat`、`validDate`、`validPostId`、`validAlias`、`strLen`、`intIn` | §0.4 的格式；字串長度、整數範圍（型別不對一律假） | 0 |
| `visibleDoc(d)` | `d != null && d.data.visible == true`（`d` 由呼叫端傳入，同一份文件只讀一次） | 0 |
| `validNewComment(me)`、`canCreateComment(ticket, parent)`、`onlyStatusChange()`、`validReceipt(key, me)` | 三種討論串共用的留言與回條規則（§2.7、§2.8）；`me`＝`allowDoc()`，取 `kind`、`alias` 不必再讀一次。`canCreateComment`、`validReceipt` 都要 `isGoogle()` | 見 §1.6 |

**寫法約定**（改規則的人要守，樣板開頭也寫了）：讀文件的呼叫（`get`／`exists`）用函式參數接住再用，同一份文件在一條規則裡
只寫一次；第一版骨架的 `myKind()`、`myAlias()`、`seatMap()` 那種「每用一次就再 get 一次」的寫法改成傳參數，最壞情況的次數才估得準（§1.6）。
下文說「自己名單上的 `kind`／`alias`」＝`allowDoc()` 那份文件的欄位。

- `isReader()` 刻意**不**讓導師短路：名單正本只有一份，導師也在名單裡。需要導師通行的地方一律寫
  `isTeacher() || (isReader() && …)`。
- 規則評估出錯（例如讀不存在文件的欄位）＝拒絕。上面每個函式都先檢查再取值。

### 1.5 「找不到」與「被拒」

前端讀單一份文件時要能分辨「這篇不存在」與「你沒有權限」，否則下架、打錯網址、真的被擋全部長得一樣。
Firestore 對不存在的文件照樣跑規則，這時 `resource == null`；規則若去讀 `resource.data.visible` 會出錯＝拒絕。
所以**每個會讀 `resource` 的集合，get 與 list 分開寫**：

```
allow get:  if isTeacher() || (isReader() && (resource == null || resource.data.visible == true));
allow list: if isTeacher() || (isReader() && resource.data.visible == true);
```

- get 對不存在的文件：有門票的人拿到「找不到」（前端收到 `exists() == false`），沒門票的人照樣被拒
  （私密紀事不會因此洩漏「有沒有這一篇」）。
- list 不寫 `resource == null`：查詢是用條件證明「每一份都符合」，不需要也不應該放這一條。
- 已存在但 `visible == false` 的文件，非導師 get 會被拒。前端在「Session 是讀者、卻對單篇被拒」時
  顯示「這篇找不到（可能已下架）」，不顯示「沒有權限」。
- 規則沒有讀 `resource` 的集合（例如 `content/main`、照片文件、自己的名單文件）不需要這一條：不存在就直接回「找不到」。

### 1.6 文件存取次數預算（上限：單次 10、批次整批 20）

| 操作 | 規則會碰的文件 | 不重複的文件 | 最壞呼叫次數 |
|---|---|---|---|
| 讀者 get／list 紀事、相簿、單頁 | `allowlist/{自己}` | 1 | 1 |
| 讀者讀正文、照片、留言 | `allowlist/{自己}`、父文件 | 2 | 2 |
| 讀者留言、寫回條 | `allowlist/{自己}`、父文件 | 2 | 3 |
| 私密讀者讀私密紀事、照片、留言 | `allowlist`、`private_allowlist`、父文件 | 3 | 3 |
| 私密讀者留言、寫回條 | 同上 | 3 | 4 |
| 座號家長／同仁讀部落格主頁、文章 | `allowlist`、`parent_child_map` | 2 | 2 |
| 座號家長／同仁讀文章照片；家長讀對話串 | `allowlist`、`parent_child_map`、文章 | 3 | 3 |
| 座號家長寫對話串 | `allowlist`、`parent_child_map`、文章 | 3 | 4 |
| **座號家長發文批次**（1 篇文章＋最多 3 份縮圖＋3 份顯示圖＝7 個寫入） | 每個寫入：`allowlist`、`parent_child_map` | 每個寫入 2 | 文章 3、每張照片 2；**整批 15**（≤ 20） |
| 導師任何操作 | 導師留言時讀自己的 `allowlist`；留言、對話串讀父文件 | ≤ 2 | 靜態估算不分角色，照該路徑那一列 |

「最壞呼叫次數」＝不管 `&&`／`||` 的短路、不假設同一份文件會被快取，把條件裡每一個 `get`／`exists` 都算進去
（`scripts/lib/rules_budget.py` 對規則原文逐條估；`python3 scripts/test_rules.py` 印全表，`tests/test_rules_template.py`
在 `check.py` 裡擋「任何一條 > 10、批次 > 20」）。**查詢（list）這一項只能靠它**：模擬器對查詢量到的上限是 20，比正式環境的 10 寬。

照片寫入**刻意不**用 `getAfter()` 檢查「同一批裡真的有那篇文章」：那會讓每個照片寫入多 1–2 次，
7 個寫入的批次在沒快取時會超過 20。代價是「家長可以在自己座號底下寫孤兒照片文件」（沒有文章、或不在文章
`photos` 清單裡），而且規則沒有數量上限：**單一家長帳號就能把 Spark 的 1 GiB 灌滿**，之後全班的寫入都會失敗。
前端只顯示文章 `photos` 清單列出的 pid，孤兒文件看不到。實況：`backup.py firestore` 備份完對帳，印出孤兒照片的
座號、遮住的 postId、份數與估算大小（不印內容），統計記進 `data/ledgers/backup-state.json`，`status.py` 跟著提醒；
`data_exit.py seat`（整個座號的部落格本來就全刪）與 `data_exit.py parent`（他對應座號底下的孤兒）會一起刪。
處置（先撤那個帳號擋住來源、再清）寫在 `playbooks/data-exit.md` 第 5 段「孤兒照片」。

---

## 2. Firestore 集合

### 2.0 總表

| 路徑 | doc id | 內容 | 寫入者 | 誰讀得到 | 批次 |
|---|---|---|---|---|---|
| `allowlist/{key}` | email 鍵 | 班網讀者名單＋角色＋作者代號 | 腳本 | 本人（自己那份）、導師 | v1 |
| `private_allowlist/{key}` | email 鍵 | 私密讀者名單 | 腳本 | 本人（自己那份）、導師 | v1 |
| `site_access/teacher` | 固定 | 導師探針（文件不存在） | 沒有人 | 導師 | v1 |
| `parent_child_map/{key}` | email 鍵 | 帳號對座號 | 腳本 | 本人（自己那份）、導師 | v1 |
| `config/site` | 固定 | 導師稱呼、校名、人數、公開行事曆網址 | 腳本 | 讀者 | v1 |
| `posts/{slug}` | slug | 班級紀事摘要（列表用） | 腳本 | 讀者（可見者）、導師 | v1 |
| `posts/{slug}/content/main` | 固定 `main` | 紀事正文區塊 | 腳本 | 同父文件 | v1 |
| `{主人}/thumbs/{pid}`、`{主人}/images/{pid}` | pid | 照片：縮圖、顯示圖（base64 JPEG） | 腳本；部落格文章的照片由座號家長與導師在瀏覽器寫 | 同主人文件 | v1 |
| `{紀事、相簿、私密紀事}/comments/{cid}` | 自動 | 留言 | Google 登入的讀者（私密紀事：私密讀者）、導師 | 讀者（私密紀事：私密讀者；可見者）、導師 | v1 |
| `{紀事、私密紀事}/reads/{key}` | email 鍵 | 已讀回條 | Google 登入的讀者（私密紀事：私密讀者） | 本人（自己那份）、導師 | v1 |
| `albums/{slug}` | slug | 相簿（照片在子集合） | 腳本 | 讀者（可見者）、導師 | v1 |
| `private_posts/{slug}` | slug | 私密紀事（摘要＋正文同一份） | 腳本 | 私密讀者（可見者）、導師 | v1 |
| `pages/{pageId}` | pageId | 首頁橫幅、課程頁、關於我們、專題活動、行事曆、獨立單頁 | 腳本 | 讀者（可見者）、導師 | v1（詩 v1.1） |
| `student_blogs/{seat}` | 座號 | 部落格主頁 | 腳本 | 該座號家長與同仁、導師 | v1 |
| `student_blogs/{seat}/entries/{postId}` | postId | 部落格文章 | 該座號家長、導師、腳本 | 該座號家長與同仁（可見者）、導師 | v1 |
| `…/entries/{postId}/blog_comments/{cid}` | 自動 | 導師與家長的對話串 | 該座號家長、導師 | 該座號家長（可見者）、導師 | v1 |
| `roster/students`、`roster/links` | 固定 | 座號對姓名、導師連結 | 腳本 | 導師 | v1 |
| `ops/backup_status` | 固定 | 備份心跳 | 腳本 | 導師 | v1 |
| `seating/{planId}` 等 | — | 見 §2.18 | 腳本／v1.1 Functions | 導師 | v1.1 |

`{主人}` 是這幾種文件之一：`posts/{slug}`、`albums/{slug}`、`private_posts/{slug}`、`pages/{pageId}`、
`student_blogs/{seat}/entries/{postId}`（v1.1 再加 `parent_photo_display/{seat}`、`personal_photos/{seat}`）。

**不在本 repo 的集合**：學生個別觀察、全班觀察與課程紀錄——見 §2.21。

---

### 2.1 `allowlist/{key}` — 班網讀者名單

| 欄位 | 型別 | 必填 | 限制 | 說明 |
|---|---|---|---|---|
| `kind` | string | ✓ | `'teacher'`｜`'parent'`｜`'staff'` | 規則用它強制留言的角色標籤；`'teacher'` 只給導師本人 |
| `alias` | string | ✓ | `^[a-z0-9]{12}$` | 作者代號（§0.5），名單期間不變 |
| `updatedAt` | timestamp | ✓ | | 最後對帳時間 |

**不放姓名、座號、電話**。

| 操作 | 未登入 | 登入但不在名單 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|---|
| get 自己那份 | ✗ | ✓（email 已驗證；回「找不到」） | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| get 別人那份 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| list | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 建／改／刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

「get 自己那份」只要求 email 已驗證（`verified() && key == emailKey()`）：不在名單的人讀自己那份拿到「找不到」，
這正是前端判斷「尚未授權」的方式（§1.2）。規則裡的 `get()` 是伺服器特權查詢，不受這張表限制。

### 2.2 `private_allowlist/{key}` — 私密讀者名單

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `updatedAt` | timestamp | ✓ | |

| 操作 | 未登入 | 登入但不在名單 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|---|
| get 自己那份（不在名單就回「找不到」） | ✗ | ✓（email 已驗證；回「找不到」） | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| get 別人那份、list | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 建／改／刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

規則是 `verified() && key == emailKey()`，**不看登入方式**：email 連結登入、在這份名單裡的人也讀得到自己那份（只有 `updatedAt`），
但他不是私密讀者（§1.1），私密紀事照樣被拒。前端對非 Google 登入根本不發這個請求（§1.2）。
導師的 email 鍵一定在裡面。私密紀事「已讀 X/N」的 N＝這份名單的人數減掉導師（§2.8）。

### 2.3 `site_access/teacher` — 導師探針

文件**不存在**，也不應該存在任何資料（欄位白名單：無）。只有 `teacher` 這一個 id。

| 操作 | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| get `teacher` | ✗ | ✗ | ✗ | ✗ | ✗ | ✓（回「找不到」） | ✓ |
| list、get 其他 id、建／改／刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗（也不需要） |

### 2.4 `parent_child_map/{key}` — 帳號對座號

**doc id**：email 鍵（必須是 Google 帳號）。一位家長有兩個孩子在同班時，`seats` 放兩個。

| 欄位 | 型別 | 必填 | 限制 | 說明 |
|---|---|---|---|---|
| `seats` | array<string> | ✓ | 1–3 個，每個符合座號格式 | |
| `kind` | string | ✓ | `'parent'`｜`'staff'` | **權限靠這一欄分**，不准拿顯示字串判斷 |
| `active` | bool | ✓ | | `false`＝暫停（保留資料、立即失去座號權限） |
| `relation` | string | 選填 | ≤ 10 字 | 家長稱謂（父、母、祖母…）；同仁不填。導師端顯示「A（母）」用 |
| `label` | string | ✓ | ≤ 20 字 | 只能是「座號 04 家長」「座號 04 同仁」這種**不含姓名**的字樣；規則與程式都不准拿它判斷權限 |
| `updatedAt` | timestamp | ✓ | | |

| 操作 | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| get 自己那份 | ✗ | ✓（要 Google 登入；沒有就回「找不到」） | ✓ | ✓ | ✓ | ✓ | ✓ |
| get 別人那份、list | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 建／改／刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

導師端「已讀 X/N」「全班格」的**純家長**＝`kind == 'parent' && active == true`。

### 2.5 `config/{id}` — 站台資訊

| doc | 欄位 | 型別 | 限制 | 說明 |
|---|---|---|---|---|
| `config/site` | `teacherDisplayName` | string | 1–20 字 | 家長看到的稱呼；留言區導師預設署名；頁尾 |
| | `schoolName` | string | ≤ 60 字，可空 | |
| | `studentsCount` | int | 1–40 | 導師頁用 |
| | `calendarIcsUrl` | string | ≤ 500，`https://`，可空 | **只收公開日曆網址**（`build_config.py` 擋私人 iCal 網址，因為這份文件全班讀者都讀得到） |
| | `updatedAt` | timestamp | | |

**誰寫**：`scripts/access_sync.py`（名單同步時一起寫）讀 `config/class.json` 的 `teacher.display_name`、`school_name`、
`students.count`、`calendar_ics_url` 寫進來。這幾個值**刻意不放進公開的 `site-config.js`**（知道網址的人都抓得到），
所以前端要登入後才讀得到（頁尾稱呼、行事曆訂閱鈕都在登入後才畫）。改了 `class.json` 要再跑 `access_sync.py`。
v1.1 的 `config/notify` 見 §2.18。

| 操作 | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| get `site` | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| get 其他 doc | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| list、建／改／刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

### 2.6 `posts/{slug}` 與 `posts/{slug}/content/main` — 班級紀事

**為什麼拆兩份**：Web SDK 的查詢不能只挑欄位，列表頁一次抓 20 篇就會連 20 篇正文一起下載。

**`posts/{slug}`（摘要）**

| 欄位 | 型別 | 必填 | 限制 | 說明 |
|---|---|---|---|---|
| `title` | string | ✓ | 1–120 字 | |
| `date` | string | ✓ | `YYYY-MM-DD` | 排序依據 |
| `category` | string | ✓ | ≤ 40 字 | 必須是 `class.json` 的 `categories` 之一（腳本驗） |
| `excerpt` | string | ✓ | ≤ 200 字 | 純文字，列表卡片用 |
| `coverPid` | string 或 null | ✓ | pid | 封面是哪一張（在本篇 `thumbs`／`images` 底下） |
| `coverThumb` | map 或 null | ✓ | `{ data, w, h }`，`data` ≤ 32,768 字元 | 封面縮圖的**內嵌複本**（§3.3），列表卡片不必再多讀一份；不建索引 |
| `photoCount` | int | ✓ | ≥ 0 | |
| `visible` | bool | ✓ | | 下架＝`false` |
| `publishedAt` | timestamp | ✓ | | 第一次發布時間 |
| `updatedAt` | timestamp | ✓ | | |

**`posts/{slug}/content/main`（正文）**

| 欄位 | 型別 | 必填 | 限制 | 說明 |
|---|---|---|---|---|
| `blocks` | array<map> | ✓ | ≤ 400 個區塊；整份文件 ≤ 800 KB（腳本驗） | 結構化區塊，格式見 ARCHITECTURE §4.1；**不存 HTML**；不建索引 |
| `updatedAt` | timestamp | ✓ | | |

正文的可見性**不另存一份**：規則直接讀父文件的 `visible`（多 1 次存取，換來不會兩邊不同步）。
規則只放行 id 是 `main` 的那一份（`content/` 底下別的 id 連導師都讀不到）。

**寫入順序**（`scripts/publish_post.py`）：顯示圖 → 縮圖 → `content/main` → 最後寫摘要（摘要出現在列表上時，
正文與照片一定都在）。重發時新版本沒用到的 pid 最後才刪。

| 操作 | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| get 摘要（可見，或不存在） | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| list 摘要（查詢必帶 `visible == true`） | ✗ | ✓ | ✓ | ✓ | ✓ | ✓（不必帶） | ✓ |
| get／list 下架的摘要 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| get 正文、照片（父文件可見時） | ✗ | ✓ | ✓ | ✓ | ✓ | ✓（不論可見） | ✓ |
| 建／改／刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

查詢：`posts.recent`、`posts.newer`、`posts.byCategory`（導師用 `.teacher` 版），見 §4.4。

### 2.7 留言：`posts/{slug}/comments`、`albums/{slug}/comments`、`private_posts/{slug}/comments`

三處**同一個欄位契約**，只差「誰進得了這個討論串」：

| 父集合 | 討論串門票 | 父文件必須 |
|---|---|---|
| `posts` | `isReader()`（讀）；建立另要 `isGoogle()` | 存在且 `visible == true`（導師：存在即可） |
| `albums` | `isReader()`（讀）；建立另要 `isGoogle()` | 同上 |
| `private_posts` | `isPrivateReader()`（本身就要 Google 登入） | 同上 |

父文件下架以後，**非導師連讀帶寫都不行**（下架的內容連同底下的討論一起收起來，知道網址也讀不到、留不了言）：規則的讀與建都 `get()` 父文件檢查 `visible`。
導師在下架的父文件底下照樣能讀能留言，但父文件**必須存在**（不能在不存在的紀事底下留孤兒留言；與部落格對話串「文章存在」同一個標準）。

**doc id**：`addDoc` 自動產生。

| 欄位 | 型別 | 必填 | 限制／規則驗什麼 |
|---|---|---|---|
| `authorName` | string | ✓ | 1–20 字；本人自填的署名（例「A 的媽媽」），導師預設帶 `config/site.teacherDisplayName`。**不可信**：可以署別人的名字，所以留言卡旁邊畫 `authorAlias` 前 4 碼（§0.5） |
| `body` | string | ✓ | 1–500 字；純文字（前端渲染規則見 ARCHITECTURE §4.3） |
| `role` | string | ✓ | 必須等於自己名單上的 `kind`（`teacher`／`parent`／`staff`）；是 `'teacher'` 時還必須 `isTeacher()` |
| `authorAlias` | string | ✓ | 符合 `^[a-z0-9]{12}$`，而且等於自己名單上的 `alias` |
| `status` | string | ✓ | 建立時必須 `'visible'`；之後只有導師能改成 `'hidden'` 或改回 |
| `createdAt` | timestamp | ✓ | 必須 `== request.time` |
| `replyTo` | string | 選填 | `^[A-Za-z0-9]{1,64}$`；同一串裡被回覆那則的 id，只驗格式不驗存在 |

| 操作 | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| 讀 `visible`（`posts`、`albums`；父文件可見） | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 讀 `visible`（`private_posts`；父文件可見） | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ |
| 讀 `hidden`、讀下架父文件底下的留言 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 建（Google 登入＋門票＋父文件可見＋欄位驗證） | ✗ | ✓（Google 登入；email 連結 ✗） | ✓ | ✓ | ✓（`private_posts` 只有這欄起） | ✓（父文件存在即可，不論可見） | ✓ |
| 改（只准動 `status`） | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓（資料退場） |

查詢：`comments.thread`（`where status == 'visible'`，即時）、`comments.count`、`comments.thread.teacher`、
留言後台 `comments.admin`（集合群組，只有導師，§2.19）。部落格對話串刻意叫 `blog_comments`，不會被集合群組 `comments` 罩到。

### 2.8 已讀回條：`posts/{slug}/reads/{key}`、`private_posts/{slug}/reads/{key}`

**已讀的定義故意放寬：打開過那一頁就算讀過。** 只有導師讀得到，所以直接用 email 鍵當 doc id。

| 欄位 | 型別 | 必填 | 規則驗什麼 |
|---|---|---|---|
| `kind` | string | ✓ | 等於自己名單上的 `kind`，而且只能是 `'parent'`／`'staff'`（導師不寫回條） |
| `readAt` | timestamp | ✓ | `== request.time` |

doc id 必須 `== emailKey()`（不能替別人簽到）；建立要 Google 登入（`validReceipt` 裡的 `isGoogle()`，§1.1）。

| 操作 | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| get 自己那份 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| get 別人那份、list、count | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 建（Google 登入＋門票＋父文件可見） | ✗ | ✓（`posts`；Google 登入，email 連結 ✗） | ✓（`posts`） | ✓（`posts`） | ✓（兩者） | ✗ | ✓ |
| 改／刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

- **寫法**（前端 `markRead`）：先 get 自己那份；「找不到」才建。**不靠「第二次寫入被拒」**判斷已讀過
  （那會跟真的被拒混在一起）。兩個分頁同時開造成的第二次建立被拒，只在這個方法裡吞掉。
- **X／N 判準**（前端 `read-stats.js` 單一正本；班級紀事與私密紀事各用各的門票與分母，看不到那篇的人不算進分母）：
  - 班級紀事：N＝`parent_child_map` 裡 `kind == 'parent' && active` 的 email 數；X＝回條 doc id 落在這批 email 裡的數量
    （單篇頁用 `reads.all` 精算；列表卡片徽章用 `reads.countParents` 近似）。同仁與導師兩邊都不算。
  - 私密紀事：N＝`private_allowlist` 人數減掉導師；X＝回條數（`reads.count`）。
- 相簿沒有回條。

### 2.9 `albums/{slug}` — 相簿

| 欄位 | 型別 | 必填 | 限制 | 說明 |
|---|---|---|---|---|
| `title` | string | ✓ | 1–80 字 | |
| `date` | string | ✓ | `YYYY-MM-DD` | |
| `description` | string | 選填 | ≤ 1000 字 | 純文字 |
| `order` | int | ✓ | | 小的排前面；前端排序 |
| `coverPid`、`coverThumb` | | ✓ | 同 §2.6 | |
| `photoCount` | int | ✓ | ≥ 0 | |
| `videos` | array<map> | ✓ | ≤ 20 支，每支 `{ title ≤ 80, url }`，`url` 必須 `https://` | **影片一律外部連結**（老師自選 YouTube 不公開或雲端硬碟分享），不存影片檔 |
| `linkUrl` | string | 選填 | `https://`，≤ 500 | 整本相簿另有外部連結時用（例如原圖夾）。示範模式的空卡＝`photoCount == 0` 且沒有 `linkUrl` |
| `visible` | bool | ✓ | | |
| `updatedAt` | timestamp | ✓ | | |

照片在 `albums/{slug}/thumbs/{pid}`、`albums/{slug}/images/{pid}`（§2.12），格子用 `photos.thumbs` 查詢依 `order` 排、
一次 60 張往下捲。只由 `scripts/publish_album.py` 寫；原圖不上雲端資料庫（只留在老師的電腦；複製到同步夾 `03_相簿原圖/<slug>/` 是 P4b）。

| 操作 | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| get（可見，或不存在）／list（必帶 `visible == true`） | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| get／list 下架的 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 讀照片（相簿可見時） | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 建／改／刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

留言見 §2.7（門票 `isReader()`）。

### 2.10 `private_posts/{slug}` — 私密紀事

篇數少，摘要與正文放同一份。

| 欄位 | 型別 | 必填 | 限制 |
|---|---|---|---|
| `title` | string | ✓ | 1–120 字 |
| `date` | string | ✓ | `YYYY-MM-DD` |
| `excerpt` | string | ✓ | ≤ 200 字（鎖頭卡用） |
| `blocks` | array<map> | ✓ | 同 §2.6；不建索引 |
| `coverPid`、`coverThumb` | | ✓ | 同 §2.6 |
| `photoCount` | int | ✓ | |
| `visible` | bool | ✓ | |
| `publishedAt`、`updatedAt` | timestamp | ✓ | |

只由 `scripts/publish_private.py` 寫。照片在 `private_posts/{slug}/thumbs|images/{pid}`。

| 操作 | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| get（可見，或不存在）／list（必帶 `visible == true`） | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ |
| get／list 下架的 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 讀照片（可見時） | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ |
| 建／改／刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

- 私密讀者一定是 Google 登入（§1.1）：email 連結登入的人就算在 `private_allowlist` 裡也被拒，畫面說明要改用 Google 登入。
- **併入紀事列表**：Session 沒有私密讀者身分的前端**根本不發** `private.list`；就算發了被拒，也靜默不顯示任何痕跡。
- 靜態殼裡**不得出現任何一篇私密紀事的標題、日期或路徑**。一般紀事的「上一篇／下一篇」只在 `posts` 之間走。
- 留言見 §2.7（門票 `isPrivateReader()`），回條見 §2.8。

### 2.11 `pages/{pageId}` — 首頁橫幅、課程頁與其他單頁

來源是本機 `data/pages/`（`scripts/publish_page.py`：關於我們、專題活動、首頁橫幅、獨立單頁）與 `data/courses/`
（`scripts/publish_courses.py`：`course`、`schedule`），轉成區塊與結構化資料寫入。`calendar` 這一種的寫入腳本
（從**公開**日曆網址抓活動）**還沒有實作**：v1 的行事曆只有首頁的「訂閱」按鈕（`config/site.calendarIcsUrl`）。
**不烘成靜態 HTML**（那樣知道網址就抓得到）。

| 欄位 | 型別 | 必填 | 限制 | 說明 |
|---|---|---|---|---|
| `title` | string | ✓ | 1–80 字 | |
| `kind` | string | ✓ | `'home'`｜`'course'`｜`'schedule'`｜`'about'`｜`'fun'`｜`'calendar'`｜`'standalone'`｜`'poem'`（v1.1） | |
| `blocks` | array<map> | 選填 | 同 §2.6；不建索引 | |
| `data` | map | 選填 | 依 `kind`，見下表；整份文件 ≤ 800 KB | 結構化內容（Firestore 陣列裡不能直接放陣列，一律包一層 map） |
| `order` | int | ✓ | | 同 `kind` 內排序 |
| `visible` | bool | ✓ | | |
| `updatedAt` | timestamp | ✓ | | |

| `kind` | `data` 形狀 |
|---|---|
| `home`（`pageId` 固定 `home`） | `{ bannerText ≤ 200, bannerPid? }`（橫幅照片在 `pages/home/images/{pid}`） |
| `calendar`（`pageId` 固定 `calendar`） | `{ events: [{ date, title ≤ 80, allDay }] }`，≤ 500 筆 |
| `fun` | `{ cards: [{ title ≤ 40, text ≤ 300, pid? }] }` |
| `schedule` | `{ rows: [{ cells: [string ≤ 40] }] }` |
| `course` | `{ videos: [{ title, url }], cards: [{ title, text, url? }] }` |
| `about`、`standalone` | 不用 `data`，只用 `blocks` |
| `poem`（v1.1；`pageId` 固定 `poems-YYYY-MM`，一個月一份，`scripts/publish_poems.py` 寫；`poems-` 開頭的代號保留給它，`publish_page.py` 不收） | `{ month: 'YYYY-MM', items: [{ date, title ≤ 80, author ≤ 40, text ≤ 2000, source? ≤ 200, guide? ≤ 1000 }] }`，1–31 首、日期不重複且都在那個月；不用 `blocks`。前端一次只 get 一個月那一份（不查詢）；還沒到的日子只有導師的畫面顯示。老師確認可公開使用的依據（`rights`）只留在本機母本 |

| 操作 | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| get（可見，或不存在）／list（必帶 `visible == true`） | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| get／list 下架的 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 讀照片（可見時） | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 建／改／刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

查詢：`pages.byKind`（`where visible == true`、`kind == :kind`，前端依 `order` 排）。

### 2.12 照片文件：`{主人}/thumbs/{pid}` 與 `{主人}/images/{pid}`

每張照片**兩份文件**：縮圖（格子、卡片用）與顯示圖（點開、正文裡用）。格子只讀縮圖，點開才讀顯示圖。
原圖只留在老師的電腦與雲端硬碟同步夾，不進資料庫。壓縮參數與大小算法見 §3。

**`thumbs/{pid}`**

| 欄位 | 型別 | 必填 | 限制 | 說明 |
|---|---|---|---|---|
| `data` | string | ✓ | 1–49,152 字元 | base64 的 JPEG 位元組，**不含** `data:` 前綴；不建索引 |
| `w`、`h` | int | ✓ | 1–480 | 像素 |
| `order` | int | ✓ | 0–9999 | 在主人底下的順序；部落格照片 `== int(pid)` |
| `caption` | string | 選填 | ≤ 300 字 | 只有腳本寫的照片有；部落格照片的圖說在文章的 `photos` 裡 |

**`images/{pid}`**

| 欄位 | 型別 | 必填 | 限制 | 說明 |
|---|---|---|---|---|
| `data` | string | ✓ | 1–716,800 字元 | base64 的 JPEG；不建索引 |
| `w`、`h` | int | ✓ | 1–1600 | |

- **不可變**：照片文件建立後**永遠不改**。換照片＝新 pid＋刪舊的兩份。所以前端可以「先查本機快取、沒有才上網」
  （ARCHITECTURE §4.4），重看同一張照片不花讀取次數與流量。
  腳本重發同一篇時：同一張照片的 pid 不變、顯示圖文件不重寫；只有它在這一篇裡的順序或圖說改了，腳本會重寫那份**縮圖**文件（`data` 一個位元組都不變，快取照樣正確）。
- 前端**一律**用 `'data:image/jpeg;base64,' + data` 當圖片來源，**MIME 寫死**，不從資料推斷；`<img>` 不會執行內容，
  所以就算資料被塞了別的東西也只是破圖（ARCHITECTURE §4.4）。
- 誰讀得到＝誰讀得到主人文件：規則對每種主人各寫一次（`get()` 主人文件看 `visible`，§A）。
- 誰寫：腳本（全部主人）；瀏覽器**只有部落格文章**底下的照片（§2.14）。

| 操作（主人文件可見時；導師不論可見） | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| 讀：紀事、相簿、單頁的照片 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 讀：私密紀事的照片 | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ |
| 讀：部落格文章的照片（自己被授權的座號） | ✗ | ✗ | ✓ | ✓ | ✗ | ✓ | ✓ |
| 讀：v1.1 家長合照、個人照 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 建：部落格文章的照片（跟文章同一批，下表） | ✗ | ✗ | ✓（自己座號） | ✗ | ✗ | ✓ | ✓ |
| 建：其他主人的照片 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |
| 改 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗（不可變；換照片＝新 pid） |
| 刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

| 瀏覽器寫部落格照片時規則驗什麼 | |
|---|---|
| 路徑 | `validSeat(seat)`、`validPostId(postId)`、`pid` 是 `'0'`、`'1'`、`'2'` |
| 身分 | `isTeacher()` 或 `isParentOf(seat)` |
| 欄位 | 縮圖只准 `data`、`w`、`h`、`order`（`order == int(pid)`）；顯示圖只准 `data`、`w`、`h`；型別與上限照上兩表 |
| 操作 | 只准建，不准改、不准刪（同一個 pid 第二次寫＝改＝被拒；重試一律換新 `postId`，§2.14） |

### 2.13 `student_blogs/{seat}` — 部落格主頁

**doc id**：座號。由 `scripts/open_blogs.py`（開部落格）依名冊建立，全班一次開好。

| 欄位 | 型別 | 必填 | 限制 | 說明 |
|---|---|---|---|---|
| `seat` | string | ✓ | 等於 doc id | |
| `displayName` | string | ✓ | 1–10 字 | 家長看到的孩子稱呼，**只放名、不放姓**（全名只在導師限定的 `roster`） |
| `intro` | string | 選填 | ≤ 500 字 | |
| `avatar` | map 或 null | ✓ | `{ data ≤ 32,768 字元, w, h }` | 頭像（內嵌 base64 JPEG）；不建索引 |
| `updatedAt` | timestamp | ✓ | | |

| 操作 | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| get 自己（被授權）的座號 | ✗ | ✗ | ✓ | ✓ | ✗ | ✓ | ✓ |
| get 別的座號、list | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 建／改／刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

家長**不能 list 整個集合**（規則無法對每一份證明座號相符），只能 get 自己座號那份——這是「家長只看得到自己孩子」的關鍵。

### 2.14 `student_blogs/{seat}/entries/{postId}` — 部落格文章

子集合名是 `entries`（不叫 `posts`，免得跟班級紀事的 `posts` 集合群組撞名：導師用集合群組查詢時會把兩種混在一起）。

| 欄位 | 型別 | 必填 | 限制／規則驗什麼 | 寫入者 |
|---|---|---|---|---|
| `title` | string | ✓ | 1–200 字 | 發文者；之後導師可改 |
| `body` | string | ✓ | 1–10,000 字；**純文字、逐字保留**；不建索引 | 發文者；之後導師可改 |
| `date` | string | ✓ | `YYYY-MM-DD`，**而且等於 `postId` 的前 10 碼**（規則 `d.date == postId[0:10]`：不能把日期填到未來、釘在最上面） | 發文者 |
| `author` | string | ✓ | 家長發 `'parent'`、導師發 `'teacher'`，與登入身分一致 | 發文者 |
| `authorAlias` | string | ✓ | 符合 `^[a-z0-9]{12}$`，而且等於自己名單上的 `alias`（腳本發的導師文寫導師的代號） | 發文者 |
| `photos` | array<map> | ✓ | 0–3 個；第 i 個必須是 `{ pid: 'i', w, h, caption? }`（`caption` ≤ 300 字）；可以是空陣列 | 發文者 |
| `visible` | bool | ✓ | 建立時必須 `true` | 發文者；之後導師 |
| `createdAt` | timestamp | ✓ | `== request.time` | 發文者 |
| `updatedAt` | timestamp | 選填 | 導師改文時 `== request.time` | 導師 |

**沒有**留言數、最後留言時間這類反正規化欄位：v1 沒有背景程式維護它們。對話則數用 `blogComments.count` 即時查；
導師端的「未讀」用集合群組查詢 `entries.recentParent`、`blogComments.recentParent` 比對導師本機記的「已看到哪裡」。

| 操作 | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| get 自己座號（可見，或不存在）／list（必帶 `visible == true`） | ✗ | ✗ | ✓ | ✓ | ✗ | ✓ | ✓ |
| 讀下架的、讀別的座號 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 讀照片（文章可見時） | ✗ | ✗ | ✓ | ✓ | ✗ | ✓ | ✓ |
| 建文章＋照片 | ✗ | ✗ | ✓（自己座號、`author:'parent'`） | ✗ | ✗ | ✓（任何座號、`author:'teacher'`） | ✓ |
| 改 | ✗ | ✗ | ✗（家長發的文不能改） | ✗ | ✗ | ✓（只准 `title`、`body`、`visible`、`updatedAt`） | ✓ |
| 刪 | ✗ | ✗ | ✗（也不能刪） | ✗ | ✗ | ✗（網頁上只能下架） | ✓（資料退場） |

**發文＝一個批次**（瀏覽器，ARCHITECTURE §5.6）：文章＋每張照片的縮圖與顯示圖，最多 7 個寫入，**一次成功或一次失敗**。
失敗後重試**一律換新的 `postId`**（同一個 `postId` 再寫會變成「改」而被拒）。
瀏覽器重新編碼 JPEG 就丟掉了 EXIF（含 GPS）；**不上傳原檔**。

### 2.15 `…/entries/{postId}/blog_comments/{cid}` — 導師與家長的對話串

一篇部落格文章底下，導師與**那個孩子的家長**之間的對話。同仁可以看文章，但**看不到對話串**。

| 欄位 | 型別 | 必填 | 規則驗什麼 |
|---|---|---|---|
| `body` | string | ✓ | 1–500 字，純文字 |
| `role` | string | ✓ | 導師 `'teacher'`、家長 `'parent'`，與登入身分一致 |
| `authorAlias` | string | ✓ | 符合 `^[a-z0-9]{12}$`，而且等於自己名單上的 `alias` |
| `status` | string | ✓ | 建立時 `'visible'` |
| `createdAt` | timestamp | ✓ | `== request.time` |

五欄全必填、不得多帶。顯示用的「導師／家長」字樣由前端依 `role` 畫，不存。

| 操作 | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| 讀 `visible`（自己座號、文章可見；list 必帶 `status == 'visible'`） | ✗ | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ |
| 讀 `hidden`、讀下架文章底下的 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 建 | ✗ | ✗ | ✓（文章可見、`role:'parent'`） | ✗ | ✗ | ✓（文章存在、`role:'teacher'`） | ✓ |
| 改（只准 `status`） | ✗ | ✗ | 只能把**自己那則**（`authorAlias` 相符）從 `visible` 改成 `hidden`，**不能改回** | ✗ | ✗ | ✓（收起或還原任何一則） | ✓ |
| 刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓（資料退場） |

### 2.16 `roster/{id}` — 導師限定的名冊與連結

| doc | 欄位 | 說明 |
|---|---|---|
| `roster/students` | `students`: array<map> `{ seat, name ≤ 40, displayName ≤ 10 }` | `name`＝全名（雲端唯一存全名的地方）；`displayName`＝稱呼 |
| | `updatedAt` | |
| `roster/links` | `recordsKitUrl`（`https://`，可空） | 學生觀察與課程紀錄（teacher-records-kit）的網址，§2.21 |
| | `classDocsIndexUrl`（`https://`，可空） | 同步夾裡「班級文件索引」在雲端硬碟上的網址（老師自己貼） |
| | `updatedAt` | |

由 `access_sync.py`（名冊）與 `publish_site.py`（連結）寫。

| 操作 | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| get | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| list、建／改／刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

### 2.17 `ops/{id}` — 心跳

| doc | 寫入者 | 欄位 |
|---|---|---|
| `ops/backup_status` | `scripts/backup.py` | `nightly: { lastRunAt, ok }`、`weekly: { lastRunAt, ok }` |

v1 沒有排程：`weekly`＝`backup.py firestore`（整個資料庫快照），`nightly`＝`backup.py blogs`（部落格匯出）；`backup.py all` 兩個都寫，失敗寫 `ok: false`。

欄位名 `nightly`／`weekly` 是沿用的名字：v1 **沒有任何排程**，兩條線都是老師（或代理照劇本）說「備份」才跑的。
所以導師專用頁的「備份狀態」用**跟 `scripts/status.py` 同一組門檻**（正本 `scripts/lib/thresholds.py`）：
超過 7 天沒成功才提醒、14 天加重語氣；上一次寫了 `ok: false` 就提醒（`tests/test_v11_site.py` 比對前端與正本的數字）。
前身實作用「每夜 36 小時」「48 小時」這類小時級門檻，手動備份的班級幾乎每天都在誤報。

| 操作 | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本 |
|---|---|---|---|---|---|---|---|
| get | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| list、建／改／刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

### 2.18 v1.1 集合（先定形狀，v1 的規則也先寫好：只有導師讀、沒有人從網頁寫）

| 路徑 | 欄位 | 寫入者 |
|---|---|---|
| `seating/{planId}`（`YYYY-MM-DD` 或 `YYYY-MM-DD-n`，日期＝起用日） | `title ≤ 60`、`date`、`rows: [{ seats: ["01", "", "-", "03"] }]`（1–15 排、每排 1–15 格；只放座號，`""`＝空位、`"-"`＝走道；座號不重複、至少一位）、`note ≤ 500`、`updatedAt` | `publish_seating.py`（母本 `data/seating/<planId>.json`；座號要在名冊裡；名字不上雲，前端用 `roster/students` 的稱呼補） |
| `parent_photo_display/{seat}` ＋ `thumbs|images/{pid}` | `relations: [string]`（0–4 個稱謂，每個 1–10 字，預設取 `parent-roles.yaml` 那個座號的宣告；**不存家長姓名**）、`note ≤ 200`、`photoPids: [pid]`（1–3 個，內容定址）、`updatedAt` | `publish_parent_photo.py`（本機照片，或從那位孩子的部落格文章挑一張重新處理） |
| `personal_photos/{seat}` ＋ `thumbs|images/{pid}` | `photoPids: [pid]`（1–3 個）、`updatedAt` | `publish_personal_photos.py`（`data/personal-photos/<座號>.<副檔名>`，檔名只准座號，原檔名不上雲） |
| `config/notify` | `phase: 'off'|'dryrun'|'live'`（看不懂的值一律當 `off`）、`teacherMail`／`parentMail`／`digest`（bool，三種信各自的開關）、`notifyFloor`（timestamp：從 off 打開那一刻的伺服器時間，之前建立的內容一律不寄）、`teacherEmail`（導師收件）、`teacherKey`（導師 email 鍵，名單檢查用）、`fromEmail`（寄件 Gmail，SMTP 登入帳號）、`senderName ≤ 40`、`signature ≤ 300`、`className ≤ 40`、`updatedAt`。只有導師讀得到（`config/{id}` 規則）；Gmail 應用程式密碼**不在這裡**（在 Secret Manager） | `notify_config.py`（寄件人、署名、信箱從 `class.json` 來） |
| `blog_notify_queue/{queueId}`（導師發文 `{seat}__{postId}`、導師回覆 `{seat}__{postId}__{cid}`：doc id 固定，觸發器重送也只排一次） | `kind: 'post'|'comment'`、`seat`、`postId`、`cid?`、`state: 'pending'|'done'|'cancelled'|'skipped'|'failed'`、`phaseAtEnqueue`、`attempts`、`enqueuedAt`、`contentCreatedAt`、`sendAfter`（＝內容建立＋30 分鐘）、`leaseUntil?`（處理中的租約）、結束後 `mode`、`reason`、`recipientCount`、`sentCount`、`lastError`（信箱已遮）、`doneAt`。**不存標題與信箱** | v1.1 Functions（觸發器排、`cmwNotifySweep` 每 10 分鐘掃） |
| `blog_notify_queue/{queueId}/sent/{hash}` | 逐人寄信台帳：doc id＝收件人 email 鍵的 SHA-256 前 32 碼；`state: 'sending'|'sent'`、`at`、`sentAt`。先佔位再寄、寄失敗就拿掉佔位：寧可少寄一封，絕不重寄 | v1.1 Functions |
| `notify_once/{id}` | 給導師的即時信「只寄一次」的佔位（id＝事件路徑的 SHA-256 前 32 碼）：`kind`、`at` | v1.1 Functions；**規則沒有這個集合＝預設全拒**，連導師的網頁都讀不到 |
| `ops/notify_status` | 排程心跳：`lastRunAt`、`phase`、`pending`、這一輪的 `processed`／`sent`／`dryrun`／`cancelled`／`skipped`／`failed`／`retry`、`lastError`；即時信的 `lastInstantAt`、`lastInstantError`、`lastInstantErrorAt`（信箱已遮） | v1.1 Functions |
| `ops/digest_status` | 每日摘要心跳：`lastRunAt`、`sent`、`problems`、`skipped?`、`cleaned`、`lastError` | v1.1 Functions |

佇列、台帳與 `notify_once` 超過 30 天（而且已經結束）的，由每日摘要那一支順手刪掉：裡面只剩座號與雜湊，但沒有理由一直留。
Functions 走管理身分、不受規則管，所以通知信模組**不需要改任何規則**；上面這幾個集合網頁一律寫不進去（規則 `write: if false` 或預設全拒）。

| 操作（上表每一個集合與其子集合） | 未登入 | 讀者 | 座號家長 | 同仁 | 私密讀者 | 導師 | 腳本／v1.1 Functions |
|---|---|---|---|---|---|---|---|
| get／list | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| 建／改／刪 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

### 2.19 導師的集合群組讀取

```
match /{path=**}/comments/{cid}      { allow read: if isTeacher(); }   // 留言後台 comments.admin
match /{path=**}/entries/{postId}    { allow read: if isTeacher(); }   // entries.recentParent
match /{path=**}/blog_comments/{cid} { allow read: if isTeacher(); }   // blogComments.recentParent
```

遞迴規則與各路徑的規則是「聯集」，只開給導師，不會放寬任何人的權限。集合群組查詢**只准導師**（§4 程式驗證）。

### 2.20 預設拒絕

規則檔最後一定是 `match /{document=**} { allow read, write: if false; }`。本文件沒列到的路徑一律拒絕。
新增集合＝先改這份文件。

### 2.21 不在本 repo：學生觀察與課程紀錄

學生個別觀察、全班觀察與課程紀錄**不放在這個框架的資料庫裡**；需要的話另外用一套紀錄工具，例如開源的 **teacher-records-kit**
（同一台電腦另裝一份，用**另一個** Firebase 專案）。接點只有三個：導師專用頁的入口卡讀 `roster/links.recordsKitUrl`；
本機 `data/records/` 只放一份說明指向 kit 的 `data/`；建議兩邊用同一套兩位數座號。本 repo 的規則、腳本、前端**不讀、不寫**
kit 的任何集合。

---

## 3. 照片的大小與壓縮參數

### 3.1 為什麼照片放 Firestore

v1 只用 Firestore：照片跟著同一套規則、同一個登入走，沒有第二套權限要對齊，
也沒有「永久公開網址」這種東西。代價是單份文件 1 MiB 的上限與較貴的儲存，所以每張照片壓成兩份小文件。

### 3.2 大小算法（官方：Firestore 儲存大小計算）

- 文件大小＝文件名稱大小＋每個欄位（欄位名 UTF-8 位元組＋1，加上值的大小）＋32。字串值＝UTF-8 位元組＋1。
- base64 字串全是 ASCII：**字元數＝位元組數**。base64 長度＝`4 × ceil(JPEG 位元組 / 3)`（約 1.34 倍）。
- 單份文件上限 1 MiB（1,048,576 位元組）；單一欄位值上限 1,048,487 位元組；單次 API 請求 10 MiB。
- 顯示圖上限 716,800 字元＋其他欄位與名稱約 200 位元組，離 1 MiB 還有約 30% 餘裕；
  部落格批次（3 份顯示圖＋3 份縮圖＋文章）最大約 2.3 MB，遠低於 10 MiB。
- `data`、`blocks`、`coverThumb`、`avatar`、部落格 `body` 在 `firestore.indexes.json` 裡**關掉單欄索引**（§4）：
  不查詢它們，而且大字串的索引項目也佔儲存。

### 3.3 壓縮參數（腳本用 Pillow、瀏覽器用 canvas，同一套數字）

| 項目 | 縮圖 `thumbs` | 顯示圖 `images` | 內嵌縮圖 `coverThumb`／`avatar` |
|---|---|---|---|
| 最長邊 | 320 px | 1280 px | 同縮圖（320 px） |
| 格式 | JPEG，漸進式，4:2:0 取樣，sRGB，**不寫 EXIF、XMP、ICC** | 同左 | 同左 |
| 品質階梯（從左往右試，第一個符合目標就停） | 72 → 64 → 56 → 48 | 82 → 76 → 70 → 64 → 58；還太大就把最長邊改 1024 再從 82 試一輪 | 同縮圖 |
| **目標**（JPEG 位元組） | ≤ 24 KB（base64 ≤ 32,768 字元） | ≤ 300 KB（base64 ≤ 400,000 字元） | ≤ 24 KB |
| **硬上限**（規則／`schema.py` 擋的 base64 字元數） | 49,152 | 716,800 | 32,768 |
| 一般照片實際大小（估計） | 12–20 KB | 150–250 KB | 12–20 KB |

- 硬上限比目標寬，是給「階梯走完仍略超過目標」的照片留路；超過硬上限就**拒絕上傳**並告訴老師是哪一張。
- 腳本先 `ImageOps.exif_transpose()` 依 EXIF 方向轉正，再縮、再存；存完**重新開檔斷言沒有 EXIF／XMP**，斷言失敗就不寫。
- 瀏覽器端用 `createImageBitmap(file, { imageOrientation: 'from-image' })` 轉正後畫到 canvas，`canvas.toBlob('image/jpeg', q)`；
  canvas 重新編碼本身不帶任何 EXIF。

---

## 4. 查詢形狀登記表

### 4.1 為什麼要登記

Firestore 模擬器**不檢查複合索引**，本機全綠的查詢上線才噴「需要索引」；而非導師少帶一個
`visible` 條件，規則會整批拒絕。所以：

1. 每個查詢形狀先登記在 `templates/queries.json`（正本），前端 `Store.query／watch／count` **只准用登記過的查詢名**。
2. `python3 scripts/build_indexes.py` 從它產生 `firestore.indexes.json`（部署用）與 `site/js/core/queries.js`
   （前端讀的 `CMW.QUERIES`），兩個都進 git、不准手改。
3. 單元測試（`tests/test_build_indexes.py`，`scripts/check.py` 會跑）比對：每個查詢都有撐得住的索引（用獨立寫法的比對器）、
   沒有多餘的複合索引、單欄位查詢不產生複合索引、產生檔是最新的、非導師查詢都帶了成員過濾條件、集合群組查詢只給導師、
   本節的表跟登記表逐字一致、兩份文件提到的查詢名都有登記。

### 4.2 登記表格式（`templates/queries.json`）

```
{
  "version": 1,
  "roles": { "teacher": "…", "reader": "…", … },              // 說明用
  "collections": {                                             // 每個被查詢的集合 id 都要宣告，三選一：
    "posts":    { "memberFilter": ["visible", "==", true] },   //   非導師查詢一定要帶這個 where
    "reads":    { "teacherOnly": true },                       //   非導師不准查
    "thumbs":   { "gatedByParent": true }                      //   門票由主人文件決定，不必帶條件
  },
  "queries": {
    "posts.recent": {
      "use": "用在哪（寫給人看）",
      "who": ["reader"],                  // teacher｜reader｜privateReader｜seatReader｜seatParent｜functions
      "path": "posts",                    // 集合路徑；{參數} 由 CMW.paths 產生（可代表多段，例如 {thread} = posts/<slug>）
      // 或 "group": "comments"           // 集合群組查詢（只准 teacher／functions）
      "where": [["visible", "==", true], ["category", "==", ":category"]],   // 值：常數，或 :參數
      "orderBy": [["date", "desc"]],
      "limit": 20,                        // 必填（count 除外），1–500；呼叫端只能再調小
      "limitToLast": false,               // 搭 endBefore 用
      "cursor": "startAfter",             // startAfter｜endBefore｜不寫
      "count": false,                     // true＝count 聚合查詢（不能帶 orderBy／limit／cursor）
      "watch": false,                     // true＝允許 onSnapshot 即時
      "sortClient": [["order", "asc"]],   // 前端自己排（沒有 orderBy 的查詢用）
      "batch": "v1"                       // v1｜v1.1
    }
  },
  "exempt": [ { "collectionGroup": "images", "fieldPath": "data", "why": "…" } ]   // 關掉單欄索引的欄位
}
```

只支援 `==`、`<`、`<=`、`>`、`>=`（不收 `!=`、`in`、`array-contains`；要用先改產生器與這一節）。

### 4.3 索引推導規則（`build_indexes.py` 的 `required_indexes()`）

| 查詢長相 | 需要什麼 |
|---|---|
| 只有 `==` 條件、沒有範圍也沒有排序 | 不用複合索引（Firestore 合併單欄索引） |
| 沒有 `==`，總共只牽涉一個欄位（例如只 `orderBy date`，或範圍＋排序同一欄） | 不用（自動單欄索引） |
| 其他 | **複合索引**：`==` 欄位（↑，照登記順序）＋`orderBy` 欄位（照方向）＋沒被排序的範圍欄位（↑） |
| 集合群組查詢、又不需要複合時 | 每個牽涉的欄位一個「集合群組範圍」單欄索引（預設沒有），寫成 `fieldOverrides`，而且**把預設的三個集合範圍索引一起列回去**（覆寫會取代預設） |
| `exempt` 的欄位 | `fieldOverrides` 的 `indexes: []`；登記表裡的查詢不准用這些欄位 |

另外驗：範圍條件只能一個欄位、有範圍時第一個 `orderBy` 必須是它、`orderBy` 欄位不能同時是 `==` 條件、
`cursor`／`limitToLast` 要有 `orderBy`、`limitToLast` 要搭 `endBefore`。

部署索引**絕對不加 `--force`**（會刪掉線上有、檔案裡沒有的索引）。索引剛部署時要幾分鐘才建好，部署腳本會等到全部 READY
才部署網站（ARCHITECTURE §7.3）。

### 4.4 目前登記的查詢

<!-- queries-table:begin（由 python3 scripts/build_indexes.py --markdown 產生，不要手改） -->
| 查詢名 | 誰 | 集合 | where | orderBy | 上限／游標 | 索引 | 用在哪 |
|---|---|---|---|---|---|---|---|
| `albums.list` | reader | `albums` | visible == true | — | 200 | 不用（只有等號） | 相簿列表、首頁相簿條 |
| `albums.list.teacher` | teacher | `albums` | — | — | 200 | 不用 | 導師看的相簿列表（含已下架） |
| `allowlist.all` | teacher | `allowlist` | — | — | 500 | 不用 | 導師端把留言上的作者代號（authorAlias）對回名單與身分 |
| `blogComments.count` | seatParent、teacher | `{entry}/blog_comments` | status == "visible" | — | count | 不用（只有等號） | 部落格文章卡片上的對話則數（導師也用這一個） |
| `blogComments.recentParent` | teacher | 群組 `blog_comments` | role == "parent" | createdAt desc | 200 | 複合（集合群組）：role↑ createdAt↓ | 導師端「家長新留的話」未讀（集合群組） |
| `blogComments.thread` | seatParent | `{entry}/blog_comments` | status == "visible" | — | 200 | 不用（只有等號） | 部落格文章底下導師與家長的對話串 |
| `blogComments.thread.teacher` | teacher | `{entry}/blog_comments` | — | — | 200 | 不用 | 導師看的對話串（含已收起） |
| `blogs.all` | teacher | `student_blogs` | — | — | 40 | 不用 | 我的孩子導師端全班格 |
| `comments.admin` | teacher | 群組 `comments` | — | createdAt desc | 200 startAfter 即時 | 集合群組單欄：createdAt↓ | 留言後台：全站最新留言（集合群組） |
| `comments.count` | reader、privateReader、teacher | `{thread}/comments` | status == "visible" | — | count | 不用（只有等號） | 卡片上的留言數（導師也用這一個） |
| `comments.thread` | reader、privateReader | `{thread}/comments` | status == "visible" | createdAt desc | 100 即時 | 複合：status↑ createdAt↓ | 紀事、相簿、私密紀事三種留言串（即時）；{thread} 由 CMW.paths 產生（posts/<slug>、albums/<slug>、private_posts/<slug>），私密紀事的串要私密讀者 |
| `comments.thread.teacher` | teacher | `{thread}/comments` | — | createdAt desc | 100 即時 | 不用（自動單欄） | 導師看的留言串（含已收起） |
| `entries.bySeat` | seatReader | `student_blogs/{seat}/entries` | visible == true | — | 300 | 不用（只有等號） | 我的孩子：某個座號的文章列表（家長與同仁） |
| `entries.bySeat.teacher` | teacher | `student_blogs/{seat}/entries` | — | — | 300 | 不用 | 導師看某個座號的文章（含已下架） |
| `entries.recentParent` | teacher | 群組 `entries` | author == "parent" | createdAt desc | 100 | 複合（集合群組）：author↑ createdAt↓ | 導師端「家長新發的文」未讀（集合群組；比對導師本機的已看時間） |
| `notifyQueue.due` | functions | `blog_notify_queue` | state == "pending"、sendAfter <= :now | sendAfter asc | 50（v1.1） | 複合：state↑ sendAfter↑ | v1.1 通知信：掃描到期的待寄佇列 |
| `pages.byKind` | reader | `pages` | visible == true、kind == :kind | — | 100 | 不用（只有等號） | 課程頁、專題活動卡片、關於我們等同類單頁 |
| `pages.byKind.teacher` | teacher | `pages` | kind == :kind | — | 100 | 不用（只有等號） | 導師看的同類單頁（含已下架） |
| `parentMap.all` | teacher | `parent_child_map` | — | — | 500 | 不用 | 已讀 X/N 的 N、全班格的身分標示「A（母）」 |
| `parentPhotos.all` | teacher | `parent_photo_display` | — | — | 40（v1.1） | 不用 | 導師限定的個人照相簿：全班的家長合照文件（稱謂、備註、照片 pid） |
| `personalPhotos.all` | teacher | `personal_photos` | — | — | 40（v1.1） | 不用 | 導師限定的個人照相簿：全班的個人照文件（照片本身再用 photoSrc 讀縮圖） |
| `photos.thumbs` | reader、privateReader、seatReader、teacher | `{owner}/thumbs` | — | order asc | 60 startAfter | 不用（自動單欄） | 相簿格、紀事／單頁的縮圖列；{owner} 是照片的主人文件（相簿、紀事、私密紀事、單頁、部落格文章），門票由主人文件決定 |
| `posts.byCategory` | reader | `posts` | visible == true、category == :category | date desc | 20 startAfter | 複合：visible↑ category↑ date↓ | 分類頁 |
| `posts.byCategory.teacher` | teacher | `posts` | category == :category | date desc | 20 startAfter | 複合：category↑ date↓ | 導師看的分類頁（含已下架） |
| `posts.newer` | reader | `posts` | visible == true | date desc | 1 limitToLast endBefore | 複合：visible↑ date↓ | 單篇頁的「下一篇」（較新那篇：endBefore 目前這篇、limitToLast 1） |
| `posts.newer.teacher` | teacher | `posts` | — | date desc | 1 limitToLast endBefore | 不用（自動單欄） | 導師看的下一篇（含已下架） |
| `posts.recent` | reader | `posts` | visible == true | date desc | 20 startAfter | 複合：visible↑ date↓ | 首頁最新 3 篇（limit 3）、紀事列表（往下捲 startAfter）、單篇頁的「上一篇」（startAfter 目前這篇、limit 1） |
| `posts.recent.teacher` | teacher | `posts` | — | date desc | 20 startAfter | 不用（自動單欄） | 導師看的首頁／列表／上一篇（含已下架） |
| `private.list` | privateReader | `private_posts` | visible == true | — | 100 | 不用（只有等號） | 私密紀事列表、併入紀事列表的鎖頭卡 |
| `private.list.teacher` | teacher | `private_posts` | — | — | 100 | 不用 | 導師看的私密紀事列表（含已下架） |
| `privateAllowlist.all` | teacher | `private_allowlist` | — | — | 500 | 不用 | 私密紀事已讀的分母（私密名單人數，不算導師） |
| `reads.all` | teacher | `{thread}/reads` | — | — | 200 | 不用 | 單篇頁導師看已讀名單（X/N 的 X） |
| `reads.count` | teacher | `{thread}/reads` | — | — | count | 不用 | 私密紀事卡片上的已讀數（分母＝私密名單人數，見 DATA-MODEL §2.8） |
| `reads.countParents` | teacher | `{thread}/reads` | kind == "parent" | — | count | 不用（只有等號） | 紀事卡片上的導師已讀徽章：家長回條數 |
| `seating.all` | teacher | `seating` | — | — | 100（v1.1） | 不用 | 導師專用頁的座位表 |
<!-- queries-table:end -->

`{thread}`、`{owner}`、`{entry}`、`{seat}` 一律由 `site/js/core/paths.js`（`CMW.paths`）產生，頁面程式不自己拼路徑。

---

## 5. 容量與費用（預設 Spark 免費方案）

### 5.1 Spark 免費額度（2026-09-25 查官方價目頁與 Auth 限制頁）

| 項目 | Spark 免費額度 | 一個班大概用多少（§5.2） |
|---|---|---|
| Firestore 儲存 | **1 GiB**（總量，含索引與中繼資料） | 一學年約 460–760 MB，**主要是照片** |
| Firestore 讀取 | 50,000 次／天 | 平常 5,000–10,000；新相簿那天 15,000–20,000 |
| Firestore 寫入 | 20,000 次／天 | 幾百；上一本 80 張的相簿＝161 次 |
| Firestore 刪除 | 20,000 次／天 | 平常近 0；學年末清空一次約 6,000 |
| Firestore 網路流量 | 10 GiB／月 | 約 2–4 GiB（照片佔大宗） |
| Hosting 儲存 | 10 GB | 網站空殼不到 5 MB |
| Hosting 傳輸 | 360 MB／天 | 約 30–50 MB |
| Auth：Google 登入 | 一個班的量沒有限制 | — |
| Auth：**email 連結登入信** | **5 封／天**（Blaze：25,000 封／天；官方註明「加上付款方式才能超過 5 封」） | 見下方說明 |

- 每日額度大約在美國太平洋時間午夜重置（台灣下午 3–4 點）；網路流量按月。
- 只有 `(default)` 資料庫吃得到免費額度，所以**只用這一個資料庫**。
- 規則裡的 `get()`／`exists()` 每份文件算一次讀取（同一請求同一份只算一次），已算進上表。
- **email 連結登入每天 5 封**是 Spark 最可能卡到人的地方：一封信只登入一台裝置，登入後會一直保持登入。
  所以：Google 登入是主要入口（家長有 Gmail 就用它，沒有數量限制）；email 連結給沒有 Google 帳號的人，
  開學第一週請老師分批發連結（一天最多 5 位）。超過時前端顯示「今天的登入信額度用完了，請改用 Google 帳號登入，或明天再試」
  （ARCHITECTURE §3.4）。非 Google 帳號的家長很多的班級，建議直接升 Blaze（§5.4）。
- **這 5 封任何知道網址的人都能耗盡**：登入閘的「寄登入連結」不需要先登入，隨便填 5 個信箱，當天全班沒有 Google 帳號的家長
  就收不到登入信（也等於能用班網的網域寄信給任意地址）。建議開 **App Check（reCAPTCHA）** 擋掉不是從你網站送出的請求，
  或乾脆**不開 email 連結**（只用 Google 登入；§1.1 另有「帳號預先註冊」的理由）。

### 5.2 一個班一年的估算

**每張照片佔多少**（§3.3 的參數；「其他」＝兩份文件的名稱、欄位、`w`／`h`／`order` 的索引項目，約 2.5 KB）：

| 情況 | 顯示圖 base64 | 縮圖 base64 | 合計（含其他） |
|---|---|---|---|
| 一般照片（JPEG 顯示圖約 180 KB、縮圖約 15 KB） | 240,000 | 20,000 | **約 262 KB** |
| 每張都壓到目標上限 | 400,000 | 32,768 | 約 435 KB |
| 每張都頂到硬上限（幾乎不會發生） | 716,800 | 49,152 | 約 768 KB |

**幾張照片會碰到 1 GiB**（先保留 50 MB 給文字、留言、名單、單頁）：

| 情況 | 張數 |
|---|---|
| 一般照片 | **約 3,900 張** |
| 每張都壓到目標上限 | 約 2,350 張 |
| 每張都頂到硬上限 | 約 1,330 張 |

**一個班一學年大概會放幾張**（假設，老師自己的習慣可能差很多）：

| 來源 | 假設 | 張數 |
|---|---|---|
| 相簿 | 每月 2 本 × 每本 40 張 × 10 個月 | 800 |
| 班級紀事 | 每週 2–3 篇 × 平均 3 張 × 40 週 | 300 |
| 部落格 | 25 位 × 每學期 8 篇 × 2 學期 × 平均 1.5 張 | 600 |
| 私密紀事、單頁 | | 50 |
| **合計** | | **約 1,750 張 → 一般約 460 MB，壓到上限約 760 MB** |

**結論**：一學年放得下；**第二學年累積就會碰到 1 GiB**。學年結束照 §6.2 封存或清掉照片文件（腳本發的照片原圖本來就在
同步夾，部落格照片由每夜備份存下來），或升 Blaze（§5.4）。每週拍 100 張以上的老師，一學年內就會碰到，建議一開始就升 Blaze。

**讀取**：一次頁面載入大約 10–80 次讀取（相簿格一張縮圖 1 次；Session 解析 3–4 次，分頁內快取 30 分鐘）。
50 位讀者平常一天約 5,000–10,000 次；新相簿那天大家都去看，約 15,000–20,000 次。導師的留言後台一次讀 200 則、
全班格一次約 300 次。已內建的省法：照片文件不可變，前端**先查本機快取**（§2.12）；每個查詢都有上限（§4）；
計數一律用 count 查詢（每 1,000 筆索引項目只算 1 次讀取）。

**流量**：每位讀者每月看 8 本新相簿（每本 60 張縮圖＋點開 10 張，約 3.6 MB）＋12 篇紀事（約 1 MB）≈ 41 MB；
50 位約 2 GiB，重複觀看沒吃到快取的話約翻倍。**備份必須是增量的**：`backup.py` 只下載新增的照片文件
（其餘只列名稱比對），否則 1 GB 的資料庫每天全抓一次，一個月就是 30 GiB。

### 5.3 用完時長什麼樣

- Spark 用量到頂時，**那一項服務暫停到額度重置**，不會收費。前端把 Firestore 的 `resource-exhausted` 轉成
  `StoreError('quota')`，畫面顯示「今天的免費額度用完了，台灣時間下午 4 點左右恢復」＋「老師可以升級方案，不用改任何設定」。
- 儲存超過 1 GiB：之後的寫入（發文、上傳、留言）失敗，讀取照常。腳本寫入失敗時原樣印出錯誤＋提示看用量頁。
- `scripts/status.py` 用最近一份資料庫備份估算佔用（文件 JSON＋照片池檔的實際大小＋每份文件約 1.25 KB 的名稱與索引），**超過 1 GiB 的 70%（約 750 MB）就提醒**。
- 看實際用量：Firebase 主控台 → Firestore → 「用量」分頁；Authentication → 「用量」。

### 5.4 升 Blaze（不改任何程式）

1. Firebase 主控台左下角方案名稱 →「升級」→ 選 Blaze → 建立或選一個 Cloud Billing 帳戶（要信用卡）。
2. **馬上設預算警示**：Google Cloud 主控台 → 帳單 → 預算與快訊 → 建一個（例如每月 US$5，50%／90%／100% 寄信）。
   警示**只會通知，不會封頂**；安裝精靈要照實講。
3. 其他都不用動：同一個專案、同一個網址、同一套規則、同一份資料。`doctor.py --cloud` 會顯示「方案：Blaze」。
4. Blaze 保有同樣的免費額度，只付超過的部分（Firestore 儲存約 US$0.15–0.20／GiB·月、讀取每 10 萬次約 US$0.03–0.04，
   依地區；以官方價目頁為準）。email 連結登入信變成每天 25,000 封。
5. v1.1 的通知信模組**一定要** Blaze（ARCHITECTURE §10）。

### 5.5 地區

| 服務 | 地區 | 怎麼決定 | 能不能改 |
|---|---|---|---|
| Firestore `(default)` | `config.region`（預設 `asia-east1`） | 安裝精靈第 2 步在主控台建立資料庫時選，**必須與 `class.json` 的 `region` 相同** | **不能**（建了就固定） |
| Hosting、Auth | 全球 | — | — |
| （v1.1）Cloud Functions | 同 Firestore | `build_config.py` 產生的設定 | 重新部署即可 |

`doctor.py --cloud` 檢查 Firestore 資料庫的實際地區等於 `class.json` 的 `region`。

---

## 6. 資料退場

雲端也有個資（學生稱呼與全名、家長 email、照片、留言）。三種情況，代理照 `playbooks/` 的資料退場劇本與
`scripts/data_exit.py`（`playbooks/data-exit.md`、`year-end.md`）執行。**每一種都是「先備份、再撤權限、再刪資料、最後清備份」**，預設只預覽
（印清單給老師看），`--apply` 才做、做之前自動備份。`data_exit.py` 走管理端權杖，規則管不到它，刪了**無法復原**。

**順序鐵則**：要找某位家長寫過的東西，先從 `allowlist/{key}` 讀出他的 `alias`，**再**撤名單——名單一刪，代號就查不到了。

Firestore 的 REST 沒有「遞迴刪除」：刪一份文件不會刪它底下的子集合。`data_exit.py` 一律先列子集合
（`listCollectionIds`）逐層刪到底，再刪父文件。

### 6.1 學生轉出（座號 S）

**撤權限（立即生效）**

| 位置 | 動作 |
|---|---|
| `parent_child_map/{key}`（`seats` 含 S 的每一份） | 先記下這些家長的 email 鍵與 `alias`；`seats` 拿掉 S，拿完是空的就刪整份 |
| `allowlist/{key}`、`private_allowlist/{key}`（上面那些家長，且沒有其他孩子在班上） | 刪 |

**刪資料**

| 位置 | 動作 |
|---|---|
| `student_blogs/{S}` 與底下 `entries/*`、`entries/*/thumbs/*`、`entries/*/images/*`、`entries/*/blog_comments/*` | 逐層刪 |
| `roster/students` 裡 S 那一筆 | 移除 |
| `seating/*` 的 `rows` 裡的 S（v1.1） | 改成空字串（歷史座位表保留格子） |
| `parent_photo_display/{S}`、`personal_photos/{S}` 與其照片（v1.1） | 逐層刪 |
| 那些家長在 `posts/*/reads/{key}`、`private_posts/*/reads/{key}` 的回條 | 刪（doc id 就是 email 鍵，逐篇直接刪） |
| 那些家長在三種 `comments` 的留言（`authorAlias` 相符） | **預設保留、`authorName` 改「已退場家長」、`status` 改 `'hidden'`**；老師選「全刪」才刪（留言串的上下文可能牽涉其他家長）。逐篇掃，不為此開索引 |
| `blog_notify_queue/{S}__*` 與其 `sent/*`（v1.1） | 刪 |
| Firebase Auth 裡那些家長的帳號 | 刪（主控台「Authentication → 使用者」，或腳本；§7 第 3 點） |

**人工檢查（程式找不出來）**：班級紀事、相簿、私密紀事裡**出現這位孩子的照片或文字**——`data_exit.py` 只能提醒老師過目全部紀事與相簿
讓老師過目，由老師決定哪幾篇要換照片（重發＝新 pid、舊照片文件刪掉）或下架。

**本機與備份**

| 位置 | 動作 |
|---|---|
| `data/roster.csv`、`data/contacts.csv`、`data/parent-roles.yaml` | 移除該行 |
| `data/student-blogs/{S}/` | 刪 |
| `data/personal-photos/{S}.*`、`data/parent-photos/{S}.*`（v1.1，檔名只用座號） | 移到垃圾桶 |
| 同步夾 `04_部落格歸檔/{S}/`、`01_機密（只有導師）/學生個別資料/{S}/` | 刪 |
| 同步夾 `05_全站備份/` 的舊快照 | 裡面仍有這位孩子的資料：照備份輪替自然過期；老師要求立即清除：`data_exit.py … --purge-backups`（做完後重做一份乾淨的備份，刪掉所有較舊的快照與紀錄備份；照片池裡被刪的照片在退場時就一併刪掉） |
| teacher-records-kit 裡的觀察紀錄 | 不歸本 repo 管，照 kit 自己的刪除流程 |

### 6.2 學年結束

1. **先完整備份**：`05_全站備份/` 做一份學年快照（Firestore 全部集合匯出 JSON，照片文件解回 JPEG 檔），
   `04_部落格歸檔/<座號>/<學年>/` 匯出每位孩子的部落格。驗 md5 後才往下。
2. **撤權限**：清空 `allowlist`（只留導師）、`private_allowlist`（只留導師）、`parent_child_map`。從這一刻起家長與同仁全部進不了站。
3. 老師選一條：
   - **封存**：資料留在雲端，只有導師讀得到（上一步已達成）。儲存照樣佔 1 GiB 額度。
   - **只清照片**：刪所有 `thumbs`、`images` 子集合與內嵌的 `coverThumb`（改成 `null`），文字留著。騰出額度給新學年。
   - **清空**：刪所有內容集合（`posts`、`albums`、`private_posts`、`pages`、`student_blogs`、`roster`、`ops`，v1.1 再加
     `seating`、`parent_photo_display`、`personal_photos`、`blog_notify_queue`）連同全部子集合，刪 Firebase Auth 裡除導師外的所有帳號。
   - **整個專案刪除**：在 Firebase 主控台刪專案（30 天內可復原，之後永久刪除）。
4. 本機 `data/` 依學校規定保存或刪除；同步夾的備份依學校規定保存年限。

刪除次數：清掉一學年約 1,750 張照片＝3,500 次刪除，加上其他文件，一天的 20,000 次額度內做得完。

### 6.3 家長要求刪除自己的資料

| 位置 | 動作 |
|---|---|
| `allowlist/{key}`（**先讀出 `alias`**）、`private_allowlist/{key}`、`parent_child_map/{key}` | 刪（撤權限） |
| 三種 `comments` 裡 `authorAlias` 相符的留言 | 刪 |
| `posts/*/reads/{key}`、`private_posts/*/reads/{key}` | 刪 |
| 他座號底下 `entries/*` 裡 `author == 'parent'` 且 `authorAlias` 相符的文章，連同 `thumbs`、`images`、`blog_comments` | 逐層刪 |
| 其他文章底下 `blog_comments` 裡 `authorAlias` 相符的對話 | 刪 |
| `blog_notify_queue/*/sent/{hash}`（v1.1；`hash`＝該 email 鍵的 SHA-256 前 32 碼） | 刪 |
| Firebase Auth 帳號 | 刪 |
| `data/contacts.csv`、`data/parent-roles.yaml` 該家長那一格 | 移除 |
| 同步夾備份（`05_全站備份/`、`01_機密/紀錄備份/`）裡的舊快照 | 照 6.1 的快照處理方式 |

---

## 7. 仍待拍板、或 P2／P3 要一起遵守的地方

1. **Spark 的 email 連結登入每天只有 5 封**（§5.1，官方 2026-09-24 更新的限制頁）。本文件的預設：Google 登入為主、
   email 連結為輔、開學分批發；非 Google 家長多就升 Blaze。前端必須處理 `auth/quota-exceeded`（ARCHITECTURE §3.4）。
2. **作者代號 `alias` 取代「直接存 email 鍵」**（§0.5）：最早的構想是「留言與回條直接存規則驗過的 emailKey」；
   本文件只在導師才讀得到的回條這樣做，全班讀得到的留言與部落格改存規則驗過的 `alias`，理由是 Firestore 沒有欄位層級讀取權限，
   存 email 會把信箱公開給全班。導師端對回身分的方式不變（多查一次 `allowlist`）。
3. **刪 Firebase Auth 帳號**（資料退場）：已定案＝**主控台手動**（零額外 API）。`data_exit.py` 不刪登入帳號，
   只把要刪的完整信箱寫進只給老師開的清單檔、印主控台的操作步驟（`scripts/data_exit.py` 開頭說明、`playbooks/data-exit.md`）。
4. P2 與 P3 平行施工時，唯一的共同介面就是：本文件的欄位白名單與權限表、§4 的查詢登記表（`CMW.QUERIES`）、
   §0.3 的 email 鍵測試向量、ARCHITECTURE §4.1 的區塊格式。任何一邊想改，先改文件再通知另一邊。

---

## A. 安全規則全文（`templates/firestore.rules.tmpl` 的逐字複本）

下面這段就是樣板本身，已經在模擬器驗證過（`python3 scripts/test_rules.py`）。`tests/test_rules_template.py` 逐字比對這一段與樣板，
**改規則要兩邊同一個 commit 一起改**（先改本文件的權限表與欄位白名單，再改樣板、再貼回這裡）。
`{{TEACHER_EMAIL_KEY}}` 由 `build_config.py` 代換（含雙引號的 JSON 字串）；產生的 `firestore.rules` 被 `.gitignore` 擋住。

跟第一版骨架（架構 v2 定稿時寫、當時沒有編譯過）的差別，都是模擬器與靜態檢查逼出來的：

| 地方 | 第一版骨架 | 驗證過的規則 | 為什麼 |
|---|---|---|---|
| `verified()` | 只驗 `split('@').size() == 2` | 用與 `EMAIL_RE` 同一個正規式比對（先 `trim()`），另外擋 gmail 去點後是空的 | 向量檔的 `invalid` 在 Python 拒收；規則端要拒收同一批（§0.3「三邊一套」） |
| `emailKey()` | 只 `lower()` | `trim().lower()` | Python 會去掉前後空白；向量檔有前後空白、tab、換行的案例（模擬器實測 `trim()` 會去掉 tab 與換行） |
| `isGoogle()` | `token.firebase.sign_in_provider` | `token.get('firebase', {}).get('sign_in_provider', '')` | token 少欄位時不出錯 |
| `myKind()`、`myAlias()`、`seatMap()` | 每用一次就 `get()` 一次 | 刪掉；`allowDoc()`、`parent_child_map` 的文件改由呼叫端傳參數 | 最壞情況的存取次數才估得準、也比較少（§1.6） |
| 留言、回條的 `kind`／`alias` | 只比「等於名單上的值」 | 另外驗 `alias` 格式、`kind` 只能是那三種 | 名單文件缺欄位時，`get(欄位, '')` 會讓「填空字串」剛好相等 |
| 留言建立 | 導師不論父文件 | 導師要父文件存在（不論可見） | 不留孤兒留言；與部落格對話串同一個標準（§2.7） |
| `content/{docId}` | 任何 id | 只有 `main` | §2.6 規定正文固定叫 `main` |
| 部落格文章的建立 | `isTeacher() && validNewEntry('teacher')` 或家長那條，`validNewEntry` 各算一次 | `validNewEntry(isTeacher() ? 'teacher' : 'parent', allowDoc()) && (isTeacher() \|\| isParentOf(seat))` | 最壞次數 4 → 3，批次 15 |
| 照片 `order` | `== int(pid)` | 另外要求 `is int` | 小數 `0.0` 不算 |
| 私密門票、留言、回條 | 讀者（私密：＋私密名單）即可 | 另外要 `isGoogle()` | 帳號預先註冊（§1.1）：email 連結與密碼登入的 token 分不出來 |
| 部落格文章 `date` | 只驗格式 | 另外要 `== postId[0:10]` | 不能把日期填到未來、釘在列表最上面 |

```
rules_version = '2';

// 由 scripts/build_config.py 從 templates/firestore.rules.tmpl 產生——不要手改產生出來的 firestore.rules。
// 正本是 docs/DATA-MODEL.md（每個集合的權限表、欄位白名單；附錄 A 是這份樣板的逐字複本，單元測試會比對）。
// 改規則的順序：改 DATA-MODEL → 改這份樣板（連附錄 A 一起）→ python3 scripts/test_rules.py 全綠。
//
// 寫法約定（改的人一定要守）：
//  · 讀文件（get／exists）要先用函式參數接住再用：同一份文件在一條規則裡只寫一次 get。
//    正式環境「查詢」的存取上限是 10 次（模擬器量到 20，模擬器全綠不代表線上不會超過），
//    scripts/lib/rules_budget.py 對每條 allow 估最壞情況的次數，超過 10 測試就失敗。
//  · 會讀 resource 的集合，get 與 list 分開寫：get 多放一條 resource == null（不存在的文件回「找不到」），list 不放。
//  · 規則評估出錯＝拒絕。文件先判斷不是 null 再取欄位；可能沒有的欄位用 .get(欄位, 預設值)。
service cloud.firestore {
  match /databases/{database}/documents {

    // ══ 身分（DATA-MODEL §1）════════════════════════════════════════════

    function signedIn() {
      return request.auth != null;
    }

    // email 已驗證，而且 email 的寫法與 scripts/lib/emailkey.py 的 EMAIL_RE 同一套
    // （剛好一個 @、前後都不是空的、不含引號空白等字元；gmail 去掉點號後不能是空的）。
    // emailKey() 只准在這個為真之後呼叫。
    function verified() {
      return signedIn()
        && request.auth.token.get('email', null) is string
        && request.auth.token.get('email_verified', false) == true
        && request.auth.token.email.trim().matches('^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}$')
        && !emailKey().matches('^@.*$');
    }

    // Google 登入。email 連結登入的 sign_in_provider 是 'password'，不算。
    // 密碼登入的 sign_in_provider 也是 'password'，規則分不出這兩種；而任何人都能拿一個還沒登入過的家長信箱
    // 先註冊密碼帳號（DATA-MODEL §1.1）。所以非導師的寫入與私密讀取一律要 isGoogle()，email 連結讀者只能讀公開內容。
    function isGoogle() {
      return request.auth.token.get('firebase', {}).get('sign_in_provider', '') == 'google.com';
    }

    // email 鍵（DATA-MODEL §0.3）：前後空白去掉、小寫；gmail／googlemail 去掉 @ 前面的點號並統一成 gmail.com。
    // 與 scripts/lib/emailkey.py、site/js/core/emailkey.js 同一套，共用 tests/fixtures/emailkey_vectors.json。
    // replace() 的第一個參數是 RE2 正規式：點號一定要寫 '[.]'（寫 '.' 會把每個字都換掉）。
    function emailKey() {
      let e = request.auth.token.email.trim().lower();
      let parts = e.split('@');
      return (parts[1] == 'gmail.com' || parts[1] == 'googlemail.com')
        ? parts[0].replace('[.]', '') + '@gmail.com'
        : e;
    }

    // 導師：email 已驗證＋Google 登入＋email 鍵等於導師的。
    // {{TEACHER_EMAIL_KEY}} 由 build_config.py 代換成含雙引號的字串（已過 EMAIL_RE，不含引號與反斜線）。
    function isTeacher() {
      return verified() && isGoogle() && emailKey() == {{TEACHER_EMAIL_KEY}};
    }

    // 自己的 allowlist 文件（不在名單＝null）。只在 verified() 為真之後呼叫。
    function allowDoc() {
      return get(/databases/$(database)/documents/allowlist/$(emailKey()));
    }

    // 班網讀者：email 已驗證而且在 allowlist。刻意不讓導師短路：導師也在名單裡，
    // 需要導師通行的地方一律寫 isTeacher() || (isReader() && …)。
    function isReader() {
      return verified() && allowDoc() != null;
    }

    // 私密讀者：導師，或（讀者＋Google 登入＋在 private_allowlist）
    function isPrivateReader() {
      return isTeacher() || (isReader() && isGoogle()
        && exists(/databases/$(database)/documents/private_allowlist/$(emailKey())));
    }

    // 座號權限（DATA-MODEL §1.1）：一律同時是讀者＋Google 登入＋自己的 parent_child_map 有效且含這個座號。
    // m＝parent_child_map 的自己那份（可能是 null）。
    function seatGrants(m, seat, kinds) {
      return m != null
        && m.data.get('active', false) == true
        && m.data.get('kind', '') in kinds
        && m.data.get('seats', []) is list
        && seat in m.data.get('seats', []);
    }
    function hasSeat(seat, kinds) {
      return isReader() && isGoogle()
        && seatGrants(get(/databases/$(database)/documents/parent_child_map/$(emailKey())), seat, kinds);
    }
    function isParentOf(seat) {
      return hasSeat(seat, ['parent']);
    }
    function isSeatReaderOf(seat) {
      return hasSeat(seat, ['parent', 'staff']);
    }

    // ══ 格式（DATA-MODEL §0.4）══════════════════════════════════════════

    function validSeat(s) {
      return s is string && s.matches('^(0[1-9]|[1-3][0-9]|40)$');
    }
    function validDate(s) {
      return s is string && s.matches('^[0-9]{4}-[0-9]{2}-[0-9]{2}$');
    }
    function validPostId(s) {
      return s is string && s.matches('^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]{8}$');
    }
    function validAlias(s) {
      return s is string && s.matches('^[a-z0-9]{12}$');
    }
    function strLen(s, lo, hi) {
      return s is string && s.size() >= lo && s.size() <= hi;
    }
    function intIn(n, lo, hi) {
      return n is int && n >= lo && n <= hi;
    }
    // d＝某份文件（可能是 null）；存在而且 visible == true
    function visibleDoc(d) {
      return d != null && d.data.get('visible', false) == true;
    }

    // ══ 三種討論串共用：留言、回條（DATA-MODEL §2.7、§2.8）══════════════

    // 新留言的欄位。me＝自己的 allowlist 文件（呼叫端傳 allowDoc()，同一份只讀一次）。
    function validNewComment(me) {
      let d = request.resource.data;
      return me != null
        && d.keys().hasAll(['authorName', 'body', 'role', 'authorAlias', 'status', 'createdAt'])
        && d.keys().hasOnly(['authorName', 'body', 'role', 'authorAlias', 'status', 'createdAt', 'replyTo'])
        && strLen(d.authorName, 1, 20)
        && strLen(d.body, 1, 500)
        && d.role in ['teacher', 'parent', 'staff']
        && d.role == me.data.get('kind', '')
        && (d.role != 'teacher' || isTeacher())
        && validAlias(d.authorAlias)
        && d.authorAlias == me.data.get('alias', '')
        && d.status == 'visible'
        && d.createdAt == request.time
        && (!('replyTo' in d) || (d.replyTo is string && d.replyTo.matches('^[A-Za-z0-9]{1,64}$')));
    }

    // 建留言：一律 Google 登入；導師（父文件存在即可，不論可見），或有門票（ticket）而且父文件存在且可見；欄位另驗。
    // ticket＝呼叫端算好的 isReader()／isPrivateReader()；parent＝父文件（可能是 null）。
    function canCreateComment(ticket, parent) {
      return isGoogle()
        && ((isTeacher() && parent != null) || (ticket && visibleDoc(parent)))
        && validNewComment(allowDoc());
    }

    // 留言只准改 status（導師收起／還原）
    function onlyStatusChange() {
      return request.resource.data.diff(resource.data).affectedKeys().hasOnly(['status'])
        && request.resource.data.status in ['visible', 'hidden'];
    }

    // 回條：Google 登入；doc id 必須是自己的 email 鍵；kind 等於自己名單上的 kind 而且不是導師；readAt 是伺服器時間。
    function validReceipt(key, me) {
      let d = request.resource.data;
      return me != null
        && isGoogle()
        && key == emailKey()
        && d.keys().hasAll(['kind', 'readAt'])
        && d.keys().hasOnly(['kind', 'readAt'])
        && d.kind in ['parent', 'staff']
        && d.kind == me.data.get('kind', '')
        && d.readAt == request.time;
    }

    // ══ 名單與探針（DATA-MODEL §2.1–§2.4）════════════════════════════════

    // 自己那份：email 已驗證就能讀（不在名單回「找不到」，前端靠這個判斷「尚未授權」）
    match /allowlist/{key} {
      allow get: if isTeacher() || (verified() && key == emailKey());
      allow list: if isTeacher();
      allow write: if false;
    }

    match /private_allowlist/{key} {
      allow get: if isTeacher() || (verified() && key == emailKey());
      allow list: if isTeacher();
      allow write: if false;
    }

    // 導師探針：文件不存在；只有導師 get 得到「找不到」，其他人一律被拒
    match /site_access/{probe} {
      allow get: if probe == 'teacher' && isTeacher();
      allow list, write: if false;
    }

    // 自己那份：要讀者＋Google 登入
    match /parent_child_map/{key} {
      allow get: if isTeacher() || (isReader() && isGoogle() && key == emailKey());
      allow list: if isTeacher();
      allow write: if false;
    }

    // ══ 站台與導師限定（DATA-MODEL §2.5、§2.16、§2.17）════════════════════

    match /config/{id} {
      allow get: if isTeacher() || (id == 'site' && isReader());
      allow list, write: if false;
    }

    match /roster/{id} {
      allow get: if isTeacher();
      allow list, write: if false;
    }

    match /ops/{id} {
      allow get: if isTeacher();
      allow list, write: if false;
    }

    // ══ 班級紀事（DATA-MODEL §2.6–§2.8、§2.12）══════════════════════════

    match /posts/{slug} {
      function postDoc() {
        return get(/databases/$(database)/documents/posts/$(slug));
      }

      allow get: if isTeacher() || (isReader() && (resource == null || resource.data.visible == true));
      allow list: if isTeacher() || (isReader() && resource.data.visible == true);
      allow write: if false;

      match /content/{docId} {
        allow get: if docId == 'main' && (isTeacher() || (isReader() && visibleDoc(postDoc())));
        allow list, write: if false;
      }
      match /thumbs/{pid} {
        allow read: if isTeacher() || (isReader() && visibleDoc(postDoc()));
        allow write: if false;
      }
      match /images/{pid} {
        allow read: if isTeacher() || (isReader() && visibleDoc(postDoc()));
        allow write: if false;
      }
      match /comments/{cid} {
        allow get: if isTeacher()
          || (isReader() && visibleDoc(postDoc()) && (resource == null || resource.data.status == 'visible'));
        allow list: if isTeacher()
          || (isReader() && visibleDoc(postDoc()) && resource.data.status == 'visible');
        allow create: if canCreateComment(isReader(), postDoc());
        allow update: if isTeacher() && onlyStatusChange();
        allow delete: if false;
      }
      match /reads/{key} {
        allow get: if isTeacher() || (isReader() && key == emailKey());
        allow list: if isTeacher();
        allow create: if isReader() && visibleDoc(postDoc()) && validReceipt(key, allowDoc());
        allow update, delete: if false;
      }
    }

    // ══ 相簿（DATA-MODEL §2.9）═════════════════════════════════════════

    match /albums/{slug} {
      function albumDoc() {
        return get(/databases/$(database)/documents/albums/$(slug));
      }

      allow get: if isTeacher() || (isReader() && (resource == null || resource.data.visible == true));
      allow list: if isTeacher() || (isReader() && resource.data.visible == true);
      allow write: if false;

      match /thumbs/{pid} {
        allow read: if isTeacher() || (isReader() && visibleDoc(albumDoc()));
        allow write: if false;
      }
      match /images/{pid} {
        allow read: if isTeacher() || (isReader() && visibleDoc(albumDoc()));
        allow write: if false;
      }
      match /comments/{cid} {
        allow get: if isTeacher()
          || (isReader() && visibleDoc(albumDoc()) && (resource == null || resource.data.status == 'visible'));
        allow list: if isTeacher()
          || (isReader() && visibleDoc(albumDoc()) && resource.data.status == 'visible');
        allow create: if canCreateComment(isReader(), albumDoc());
        allow update: if isTeacher() && onlyStatusChange();
        allow delete: if false;
      }
    }

    // ══ 私密紀事（DATA-MODEL §2.10）══════════════════════════════════════
    // 不存在的私密紀事：沒有私密門票的人照樣被拒（不洩漏「有沒有這一篇」）。

    match /private_posts/{slug} {
      function privateDoc() {
        return get(/databases/$(database)/documents/private_posts/$(slug));
      }

      allow get: if isTeacher() || (isPrivateReader() && (resource == null || resource.data.visible == true));
      allow list: if isTeacher() || (isPrivateReader() && resource.data.visible == true);
      allow write: if false;

      match /thumbs/{pid} {
        allow read: if isTeacher() || (isPrivateReader() && visibleDoc(privateDoc()));
        allow write: if false;
      }
      match /images/{pid} {
        allow read: if isTeacher() || (isPrivateReader() && visibleDoc(privateDoc()));
        allow write: if false;
      }
      match /comments/{cid} {
        allow get: if isTeacher()
          || (isPrivateReader() && visibleDoc(privateDoc()) && (resource == null || resource.data.status == 'visible'));
        allow list: if isTeacher()
          || (isPrivateReader() && visibleDoc(privateDoc()) && resource.data.status == 'visible');
        allow create: if canCreateComment(isPrivateReader(), privateDoc());
        allow update: if isTeacher() && onlyStatusChange();
        allow delete: if false;
      }
      match /reads/{key} {
        allow get: if isTeacher() || (isPrivateReader() && key == emailKey());
        allow list: if isTeacher();
        allow create: if isPrivateReader() && visibleDoc(privateDoc()) && validReceipt(key, allowDoc());
        allow update, delete: if false;
      }
    }

    // ══ 單頁（DATA-MODEL §2.11）═════════════════════════════════════════

    match /pages/{pageId} {
      function pageDoc() {
        return get(/databases/$(database)/documents/pages/$(pageId));
      }

      allow get: if isTeacher() || (isReader() && (resource == null || resource.data.visible == true));
      allow list: if isTeacher() || (isReader() && resource.data.visible == true);
      allow write: if false;

      match /thumbs/{pid} {
        allow read: if isTeacher() || (isReader() && visibleDoc(pageDoc()));
        allow write: if false;
      }
      match /images/{pid} {
        allow read: if isTeacher() || (isReader() && visibleDoc(pageDoc()));
        allow write: if false;
      }
    }

    // ══ 部落格（DATA-MODEL §2.13–§2.15）═════════════════════════════════
    // 家長不能 list 整個 student_blogs（規則無法對每一份證明座號相符），只能 get 自己座號那份。

    match /student_blogs/{seat} {
      allow get: if isTeacher() || (validSeat(seat) && isSeatReaderOf(seat));
      allow list: if isTeacher();
      allow write: if false;

      match /entries/{postId} {
        function entryDoc() {
          return get(/databases/$(database)/documents/student_blogs/$(seat)/entries/$(postId));
        }

        // photos 的第 i 個：{ pid: 'i', w, h, caption? }
        function validPhotoRef(p, pid) {
          return p is map
            && p.keys().hasAll(['pid', 'w', 'h'])
            && p.keys().hasOnly(['pid', 'w', 'h', 'caption'])
            && p.pid == pid
            && intIn(p.w, 1, 1600)
            && intIn(p.h, 1, 1600)
            && (!('caption' in p) || strLen(p.caption, 0, 300));
        }
        function validPhotos(ps) {
          return ps is list && ps.size() <= 3
            && (ps.size() < 1 || validPhotoRef(ps[0], '0'))
            && (ps.size() < 2 || validPhotoRef(ps[1], '1'))
            && (ps.size() < 3 || validPhotoRef(ps[2], '2'));
        }
        // 新文章。author：導師 'teacher'、家長 'parent'；me＝自己的 allowlist 文件。
        // date 綁 postId 的前 10 碼（不能把文章日期填到未來、釘在最上面）。
        function validNewEntry(author, me) {
          let d = request.resource.data;
          return me != null
            && d.keys().hasAll(['title', 'body', 'date', 'author', 'authorAlias', 'photos', 'visible', 'createdAt'])
            && d.keys().hasOnly(['title', 'body', 'date', 'author', 'authorAlias', 'photos', 'visible', 'createdAt'])
            && strLen(d.title, 1, 200)
            && strLen(d.body, 1, 10000)
            && validDate(d.date)
            && d.date == postId[0:10]
            && d.author == author
            && validAlias(d.authorAlias)
            && d.authorAlias == me.data.get('alias', '')
            && d.visible == true
            && d.createdAt == request.time
            && validPhotos(d.photos);
        }
        // 導師改文：只准動 title、body、visible、updatedAt
        function validEntryEdit() {
          let d = request.resource.data;
          return d.diff(resource.data).affectedKeys().hasOnly(['title', 'body', 'visible', 'updatedAt'])
            && strLen(d.title, 1, 200)
            && strLen(d.body, 1, 10000)
            && d.visible is bool
            && d.updatedAt == request.time;
        }
        // 瀏覽器只准在部落格文章底下建照片：pid 只能是 '0'、'1'、'2'；導師或該座號家長。
        function canCreatePhoto(pid) {
          return validSeat(seat) && validPostId(postId) && pid.matches('^[0-2]$')
            && (isTeacher() || isParentOf(seat));
        }
        function validThumb(pid) {
          let d = request.resource.data;
          return d.keys().hasAll(['data', 'w', 'h', 'order'])
            && d.keys().hasOnly(['data', 'w', 'h', 'order'])
            && strLen(d.data, 1, 49152)
            && intIn(d.w, 1, 480)
            && intIn(d.h, 1, 480)
            && d.order is int && d.order == int(pid);
        }
        function validImage() {
          let d = request.resource.data;
          return d.keys().hasAll(['data', 'w', 'h'])
            && d.keys().hasOnly(['data', 'w', 'h'])
            && strLen(d.data, 1, 716800)
            && intIn(d.w, 1, 1600)
            && intIn(d.h, 1, 1600);
        }

        allow get: if isTeacher()
          || (isSeatReaderOf(seat) && (resource == null || resource.data.visible == true));
        allow list: if isTeacher() || (isSeatReaderOf(seat) && resource.data.visible == true);
        // 同一個 postId 第二次寫＝改（只有導師改文那條）→ 家長重送一律被拒，重試要換新 postId
        allow create: if validSeat(seat) && validPostId(postId)
          && validNewEntry(isTeacher() ? 'teacher' : 'parent', allowDoc())
          && (isTeacher() || isParentOf(seat));
        allow update: if isTeacher() && validEntryEdit();
        allow delete: if false;

        // 照片不可變：只准建，不准改、不准刪（換照片＝新 pid）
        match /thumbs/{pid} {
          allow read: if isTeacher() || (isSeatReaderOf(seat) && visibleDoc(entryDoc()));
          allow create: if canCreatePhoto(pid) && validThumb(pid);
          allow update, delete: if false;
        }
        match /images/{pid} {
          allow read: if isTeacher() || (isSeatReaderOf(seat) && visibleDoc(entryDoc()));
          allow create: if canCreatePhoto(pid) && validImage();
          allow update, delete: if false;
        }

        // 對話串只屬於導師和「那個孩子的家長」：同仁可以看文章，看不到對話
        match /blog_comments/{cid} {
          function validNewBlogComment(role, me) {
            let d = request.resource.data;
            return me != null
              && d.keys().hasAll(['body', 'role', 'authorAlias', 'status', 'createdAt'])
              && d.keys().hasOnly(['body', 'role', 'authorAlias', 'status', 'createdAt'])
              && strLen(d.body, 1, 500)
              && d.role == role
              && validAlias(d.authorAlias)
              && d.authorAlias == me.data.get('alias', '')
              && d.status == 'visible'
              && d.createdAt == request.time;
          }
          // entry＝文章（可能是 null）：導師要文章存在，家長要文章存在且可見
          function canCreateBlogComment(entry) {
            return (isTeacher() ? entry != null : (isParentOf(seat) && visibleDoc(entry)))
              && validNewBlogComment(isTeacher() ? 'teacher' : 'parent', allowDoc());
          }
          // 家長只能把自己那則從 visible 改成 hidden，不能改回；導師收起或還原任何一則
          function canChangeStatus() {
            return request.resource.data.diff(resource.data).affectedKeys().hasOnly(['status'])
              && request.resource.data.status in ['visible', 'hidden']
              && (isTeacher()
                || (isParentOf(seat)
                  && resource.data.authorAlias == allowDoc().data.get('alias', '')
                  && resource.data.status == 'visible'
                  && request.resource.data.status == 'hidden'));
          }

          allow get: if isTeacher()
            || (isParentOf(seat) && visibleDoc(entryDoc()) && (resource == null || resource.data.status == 'visible'));
          allow list: if isTeacher()
            || (isParentOf(seat) && visibleDoc(entryDoc()) && resource.data.status == 'visible');
          allow create: if canCreateBlogComment(entryDoc());
          allow update: if canChangeStatus();
          allow delete: if false;
        }
      }
    }

    // ══ v1.1 集合（DATA-MODEL §2.18）：只有導師讀，網頁不寫 ══════════════

    match /seating/{planId} {
      allow read: if isTeacher();
      allow write: if false;
    }
    match /parent_photo_display/{seat} {
      allow read: if isTeacher();
      allow write: if false;
      match /{sub}/{pid} {
        allow read: if isTeacher() && sub in ['thumbs', 'images'];
        allow write: if false;
      }
    }
    match /personal_photos/{seat} {
      allow read: if isTeacher();
      allow write: if false;
      match /{sub}/{pid} {
        allow read: if isTeacher() && sub in ['thumbs', 'images'];
        allow write: if false;
      }
    }
    match /blog_notify_queue/{qid} {
      allow read: if isTeacher();
      allow write: if false;
      match /sent/{h} {
        allow read: if isTeacher();
        allow write: if false;
      }
    }

    // ══ 導師的集合群組讀取（DATA-MODEL §2.19）：與上面各路徑是聯集，只開給導師 ══

    match /{path=**}/comments/{cid} {
      allow read: if isTeacher();
    }
    match /{path=**}/entries/{postId} {
      allow read: if isTeacher();
    }
    match /{path=**}/blog_comments/{cid} {
      allow read: if isTeacher();
    }

    // ══ 預設拒絕（DATA-MODEL §2.20）：上面沒列到的路徑一律拒絕。這一條永遠放最後。══

    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```

P3 的規則測試（ARCHITECTURE §8.2）必測、而且是最容易寫錯的地方（`tests/rules/` 每一項都有對應的一段）：

- 不存在的紀事／留言／部落格文章：有門票的人 get 拿到「找不到」、沒門票的人被拒（§1.5）。→「找不到」與「被拒」、各集合的「get 不存在的」
- 父文件下架後，非導師讀不到、也寫不進它底下的留言、照片、正文（§2.7）。→ 各集合的「父文件下架」
- 座號家長從 `allowlist` 移除（`parent_child_map` 還在）→ 部落格立刻全部被拒（§1.1）。→「撤名單立即生效」
- 用向量檔裡 gmail 大小寫、點號、googlemail 的各種寫法登入，都對得上名單；非 gmail 網域少一個點就對不上（§0.3）。→「email 鍵：共用向量」
- 同仁讀得到文章與照片、讀不到也寫不進對話串；家長只能把自己那則對話改成 `hidden`、不能改回。→「部落格對話串」
- 家長發文批次（1 文章＋3 縮圖＋3 顯示圖）通過；同一個 `postId` 再送一次被拒；「沒有任何快取」的最壞次數由靜態檢查保證（整批 15 ≤ 20）。→「部落格發文批次」
- 非導師查詢少帶 `visible`／`status` 條件被拒；集合群組查詢只有導師能跑。→「查詢形狀」「集合群組」
- `role`、`authorAlias`、`kind` 冒名（填別人的代號、讀者填 `'teacher'`）被拒。→「欄位白名單」
- 導師 email 用 gmail 點號寫法登入也認得是導師；用 email 連結登入的導師帳號**不是**導師（`isGoogle()`）。→「導師身分」兩段
- password 登入（email 連結，或別人預先註冊的密碼帳號）、email 已驗證、在私密名單：讀得到公開紀事，讀不到私密紀事、留不了言、簽不了回條；
  同一個信箱改用 Google 登入就全部恢復（§1.1）。→「預先註冊的密碼帳號」、各權限表的 `linkPrivate` 角色
- 測試本身會咬人：拿掉關鍵判斷（座號不看名單、列表不看 `visible`、留言不看父文件、不驗代號、導師不必 Google、私密／留言／回條不必 Google、
  文章日期不綁 `postId`……），對應的案例必須翻盤。→「咬人檢查」

---

## B. 查證來源（2026-09-25 查）

- 規則字串方法（`lower`、`split`、`replace`、`matches` 皆以 RE2、`replace` 取代全部）：
  <https://firebase.google.com/docs/reference/rules/rules.String>
- `get()`／`getAfter()` 文件不存在回 `null`：<https://firebase.google.com/docs/reference/rules/rules.firestore>
- 規則語言（三元運算子、`let` 最多 10 個、集合專屬函式放進 `match` 以免編譯超限）：
  <https://firebase.google.com/docs/rules/rules-language>
- Firestore 限制（文件 1 MiB、欄位值 1,048,487 位元組、請求 10 MiB、規則存取次數 單次 10／批次 20、函式參數 7、
  運算式 1,000、規則檔 256 KB／250 KB）：<https://firebase.google.com/docs/firestore/quotas>
- 儲存大小計算（字串＝UTF-8 位元組＋1、文件＋32、索引項目）：<https://firebase.google.com/docs/firestore/storage-size>
- 計費（規則讀取怎麼算、count 查詢怎麼算、監聽怎麼算、各地區單價）：<https://cloud.google.com/firestore/pricing>
- Spark／Blaze 額度（Firestore 1 GiB、5 萬讀／2 萬寫／2 萬刪每天、10 GiB 流量每月；Hosting 10 GB、360 MB／天）：
  <https://firebase.google.com/pricing>
- Auth 限制（Spark 的 email 連結登入信每天 5 封、Blaze 25,000 封）：<https://firebase.google.com/docs/auth/limits>
- 索引設定檔格式（`fieldOverrides`、空的 `indexes` 關掉單欄索引、`queryScope`）：
  <https://firebase.google.com/docs/reference/firestore/indexes>
