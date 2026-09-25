#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""thresholds.py — 「備份多久沒做要提醒」的門檻，唯一正本。

用到的地方（三邊同一套數字，不會一邊說正常、一邊說太久）：
  · scripts/status.py：代理每次開工先跑的狀態檢查
  · v1.1 通知信模組的每日摘要（functions/）：build_config.py 把這兩個數字寫進 functions/cmw.generated.json
v1 的備份都是手動（老師或代理說「備份」才跑），所以門檻以「天」計；不要改成小時級的門檻，
那會讓一週備份一次的班級每天被誤報。
"""

BACKUP_REMIND_DAYS = 7
BACKUP_URGENT_DAYS = 14
