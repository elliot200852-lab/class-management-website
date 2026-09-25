# data/backups/

網站資料庫的本機快照，由 `scripts/backup.py` 自動產生（`playbooks/backup.md`）。**不要手動放檔案進來。**

```
data/backups/
  firestore/<日期時間>/        一份快照：documents.jsonl（照片以外的全部文件）、photos.jsonl、manifest.json
  firestore/photos/            照片池：每一份照片文件一個檔，只增不減（資料退場時才照路徑精準刪）
  .lock                        備份或歸檔正在跑時才有；跑完自動刪
```

- **含真名**：快照裡有網站上的全部資料（名冊、留言、名單），等同名冊等級的機密。
- **會不會上雲**：會。`backup.py` 每次都把快照與新照片複製到 Google 雲端硬碟同步夾的 `05_全站備份/firestore/`，
  逐檔比對 md5；雲端硬碟程式再自己上傳。本機保留最近 30 份（`--keep` 可以改），只刪這個工具自己建的快照。
- 還原：`python3 scripts/backup.py restore firestore`（預設只預覽，清單寫在 `data/exports/restore-plan-<日期時間>.txt`；`playbooks/restore.md`）。
- **AI 代理讀不到這個資料夾**（`.claude/settings.json`、`.geminiignore`、`.aiexclude` 擋住）：快照裡有全名與信箱。代理只需要跑腳本、看腳本的輸出。
