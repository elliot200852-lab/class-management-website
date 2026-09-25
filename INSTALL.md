# INSTALL.md — 不靠 AI 的安裝步驟（純指令版）

給會開終端機、看得懂錯誤訊息、想自己一步一步裝的人。流程和 `AGENTS.md` 完全相同（順序、檢查點都一樣），
這裡只留指令與要點；每一步的常見失敗與處理方式寫在 `AGENTS.md` 對應的步驟裡。

- **Mac** 的指令在「終端機」裡打（zsh／bash）。
- **Windows** 的指令在「**命令提示字元**」（`cmd`）裡打。PowerShell 預設會擋掉 npm、firebase 的指令碼，安裝與登入請用 `cmd`。
- 所有指令都在這個資料夾的最上層（有 `AGENTS.md` 的那一層）執行。
- 會寫進網站的腳本都是兩段式：不加旗標只預覽；確認後才加 `--apply`／`--publish`（部署是 `--yes`）。

---

## 0. 放對位置

把資料夾放在不會被 iCloud、OneDrive、Google 雲端硬碟自動同步的地方（例如 Mac 的 `~/class-management-website`、
Windows 的 `C:\Users\<你>\class-management-website`）。之後 `data/` 裡會有學生名單。

取得方式二選一：

```
git clone https://github.com/elliot200852-lab/class-management-website.git
```

或在 <https://github.com/elliot200852-lab/class-management-website> 按 **Code → Download ZIP** 後解壓縮。

## 1. 裝工具（全部從官方來源，自己裝）

| 工具 | Mac | Windows | 驗證 |
|---|---|---|---|
| Python 3.9+ | <https://www.python.org/downloads/> 的 `.pkg`；**裝完雙擊 `/Applications/Python 3.x/Install Certificates.command`** | 同一頁的「Python install manager」 | Mac `python3 --version`；Win `py -3 --version` |
| git（選用，ZIP 下載可略） | `xcode-select --install` | <https://git-scm.com/install/windows> | `git --version` |
| Node.js LTS | <https://nodejs.org/en/download> 的 macOS Installer (.pkg) | 同一頁的 Windows Installer (.msi) | `node --version` |
| Firebase CLI | `npm install -g firebase-tools`（EACCES 時加 `sudo`） | `npm install -g firebase-tools`（開新的 `cmd`） | `firebase --version` |
| Google Cloud CLI | <https://cloud.google.com/sdk/docs/install> 的 macOS 壓縮檔（Apple 晶片 `darwin-arm`、Intel `darwin-x86_64`；`uname -m` 可查），解壓到家目錄後 `~/google-cloud-sdk/install.sh` | 同一頁的 `GoogleCloudSDKInstaller.exe` | `gcloud --version` |
| Pillow（處理照片） | `python3 -m pip install --user Pillow` | `py -3 -m pip install --user Pillow` | 見下方 `doctor.py` |
| Google 雲端硬碟電腦版（選用，備份用） | <https://www.google.com/drive/download/> | 同左 | 見下方 `doctor.py` |

裝完**關掉所有終端機再開新的**（PATH 才會更新），然後健檢：

```
python3 scripts/doctor.py          （Mac）
py -3 scripts/doctor.py            （Windows）
```

必要項（Python、Node.js、Firebase CLI、Google Cloud CLI）要全部 ✓。git、Pillow、雲端硬碟、「AI 代理（終端機版）」是選用（！），
用 ZIP 下載、不用 AI 或用代理桌面版的都可以不管。

以下指令一律寫成 Mac 的 `python3`；**Windows 把 `python3` 換成 `py -3`**，其餘照打（`/` 在 `cmd` 裡也能用）。

## 2. Firebase 專案（在 <https://console.firebase.google.com>）

用你要拿來管理網站的 Google 帳號（之後的 `teacher.email`、`gcloud`、`firebase` 登入全部要是同一個）。

1. 建立專案。專案 ID 會變成網址 `https://<專案 ID>.firebaseapp.com`，建好不能改；不要放校名與孩子的名字。
   Gemini、Google Analytics 可以關。
2. Firestore（Databases & Storage → Firestore）→ 建立資料庫：**Standard 版**、ID `(default)`、位置 `asia-east1`（或你要的地區，
   建好不能改）、**正式版模式（Production mode）**。
3. Authentication（Security → Authentication）→ 開始使用 → 登入方式：啟用 **Google**（支援信箱選你自己）；啟用
   **電子郵件/密碼**，並打開 **電子郵件連結（無密碼登入）**。
4. Hosting（Hosting & Serverless → Hosting）→ 開始使用 → 一路下一步到「前往主控台」。畫面上的指令**不要照打**
   （尤其不要 `firebase init`，會蓋掉這個專案的 `firebase.json`）。
5. 專案總覽 → `</>` 新增網頁應用程式（不用勾 Hosting）→ 記下 `firebaseConfig` 的 `projectId`、`apiKey`、`appId`、`messagingSenderId`。
6. 方案維持 **Spark（免費）**。

## 3. 班級設定

```
cp config/class.example.json config/class.json          （Mac）
copy config\class.example.json config\class.json        （Windows）
```

照 `config/README.md` 逐欄填：`class_name`（公開）、`teacher.email`、`teacher.display_name`、`school_name`、`students.count`、
`region`（＝第 2 步選的位置）、`firebase.project_id`／`api_key`／`app_id`／`messaging_sender_id`（`auth_domain` 留 `""`）、
`pages`、`categories`、`calendar_ics_url`（只收**公開**日曆的 iCal 網址，或留 `""`）、
`school_year`（學年從幾月開始、分哪幾個學期；依學校，預設 8 月＋上學期／下學期）。

- 用純文字編輯器存成 **UTF-8、不加 BOM**。Windows 的「記事本」預設就是；Mac 的「文字編輯」請先關掉「編輯 → 替代 → 智慧型引號」，
  否則 `"` 會被換成彎引號。

```
python3 scripts/build_config.py --check
```

## 4. 產生網站設定與安全規則

```
python3 scripts/build_config.py
python3 scripts/build_indexes.py --check
```

產生四個檔：`site/js/site-config.js`、`.firebaserc`、`firestore.rules`、`functions/cmw.generated.json`（通知信模組的設定；
沒開通知信也會產生，用不到而已，無害）。都不進 git、不要手改；改設定就改 `config/class.json` 再重跑。

## 5. 雲端硬碟裡的班級資料夾（選用）

雲端硬碟電腦版要先登入。旗標以 `--help` 為準：

```
python3 scripts/drive_init.py                     （列出找得到的同步夾，唯讀）
python3 scripts/drive_init.py --pick 1 --apply    （選第 1 個：寫進 config/class.json 並建資料夾樹）
python3 scripts/drive_init.py --path "<同步夾路徑>" --apply   （自動找不到時自己給路徑）
python3 scripts/drive_init.py --check
```

備份、歸檔、資料退場都只認這棵樹；找不到就停，不會自己另建。

## 6. 兩次登入＋部署

兩個工具各要登入一次，**都用 `teacher.email` 那個帳號**（腳本用 gcloud 寫資料庫，部署用 firebase CLI）：

```
gcloud auth login
firebase login
```

確認帳號，再做雲端健檢（唯讀）：

```
gcloud auth list
firebase login:list
python3 scripts/doctor.py --cloud
```

「部署前」的項目要全部 ✓。然後：

```
python3 scripts/deploy.py            （只印計畫）
python3 scripts/deploy.py --yes      （規則 → 索引〔等全部建好，最多 20 分鐘〕→ 網站 → 檢查）
```

任何一步都可以單獨重跑：`python3 scripts/deploy.py --only <步驟> --yes`，`<步驟>` 是 check、build、rules、indexes、functions、hosting、verify
其中一個（functions 是選配的通知信模組，沒開就略過）。
不要用 `firebase deploy` 直接部署，也不要加 `--force`。

hosting 那一步出現 `there is no Hosting site`（新專案不一定有預設網站）：回主控台做第 2 步第 4 點，再跑 `--only hosting --yes`。
不要用 `firebase hosting:sites:create`（會另建一個名字不同的網站，網址就不是 `<專案 ID>.firebaseapp.com`）。

## 7. 名冊與家長名單 → 寫進網站 → 開部落格

```
python3 scripts/init_data.py
```

用 Excel／Numbers 填（存成 **CSV UTF-8**，第一列表頭不要改）：

- `data/roster.csv`：`座號,姓名,稱呼,備註`（稱呼＝家長看到的孩子名字，只放名，1–10 字）
- `data/contacts.csv`：`座號,關係,姓名,Email,私密讀者,暫停,備註`（一列一個「人 × 座號」；同事的關係填 `同仁`、座號可空；
  導師不用寫，程式會自動加入）

`data/parent-roles.yaml`：每個座號「應該有帳號」的家長稱謂（安全閘的下限；還沒給信箱的先不要寫）：

```yaml
"01": [母, 父]
"02": [母]
```

```
python3 scripts/access_sync.py             （預覽）
python3 scripts/access_sync.py --apply
python3 scripts/open_blogs.py              （預覽）
python3 scripts/open_blogs.py --apply
python3 scripts/access_sync.py --check
python3 scripts/doctor.py --cloud          （這次應該全部 ✓）
```

名單改了就再跑 `access_sync.py`（一次移除超過 3 人會擋下來，確認後加 `--max-deletes N`）。

## 8. 真機試跑

1. 用第二個 Google 帳號當測試家長：加進 `contacts.csv`（座號 1、關係 `測試`）→ `access_sync.py --apply`。
2. 手機 LINE 點網址 → 改用手機瀏覽器開 → Google 登入。
3. 發一篇測試紀事（寫法見 `data/class-posts/README.md`）：

   ```
   python3 scripts/publish_post.py <slug> --open
   python3 scripts/publish_post.py <slug> --publish
   ```

4. 小相簿（`data/albums/<slug>.md`＋同名資料夾）：`publish_album.py <slug>` → `--publish`。
5. 替 1 號發部落格（`data/blog-drafts/01/<草稿名>.md`）：`publish_blog.py --seat 1 <草稿名>` → `--publish`。
6. 手機上看紀事、相簿、「我的孩子」，留言；電腦上用導師帳號看留言後台與「我的孩子」全班格。
7. 收尾：測試內容的 md 改 `visible: false` 後 `--publish --update`；部落格測試文在網頁上下架；刪掉 `contacts.csv` 的測試列再同步。

## 9. 備份

要先做第 5 步。旗標以 `--help` 為準：

```
python3 scripts/backup.py all      （網站資料庫 → 學生部落格 → 本機 data/，寫進雲端硬碟同步夾）
python3 scripts/backup.py list
python3 scripts/status.py          （每次開始先跑：備份幾天沒成功、名單待同步、容量）
```

還原：`python3 scripts/backup.py restore firestore …` 或 `python3 scripts/backup.py restore records …`
（預設只預覽，見 `playbooks/restore.md`）。

## 10. 之後

- 日常操作：`playbooks/` 每個動作一份劇本（先預覽、再上線）。
- 每次開始先跑 `python3 scripts/status.py`。
- 升級：`git pull`（或下載新 ZIP，把舊資料夾的 `data/`、`config/class.json`、`setup/progress.json` 複製過去），然後
  `doctor.py` → `init_data.py` → `build_config.py` → `build_indexes.py --check` → `deploy.py --yes` → `doctor.py --cloud`。
  先讀 `CHANGELOG.md`。
- 有裝通知信模組的，升級時 `deploy.py --yes` 會連 Functions 一起部署；先跑 `notify_setup.py`，它說要重裝套件就照它印的 `npm ci` 打一次。
- 免費方案的額度、升 Blaze、沒有 Google 帳號的家長、導師專用頁的兩個入口網址：見 `AGENTS.md` 最後幾節。

## 選配：通知信模組（要 Blaze）

完整說明（費用、寄件帳號、預演、移除）在 `playbooks/notify.md`。指令順序：

```
（config/class.json：notifications.enabled 改 true，填 gmail_address／sender_name／signature／digest_hour）
python3 scripts/build_config.py
python3 scripts/notify_setup.py                         （本機檢查表，照「下一步」做）
npm ci --prefix "<這個資料夾>/functions"                  （裝 Functions 的套件；版本照 package-lock.json）
firebase functions:secrets:set CMW_GMAIL_APP_PASSWORD --project <專案 ID>   （貼 Gmail 應用程式密碼）
python3 scripts/notify_setup.py --cloud                 （Blaze、密碼有沒有放）
python3 scripts/deploy.py --only functions --yes        （第一次會自動補設映像檔清理政策；不要加 --force）
python3 scripts/notify_config.py --phase dryrun --apply （預演：給家長的信只記錄不寄）
python3 scripts/notify_config.py --phase live --apply   （預演一兩天沒問題之後）
python3 scripts/notify_config.py --phase off --apply    （隨時煞車）
```
