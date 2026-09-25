# data/parent-photos/

**家長合照**（選用）：在個人照相簿點開一位孩子時，跟孩子的照片並排的那一張。放上網站後**只有導師**看得到。

- **建議檔名只用座號**：`04.jpg`（原始檔名不會上網，但檔名會跟著這台電腦的備份走，不要寫名字）。
- 放好以後照 `playbooks/parent-photo.md` 做：
  `scripts/publish_parent_photo.py --seat 4 --from-file data/parent-photos/04.jpg`（先預覽，老師說好才 `--publish`）。
- 也可以不放檔案，直接從那位孩子部落格裡的某一篇文章挑一張（`--from-blog <文章編號>`）。
- **雲端只存稱謂、不存家長姓名**：稱謂預設是 `parent-roles.yaml` 裡那個座號寫的（母、父……）；照片裡只有其中幾位就用 `--who 母`。
- AI 助理不打開這裡的照片；照片對不對由老師看預覽檔確認。
