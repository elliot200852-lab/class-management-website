# 網站與腳本架構（ARCHITECTURE）v2

> 這份講「程式怎麼分層、誰呼叫誰、資料怎麼流、內容長什麼樣、怎麼部署、怎麼測」。
> 集合、欄位、權限、查詢形狀的正本在 `docs/DATA-MODEL.md`；兩份衝突時以 DATA-MODEL 為準，並回頭修這份。
>
> 讀者：寫前台（P2）、規則（P3）、管理腳本（P4）的人或 AI 代理。老師不必讀。
>
> **v2 重點**（各項的理由寫在下面對應的章節與 `docs/DATA-MODEL.md`）：v1 只用 Firestore＋Auth＋Hosting、預設 Spark 免費方案；Store 縮成少數通用方法；
> 示範模式只負責展示畫面、不模擬拒絕；正文是結構化區塊、前端只用 DOM API 畫；照片以 base64 存在 Firestore；
> 網站正式網址＝`<專案>.firebaseapp.com`。

---

## 0. 一張圖

```
 老師的電腦（clone 下來的資料夾）                         老師自己的 Firebase 專案（Spark）
┌───────────────────────────────────────┐          ┌──────────────────────────────────┐
│ data/            ← 這一班的母本，不進 git  │          │ Firestore (default)              │
│   class-posts/<slug>.md  albums/  …    │ 管理腳本  │   名單、紀事、相簿、部落格、       │
│ config/class.json                      │──REST──▶ │   照片（base64 縮圖＋顯示圖）      │
│ scripts/*.py（gcloud 使用者權杖＋       │  (IAM)   │ Authentication（Google、email 連結）│
│   x-goog-user-project；Pillow 處理照片） │          │ Hosting（site/ 靜態空殼）          │
│                                        │          └────────────────▲─────────────────┘
│ scripts/build_config.py                │                           │ Firebase JS SDK
│   → site/js/site-config.js（公開）       │                           │（ID token，受規則管）
│   → firestore.rules（導師 email 鍵）     │          ┌────────────────┴─────────────────┐
│ scripts/build_indexes.py               │          │ 家長／同仁／導師的瀏覽器            │
│   → firestore.indexes.json、queries.js  │          │ https://<專案>.firebaseapp.com     │
│ scripts/deploy.py → firebase deploy     │          │ site/*.html ＋ js（沒有任何內容）    │
└──────────────┬────────────────────────┘          │ 登入 → Store → 讀資料、畫區塊        │
               │ 寫進本機同步夾                       └──────────────────────────────────┘
               ▼
      Google 雲端硬碟桌面版同步夾（備份、原圖、歸檔）
```

四條原則：

1. **網站是空殼。** `site/` 裡沒有任何一篇紀事、一張照片、一個學生名字。內容全部在 Firestore，登入且規則放行才拿得到。
2. **發文不用重新部署。** 腳本把內容寫進 Firestore，網站下一次讀取就看到。只有改程式、改規則、改設定才需要部署。
3. **前端只透過 Store 拿資料。** 頁面程式不直接碰 Firebase SDK。Store 有兩個實作：真站用的 `FirestoreStore`、
   示範用的 `DemoStore`（零網路）。
4. **查詢只准用登記過的名字。** 每個查詢形狀都在 `templates/queries.json` 登記、由程式產生索引（DATA-MODEL §4）；
   頁面程式呼叫 `store.query('posts.recent', …)`，不自己組查詢。

---

## 1. 目錄結構與各層職責

```
class-management-website/
├─ AGENTS.md CLAUDE.md GEMINI.md …     安裝精靈與操作鐵則（三家代理共用 AGENTS.md）
├─ config/class.example.json           設定範本；真的 class.json 不進 git（逐欄說明 config/README.md）
├─ templates/
│  ├─ manifest.json                    樣板 → 輸出路徑對照表（public: true 的輸出只准用公開欄位）
│  ├─ site-config.js.tmpl  firebaserc.tmpl
│  ├─ firestore.rules.tmpl             安全規則樣板（DATA-MODEL 附錄 A 是它的逐字複本）
│  ├─ functions-config.json.tmpl       v1.1 通知信模組的部署設定 → functions/cmw.generated.json（不公開、沒有信箱）
│  └─ queries.json                     查詢形狀登記表（DATA-MODEL §4）
├─ firebase.json                       部署設定（hosting 公開目錄與標頭、規則與索引檔名、模擬器埠）；不含秘密，進 git
├─ firestore.indexes.json              產生檔（build_indexes.py），進 git
├─ requirements.txt                    只有 Pillow（只給處理照片的腳本；P4）
├─ site/                               Hosting 公開目錄＝靜態空殼
│  ├─ *.html                           每頁一個「殼」，長得幾乎一樣（§3.2）
│  ├─ robots.txt                       Disallow: /
│  ├─ css/
│  └─ js/
│     ├─ site-config.js                產生檔（gitignored）
│     ├─ boot.js                       依 body[data-page] 依序載入 core 與該頁 view
│     ├─ core/
│     │  ├─ ns.js                      建立 window.CMW 命名空間、版本
│     │  ├─ queries.js                 產生檔（build_indexes.py，進 git）：CMW.QUERIES
│     │  ├─ util.js                    日期、座號 key（CMW.seats.key）
│     │  ├─ emailkey.js                CMW.emailKey（DATA-MODEL §0.3，共用測試向量）
│     │  ├─ paths.js                   CMW.paths：**唯一**組 Firestore 路徑的地方（§2.4）
│     │  ├─ validate.js                瀏覽器寫入前的欄位檢查（與規則同一套上限，§2.5）
│     │  ├─ errors.js                  StoreError 與錯誤碼
│     │  ├─ store.js                   Store 介面說明＋選擇器 CMW.getStore()
│     │  ├─ store-firestore.js         FirestoreStore —— **全 repo 唯一 import Firebase SDK 的檔**
│     │  ├─ store-demo.js              DemoStore（零網路）
│     │  ├─ query-eval.js              照 CMW.QUERIES 的形狀在記憶體裡跑查詢（DemoStore 用）
│     │  ├─ demo-data.js  demo-art.js  示範資料、用程式畫的剪影（SVG data URL）
│     │  ├─ session.js                 登入閘畫面＋呼叫 Store 的登入方法
│     │  ├─ layout.js                  頁首、頁尾、導覽、導師浮鈕 —— **唯一來源**（§3.3）
│     │  ├─ blocks.js                  正文區塊渲染器（§4.2）
│     │  ├─ text.js                    純文字＋網址轉連結（§4.3）
│     │  ├─ photo-encode.js            瀏覽器端照片重新編碼（§5.6）
│     │  ├─ blog-compose.js            部落格發文：編碼照片 → 組批次 → Store.batch（§5.6）
│     │  ├─ read-stats.js              「已讀 X/N」判準唯一正本（DATA-MODEL §2.8）
│     │  ├─ seen.js                    導師端「我的孩子」未讀：判準＋本機「已看到哪裡」（localStorage，全程 try/catch）
│     │  ├─ route.js                   頁面與網址對照：CMW.route.href／current（多檔網站與單一 HTML 的 #/ 路由共用）
│     │  ├─ photos.js                  照片載入（photoSrc 記憶、顯示圖同時最多 4 張、捲到附近才讀、封面框）
│     │  ├─ lightbox.js                燈箱：點開才讀顯示圖、左右換張、Esc 關、手機左右滑
│     │  ├─ cards.js                   列表卡片：紀事、私密鎖頭卡、相簿、專題活動、課表
│     │  ├─ comments.js                留言區（紀事、相簿、私密紀事三處共用；即時）
│     │  └─ app.js                     啟動：網址正規化 → layout → session → 該頁 view；# 改變就重畫
│     └─ views/                        每頁一支，只做畫面，資料一律跟 Store 拿
│        ├─ home.js  blog.js（紀事列表＋分類頁）  post.js  admin.js  page.js
│        ├─ gallery.js（相簿列表＋單本相簿）  private.js（私密紀事列表＋單篇）  courses.js  teacher.js
│        ├─ my-child.js（家長端、同仁、單篇＋對話串、寫一篇）  my-child-admin.js（導師全班格＋未讀）
│        ├─ seating.js（座位表分頁：SVG 由 createElementNS 產生）  family-photos.js（導師限定個人照＋家長合照並排）
│        ├─ print.js（匯出 PDF：blog-print、my-child-print，瀏覽器列印成 A4）  poem.js（每日一詩）   （v1.1）
│        ├─ placeholder.js             還沒做好的頁面顯示「建置中」（後備）
│        └─ demo-bar.js                示範模式的角色切換列與「清除示範資料」
├─ scripts/                            管理腳本（Python 3.9+，只用標準庫；處理照片的腳本另需 Pillow）
│  ├─ build_config.py build_indexes.py doctor.py status.py check.py privacy_scan.py init_data.py  （已有）
│  ├─ test_rules.py                    規則測試一鍵跑（開發與 CI 用，§8.2）
│  ├─ smoke_emulator.py                模擬器＋真 SDK＋正式站模式的冒煙測試（開發與 CI 用，§8.4）
│  ├─ build_site.py verify_site.py     組網站／示範站／單一 HTML；無頭 Chrome 驗收示範站（§8.3）
│  ├─ deploy.py access_sync.py open_blogs.py publish_post.py publish_private.py publish_album.py
│  ├─ publish_blog.py publish_page.py test_admin.py（模擬器整合測試，§8.2）          （P4a）
│  ├─ publish_site.py（只剩 roster/links 兩個網址；config/site 由 access_sync.py 寫）  publish_courses.py（課程頁、課表）
│  │                                   （sync_calendar.py：行事曆活動清單，尚未實作；v1 只有訂閱鈕）
│  ├─ drive_init.py backup.py archive_media.py new_block.py data_exit.py where.py   （P4b：同步夾、備份還原、歸檔、退場）
│  ├─ publish_seating.py publish_personal_photos.py publish_parent_photo.py publish_poems.py  （v1.1）
│  ├─ docs_index.py（班級文件索引 index.md）  parent_note.py（家長通知信：只用預設郵件程式打開，不寄）  （v1.1）
│  ├─ notify_setup.py（通知信安裝檢查表）  notify_config.py（開關 config/notify）  test_functions.py（§10）（v1.1 選配）
│  └─ lib/
│     ├─ paths.py seats.py hostos.py console.py emailkey.py      （已有）
│     ├─ rules_budget.py       安全規則的文件存取次數靜態估算（§8.2）
│     ├─ cdp.py                驅動本機無頭 Chrome（DevTools Protocol，只用標準庫；verify_site／smoke_emulator 用）
│     ├─ gauth.py              取 gcloud 使用者權杖；模擬器模式回 "owner"
│     ├─ firestore_rest.py     Firestore REST（讀、commit、列子集合、讀回比對；一律帶 x-goog-user-project）
│     ├─ frontmatter.py        md 檔頭（只收 key: value 與簡單清單）
│     ├─ mdlite.py             Markdown 子集 → 區塊 JSON（§5.2）
│     ├─ blocks.py             區塊格式驗證（§4.1 的 Python 版）
│     ├─ images.py             Pillow 包裝：轉正、兩種尺寸、JPEG、清 EXIF、品質階梯（§5.3）
│     ├─ schema.py             DATA-MODEL 欄位白名單的 Python 版：腳本寫入前先驗，不合就不寫
│     ├─ classcfg.py sources.py 讀 config/class.json；讀名冊、聯絡人、parent-roles（錯誤訊息不印姓名與 email）
│     ├─ publishing.py preview.py 發文共用流程（兩段式、寫入順序、讀回比對、台帳）；本機預覽頁
│     ├─ multipub.py           一次送好幾份導師限定內容（座位方案、全班個人照）：一樣的略過、改過要 --update、拿掉（v1.1）
│     ├─ drivetree.py filesafe.py fsbackup.py ledgers.py namecheck.py   同步夾與資料夾樹、驗過 md5 才算數的複製、
│     │                        資料庫匯出／照片池／還原、本機台帳、檔名裡的學生姓名檢查（P4b）
│     └─ cloudcheck.py         doctor.py --cloud 與 deploy.py 的雲端唯讀檢查（§7.4）
├─ functions/                          v1.1 選配通知信模組（Cloud Functions 第 2 代，Node.js 22；預設不部署，§10）
│  ├─ index.js                         五個觸發器＋兩個排程的接線
│  └─ lib/ pure.js core.js mailer.js config.js   判斷與組信（純函式）／碰 Firestore 的流程／郵差／讀部署設定
├─ tests/                              unittest（純函式、架構檢查）＋ fixtures/ ＋ rules/ ＋ js/（前端，§8）＋ functions/（§10）
├─ playbooks/                          代理日常劇本（P5）
├─ data-template/                      空白資料骨架（進 git）
└─ data/                               這一班的全部資料（不進 git）
```

**分層鐵則**

| 層 | 可以做 | 不可以做 |
|---|---|---|
| `views/*` | 呼叫 `CMW.getStore()` 的方法、`CMW.paths`、`CMW.blocks`、`CMW.text`、`CMW.layout` | import Firebase SDK、自己拼路徑字串、用 `innerHTML` 一類 API（§4.2）、呼叫沒登記的查詢 |
| `core/store-*.js` | 把登記過的查詢形狀變成 SDK 呼叫、轉型別、把 SDK 錯誤轉成 `StoreError` | 畫畫面、判斷權限（權限是規則的事） |
| `core/session.js` | 登入閘畫面、呼叫 Store 的登入方法 | 替任何資料放行 |
| `scripts/*.py` | 透過 `lib/firestore_rest.py` 寫雲端；寫前經 `lib/schema.py` 驗證 | 繞過 `schema.py` 直接組 JSON 寫進去；印出權杖 |

**前端用傳統 `<script>`，不用 ES module。** 每支檔案用 IIFE 包起來、掛在 `window.CMW` 底下；Firebase SDK 由
`store-firestore.js` 以動態 `import()` 從官方 CDN 載入（版本寫死在一個常數），**只有真站模式才載**。這樣示範模式與
「單一 HTML 的 Demo 頁」可以把所有 js 依序串接成一個檔，不需要打包工具、不需要 npm。

---

## 2. 資料存取層（Store）

### 2.1 選擇規則

```
CMW.getStore():
  SITE_CONFIG.demo === true                       → DemoStore      （GitHub Pages 示範站、Demo 頁）
  網址帶 ?demo=1                                   → DemoStore
  SITE_CONFIG.firebase.apiKey 空白或是範本值         → DemoStore（並在頁首顯示「尚未設定」）
  SITE_CONFIG.emulator === true                   → FirestoreStore，連本機模擬器
  其他                                             → FirestoreStore
```

同一頁只建一個 Store 實例。

### 2.2 型別（JSDoc，兩個實作回傳同形狀）

```
Session    { state: 'loading'|'signed-out'|'denied'|'ready',
             user:  { uid, email, emailKey, provider: 'google.com'|'emailLink' } | null,
                    // provider 讀 ID token 的 claims.firebase.sign_in_provider（與規則 isGoogle() 同源）；
                    // 'emailLink'（token 是 'password'）的非導師只能讀公開內容：CMW.readOnlyLogin(session)
             roles: { teacher: bool, reader: bool, privateReader: bool,
                      kind: 'teacher'|'parent'|'staff'|null,     // allowlist.kind
                      alias: string|null,                       // allowlist.alias（認「我的留言」用）
                      seats: string[],                          // parent_child_map.seats（active 才算）
                      seatKind: 'parent'|'staff'|null } }
Doc        { id, path, data }        // data 裡的 Timestamp 一律轉成 Date；伺服器還沒填上時是 null
                                     // 另有不可列舉的 doc.cursor（真站＝DocumentSnapshot），可直接當 { after: doc.cursor }
                                     // 或 { before: doc.cursor } 傳給 query（單篇頁找上一篇／下一篇就這樣用）
Page       { items: Doc[], next: Cursor|null }   // Cursor 不透明，呼叫端原樣傳回；next＝最後一筆的 cursor
Op         { op: 'set'|'update', path, data }
StoreError { code, message, cause }  // code 見 §2.6
CMW.SERVER_TIME                      // 寫入資料裡代表「伺服器時間」的記號（真站→serverTimestamp()）
```

### 2.3 方法清單（完整，20 個）

**A. 身分與登入**

| # | 方法 | 回傳 | 真站 | 示範 |
|---|---|---|---|---|
| 1 | `onSession(cb)` | 取消訂閱函式 | Auth 狀態改變 → 平行讀 DATA-MODEL §1.2 那四份（`allowlist`、`private_allowlist`、`parent_child_map` 自己那份、`site_access/teacher` 探針；後兩個只在 Google 登入時發）→ 組 `Session` 回呼。結果暫存在 `sessionStorage`（同一分頁 30 分鐘內、uid 相同就不重讀） | 依目前示範角色組 Session |
| 2 | `getSession()` | `Session` | 最近一次的 Session | 同左 |
| 3 | `signInWithGoogle()` | — | `signInWithPopup`；被擋（`auth/popup-blocked` 等）退回 `signInWithRedirect`（同網域，§3.4）。勾了「共用電腦」先 `setPersistence(browserSessionPersistence)` | 跳出角色選單（等同 `demoSetRole`） |
| 4 | `sendSignInLink(email)` | — | `sendSignInLinkToEmail`，回到 `siteUrl + '/index.html'`；信箱暫存本機；`auth/quota-exceeded` → `StoreError('quota')`（Spark 每天 5 封，DATA-MODEL §5.1） | 不寄信，畫面顯示「示範模式不寄信」 |
| 5 | `completeSignInLink(email?)` | bool | 網址是登入連結就完成登入；換裝置開信時本機沒有信箱 → `StoreError('invalid')`，畫面請他再輸入一次。寄信時勾了「共用電腦」（localStorage 帶到新分頁）→ 先切成關掉分頁就登出 | 回 `false` |
| 6 | `signOut()` | — | 登出 → 清 Session 暫存 → **清掉本機的 Firestore 快取**（`terminate` 後 `clearIndexedDbPersistence`，共用電腦上不留別人的資料）→ 重新載入 | 切成「未登入」 |

**B. 通用讀取**

| # | 方法 | 回傳 | 真站 | 示範 |
|---|---|---|---|---|
| 7 | `get(path)` | `Doc` 或 `null` | `getDoc`；不存在回 `null`（DATA-MODEL §1.5 讓有門票的人拿到「找不到」） | 從示範資料取；沒有回 `null` |
| 8 | `query(name, params?, page?)` | `Page` | 照 `CMW.QUERIES[name]` 組查詢：`params` 代換路徑的 `{…}` 與 where 的 `:…`、`params.limit` 只能比登記的小；`page` 是 `{ after: cursor }` 或 `{ before: cursor }`（依登記的 `cursor`）；有 `sortClient` 的在取回後排序。名字沒登記 → `StoreError('invalid')` | `query-eval.js` 照同一個形狀在記憶體裡算（等號、範圍、排序、上限、游標、`limitToLast`） |
| 9 | `watch(name, params, cb)` | 取消訂閱函式 | 同上但用 `onSnapshot`；只准登記了 `watch: true` 的查詢 | 立刻回呼一次；示範寫入後再回呼 |
| 10 | `count(name, params)` | number | `getCountFromServer`；只准登記了 `count: true` 的查詢 | 同一個形狀算筆數 |

**C. 通用寫入**（瀏覽器只准寫 §2.5 那幾種路徑；其他一律 `StoreError('invalid')`）

| # | 方法 | 回傳 | 真站 | 示範 |
|---|---|---|---|---|
| 11 | `add(collectionPath, data)` | 新 id | `addDoc`；`CMW.SERVER_TIME` 換成 `serverTimestamp()` | 產生隨機 id，時間用 `new Date()`，存 localStorage |
| 12 | `set(path, data)` | — | `setDoc`（不 merge） | 存 localStorage |
| 13 | `update(path, patch)` | — | `updateDoc` | 合併後存 localStorage |
| 14 | `batch(ops)` | — | `writeBatch`，1–7 個 `Op`，一次成功或一次失敗（DATA-MODEL §1.6） | 全部套用 |

**D. 少數語意方法**

| # | 方法 | 回傳 | 真站 | 示範 |
|---|---|---|---|---|
| 15 | `photoSrc(ownerPath, pid, size)` | data URL 字串或 `null` | `size` 是 `'thumb'`／`'image'`。照片文件不可變：先 `getDocFromCache`、沒有才 `getDoc`；**快取命中時，主人文件要在這一頁從伺服器讀成功過**（`get`／`query`／`watch` 收到 `fromCache == false` 的主人文件，或 `getDocFromServer` 問一次）才顯示，否則回 `null`（被撤權限、已下架的照片不從快取吐出來）；驗 `data` 是 base64 字元集；回 `'data:image/jpeg;base64,' + data`（MIME 寫死）；同一頁內記住結果 | `demo-art.js` 依路徑畫剪影（SVG data URL） |
| 16 | `markRead(threadPath)` | — | 導師與 email 連結登入（規則不准簽）不做事；否則 get 自己的回條（`reads/{自己的 emailKey}`），不存在才 `set({ kind, readAt: SERVER_TIME })`；兩個分頁同時建造成的被拒只在這裡吞掉（DATA-MODEL §2.8） | 不做事 |
| 17 | `newPostId(date?)` | string | `YYYY-MM-DD-` ＋ 8 碼小寫英數（`crypto.getRandomValues`）；**每次送出都叫一次，重試也是** | 同左 |

**E. 示範模式專用**（`FirestoreStore` 上呼叫一律丟 `invalid`）

| # | 方法／屬性 | 說明 |
|---|---|---|
| 18 | `isDemo` | `true`／`false`（兩個實作都有） |
| 19 | `demoSetRole(role)` | `'signed-out'`｜`'reader'`｜`'parent'`（學生 A 家長）｜`'staff'`（座號 03 同仁）｜`'private'`｜`'teacher'` |
| 20 | `demoReset()` | 清掉 localStorage 裡的示範寫入，回到初始資料 |

**真站的 Firestore 初始化**：`initializeFirestore(app, { localCache: persistentLocalCache(...) })`，IndexedDB 不能用
（私密視窗、被封鎖）就退回記憶體快取，畫面照常。這個分頁勾了「共用電腦」（`CMW.sharedDevice`，§3.4）就一開始用
`memoryLocalCache()`、Auth 用 `browserSessionPersistence`。模擬器模式呼叫 `connectAuthEmulator`、`connectFirestoreEmulator`。

### 2.4 路徑與查詢名

- **`CMW.paths`（`core/paths.js`）是唯一組路徑的地方**，每個函式先驗參數格式（DATA-MODEL §0.4），不合就丟 `invalid`：
  `post(slug)`、`postContent(slug)`、`album(slug)`、`privatePost(slug)`、`page(pageId)`、
  `thread(kind, slug)`（`kind` 是 `post`／`album`／`private`，回父文件路徑）、`comment(threadPath, cid)`、
  `receipt(threadPath, emailKey)`、`blog(seat)`、`entry(seat, postId)`、`blogComment(entryPath, cid)`、
  `thumb(ownerPath, pid)`、`image(ownerPath, pid)`、`allow(emailKey)`、`privateAllow(emailKey)`、
  `parentMap(emailKey)`、`teacherProbe()`、`configSite()`、`rosterStudents()`、`rosterLinks()`、`opsBackup()`；
  v1.1：`personalPhoto(seat)`、`parentPhoto(seat)`（這兩種也是照片的主人文件）、`poemMonth('YYYY-MM')`（＝`pages/poems-YYYY-MM`）。
  網址參數（`post.html?s=…`）一律先經這裡驗過才用，`s=../x` 這種值直接當「找不到」。
- **查詢名**：`CMW.QUERIES` 由 `build_indexes.py` 從 `templates/queries.json` 產生（DATA-MODEL §4.4 有全表）。
  路徑參數 `{thread}`、`{owner}`、`{entry}` 傳的是 `CMW.paths` 回的**文件路徑**，例如
  `store.query('comments.thread', { thread: CMW.paths.thread('post', slug) })`。
- 導師與非導師用不同的查詢名（`posts.recent` 對 `posts.recent.teacher`）：非導師版一定帶 `visible`／`status` 條件，
  由登記表的測試保證；view 依 `session.roles.teacher` 選名字。

### 2.5 瀏覽器寫得到的路徑（`core/validate.js`，與規則同一套上限）

| 路徑 | 方法 | 誰 | 驗什麼（DATA-MODEL） |
|---|---|---|---|
| `{thread}/comments` | `add` | 讀者（私密紀事：私密讀者）、導師 | §2.7 欄位白名單 |
| `{thread}/comments/{cid}` | `update({ status })` | 導師 | 只動 `status` |
| `{thread}/reads/{emailKey}` | `set`（只由 `markRead` 呼叫） | 讀者 | §2.8 |
| `student_blogs/{seat}/entries/{postId}` ＋ 其 `thumbs/{0-2}`、`images/{0-2}` | `batch`（只由 `blog-compose.js` 呼叫） | 座號家長、導師 | §2.12、§2.14 |
| `student_blogs/{seat}/entries/{postId}` | `update({ title, body, visible, updatedAt })` | 導師 | §2.14 |
| `…/entries/{postId}/blog_comments` | `add` | 座號家長、導師 | §2.15 |
| `…/blog_comments/{cid}` | `update({ status })` | 導師；家長（自己那則改 `hidden`） | §2.15 |

前端先擋一次，只是讓使用者少等一個必然失敗的請求；**真正把關的是安全規則**。

### 2.6 錯誤對應（兩個實作都照做，頁面只認這幾個碼）

| 來源 | `StoreError.code` | 頁面怎麼顯示 |
|---|---|---|
| 沒登入就呼叫 | `unauthenticated` | 交給登入閘 |
| `permission-denied` | `denied` | 讀者讀**單篇**被拒 → 「這篇找不到（可能已下架）」（DATA-MODEL §1.5）；列表被拒 → 目前帳號＋「先登出，再換一個帳號」；私密區、附加內容 → **靜默不顯示** |
| （不是錯誤）`get` 回 `null` | — | 「找不到」 |
| `failed-precondition`（索引還在建、或少了索引） | `index` | 「網站剛更新，資料庫還在準備，請幾分鐘後再試」＋重試鈕 |
| `resource-exhausted`；`auth/quota-exceeded` | `quota` | Firestore：「今天的免費額度用完了，台灣時間下午 4 點左右恢復」；登入信：「今天的登入信額度用完了，請改用 Google 帳號登入，或明天再試」（DATA-MODEL §5.3） |
| `unavailable`、`deadline-exceeded`、網路錯誤 | `unavailable` | 「可能是網路不穩」＋重試鈕 |
| 前端驗證不過（字數、張數、格式、沒登記的查詢名、不准寫的路徑） | `invalid` | 表單旁的錯誤字；程式錯誤就在主控台印名字 |
| 使用者自己關掉登入視窗 | `cancelled` | 不顯示 |

### 2.7 `DemoStore` 的行為：只展示，不模擬拒絕

- **零網路**：不載 Firebase SDK、不 `fetch` 任何東西。拔網路線也能用。
- **資料來源**：`core/demo-data.js` 的內建資料；寫入存 `localStorage`（鍵名前綴 `cmw-demo-v2:`），所有讀寫包 try/catch；
  `localStorage` 不能用時退回只存在記憶體，畫面照常。
- **不模擬權限**：示範模式任何角色讀什麼都拿得到。切換角色只改 Session，也就是**畫面長什麼樣**
  （導覽多幾項、導師工具出不出現、家長看到哪個座號）。權限只在一個地方定義——規則——並且只在模擬器驗（§8.2、§8.4）；
  示範模式不另外維護第三份權限表。
- 查詢一律走 `query-eval.js`，跟真站吃同一份 `CMW.QUERIES`，所以示範模式也會擋「沒登記的查詢名」。
- 頁首固定一條黃色提示：「示範模式：資料是假的，只存在這個瀏覽器」，旁邊是角色切換與「清除示範資料」。

### 2.8 示範資料規格

| 項目 | 內容 |
|---|---|
| 學生 | 25 位，座號 `01`–`25`，稱呼「學生 A」到「學生 Y」（名冊的 `name` 也用同一個字樣） |
| 家長 | 每位一位，「學生 A 家長」…，信箱 `parent-a@example.com` … `parent-y@example.com`，`kind: 'parent'`，代號 `demoaliasa01` 這種固定假值；稱謂 `relation` 輪流「母／父」（導師端顯示「學生 A 家長（母）」） |
| 同仁 | 一位「示範同仁」`staff-1@example.com`，`kind: 'staff'`，授權座號 `03` |
| 私密讀者 | `parent-a@example.com` 與導師 |
| 導師 | 「示範導師」`teacher@example.com` |
| 班級紀事 | 3 篇，日期用「今天往前推 2、5、9 天」在執行時算出來；分類取設定檔前三個；正文用 §4.1 的區塊，每種區塊至少出現一次 |
| 相簿 | 3 本：1 本有 9 張照片（程式畫的佔位圖）＋2 支影片連結（YouTube 與其他網站）＋外部相簿連結；2 本空卡（`photoCount == 0`、沒有 `linkUrl`，畫面顯示「尚未設定相簿連結」） |
| 私密紀事 | 1 篇（附 1 張照片；用來展示鎖頭卡併入列表） |
| 部落格 | 每個座號有主頁、至少 1 篇文章（三篇裡兩篇家長文、一篇導師文，部分附照片、部分有家長留言）；座號 `01` 另有主頁介紹、1 篇家長文、1 篇導師文，導師文底下 2 則對話 |
| 單頁 | 首頁橫幅、課程（課程說明影片、3 張各科課程大綱卡）、課表、關於我們、專題活動、獨立單頁，內容是「（在這裡寫…）」這類提示字 |
| 示範身分 | 頂端切換列：訪客、家長（選座號 01–25；座號 01 也是私密讀者）、同仁（座號 03）、導師 |
| 照片 | **沒有任何圖檔**。`demo-art.js` 依路徑雜湊畫剪影 |

**文字內容**：通用的班級生活佔位文字，**不得描述任何真實事件、地點、課程名、學校**。這些字交給**沒有任何班級脈絡的代理**撰寫，
維護者過目後才放進 `demo-data.js`；本文件只定形狀。

---

## 3. 頁面、導覽與登入閘

### 3.1 頁面清單（「讀什麼」欄的查詢名都在 DATA-MODEL §4.4）

導師看同一頁時，查詢一律換成 `.teacher` 版（看得到下架與收起的）。

| 頁面檔 | 內容 | 誰看得到 | 讀什麼 | 批次 |
|---|---|---|---|---|
| （每一頁） | 網址正規化、登入閘、`noindex` | 讀者 | Session（§2.3 #1） | v1 |
| `index.html` | 首頁：橫幅、最新 3 篇、行事曆＋訂閱鈕、相簿條、專題活動卡片、留言數 | 讀者 | `config/site`、`pages/home`、`posts.recent`（limit 3）、`albums.list`、`pages.byKind`（`fun`）、`comments.count` | v1 |
| `blog.html` | 紀事列表（私密紀事以鎖頭卡依日期併入） | 讀者 | `posts.recent`、`private.list`（私密讀者才發）、`comments.count`；導師另加 `reads.countParents`、`reads.count` | v1 |
| `category.html?c=<分類>` | 分類頁 | 讀者 | `posts.byCategory` | v1 |
| `post.html?s=<slug>` | 單篇、照片、留言、已讀、分享鈕、上一篇／下一篇 | 讀者 | `posts/{slug}`、`content/main`、`photoSrc`、上一篇＝`posts.recent`（`after` 目前這篇、limit 1）、下一篇＝`posts.newer`、`comments.thread`（即時）、`markRead`；導師另加 `reads.all`、`parentMap.all` | v1 |
| `admin.html` | 留言後台（顯示／隱藏；有站內入口） | 導師 | `comments.admin`、`allowlist.all`（代號對回身分） | v1 |
| `gallery.html` | 相簿列表 | 讀者 | `albums.list` | v1 |
| `album.html?a=<slug>` | 單本相簿、影片連結、相簿留言 | 讀者 | `albums/{slug}`、`photos.thumbs`（格子）、`photoSrc`（燈箱）、`comments.thread` | v1 |
| `private.html?p=<slug>` | 私密紀事（列表與單篇） | 私密讀者 | `private.list`、`private_posts/{slug}`、`photoSrc`、`comments.thread`、`markRead`；導師另加 `reads.all`、`privateAllowlist.all` | v1 |
| `my-child.html#/…` | 家長端：看、發文、對話串、收起自己的話；同仁：只讀文章 | 座號家長、同仁 | `student_blogs/{seat}`、`entries.bySeat`、`photoSrc`、`blogComments.thread`、`blogComments.count`；發文 `batch`（§5.6） | v1 |
| `my-child.html#/admin` | 導師端：全班格、身分標示、未讀 | 導師 | `blogs.all`、`entries.recentParent`、`blogComments.recentParent`、`entries.bySeat.teacher`、`blogComments.thread.teacher`、`parentMap.all`、`allowlist.all`、`roster/students` | v1 |
| `teacher.html` | 導師專用：學生觀察與課程紀錄入口（teacher-records-kit；沒設網址就顯示「尚未安裝」＋官方頁面連結）、班級文件索引連結、網站管理捷徑、備份狀態（門檻同 `status.py`：7 天提醒、14 天加重） | 導師 | `roster/links`、`ops/backup_status` | v1 |
| `teacher.html#/seating` | 座位表分頁：切方案（預設起用日期 ≤ 今天的最新一個）、切方向（老師站講台看／學生面向黑板看）、點座位標記、列印 A4 橫式 | 導師 | `seating.all`、`roster/students`（座號 → 稱呼） | v1.1 |
| `courses.html` | 課程頁 | 讀者 | `pages.byKind`（`course`、`schedule`） | v1 |
| `page.html?id=<pageId>` | 關於我們、專題活動、行事曆、獨立單頁 | 讀者 | `pages/{pageId}`、`photos.thumbs`（有照片時） | v1 |
| `poem.html?m=YYYY-MM&d=YYYY-MM-DD` | 每日一詩：今天那一首（沒有就這個月今天以前的最後一首）＋這個月的清單；還沒到的日子只有導師看得到 | 讀者 | `pages/poems-YYYY-MM`（一次只 get 一個月） | v1.1 |
| `family-photos.html` | 導師限定個人照相簿：全班格（縮圖）→ 點開並排孩子的個人照與家長合照（顯示圖）＋稱謂、備註 | 導師 | `personalPhotos.all`、`parentPhotos.all`、`roster/students`、`photoSrc` | v1.1 |
| `blog-print.html`、`my-child-print.html` | 匯出 PDF：選日期範圍（紀事另可選分類；部落格一人一份或全班一份）、逐篇勾選、產生列印版（封面、目錄、內文、顯示圖），照片載完才開放「列印／存成 PDF」；A4、只印列印版 | 導師 | `posts.recent.teacher`（翻頁讀完）＋`posts/{slug}/content/main`；`blogs.all`＋`entries.bySeat.teacher`；`photoSrc`（顯示圖） | v1.1 |

導師限定的 v1.1 頁面：Session 不是導師就只顯示「這一頁只有導師能用」，**一個查詢都不發**（規則照樣會擋，§8.4 驗兩層）。

- 單篇頁不再每篇一個 HTML：一律 `post.html?s=<slug>`。LINE 分享的連結就是 `https://<專案>.firebaseapp.com/post.html?s=<slug>`。
- `private.html` 的 `<title>` 與靜態內容不得透露任何一篇私密紀事的存在。
- 導師浮鈕掛在**每一頁**，包含單篇紀事與單本相簿頁。
- `my-child.html` 的子路由寫在 `#` 後面（單一 HTML 示範版是 `#/my-child/…`），`app.js` 在 `#` 改變時重畫：
  （空白）＝家長／同仁只有一個座號就直接進去、導師是全班格；`admin`＝導師全班格；`seat/<座號>`＝文章列表；
  `entry/<座號>/<postId>`＝單篇＋對話串（同仁不顯示、也不查）；`new/<座號>`＝寫一篇（該座號家長、導師）。
  座號不在自己帳號底下 → 畫面只說「不在你的帳號底下」，**一個查詢都不發**（規則照樣會擋）。
- 私密紀事頁：Session 沒有私密讀者身分就只顯示「這一頁只給私密名單」，不發任何查詢；分頁標題固定「私密紀事」，不放文章標題。

### 3.2 頁面殼（每一頁都長這樣）

```html
<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>班級網站</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="css/site.css">
</head>
<body data-page="blog">
<header id="site-header"></header>
<main id="app"></main>
<footer id="site-footer"></footer>
<script src="js/site-config.js"></script>
<script src="js/boot.js"></script>
</body>
</html>
```

每個殼只有 `data-page` 不同。`<title>` 登入後由 `layout.js` 改成班名＋頁名。殼裡**不准有任何內容文字與 inline 程式**；
`tests/test_site_arch.py` 逐檔比對。`<link rel="icon" href="data:,">` 是空的網站圖示：瀏覽器就不會再去要 `/favicon.ico`
（要不到會在主控台留一筆 404，驗收的「零主控台錯誤」就過不了）。

### 3.3 頁首頁尾導覽：單一來源

`core/layout.js` 裡一張 `NAV` 表是唯一來源；`SITE_CONFIG.pages` 的開關決定哪幾項出現。登入前頁首只顯示班名與登入閘；
Session 變成 `ready` 後依角色補上項目。

| 項目 | 連到 | `pages` 開關 | 誰看得到 |
|---|---|---|---|
| 首頁 | `index.html` | `home` | 讀者 |
| 班級紀事 | `blog.html` | `class_posts` | 讀者 |
| 相簿 | `gallery.html` | `gallery` | 讀者 |
| 課程 | `courses.html` | `courses` | 讀者 |
| 我的孩子 | `my-child.html` | `my_child` | Session 有座號，或導師 |
| 專題活動 | `page.html?id=fun` | `fun` | 讀者 |
| 關於我們 | `page.html?id=about` | `about` | 讀者 |
| 每日一詩 | `poem.html` | `poem`（沒寫＝開；不用的班級設 `false`） | 讀者 |
| 導師專用 | `teacher.html` | `teacher_only` | 導師 |

導師浮鈕（右下角）：留言後台、我的孩子（全班）、導師專用、座位表、個人照、匯出 PDF。
頁尾：班名、導師稱呼（`config/site.teacherDisplayName`，**登入後才有**）、版本（`SITE_CONFIG.version`）。

### 3.4 網址與登入閘

- **正式網址＝`SITE_CONFIG.siteUrl`＝`https://<專案>.firebaseapp.com`**，與 `authDomain` 同一個網域（理由見下面「同網域的好處」）。
  `app.js` 第一件事：主機名稱不是它（例如有人開了 `<專案>.web.app`）、又不是 `localhost`／`127.0.0.1`、也不是示範模式
  → `location.replace(siteUrl + 路徑 + 查詢字串 + #)`。同網域的好處：`signInWithRedirect` 不必跨網域存取登入狀態，
  在封鎖第三方儲存的手機瀏覽器上也能登入，也不必另外設定 OAuth 重導網址。
- **登入閘**（未登入時整頁遮罩）：主按鈕「用 Google 帳號登入」；次要連結「沒有 Google 帳號？寄登入連結到信箱」。
  - Google：`signInWithPopup`，被擋就退回 `signInWithRedirect`。
  - **App 內建瀏覽器**（使用者代理含 `Line/`、`FBAN`、`FBAV`、`Instagram`）：Google 不允許在內嵌瀏覽器登入。
    偵測到就不出 Google 按鈕，改顯示「請用手機的瀏覽器開啟」；LINE 另給一個帶 `openExternalBrowser=1` 參數的同一頁連結（LINE 會改用外部瀏覽器開）。
  - email 連結：寄信 → 回到 `index.html` 自動完成登入；換裝置開信要再輸入一次信箱。**Spark 每天全專案只能寄 5 封**，
    `auth/quota-exceeded` 照 §2.6 顯示；畫面文字說明「一台裝置只需要登入一次」。
- **登入了但不在名單**（`Session.state == 'denied'`）：顯示目前登入的信箱＋請他把這個信箱告訴老師＋登出換帳號的按鈕。不顯示任何內容。
- **email 連結登入只能讀**（DATA-MODEL §1.1）：留言框停用、私密紀事與「我的孩子」顯示「此登入方式只能閱讀，留言與私密內容請用 Google 登入。」
  （`CMW.readOnlyLogin(session)`），不靜默失敗；寄信那一段也先講。
- **登入狀態與本機快取**：家長預設用 Firebase 的本機保存（關掉瀏覽器再開仍是登入的），資料庫快取放 IndexedDB。
  - 登入閘有「這是共用電腦」勾選（記在這個分頁的 sessionStorage：`CMW.sharedDevice`）。勾了＝Auth `browserSessionPersistence`
    （關掉分頁就登出）＋ Firestore `memoryLocalCache`（不寫進硬碟）。email 連結會開在新分頁，所以寄信時把勾選另外記在
    localStorage，完成登入就刪。
  - **導師的登入一律只保留到關掉分頁**：判定是導師（探針放行）就 `setPersistence(browserSessionPersistence)`（SDK 把已登入的帳號搬過去，
    不必重新登入）。代價：導師每開一個新分頁都要重新登入。資料庫快取**不**跟著換成記憶體（要換得重新載入；而且模擬器冒煙測試裡
    記憶體快取會間歇「連不到後端」，見 §8.5）：導師在共用電腦上要勾「這是共用電腦」，或用完按登出（會清 IndexedDB）。
  - 已經登入、IndexedDB 還開著時才勾到共用（例如點登入信開在新分頁）→ 切成 session 保存、清快取、重新載入一次；
    sessionStorage 不能用時不做（避免一直重新載入）。
  - 按「登出」照舊清 IndexedDB（§2.3 第 6 個方法）。

### 3.5 部署設定裡的標頭（`firebase.json`）

| 路徑 | 標頭 |
|---|---|
| 全部 | `X-Robots-Tag: noindex, nofollow`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: strict-origin-when-cross-origin`、`Content-Security-Policy: frame-ancestors 'self'`、`X-Frame-Options: SAMEORIGIN`（防別的網站用 iframe 嵌入班網做點擊劫持；舊瀏覽器看 X-Frame-Options。用 SAMEORIGIN 不用 DENY：`authDomain` 與網站同網域，Firebase Auth 的輔助 iframe 也在同網域） |
| `js/site-config.js`、`js/core/queries.js` | `Cache-Control: no-cache`（改設定、加查詢後立刻生效） |
| 其餘靜態檔 | 可快取 |

**正式網址導向不寫在 `firebase.json`**：Firebase Hosting 的 `redirects` 只比對路徑、不能比對主機名稱，而 `<專案>.web.app` 與
`<專案>.firebaseapp.com` 是同一個站，在設定檔裡寫導向會變成自己導向自己。導向由 `app.js` 做（§3.4）。

**待補：完整的 `Content-Security-Policy`**（目前只有 `frame-ancestors`）：`script-src` 只放 `'self'` 與 Firebase SDK 的官方 CDN、
`img-src 'self' data:`、`frame-src 'self'` 與 `https://www.youtube-nocookie.com`、`connect-src` 放 Firestore 與 Auth 的 API 網域；
**必須先在 §8.4 的冒煙測試跑過真的登入流程才開**，少放一個網域登入就會壞。加的時候跟現有的 `frame-ancestors 'self'` 寫在同一個標頭裡。

---

## 4. 內容格式與渲染

### 4.1 正文結構化區塊（紀事、私密紀事、單頁的 `blocks` 欄位）

正文**不存 HTML**（存 HTML 就得讓前端解析字串，等於替 XSS 開門；區塊陣列只用 DOM API 畫，見 §4.2），存一個區塊陣列：

```
Block =
  { t: 'p',     spans: Span[] }                              段落；span.text 裡的 '\n' ＝段內換行
  { t: 'h',     level: 2 | 3 | 4, text: string }            標題（≤ 200 字）
  { t: 'list',  ordered: bool, items: [{ spans: Span[] }] }  清單（不巢狀，≤ 100 項）
  { t: 'quote', spans: Span[] }                              引言
  { t: 'img',   pid: string, caption?: string }             圖片參照：同一個主人文件底下的 images/{pid}（圖說 ≤ 300 字）
  { t: 'video', url: string, title?: string }               影片連結（url 必須 https://，≤ 500；title ≤ 80 字）
  { t: 'hr' }                                                分隔線

Span = { text: string, b?: true, i?: true, href?: string }  text ≤ 5,000 字；b＝粗體、i＝斜體；href 必須 https://，≤ 500
```

- 上限：每份 ≤ 400 個區塊、每個區塊 ≤ 200 個 span、整份文件 ≤ 800 KB（DATA-MODEL §2.6）。
- Firestore 陣列裡不能直接放陣列，所以清單項目是 `{ spans: [...] }` 這種 map，不是陣列的陣列。
- 驗證的正本：Python `scripts/lib/blocks.py`（腳本寫入前）；JS `core/blocks.js`（渲染前再驗一次，不合的區塊跳過）。
- 沒有表格：課表用 `pages` 的 `data.rows`（DATA-MODEL §2.11）。

### 4.2 渲染規則（`core/blocks.js`）

1. **只用** `document.createElement`、`document.createTextNode`、`textContent`、`appendChild`，以及對固定清單屬性的
   `setAttribute`（`href`、`rel`、`target`、`alt`、`loading`、`width`、`height`、`class`（只用程式裡寫死的類名））。
2. **全 `site/js` 禁用**：`innerHTML`、`outerHTML`、`insertAdjacentHTML`、`document.write`、`DOMParser`、`eval`、
   `new Function`、`setAttribute('on…')`、從資料來的 `style`。架構測試逐檔掃（§8.1）。
3. 區塊型別不認得、欄位型別不對 → **整個區塊跳過**（不丟錯、不畫半個）。
4. span：`b` → `<strong>`、`i` → `<em>`，文字一律 `textContent`；`'\n'` 變成 `createElement('br')`。
5. **連結只准 `https:`**：`new URL(href)` 成功且 `protocol === 'https:'` 才畫成 `<a>`，`a.href = url.href`、
   `rel = 'noopener noreferrer'`、`target = '_blank'`；否則只畫文字（`javascript:`、`data:`、`http:` 都只剩字）。
6. `img` 區塊：`<figure>`＋`<img alt="圖說或空字串" loading="lazy">`，來源由 `store.photoSrc(主人路徑, pid, 'image')` 非同步填入；
   圖說 `<figcaption>` 用 `textContent`。拿不到就顯示「這張照片讀不到」的灰框，不留空白。
7. `video` 區塊：網址是 YouTube（主機 `www.youtube.com`、`youtube.com`、`m.youtube.com`、`youtu.be`）而且影片 id 符合
   `^[A-Za-z0-9_-]{11}$` → 先畫一個 16:9 的預覽框（「縮圖」是 CSS 畫出來的，**不讀** YouTube 的縮圖、不連任何外部網站），
   **點了才**建立指向 `https://www.youtube-nocookie.com/embed/<id>` 的 iframe；其他 https 網址 → 畫成連結卡（照第 5 條）。
   相簿的影片連結、課程頁的課程說明影片都走這一條（`CMW.blocks.render([{ t: 'video', … }])`）。

### 4.3 純文字（留言、部落格文章與對話串、摘要、圖說）

`core/text.js`：逐行拆開，`https://` 開頭的網址轉成連結（照 §4.2 第 5 條；結尾的標點不算進網址），其餘一律文字節點。
部落格文章 `body` **逐字保留**（空白、換行照原樣）。

### 4.4 照片顯示

- 來源一律 `'data:image/jpeg;base64,' + data`，**MIME 寫死**；`<img>` 不會執行內容，就算資料被塞了別的東西也只是破圖。
- 照片文件不可變（DATA-MODEL §2.12）→ `photoSrc` 先查本機快取（命中時要主人文件這一頁從伺服器讀成功過，§2.3 第 15 個方法）；
  相簿燈箱只在點開時才讀顯示圖，同時最多 4 張在讀。
- 列表卡片的封面直接用摘要文件裡的 `coverThumb`，不另外讀。
- 相簿格用 `photos.thumbs` 一次 60 張往下捲（查詢結果本身就帶 `data`）。

---

## 5. 發文與上傳流程

### 5.1 共通做法（所有「把本機內容送上網站」的腳本）

1. **預設只看不寫**（`--dry-run` 是預設）：印出「要寫哪些文件、多少張照片、哪些舊照片會刪」。
   老師（或代理照老師的話）加 `--publish` 才真的寫。這就是所有發文腳本共用的兩段式：草稿 → 老師說「上傳」才發。
2. 讀本機母本 → 驗證（slug、日期、分類、欄位長度，經 `lib/schema.py`；正文經 `lib/blocks.py`）。
3. 照片經 `lib/images.py` 處理（§5.3），pid＝顯示檔的 SHA-256 前 16 碼。上線時先列出雲端已有的照片：顯示圖已經在的不重寫
   （同一張照片＝同一個 pid）；同一張照片只改了順序或圖說，只重寫那份縮圖（`data` 一個位元組都不變，快取不受影響）。
4. **順序：顯示圖 → 縮圖 → 正文 → 摘要**（摘要出現在列表時，正文與照片一定都在）。
5. 寫完**讀回逐欄比對**，對不上就 exit 非 0。
6. 最後才刪「舊版本用過、新版本沒用到」的照片文件（兩份都刪）。
7. 更新本機索引（`data/class-posts/index.md`）與台帳（`data/ledgers/published.jsonl`、`uploads.jsonl`；部落格另記 `blog-posts.jsonl`）。
8. 已上線的內容再發一次要明示 `--update`（沒加就擋下、exit 2）；`publishedAt` 保留第一次的時間。

網站下一次讀取就看得到，**不用重新部署**。

### 5.2 本機 md → 區塊 JSON（`lib/mdlite.py`，純標準庫）

```
---
title: 標題
date: 2026-01-01
category: 班級生活
cover: 01.jpg
visible: true
---
正文，段落之間空一行。段落內的換行照原樣保留。

![圖說寫在這裡](01.jpg)

[[video:https://www.youtube.com/watch?v=VIDEO_ID_11]]
```

| md 寫法 | 區塊 |
|---|---|
| 空行分隔的文字 | `p`（段內換行 → span 裡的 `'\n'`） |
| `## `、`### `、`#### ` | `h`（level 2–4） |
| `- ` 或 `1. ` 開頭的連續行 | `list`（`ordered` 依寫法） |
| `> ` 開頭 | `quote` |
| `---` 單獨一行 | `hr` |
| `![圖說](本機檔名)` 單獨一段 | `img`（`pid` 在照片處理完才填） |
| `[[video:https://…]]` 單獨一段 | `video` |
| `**粗體**`、`*斜體*`、`[文字](https://…)` | span 的 `b`、`i`、`href`（非 https 的連結只留文字） |

- **檔頭**（`lib/frontmatter.py`）：只收 `key: value` 與簡單的 `- 項目` 清單；不收任何會執行的語法。
- md 裡的原始 HTML 一律當**文字**（不解析、不支援內嵌 HTML）。

### 5.3 照片處理（`lib/images.py`，Pillow）

**選 Pillow 的理由**：Python 標準庫沒有 JPEG／PNG 解碼器；macOS 的 `sips` 只有 Mac、`cwebp` 不會依 EXIF 轉正、`ffmpeg` 太大。
Pillow 一行 pip 指令，Mac 與 Windows 都有官方預先編好的套件。`requirements.txt` 只有一行 `Pillow>=10`
（選用 `pillow-heif` 給 iPhone 的 HEIC）。這是整個專案**唯一**的 Python 第三方套件；只有處理照片的腳本才檢查它，
缺的時候 `doctor.py` 只印官方安裝說明＋那一行指令，請老師自己貼（AGENTS.md 鐵則 10）。

**處理規格**（參數正本在 DATA-MODEL §3.3，每一步都有單元測試）：

1. 開檔 → `ImageOps.exif_transpose()` 依 EXIF 方向轉正。
2. 轉成 sRGB 的 RGB 影像（有 ICC 描述檔先轉色，之後不帶描述檔）。
3. 產兩份：顯示圖（最長邊 1280，品質階梯 82→58，還太大改 1024 再試）、縮圖（最長邊 320，品質階梯 72→48）；
   JPEG 漸進式、4:2:0、`optimize=True`，**不傳 `exif=`、不寫 XMP、不寫 ICC**。
4. 重新開啟輸出，斷言沒有 EXIF（含 GPS）與 XMP；斷言失敗就不寫。超過硬上限就拒絕並說是哪一張。
5. pid＝顯示圖 JPEG 位元組的 SHA-256 前 16 碼；base64 編碼後寫進文件；md5 與 pid 記進台帳。
6. 原始檔名（可能含姓名或日期時間）**不上雲**；相簿原圖只複製到同步夾 `03_相簿原圖/<slug>/`。
7. 碰到 `.heic` 而沒裝 `pillow-heif`：拒絕處理，說明兩個選項（裝它，或手機相機格式改「最相容」）。

### 5.4 REST 寫入（`lib/firestore_rest.py`）

- 端點：`https://firestore.googleapis.com/v1/projects/<專案>/databases/(default)/documents:commit`；
  標頭一律 `Authorization: Bearer <gcloud 使用者權杖>` **＋ `x-goog-user-project: <專案>`**
  （用使用者憑證呼叫 Google API 時，少了這個標頭會被算到別的專案或直接被拒）。
- 時間欄用寫入轉換 `REQUEST_TIME`。一次 commit ≤ 500 個寫入、請求 ≤ 10 MiB：照片文件大，**每次 commit 最多 10 張顯示圖**。
- 401 → 重新取一次權杖再試一次；429／503 → 指數退避最多 5 次；其他錯誤原樣印出（不含權杖）後停止。
- 刪文件前先 `listCollectionIds` 找出子集合逐層刪（REST 沒有遞迴刪除）。
- **模擬器模式**（腳本的 `--emulator`、環境變數 `CMW_EMULATOR=1`，或 `firebase emulators:exec` 自動設的 `FIRESTORE_EMULATOR_HOST`）：
  網址換成 `http://<FIRESTORE_EMULATOR_HOST，沒有就 127.0.0.1:8080>`（只准本機位址；`demo-` 開頭的專案不走模擬器就拒跑），權杖換成字串 `owner`（模擬器把
  `Bearer owner` 當管理身分），流程完全一樣。

### 5.5 各種內容一覽

| 腳本 | 本機來源 | 寫到哪（DATA-MODEL） | 批次 |
|---|---|---|---|
| `publish_post.py <slug>` | `data/class-posts/<slug>.md`＋同名資料夾裡的照片 | `posts/{slug}/images|thumbs/*`、`posts/{slug}/content/main`、`posts/{slug}` | v1 |
| `publish_private.py <slug>` | `data/private-posts/<slug>.md`＋同名資料夾 | `private_posts/{slug}/images|thumbs/*`、`private_posts/{slug}` | v1 |
| `publish_album.py <slug>` | `data/albums/<slug>.md`（標題、日期、說明、影片連結、圖說）＋同名資料夾的全部照片 | `albums/{slug}/images|thumbs/*`、`albums/{slug}`（原圖複製到同步夾：P4b） | v1 |
| `publish_blog.py --seat 03 <草稿名>` | `data/blog-drafts/<座號>/<草稿名>.md`＋最多 3 張照片（導師用腳本幫某位孩子發；postId 每次新產生，同一份草稿不重發） | `student_blogs/{seat}/entries/{postId}` 與其照片（`author: 'teacher'`、pid `0`–`2`，一次 commit） | v1 |
| `open_blogs.py` | `data/roster.csv`（頭像選用） | `student_blogs/{seat}`（全班一次開好） | v1 |
| `publish_page.py <pageId>` | `data/pages/<pageId>.md`＋同名資料夾（`about`、`fun`、`home`、獨立單頁；課程頁、課表另外做） | `pages/{pageId}` 與其照片 | v1 |
| `sync_calendar.py`（**尚未實作**；v1 的行事曆只有首頁訂閱鈕） | `class.json` 的**公開**行事曆網址 | `pages/calendar` 的 `data.events` | — |
| `publish_site.py --records-kit <網址> --class-docs <網址>` | 導師專用頁兩張入口卡的網址（`""`＝拿掉） | `roster/links`（只改給的那一欄） | v1 |
| `publish_courses.py <courses…｜schedule…>` | `data/courses/<頁面代號>.md`（課程介紹、`## 課程說明影片`、`## 各科課程大綱` 卡片；或只有一個表格的課表）；子資料夾（課程紀錄）不讀 | `pages/{pageId}`（`course`／`schedule`）與其照片 | v1 |
| `docs_index.py` | 同步夾 `01_機密（只有導師）/班級文件/` 的檔名與資料夾名（不讀內容） | 同一夾的 `index.md`（不上雲端資料庫） | v1.1 |
| `parent_note.py --seat N --draft <草稿>` | 草稿（孩子稱呼寫成 `〔孩子〕`）、`roster.csv`、`contacts.csv` | 不寫任何地方：用預設郵件程式打開一封待寄的信，老師自己按傳送 | v1.1 |
| `notify_config.py` | `class.json` 的 `notifications.*` 與 `teacher.*` | `config/notify`（§10） | v1.1 選配 |
| `access_sync.py` | `data/contacts.csv`（同仁也寫在這裡，關係欄填「同仁」）、`data/roster.csv`、`data/parent-roles.yaml`、`class.json` 的 `teacher.display_name`、`school_name`、`students.count`、`calendar_ics_url` | `allowlist`（沿用舊代號）、`private_allowlist`、`parent_child_map`、`roster/students`、`config/site`；`--check` 驗包含關係 | v1 |
| `backup.py` | 雲端 | 同步夾；照片增量（DATA-MODEL §5.2）；寫 `ops/backup_status` | v1 |
| `publish_seating.py [方案代號]` | `data/seating/<YYYY-MM-DD>.json`（只放座號） | `seating/{planId}` | v1.1 |
| `publish_personal_photos.py [--seat N]` | `data/personal-photos/<座號>.<副檔名>`（檔名只准座號） | `personal_photos/{seat}` 與其照片 | v1.1 |
| `publish_parent_photo.py --seat N --from-file <照片>`／`--from-blog <postId> --photo 0-2` | 本機照片，或那位孩子部落格文章的顯示圖（重新處理）；稱謂取 `parent-roles.yaml` | `parent_photo_display/{seat}` 與其照片 | v1.1 |
| `publish_poems.py <YYYY-MM>` | `data/poems/*.md`（一首一檔；`rights` 空白的擋下不發） | `pages/poems-YYYY-MM` | v1.1 |

### 5.6 瀏覽器端發部落格（`core/photo-encode.js`＋`core/blog-compose.js`）

1. 驗文字（標題 1–200、內文 1–10,000）與張數（≤ 3、每個檔 ≤ 30 MB）。
2. 每張照片：`createImageBitmap(file, { imageOrientation: 'from-image' })` 轉正 → 畫到 canvas → 照 DATA-MODEL §3.3
   的階梯 `canvas.toBlob('image/jpeg', q)` 產顯示圖與縮圖 → 轉 base64（分段轉，避免大字串爆堆疊）。
   canvas 重新編碼**不帶任何 EXIF**；**不上傳原檔**。瀏覽器解不開的格式（非 Safari 開 HEIC）→ 提示改用 JPEG。
3. `postId = store.newPostId()`（**每次送出都重新產生**）。
4. 組批次：`entries/{postId}`（`photos` 依序 `{ pid: '0'|'1'|'2', w, h, caption? }`）＋每張的 `images/{i}`、`thumbs/{i}`
   （`order: i`），最多 7 個 `Op` → `store.batch(ops)`。
5. 失敗：保留表單內容、顯示錯誤；使用者再按送出＝回到第 3 步換新 `postId`（同一個 `postId` 再寫會變成「改」而被規則拒絕，DATA-MODEL §2.14）。批次是原子的，
   失敗不會留下半篇。

---

## 6. 管理端腳本的寫入權限

| 做法 | 要多裝什麼 | 金鑰檔 | 學校帳號 | 只用標準庫 | 結論 |
|---|---|---|---|---|---|
| **gcloud 使用者登入＋`gcloud auth print-access-token`** | gcloud CLI（官方安裝程式） | **無** | 可用（就是老師自己的帳號） | ✓（權杖當 Bearer，REST 用 `urllib`） | **採用** |
| gcloud ADC | 同上 | ADC 檔 | 可用 | 要自己刷新權杖或裝套件 | 多一次登入，沒好處 |
| 服務帳號金鑰 JSON | 無 | **有，長期有效的秘密檔** | 新組織預設禁止建立金鑰 | ✗（簽 JWT 要 RS256） | 不採用 |
| Firebase Admin SDK（pip） | 多個 pip 套件 | 還是要 ADC 或金鑰 | 同上 | ✗ | 不採用 |
| Firebase MCP 寫入 | 綁特定代理 | — | — | — | 不採用：大量照片資料會流過代理對話 |

- 老師安裝 gcloud CLI（<https://cloud.google.com/sdk/docs/install>），執行一次 `gcloud auth login`，用**開 Firebase 專案的那個
  Google 帳號**登入。`lib/gauth.py` 每次執行時呼叫 `gcloud auth print-access-token` 取權杖（約一小時有效），
  權杖只在記憶體、**永不印出、不寫檔**。
- 以 IAM 身分呼叫 Firestore REST **不受安全規則管**；專案建立者本來就是 Owner，不需要另外授權。
  **每個請求都帶 `x-goog-user-project: <專案>`**。
- **找工具**（`lib/hostos.py`）：先查 PATH，找不到再查常見安裝位置——Windows 裝完 gcloud／Node 後，**已經開著的終端機 PATH
  不會更新**，這是新手最常卡的地方。常見位置：Windows `%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd`、
  `%APPDATA%\npm\firebase.cmd`；Mac `/opt/homebrew/bin`、`/usr/local/bin`、`~/google-cloud-sdk/bin`。找到了但不在 PATH 時，
  照常使用並提醒「重開一個終端機」。Windows 上 gcloud 與 firebase 都是 `.cmd`。
- **Windows 的 Python 一律 `py -3`**。Microsoft Store 版 Python 的陷阱：輸入 `python` 可能打開商店而不是執行
  （「應用程式執行別名」），而且它的檔案路徑被重新導向到沙箱裡。`doctor.py` 看到 `sys.executable` 含 `WindowsApps` 就提醒
  改裝 python.org 的官方版本。
- 部署用的 `firebase login` 是另一次登入；`doctor.py --cloud` 比對兩邊帳號，不一致就 ✗。

---

## 7. 設定產生與部署

### 7.1 `build_config.py`

| 去處 | 欄位 | 誰看得到 |
|---|---|---|
| `site/js/site-config.js`（**公開**，manifest 標 `public: true`） | `className`、`siteUrl`、`firebase.{projectId, apiKey, authDomain, appId, messagingSenderId}`、`pages`、`categories`、`version` | 任何人 |
| `firestore.rules`（樣板 `templates/firestore.rules.tmpl`，不公開） | `{{TEACHER_EMAIL_KEY}}`（導師 email 經 `email_key()` 正規化） | 只有 Firebase |
| `.firebaserc` | 專案 id | 本機 |
| 不經樣板 | `school_name`、`teacher.display_name`、`students.count`、`calendar_ics_url` → `access_sync.py` 寫 `config/site`；`region` → 檢查工具；`school_year` → 雲端硬碟的學年／學期資料夾（`drive_init.py`、`archive_media.py`、`backup.py`、`docs_index.py`、`new_block.py`）；`notifications.enabled` → v1.1 | 登入後的讀者／導師 |

- 公開樣板只准用 `PUBLIC_KEYS` 裡的欄位，多用一個（例如有人把 `{{TEACHER_EMAIL_KEY}}` 加進 `site-config.js.tmpl`）
  → exit 1。`authDomain` 留空就是 `<專案>.firebaseapp.com`，填別的 → exit 1。行事曆填私人 iCal 網址 → exit 1。
- 全部輸出 gitignored，**永遠由腳本產生，代理不准手寫**。還留著範本值就 exit 1；`--allow-placeholders` 只給測試與示範。
- 示範站的設定由 `scripts/build_site.py --demo` 產生（`demo: true`、不含任何 Firebase 值）。
- `--emulator`（P2b，給 §8.4 的冒煙測試）：專案 id 不是 `demo-` 開頭就換成 `demo-cmw`、空的或範本值的 apiKey／appId 換成假值、
  網站設定多一個 `emulator: true`（前端改連本機的 Auth 9099／Firestore 8080 模擬器）；隱含 `--allow-placeholders`。
  **一定要搭 `--root` 指到別的資料夾**：產生檔的位置就是正式網站的位置，寫進 repo 本身的話下一次部署會把「連本機模擬器」送上線，
  所以 `--root` 等於 repo 時直接 exit 1。正式建置的 `emulator` 永遠是 `false`（公開欄位 `EMULATOR`，只是一個布林值）。

### 7.2 `build_indexes.py`

`templates/queries.json` → `firestore.indexes.json`（repo 根）＋`site/js/core/queries.js`，兩個都進 git。
`--check` 只驗不寫（單元測試會跑），`--markdown` 印 DATA-MODEL §4.4 的表。規則與測試見 DATA-MODEL §4。

### 7.3 部署順序（`scripts/deploy.py`，順序寫死）

| 步驟 | 做什麼 | 為什麼在這個位置 |
|---|---|---|
| 0 | `doctor.py --cloud` 的必要項全過（§7.4） | 前提不對就別開始 |
| 1 | `build_config.py`（不准範本值）＋`build_indexes.py --check`（`firebase.json` 的網站資料夾不是 `site/` 時另跑 `build_site.py`） | 規則裡的導師 email 鍵要是真的；索引檔要是最新的 |
| 2 | `firebase deploy --only firestore:rules` | 預設全拒的規則先上，資料一開始就有門 |
| 3 | `firebase deploy --only firestore:indexes`（**絕不加 `--force`**），然後每 20 秒查一次索引狀態，**全部 READY 才往下**（最多等 20 分鐘，逾時就停並說明） | 網頁一上線就會查；索引還在建時查詢會失敗 |
| 4 | 只有 `class.json` 的 `notifications.enabled` 是 `true` 才做（v1 預設略過）：`firebase functions:artifacts:setpolicy` → `firebase deploy --only functions`（§10） | 通知信的觸發器要比網頁早上線；沒開的班級什麼都不做 |
| 5 | `firebase deploy --only hosting` | 最後才讓網頁上線 |
| 6 | 部署後檢查：`<siteUrl>/robots.txt` 回 200、回應帶 `X-Robots-Tag: noindex`、`site-config.js` 的 `projectId` 對 | 確認不被搜尋引擎收錄、部署的是對的專案 |

- 每一步都帶 `--only`、`--project`、`--non-interactive`，一步失敗就停，**原樣印出那一步的指令與錯誤訊息**。
  `deploy.py --only <步驟>` 可單獨重跑某一步。**任何一步都不加 `--force`**。
- 部署**不動任何資料**。部署完才跑資料腳本：`access_sync.py`（名單＋`config/site`，導師一定在內）→ `open_blogs.py`。
  不加 `--yes` 只印計畫（代理先把計畫講給老師聽）。
- `firebase.json`：`firestore.rules`、`firestore.indexes` 指到產生檔；hosting 公開目錄 `site`、標頭照 §3.5；
  模擬器埠 auth 9099、firestore 8080、hosting 5000，`ui.enabled: false`。

### 7.4 `doctor.py --cloud`：只有真雲端才會壞的項目，唯讀檢查清單

全部是**讀取**（REST GET，帶 `x-goog-user-project`），不改任何東西。「必要」項沒過，`deploy.py` 不動手。

| # | 檢查 | 怎麼查 | 通過條件 | 必要 |
|---|---|---|---|---|
| 1 | 兩邊登入同一個帳號 | `gcloud auth list`、`firebase login:list` | 帳號相同 | ✓ |
| 2 | 專案存在且讀得到 | Firestore `GET projects/<p>/databases/(default)` | 200 | ✓ |
| 3 | Firestore 位置與模式 | 同上的 `locationId`、`type` | `locationId == class.json 的 region`、`type == FIRESTORE_NATIVE` | ✓ |
| 4 | **authDomain 與網址一致** | Firebase Management API 讀網頁應用程式設定 | 線上 `authDomain == <p>.firebaseapp.com == SITE_CONFIG.siteUrl 的主機`；`apiKey`、`appId` 與 `class.json` 相同 | ✓ |
| 5 | **Auth 登入方式已開** | Identity Toolkit 管理 API 讀專案設定與 Google 提供者設定 | Google 已啟用；電子郵件登入已啟用且 `passwordRequired == false`（＝email 連結）；授權網域含 `<p>.firebaseapp.com` | ✓ |
| 6 | **索引已部署** | Firestore 管理 API 列出索引與欄位覆寫 | `firestore.indexes.json` 的每個複合索引都在且 `READY`；每個欄位覆寫都生效 | ✓（部署前允許缺，部署後必須全有） |
| 7 | 規則已部署且是本機這份 | Firebase Rules API 讀 `cloud.firestore` 的 release 與 ruleset | 線上內容＝本機產生的 `firestore.rules` | ✓（部署後） |
| 8 | **專案方案** | Cloud Billing API 讀 `billingInfo` | `billingEnabled == false` → 印「Spark：email 連結登入每天 5 封」；`true` → 印「Blaze：記得設預算警示」。API 沒開或沒權限 → 「！無法判斷」（不算失敗） | — |
| 9 | 網站上線 | GET `<siteUrl>/robots.txt` 與 `js/site-config.js` | 200、帶 `X-Robots-Tag`、`projectId` 對 | 部署後 |
| 10 | 名單包含關係 | `access_sync.py --check` | 導師在兩份名單、包含關係成立 | 部署後 |

各 API 的確切網址由 P4 實作時逐一對照官方 REST 參考寫進程式；查不到或回 403 時**原樣印出錯誤**並說明可能原因
（API 沒啟用、登錯帳號、學校組織政策擋住），不要吞掉。
**安裝第 8 步還要真人冒煙**：老師用一支真的手機，從 LINE 點網站連結 → 照 §3.4 改用瀏覽器開 → 用家長帳號登入 → 看得到紀事與照片。

---

## 8. 測試四層

**所有測試都不碰任何真雲端專案**（本專案沒有、也不開測試用的雲端專案：測試一律用模擬器與暫存目錄，跑測試的人不會動到任何真的班級資料，也不會產生費用）。

### 8.1 純函式與架構檢查（`python3 scripts/check.py`，三個平台的 CI 都跑）

`unittest`：座號、email 鍵（共用向量）、`build_config`（公開欄位、注入、authDomain、行事曆）、`build_indexes`（每個查詢有索引、
沒有多餘索引、產生檔最新、文件表格一致）、檔頭、mdlite → 區塊、`blocks.py` 驗證（含惡意連結）、`images.py`（沒裝 Pillow 就 skip；
驗 EXIF 與 GPS 真的被清掉、直拍照片真的被轉正、品質階梯與硬上限）、`schema.py`、`access_sync` 的對帳計畫（包含關係、代號沿用）、
`data_exit` 的本機閘與計畫檔遮信箱、`backup`／`archive_media`／`status` 的純函式（同步夾一律用暫存目錄模擬，Windows 路徑用 `PureWindowsPath`）、REST 請求組裝（每個請求都帶 `x-goog-user-project`，不連網）。

**架構檢查**（同樣是 unittest）：
- `site/js/` 裡除了 `core/store-firestore.js` 以外，沒有任何檔提到 Firebase SDK 的網址。
- 整個 `site/` 沒有 §4.2 第 2 條列的任何禁用 API、沒有 `firebase/storage`。
- `views/` 裡沒有集合路徑字串（`'posts/'`、`'student_blogs/'` 這類），路徑一律經 `CMW.paths`。
- 每個 `site/*.html` 符合 §3.2 的殼。
- 公開樣板只用公開欄位（`tests/test_build_config.py`）。
- 安全規則樣板（`tests/test_rules_template.py`，不需要 Java）：manifest 產生 `firestore.rules` 而且不公開、樣板只用
  `{{TEACHER_EMAIL_KEY}}`、最後一條是預設全拒、文件存取次數靜態檢查（每條 allow 最壞 ≤ 10、瀏覽器批次 ≤ 20；
  `lib/rules_budget.py` 另用一份已知答案的小規則自我測試）、DATA-MODEL 附錄 A 與樣板逐字相同。

### 8.2 規則測試（模擬器，`python3 scripts/test_rules.py`，或 `python3 scripts/check.py --rules`）

- **一鍵**：`python3 scripts/test_rules.py`（Windows：`py -3 scripts/test_rules.py`）。依序：
  1. 用測試用設定（導師 email 是 `@example.com`）呼叫 `build_config.py`，把規則產生到暫存資料夾——測的就是 `build_config.py`
     真的會產生的那份，不另外手寫規則副本。另外產一份「導師信箱是 gmail」的規則（信箱在執行時才從兩段接起來）。
  2. 文件存取次數靜態檢查（`lib/rules_budget.py`）：印出每個路徑 × 操作的最壞次數。**模擬器對查詢（list）量到的上限是 20，
     正式環境是 10**，這一項只能靠靜態檢查。
  3. 找 Java 21 以上、Node.js 20 以上（`hostos.find_exe_all()`：先查 PATH，再查常見安裝位置；Mac 的 `/usr/bin/java` 是殼，
     一律實際跑一次版本指令）。找不到只印官方下載頁（Java：<https://adoptium.net/>、Node.js：<https://nodejs.org/en/download>），不代裝。
  4. `tests/rules/` 裡 `npm ci`（`package-lock.json` 釘死 `@firebase/rules-unit-testing`、`firebase`、`firebase-tools` 的版本，
     連帶釘住模擬器版本；裝過而且鎖檔沒變就跳過）。
  5. `firebase emulators:exec --only firestore --project demo-cmw` 跑 `tests/rules/run.mjs`（`firebase-tools` 用 `tests/rules`
     裡釘住的那一版，交給它的指令用真的 `node` 絕對路徑）。專案 id 用 `demo-` 開頭：模擬器保證不會碰到任何真實資源。
- **測試怎麼寫**（官方 `@firebase/rules-unit-testing`＋Firebase JS SDK）：種資料用「關掉規則」的管理身分；各角色用
  `authenticatedContext()` 自己放 `email`、`email_verified`、`firebase.sign_in_provider`。每一段先清空、重種同一份資料。
  - 14 種登入身分：未登入、匿名、非名單、名單內但 email 未驗證、被移出名單（座號對應還在）、班網讀者、座號暫停、座號家長（01）、
    同仁（01、03）、私密讀者、email 連結登入的名單者、導師、email 未驗證的導師 email、email 連結登入的導師 email。
  - `suites/` 是 DATA-MODEL 每一張權限表的**逐格翻譯**：每一格對 14 種身分各跑一次（允許與拒絕兩面），get 與 list 分開；
    「找不到」（`exists() == false`）與「被拒」（`permission-denied`）分開驗。
  - 另外有：欄位白名單（多一欄、少必填、型別、大小、冒用代號）、email 鍵共用向量（`tests/fixtures/emailkey_vectors.json`，
    規則端與 Python 拒收同一批）、撤名單立即生效、部落格發文批次（7 個寫入、同一個 `postId` 重送被拒、整批原子）、導師身分的各種寫法。
  - 查詢形狀：`templates/queries.json` 的**每一個**查詢，用 `who` 裡的每種角色實際跑一次（通過；有 `watch` 的另外用 `onSnapshot`），
    再用拿掉成員條件、沒有門票的主人、不該有的角色各跑一次（被拒）。
  - 咬人檢查（突變測試）：把規則裡幾個關鍵判斷各拿掉一個，對應的案例必須翻盤，證明測試不是擺好看的。
- 輸出：每一段一行統計（失敗的案例逐條印；`--verbose` 全印）。跑完成功會刪掉模擬器留在 `tests/rules/` 的紀錄檔；
  `--clean` 另外刪掉 `tests/rules/node_modules`（約 400 MB；它有二進位檔，公開前的隱私掃描會擋）。`--budget-only` 只做第 1、2 步。
- CI：`.github/workflows/ci.yml` 的 `rules` 工作（只在 ubuntu；setup-java 21、setup-node 22、Python 3.12）跑同一支。
  老師的電腦不跑這一層（沒有 Java），`check.py` 預設也不跑，加 `--rules` 才跑。
- **管理腳本整合測試**（`python3 scripts/test_admin.py`，或 `check.py --integration`）：同一套 Java／Node，另開隨機埠的模擬器，
  照老師的用法跑 `access_sync`（預覽、兩次 `--apply`＝冪等、截斷／缺檔／一次刪太多三道閘）、`open_blogs`、`publish_*`（兩段式、`--update`、
  刪舊照片、重複發文被擋）；每份文件過 `schema.py`、每張照片解回 JPEG 驗沒有 EXIF／GPS 且已轉正；最後 `tests/rules/admin/readback.mjs`
  用真規則＋真 SDK 以家長、同仁、私密讀者、導師讀回，並用導師身分在瀏覽器端重建一篇腳本發的文章（規則放行＝形狀一致）。
  CI 在 `rules` 工作裡跑（另裝 Pillow）。

### 8.3 前端（`node --test tests/js/*.test.js`，Node 內建測試，零 npm 套件；`check.py` 有 Node 就會跑）

- Store 契約：兩個類別的方法清單與 §2.3 完全一致（讀原始碼比對，不執行 SDK）。
- `emailkey.js` 跑共用向量；`paths.js` 擋掉壞參數。
- `query-eval.js` 對 `CMW.QUERIES` 每個查詢的語意（等號、範圍、排序、上限、游標、`limitToLast`、count）。
- `blocks.js`、`text.js`：用一個測試內建的極簡假 DOM（只實作 createElement／createTextNode／appendChild／setAttribute），
  驗 `javascript:` 連結只剩文字、不認得的區塊被跳過、`rel` 一定有 `noopener`。
- `validate.js` 的上限與 DATA-MODEL 一致；`read-stats.js` 的 X/N（多裝置同一 email 只算一次、同仁與導師不算）。
- `photo-encode.js`（`tests/js/photo-encode.test.js`）：尺寸（等比、不放大）、品質階梯（第一個達標就停、1280 → 1024、
  硬上限拒絕、參數與 DATA-MODEL §3.3 逐字一致）、分段 base64、**EXIF 清除以「輸出沒有 APP1 區段」判定**（編碼器換成假的，
  故意吐出帶 APP1 的位元組 → 一定拒絕）；`blog-compose.js` 的批次形狀與重試換新 `postId`；`seen.js` 的未讀判準。
  需要的 JPEG 位元組由 `tests/fixtures/exif-jpeg.js` 在測試執行時產生（repo 裡不放任何圖檔）。
- **示範站驗收**：`python3 scripts/verify_site.py`（本機有 Chrome 才跑；截圖預設放系統暫存資料夾的 `cmw-verify/`）：
  訪客／家長／導師 × 每一頁 × 手機 390px（DevTools 裝置模擬）與桌機，零主控台錯誤、零橫向溢出、零外部連線；
  互動：留言、收起、燈箱、相簿、影片預覽框、家長發文（瀏覽器裡真的 canvas 重新編碼一張帶 EXIF 方向與 GPS 的 JPEG，
  驗輸出沒有 APP1、沒有 GPS、方向已轉正）、對話串與收起、導師未讀、同仁、非私密讀者；單一 HTML 的 `#/` 路由。

### 8.4 模擬器＋真 Firebase JS SDK 冒煙（`python3 scripts/smoke_emulator.py`；補 §2.7「示範模式不模擬權限」留下的空缺）

示範模式不經過 SDK 也不經過規則，所以**另外要有一條走真 SDK、真規則、正式站模式的路徑**：

1. 用測試設定（導師 `class.teacher@example.com`、專案 `demo-cmw`）跑 `build_config.py --root <暫存> --emulator`：
   測的就是真的會部署的網站設定與安全規則。把 `site/` 複製到暫存資料夾、放進產生的網站設定。
2. 找 Chrome、Java 21＋、Node.js 20＋（`tests/rules` 的 `firebase-tools`，跟規則測試共用同一份 `npm ci`），然後
   `firebase emulators:exec --only auth,firestore --project demo-cmw --config <暫存>/firebase.json` 跑同一支腳本的內層。
3. 內層：用 REST（`Bearer owner`，不受規則管）種一班資料（名單、2 篇紀事其中 1 篇下架、相簿、私密紀事、單頁、3 個座號的部落格與對話）；
   照片是在 Chrome 裡當場畫出來轉成 JPEG 的。本機只聽 127.0.0.1 的小伺服器放網站；無頭 Chrome 每個身分一個獨立的瀏覽器情境，
   Firebase SDK 從官方 CDN 載入（版本就是 `store-firestore.js` 寫死的那一個），用 Auth 模擬器接受的假 Google 憑證
   （`signInWithCredential`，走 Store 用的同一個 SDK 實例）登入：導師、學生 A 家長（私密讀者）、學生 B 家長、同仁（座號 03）、名單外。
4. 逐頁逐項驗（每一頁：畫完、零主控台錯誤、手機寬零溢出）：Session 解析（導師探針放行／被拒）、紀事列表與鎖頭卡、下架文章
   （導師看得到、家長「找不到」＋規則拒絕）、留言送出即時出現、已讀回條寫進資料庫（紀事與私密紀事）、導師已讀 X/N、
   相簿格（查詢結果帶的縮圖）與燈箱（`photoSrc` 顯示圖）、課程影片點了才建 youtube-nocookie、導師專用頁、留言後台（集合群組）、
   家長發文批次（照片帶 EXIF 方向＋GPS → 資料庫裡的 JPEG 沒有 APP1、沒有 GPS、已轉正）、同一 `postId` 重送被拒、
   家長收起自己的留言而且改不回來、看不到別人座號（畫面不發查詢＋規則拒絕）、同仁讀不到對話串、名單外看到換帳號畫面、
   導師全班格未讀亮起／看過熄掉、代號對回「學生 A 家長（母）」、下架家長文章、收起留言；另外按一次「用 Google 帳號登入」，
   確認真的開出 Auth 模擬器的登入視窗（`signInWithPopup`）。最後印 `PASS n/n`。
5. 本機沒有 Chrome 就印「SKIP：找不到 Chrome」，不算失敗（`--require-chrome` 就算失敗）。
   CI：`.github/workflows/ci.yml` 的 `smoke` 工作（ubuntu、`needs: rules`、Java 21、Node 22、Python 3.12、官方 setup-chrome，
   `CMW_CHROME_ARGS=--no-sandbox` 只給 CI）。`--shots 目錄` 另存每一頁的手機截圖（不要存在 repo 裡）。

### 8.5 模擬器驗不到的東西

複合索引是否存在（交給 §8.1 的登記表測試）、Auth 的登入方式有沒有開、authDomain 與網址、實際地區、方案、真手機的 App 內建瀏覽器
——全部集中在 `doctor.py --cloud`（§7.4）與安裝第 8 步的真人冒煙。

§8.4 另外刻意沒有涵蓋、只有真雲端或真手機才知道的：真的 Google 帳號選擇畫面走完（模擬器只驗到「視窗開得出來」，
登入本身用假憑證）、`signInWithRedirect` 退路走完回到網站、email 連結登入信（Spark 每天 5 封）、查詢的文件存取次數上限
（正式環境 10、模擬器 20，只能靠 §8.2 的靜態檢查）、iPhone Safari 的 HEIC 與 `createImageBitmap` 轉正、Content-Security-Policy（§3.5）、
「這是共用電腦」的記憶體快取（`memoryLocalCache`，§3.4）：在模擬器＋無頭 Chrome 裡把整套冒煙改成記憶體快取跑，會間歇出現
「Could not reach Cloud Firestore backend」而轉成離線（2026-09-26 實測，原本的 IndexedDB 快取全過），所以 §8.4 不涵蓋這條路徑，
要在真雲端用真手機勾選登入驗一次。

---

## 9. Mac 與 Windows

- 腳本全部 Python，路徑一律 `pathlib`；**不寫 bash 限定的流程**。
- 外部指令（`gcloud`、`firebase`、`java`、Chrome）一律經 `lib/hostos.py` 找執行檔（§6）。
- 寫出的文字檔一律 LF 換行、UTF-8；主控台輸出經 `lib/console.py` 的 `setup_utf8()`。
- 說明文件的指令分 Mac／Windows 兩欄（`python3 …`／`py -3 …`）。
- CI 在 ubuntu、macos、windows × Python 3.9／3.12 跑 `check.py`；規則測試與冒煙只在 ubuntu 跑（模擬器行為與平台無關）。

---

## 10. v1.1 選配：通知信模組（需要 Blaze，會部署 Cloud Functions）

v1 沒有任何伺服器端程式。這個模組是**選配**、預設關閉，裝了才有（老師端的說明與取捨：`playbooks/notify.md`）：

| 功能 | Function（第 2 代，全部部署在 `class.json` 的 `region`，與資料庫同區） | 寄給誰 |
|---|---|---|
| 紀事、相簿、私密紀事的新留言（導師自己的不寄） | `cmwCommentPost`／`cmwCommentAlbum`／`cmwCommentPrivate`（Firestore onCreate） | 導師，即時 |
| 家長在「我的孩子」發文 | `cmwBlogEntry`（onCreate；`author: 'parent'`） | 導師，即時 |
| 家長在對話串回話 | `cmwBlogComment`（onCreate；`role: 'parent'`） | 導師，即時 |
| 導師發文、導師在對話串回覆 | 同上兩支觸發器只**排進** `blog_notify_queue`（`sendAfter`＝內容建立＋30 分鐘）；`cmwNotifySweep`（每 10 分鐘，查詢 `notifyQueue.due`，一輪最多 30 筆）到期才寄 | 那個座號的家長，一位一封 |
| 每日摘要＋看門狗 | `cmwDailyDigest`（每天 `notifications.digest_hour` 點，`time_zone`） | 導師（沒有新東西也沒問題的日子不寄） |

**設定分三處**（`scripts/lib/notify.py`）：`class.json` 的 `notifications.*`（只在老師電腦）→ `build_config.py` 產生
`functions/cmw.generated.json`（部署時讀：專案、地區、網址、時區、摘要時間、備份門檻；**沒有任何信箱**）；
資料庫 `config/notify`（`notify_config.py` 寫，網頁寫不進去；階段、三個開關、起始線、收件與寄件信箱、署名；改了不用重新部署）；
Gmail 應用程式密碼只在 Secret Manager（`CMW_GMAIL_APP_PASSWORD`；老師自己在終端機 `firebase functions:secrets:set`，代理不經手）。

**階段**（`config/notify.phase`）：`off`（全部不寄；排隊中的下一輪全部取消，不會積到下次打開時補寄）→ `dryrun`（給導師的信照寄、
給家長的只記錄 `mode: 'dryrun'`）→ `live`。給家長的信只有「入列當下是 live、現在也是 live、`parentMail` 開著」才真的寄：
dryrun 期間排的切 live 也不補寄；窗內切回 dryrun／off 就煞住。`notify_config.py` 只准從 dryrun 切 live，而且要排程心跳 60 分鐘內。

**不重寄、不亂寄的幾道閘**（`functions/lib/pure.js`、`core.js`）：
- 回填閘（一律 fail-closed）：內容的 `createdAt` 讀不懂 → 不寄；早於 `notifyFloor`（從 off 打開那一刻）→ 不寄；
  觸發當下內容已經建立超過 2 小時（還原備份、批次回填時的舊內容一次湧進來）→ 不寄。
- 30 分鐘修正窗：掃到時重讀文章與回覆，不在了、下架了、收起了、作者不是導師 → 整筆 `cancelled`。
- 冪等：佇列 doc id 固定（`{seat}__{postId}`、`{seat}__{postId}__{cid}`）＋`create()`；給導師的即時信先在 `notify_once` 佔位再寄；
  處理佇列先用交易拿租約（兩輪同時掃也只處理一次）；逐人台帳 `sent/{sha256(email 鍵)前 32 碼}` 先佔位再寄、寄失敗拿掉佔位
  （寄到一半斷電＝寧可少寄一封，絕不重寄）。寄失敗 5 次轉 `failed`。
- 收件人：`parent_child_map` 裡 `seats` 含這個座號、`kind == 'parent'`、`active`、而且還在 `allowlist` 的 email 鍵（本身就是可投遞的地址）。
- 信裡**只有座號、標題、連結**（私密紀事連標題都不寫，只寫 slug）；不夾正文、不寫姓名；錯誤訊息落地前一律遮掉信箱。
- 寄件：Gmail SMTP（`smtp.gmail.com:465`），登入帳號＝`fromEmail`（From 不能是別的地址）；導師收件信箱不同時加 Reply-To。
  套件：`firebase-functions`、`firebase-admin`（官方）＋`nodemailer`，版本釘死在 `functions/package-lock.json`。

**每日摘要**：過去 24 小時的新留言（依篇計數：家長／同仁，導師自己的不算；查詢 `comments.admin`）、家長發的部落格（`entries.recentParent`）、
家長在對話串留的話（`blogComments.recentParent`）；「需要處理」：名單包含關係（與 `access_sync.py` 同一套判斷）、備份心跳
（門檻與 `status.py` 同一組，正本 `scripts/lib/thresholds.py`：7 天提醒、14 天加重；`ok: false` 也提醒）、通知排程停了（心跳超過 1 小時）、
過去 24 小時寄不出去、過了預定時間 2 小時還在排隊、即時信寄不出去。用到的查詢都是登記表裡已有的形狀，或只有等號／單一欄位範圍
（Firestore 自動單欄索引就夠），**不需要新增索引**。

**部署**（`deploy.py` 第 4 步；只有 `notifications.enabled` 才做；**任何指令都不加 `--force`**）：
1. 本機前提：`functions/node_modules`（老師自己打 `npm ci --prefix "<資料夾>/functions"`；鐵則 10 代理不跑安裝指令）、
   `functions/cmw.generated.json` 是這個專案的。
2. `firebase functions:artifacts:setpolicy --location <region> --non-interactive`：第一次部署前映像檔倉庫（`gcf-artifacts`）還不存在，
   它只印「先部署」然後 exit 0；之後每次都是「已經設好」。
3. `firebase deploy --only functions --non-interactive`：第一次部署時 CLI 會在「Functions 已部署」**之後**報
   `could not set up cleanup policy` 並回非 0（非互動模式不問天數）——`deploy.py` 認得這一句，接著再跑一次第 2 步
   （這次倉庫已經在了，確認題的預設是「是」，不需要 `--force`）。`--force` 除了設政策，還會刪掉程式碼裡沒有的 Functions，所以不用。
4. 其他錯誤的白話說明在 `lib/notify.py` 的 `DEPLOY_HINTS`（密碼沒放、Eventarc 權限還在開、線上有別的 Functions、不是 Blaze）。
`notify_setup.py --cloud`（唯讀）查：Blaze、Secret Manager 有沒有密碼版本（不讀內容）、七支 Functions 在不在同一區、
`gcf-artifacts` 的清理政策、`config/notify`、兩個心跳。

**規則不用改**：Functions 走管理身分；`config/notify`、`blog_notify_queue`、`ops/*` 的規則在 v1 就是「只有導師讀、網頁不寫」，
`notify_once` 沒有規則＝預設全拒（DATA-MODEL §2.18）。

**測試**（`python3 scripts/test_functions.py`；CI 的 `functions` job：ubuntu、Node 22、Java 21）：
- `tests/js/notify-pure.test.js`（`check.py` 三個平台都跑，零套件）：email 鍵共用向量、設定正規化、三道閘、live／dryrun 判斷、
  收件人篩選、信的內容（沒有正文與姓名）、遮信箱、名單包含關係、備份門檻、摘要內容、部署設定檔的形狀與樣板一致。
- `tests/functions/core.test.js`（Firestore 模擬器，直接呼叫 `core.js`、時間用注入的 `now()` 往後撥）：30 分鐘延遲、窗內下架／刪除／
  收起就取消、dryrun 不寄給家長、off 取消排隊、回填閘、逐人台帳冪等、寄失敗重試與放棄、兩輪同時掃、給導師的即時信、每日摘要、清舊資料。
  接著跑管理腳本：`notify_config.py` 的規矩（Functions 讀得懂它寫的設定）、`publish_site.py`、`publish_courses.py`。
- `tests/functions/triggers.test.js`（Firestore＋Functions 模擬器，真的 `functions/index.js`）：寫文件 → 對的那支觸發器被叫到、做對的事；
  off 時留言不寄、導師發文不排。
- **模擬器裡的郵差一律是假的**（`lib/mailer.js`：`FUNCTIONS_EMULATOR` 或 `FIRESTORE_EMULATOR_HOST` 存在就只寫進模擬器的
  `_emulator_outbox`）；模擬器裡也不掛 Secret Manager 的秘密（不去問雲端）。專案一律 `demo-cmw-fn`。

**只有真雲端才驗得到的**（作者沒有真雲端專案）：真的 Gmail SMTP 與應用程式密碼、學校帳號的管理政策、Eventarc 觸發的實際延遲與
「至少一次」重送、第一次部署的 API 啟用與權限傳播、清理政策那一段 CLI 行為（照 firebase-tools 15.31 原始碼寫的）、
Cloud Scheduler 的時區與實際觸發、Blaze 的帳單與預算警示、信進不進垃圾郵件。

---

## 11. 這套不做的事

- v1 不用 Cloud Storage、不部署 Cloud Functions、不蓋 custom claims（少一套服務就少一套權限要對齊、少一個要付費的方案：照片放 Firestore 的理由見 DATA-MODEL §3.1，身分一律由規則當場查名單判斷，見 DATA-MODEL §1）。
- 不用 Google Drive API（備份與原圖只寫進本機的雲端硬碟同步夾，由雲端硬碟程式自己上傳：不必申請任何憑證，老師在自己電腦上就看得到每一份檔案在哪）。
- 不收錄學生觀察與課程紀錄（用 teacher-records-kit，DATA-MODEL §2.21）。
- 不產生任何不用登入就能看的照片網址；影片不存檔，只存老師自選分享範圍的外部連結。
- 不存 HTML 正文；前端不用任何會解析 HTML 字串的 API。
- 不打包、不用前端框架、不需要 npm 就能跑前台。
- 不替老師安裝任何工具；只檢查、只給官方連結。
