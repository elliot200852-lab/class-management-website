# 劇本：發私密紀事

老師會說：「發私密紀事」「這篇只給某幾位家長看」「誰看得到私密紀事」「那篇私密的下架」。

腳本：`scripts/publish_private.py`。母本在 `data/private-posts/<slug>.md`，照片在同名資料夾。只有「私密讀者」與導師看得到。
寫法說明：`data/private-posts/README.md`（跟班級紀事一樣，但沒有分類）。**兩段式**：預覽 → 老師說好才 `--publish`。

## 1. 代理要問什麼（一次一題）

1. 「這篇要寫什麼？標題？日期？」
2. 「這篇要給誰看？」——**收看名單是全網站共用的一份**（`contacts.csv` 的「私密讀者」欄），不是每篇各自設定。
   先跑 `python3 scripts/publish_private.py --viewers`（唯讀）告訴他目前有幾位；他要增減，先走 `sync-access.md`。
3. 「有照片嗎？」（放進同名資料夾；圖說他沒給就留空）

## 2. 老師去哪裡拿

- 收看名單：他自己在 `data/contacts.csv` 的「私密讀者」欄填「是」（你不要打開那個檔）。
- 內容若涉及個別孩子的狀況：提醒他想清楚名單上每一位都看得到。

## 3. 代理要做什麼

1. 寫 `data/private-posts/<slug>.md`（`title`、`date`，選填 `cover`、`excerpt`、`visible`）。
2. 預覽並打開給他看：`python3 scripts/publish_private.py <slug> --open`；念摘要，特別講「上線後誰看得到」那一行。
3. 他說好：「我接下來要把這篇私密紀事放上網站，只有私密名單上的 N 位和你看得到」，他點頭才跑：
   ```
   python3 scripts/publish_private.py <slug> --publish
   ```
4. 下架或改內容：改 md（下架＝`visible: false`），預覽，他同意後 `--publish --update`。

## 4. 怎麼驗證＋失敗怎麼辦

- 成功：「✓ 已上線……讀回比對一致」。私密讀者登入後，紀事列表會出現一張鎖頭卡。
- `--viewers` 顯示「導師不在名單裡」：跑 `sync-access.md`（名單同步會把導師補回去）。
- 預覽檔 `exports/preview/private-<slug>.html` 內容敏感：他看完可以刪。
- 其他錯誤同 `class-post.md` 第 4 段。
