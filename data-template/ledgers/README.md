# data/ledgers/

各種台帳：各個腳本自動寫入，**不要手改**（改壞了程式會把壞掉的檔改名成 `.corrupt-<時間>` 留著，再從頭記）。

| 檔 | 誰寫 | 記什麼 |
|---|---|---|
| `backup-state.json` | `backup.py` | 三條備份（資料庫、紀錄、部落格）最後一次**成功**的時間；失敗只記在 `last_fail`，所以 `status.py` 的提醒會一直叫到成功為止 |
| `media-ledger.jsonl` | `archive_media.py` | 課堂檔案歸檔的每一筆（只增不改）：歸檔了什麼、md5、老師在雲端硬碟刪掉了（墓碑，不重傳）、又救回來了 |
| `media-mirror.json`、`blog-mirror.json` | `backup.py` | 照片與部落格複製到雲端硬碟時，每個檔上次複製的 md5（只複製新的或改過的） |
| `access-sync.json` | `access_sync.py` | 名單最後一次同步成功的時間（`status.py` 拿名單檔的修改時間跟它比） |
| `alias-history.jsonl` | `access_sync.py` | 被移出名單的人的作者代號（資料退場時靠它找這個人寫過的留言） |
| `blog-posts.jsonl` | `publish_blog.py` | 導師替孩子發過哪些部落格草稿（同一份草稿不重發） |

- **會不會上雲**：不直接上雲；`backup.py records` 會把整個 `data/ledgers/` 一起包進紀錄備份。
