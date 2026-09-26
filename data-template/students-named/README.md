# data/students-named/

保留給「非放不可、而且會直接寫出學生真實姓名」的檔案用。含真名的核心檔已經直接放在 `data/` 底下，
不需要放進這裡：名冊 `roster.csv`、家長名單 `contacts.csv`，以及網站資料庫的本機備份 `backups/`、
teacher-records-kit 的紀錄 `records/`（對照 `data-template/README.md` 的總表）。`parent-roles.yaml` 只有座號與稱謂、
不含真名。這個目錄是給以後萬一需要的其他含名檔案多一層保護用的。

- **AI 代理的禁讀清單列了這個目錄**：`.claude/settings.json`、`.geminiignore`、`.aiexclude`
  都把 `data/students-named/**` 列進去，跟 `roster.csv`、`contacts.csv` 一樣。這是盡力而為的防呆，不是安全邊界
  （換個指令或寫段程式照樣讀得到），真正的規矩是 `AGENTS.md` 鐵則 5：代理不打開這些檔。
- 目前是空的，沒有任何腳本會寫進這裡。
