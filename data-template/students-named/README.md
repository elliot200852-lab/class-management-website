# data/students-named/

保留給「非放不可、而且會直接寫出學生真實姓名」的檔案用（目前的三個核心名冊檔
`roster.csv`、`contacts.csv`、`parent-roles.yaml` 已經直接放在 `data/` 底下，
不需要放進這裡；這個目錄是給以後萬一需要的其他含名檔案多一層保護用的）。

- **AI 代理讀不到這個目錄**：`.claude/settings.json`、`.geminiignore`、`.aiexclude`
  都把 `data/students-named/**` 列進拒讀清單，跟 `roster.csv`、`contacts.csv` 一樣，
  作為額外的安全網——代理的工作目錄本來就是老師的個資目錄，這是刻意的第二道防線。
- 目前是空的（P1 骨架階段），沒有任何腳本會寫進這裡。
