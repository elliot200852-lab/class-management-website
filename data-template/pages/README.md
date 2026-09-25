# data/pages/

網站上的單頁：一頁一個 `<頁面代號>.md`，照片放同名資料夾。由 `scripts/publish_page.py <頁面代號>` 送上網站。

| 檔名 | 是什麼 | 寫法 |
|---|---|---|
| `about.md` | 關於我們 | 正文寫法同班級紀事 |
| `fun.md` | 專題活動 | 每個 `## 標題` 開一張卡片，下面的文字是卡片內容（≤ 300 字），卡片裡第一張 `![](照片)` 是卡片照片；第一個 `##` 之前的文字是開場白 |
| `home.md` | 首頁橫幅 | 檔頭 `banner:` 是橫幅那句話（≤ 200 字）、`banner_image:` 是橫幅照片的檔名 |
| 其他（例如 `trip-guide.md`） | 獨立單頁 | 正文寫法同班級紀事；網址 `<網站>/page.html?id=trip-guide` |

頁面代號：英文小寫開頭，只能用英文小寫、數字、連字號（最多 40 字）。

檔頭：`title`（必填，1–80 字）、`order`（整數，預設 0）、`visible`（預設 true）、`kind`（通常不用寫，照檔名判斷）。

發布：`python3 scripts/publish_page.py about`（預覽）→ 老師說好 → `--publish`；改內容：`--publish --update`。
