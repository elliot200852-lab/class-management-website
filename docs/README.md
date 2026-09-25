# docs/ — 給開發者與 AI 代理的設計文件

老師不必讀這個資料夾；安裝與日常操作看 repo 根目錄的 `AGENTS.md`。

| 文件 | 內容 | 誰要照著做 |
|---|---|---|
| `DATA-MODEL.md` | v1 用哪些服務（只有 Firestore、Auth、Hosting，Spark 免費方案）、角色、email 鍵正規化、每個 Firestore 集合的路徑／doc id／欄位白名單／大小上限／「讀／建／改／刪 × 角色」權限表、照片文件的壓縮參數、安全規則完整骨架、查詢形狀登記表與索引、容量與費用、資料退場 | 寫安全規則、規則測試、前端資料層、管理腳本的人 |
| `ARCHITECTURE.md` | 目錄與分層、Store 通用介面（真站與示範模式）、頁面與登入閘、結構化正文區塊與渲染規則、發文與照片處理流程、管理端寫入、設定產生與部署順序、`doctor.py --cloud`、測試四層、v1.1 通知信模組 | 寫前台、腳本、部署流程的人 |

兩份衝突時以 `DATA-MODEL.md` 為準。改集合、欄位、權限或查詢：先改 `DATA-MODEL.md`（查詢改
`templates/queries.json` 再跑 `python3 scripts/build_indexes.py`），再改程式、規則與規則測試，放在同一個 commit。
