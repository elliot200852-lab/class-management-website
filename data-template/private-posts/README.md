# data/private-posts/

私密紀事：只有「私密讀者」（`data/contacts.csv` 的「私密讀者」欄填「是」的人）與導師看得到。
寫法跟班級紀事一樣：`<slug>.md` ＋同名資料夾放照片，但檔頭**沒有** `category`
（有 `title`、`date`、`cover`、`excerpt`、`visible`）。

- **收看名單**不在這裡改：改 `data/contacts.csv` 的「私密讀者」欄，再跑 `scripts/access_sync.py`。
  `python3 scripts/publish_private.py --viewers` 只數一下目前有幾位（唯讀）。
- 發布：`python3 scripts/publish_private.py <slug>`（預覽）→ 老師說好 → `--publish`；下架：檔頭 `visible: false` 後 `--publish --update`。
- 這裡的內容通常比較敏感：預覽檔在 `exports/preview/`，看完可以刪。
