# data/inbox/

待處理素材的暫存收件匣：上課拍的照片、影片、錄音、講義，等著被歸檔。

- **誰放**：老師手動丟進來（手機用 AirDrop、LINE 傳到電腦後存到這裡；`python3 scripts/where.py --open inbox` 直接打開）。
- **課程歸檔**：`python3 scripts/archive_media.py`（`playbooks/archive-media.md`）把這裡的檔依課程單元與日期改名
  （`YYYYMMDD-單元-類型-說明.副檔名`），複製到雲端硬碟 `01_機密（只有導師）/課堂檔案/<學年>/<單元>/`，
  **讀回來比對 md5 對得上、記進台帳之後**，才把這裡的原檔移到系統垃圾桶（反悔還拿得回來）。
  放不進垃圾桶時會搬到 `data/inbox/.archived/`，請老師確認雲端硬碟上有了再自己清。
- **處理完應該是空的**：`python3 scripts/status.py` 會提醒這裡有幾個檔在等。
- **會不會上雲**：這個資料夾本身不會；歸檔後的那一份在雲端硬碟（只有導師看得到，不分享給任何人）。
