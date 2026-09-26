# Changelog

本專案版本遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)（開發中的版本號帶 `-dev` 後綴）。

## [0.1.1] - 2026-09-26

結案後第一次完整審查（兩支獨立審查者：計畫書對照 repo、對抗式程式碼審查）抓到的問題。規則與前端本體沒有越權讀取；
以下修的是規則之外的信任假設、還原語意、配額與文件。

### 安全與權限

- **信箱連結登入改成唯讀**：Firebase 的信箱連結登入與密碼登入在 token 裡都是 `password`，規則分不出來；
  而開「電子郵件/密碼」provider 等於開放任何人用還沒登入過的家長信箱預先註冊、再誘使家長點驗證信。
  現在私密紀事、留言、已讀回條、「我的孩子」全部要求 Google 登入；信箱連結只能看公開紀事與相簿，畫面會說明。
  安裝步驟把信箱連結改成選用並寫明風險；`doctor.py --cloud` 沒開信箱連結不再算失敗（開了密碼卻沒開連結才算）。
- **整庫還原不再復活已撤的權限與已下架的內容**：`backup.py restore firestore` 預設不寫 `allowlist`、`private_allowlist`、
  `parent_child_map`（名單改跑 `access_sync.py`；整庫清空要重建作者代號才加 `--include-lists`）；快照早於資料退場或學年封存、
  又碰到那些人的資料就停（`--include-exited` 才放行）；覆蓋既有文件時保留現在的 `visible`／`status`（`--restore-visibility` 才蓋回）。
  新增退場台帳 `data/ledgers/data-exit.jsonl`（只存座號與雜湊）。
- 共用電腦：登入畫面加「這是共用電腦」（只保留到關掉分頁、不留本機快取）；導師帳號一律只保留到關掉分頁；
  快取裡的照片只在主文件從伺服器讀成功後才顯示。
- 部落格文章的 `date` 綁 postId 前 10 碼；留言卡顯示作者代號前 4 碼，同名署名分得出來；前端判定 Google 登入改讀
  token 的 `sign_in_provider`，與規則同源。
- Hosting 加 `Content-Security-Policy: frame-ancestors 'self'` 與 `X-Frame-Options: SAMEORIGIN`。

### 配額與對帳

- `backup.py firestore` 備份完對帳孤兒照片（沒有文章、或不在文章清單裡的 `thumbs`／`images`），統計進 `status.py`；
  `data_exit.py parent` 一併刪掉該座號的孤兒照片；DATA-MODEL §1.6 改成實況，`playbooks/data-exit.md` 補「單一帳號灌滿配額」的處置。
- `data_exit.py` 刪同步夾不再 `ignore_errors`：逐項刪、讀回確認，刪不掉的列出來並 exit 1。

### CI 與代理

- workflow 最小權限（`contents: read`；Pages 寫入只給 deploy job）；`setup-chrome` 釘 commit SHA；
  官方 actions 升到目前主版本；`ubuntu-latest` 改 `ubuntu-24.04`。
- 三處代理禁讀清單補 `data/records/**`、`data/ledgers/alias-history.jsonl`；`.claude/settings.json` 另擋常見終端機讀檔指令；
  AGENTS 鐵則 5 改寫成「盡力而為的防呆，不是安全邊界」。

### 文件

- DATA-MODEL 權限表把「未登入」與「登入但不在名單」分成兩欄；§5.1 寫明信箱連結每日 5 封可被外人耗盡、App Check 尚未內建；
  §7 刪 Auth 帳號定案為主控台手動。ARCHITECTURE 拿掉施工期的 P1／P4 標記，§3.4／§8.5 記錄快取模式的取捨。
  `data-template/students-named/README.md` 與總表一致（`parent-roles.yaml` 不含真名）。

## [0.1.0] - 2026-09-26

第一個公開版本。以下依開發順序記錄；v1 核心、v1.1 選配與安裝說明全部包含在內。

### 新增與修正（照文件實走安裝抓到的問題）

- **先試玩**：`scripts/try_emulator.py`＋`playbooks/try.md`（README、AGENTS.md 步驟 0 之前有入口）。在這台電腦上開一個
  虛構班級的網站（Firestore＋Auth 模擬器、本機網站；內容跟示範站同一份、名單用真的 `access_sync.py`／`open_blogs.py` 寫），
  不用任何帳號、不碰雲端；模擬器工具只下載到 `tests/rules/node_modules/`（版本釘死、要 `--download` 同意），不做任何全域安裝。
  試玩環境裡其他腳本加 `--root try --emulator`；Ctrl-C 收掉一切。
- 腳本在模擬器／`--root` 下印的「再跑：…」原樣帶回 `--root`、`--emulator`（`lib/paths.rerun_flags`）。
- 學年封存旗標：`data_exit.py year-end` 撤權限前立旗標；`status.py` 最先警告、`access_sync.py --apply` 要多加 `--new-roster`。
- 資料退場：每次預覽把要刪的登入帳號完整信箱寫進只給老師開的 `data/exports/data-exit/…-auth-cleanup.txt`（聯集保留），
  劇本改成先預覽、再刪名單列；`exports/**`、`data/exports/**` 加進三處禁讀清單。
- `status.py`：安裝做到一半只說做到第幾步；`drive_init.py`：安裝中的下一步指回 AGENTS.md。
- `where.py --open` 收這個資料夾裡的路徑（打開資料夾與檔案的唯一寫法，三種 Windows 終端機都通）。
- `doctor.py`：必要項 ✗ 時 exit 1；Windows 的 Python 說明改成 Python install manager。
- `parent_note.py`：草稿檔名的座號跟 `--seat` 不同就停；`backup.py`：還原的「要反悔」改印預覽指令並提醒新建的文件要另外下架、
  備份失敗時不再說「備份本身不受影響」；`publish_poems.py`：rights 空白時不給上線指令；`smoke_emulator.py`：
  Firebase 程式庫從 gstatic 載不下來時印白話原因、不丟 traceback；`build_config.py` 的 JSON 錯誤提示點名彎引號。
- 文件：build_config 產生四個檔、home 頁也要 `title`、`deploy.py --only` 含 `functions`、npm 的黃字 warn 可以不理、
  全新 Mac 跑 `python3 --version` 會跳「安裝開發者工具」、範本的 `example.com` 信箱一定要換掉。

### 新增（v1.1 後端：選配通知信模組與其他管理腳本）

- `functions/`（選配、預設不部署、要 Blaze）：新留言與家長發文即時寄導師；導師發文／回覆排進佇列，30 分鐘後逐位寄給那個座號的家長
  （窗內下架、刪除、收起就取消）；每 10 分鐘掃佇列；每日摘要＋看門狗（名單包含關係、備份心跳、通知線健康）。回填閘、逐人台帳、
  租約、dryrun 洩壓閥。信裡只有座號、標題、連結。
- `scripts/notify_setup.py`（安裝檢查表，唯讀）、`scripts/notify_config.py`（開關 off／dryrun／live，只准先 dryrun 再 live）、
  `deploy.py` 第 4 步 `functions`（沒開模組就略過；第一次部署自動補設映像檔清理政策，不加 `--force`）。
- `scripts/test_functions.py`（Firestore＋Functions 模擬器、假的郵差）與 CI 的 `functions` job（ubuntu、Node 22、Java 21）；
  `check.py --functions`。
- `scripts/docs_index.py`：同步夾「班級文件」的 `index.md`（類別欄人工改過的保留；螢幕上不印檔名）。
- `scripts/publish_site.py`：導師專用頁兩個入口網址（`roster/links`；文件早就寫了、程式之前沒有）。
- `scripts/publish_courses.py`：課程頁（課程介紹、影片、各科課程大綱卡）與課表（文件早就寫了、程式之前沒有）。
- `scripts/parent_note.py`：家長通知信只用預設郵件程式打開、由老師自己按傳送（不接任何寄信服務；代理看不到姓名與信箱）。
- 劇本：`notify.md`、`class-docs.md`、`courses.md`、`subject-syllabus.md`、`parent-note.md`。
- `config/class.json` 新增 `school_year`（`start_month` 學年從幾月開始、`terms` 學期名稱；依學校，預設 8 月＋上學期／下學期）：
  雲端硬碟的學年／學期資料夾、班級文件索引的「學期」欄、課堂檔案與部落格歸檔的學年都照它算。
  選填的 `term_aliases`（預設空）讓班級文件索引認得老師自己用別的叫法建的學期資料夾。
- 課程資料以「課程單元」為單位（`data/units/`、`templates/unit/`）；雲端硬碟的班級文件分成通用的幾格；
  預設紀事分類用中性用語；網站色票與字型、登入畫面與頁尾文字定稿。

### 修正（v1 收尾）

- `doctor.py`：git 改成選用；認得 Antigravity CLI（`agy`）；找不到代理的終端機指令不算失敗（桌面版代理）；`--cloud` 檢查
  Firestore 版本（只接受 Standard，Enterprise 要重建）。
- `deploy.py`：新專案沒有預設 Hosting 網站時，說明要到主控台按「開始使用」（不要 `hosting:sites:create`）。
- `build_config.py`：`config/class.json` 用 `utf-8-sig` 讀（Windows 記事本存的 BOM），與管理腳本一致。
- 系統垃圾桶：Linux 改用 freedesktop 規格（`~/.local/share/Trash` 的 files＋info）；測試一律用假的 HOME
  （Windows 用 `CMW_TRASH_DIR`），不碰真的垃圾桶。修掉 CI 在 ubuntu 上資料退場整合測試的紅燈。
- 備份門檻的正本移到 `scripts/lib/thresholds.py`（`status.py`、每日摘要、導師專用頁同一組）。
- 文件：Windows 指令一律 `py -3` 加正斜線；`AGENTS.md` 日常劇本表補齊、禁讀清單寫明 `data/backups/**`。

## [0.1.0-dev] - 2026-09-25

### 新增（P1：骨架）

- `LICENSE`（MIT）、`VERSION`、`CHANGELOG.md`、`README.md` 骨架。
- `config/class.example.json` 與 `config/README.md`：班級設定範本與逐欄說明。
- `scripts/lib/`：`paths.py`（repo 根與 `data/` 定位）、`seats.py`（座號唯一標準寫法）、
  `hostos.py`（精簡版平台差異判斷）。
- `scripts/build_config.py`：讀 `config/class.json`、驗證、渲染 `templates/*.tmpl` 到
  `site/js/site-config.js`、`.firebaserc`（`--check`、`--allow-placeholders`）。
- `scripts/doctor.py`：健檢 Python／git／Node.js／Firebase CLI／Google 雲端硬碟桌面版／
  AI 代理 CLI，只提示官方下載頁，不代裝任何東西。
- `scripts/privacy_scan.py`：公開版通用隱私掃描器（自走檔案樹、只印路徑與類別、不印命中字串）。
- `scripts/init_data.py`：把 `data-template/` 複製成 `data/`（不覆蓋既有檔），
  並提醒 repo 路徑是否落在 iCloud／OneDrive 同步範圍。
- `scripts/status.py`：代理每次開工前要跑的狀態檢查（P1 先是 stub）。
- `scripts/check.py`：一行本機跑完 unittest ＋ privacy_scan（Mac／Windows 通用，CI 也呼叫同一支）。
- `data-template/`：空白資料框架（有進 git），每個子目錄一份 `README.md` 說明放什麼、誰寫、會不會上雲。
- 代理入口：`AGENTS.md`（鐵則＋安裝步驟標題）、`CLAUDE.md`、`GEMINI.md`、
  `.github/copilot-instructions.md`、`.cursor/rules/agents.mdc`（皆指回 `AGENTS.md`）。
- 代理讀取限制：`.claude/settings.json`、`.geminiignore`、`.aiexclude`。
- `tests/`：build_config、privacy_scan、seats、init_data、doctor 的 unittest。
- `.github/workflows/ci.yml`：push／pull_request／workflow_dispatch 都跑
  ubuntu／macos／windows × Python 3.9／3.12 完整矩陣。
