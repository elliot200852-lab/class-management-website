#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""classcfg.py — 管理腳本讀 config/class.json（只讀、只取用得到的欄位）。

完整的設定檢查在 scripts/build_config.py；這裡只驗管理腳本一定要對的幾欄（專案 id、導師 email），
其他欄位缺了就用安全的預設值。讀不到檔 → ConfigError（白話說明怎麼補）。
"""
import re
import json

from . import paths
from .emailkey import email_key

PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{5,29}$")


class ConfigError(Exception):
    pass


class ClassConfig(object):
    def __init__(self, raw):
        self.raw = raw
        fb = raw.get("firebase") or {}
        teacher = raw.get("teacher") or {}
        self.project_id = str(fb.get("project_id") or "").strip()
        self.api_key = str(fb.get("api_key") or "").strip()
        self.app_id = str(fb.get("app_id") or "").strip()
        self.teacher_email = str(teacher.get("email") or "").strip()
        self.teacher_display_name = str(teacher.get("display_name") or "").strip()
        self.school_name = str(raw.get("school_name") or "").strip()
        students = raw.get("students") or {}
        self.students_count = students.get("count")
        self.calendar_ics_url = str(raw.get("calendar_ics_url") or "").strip()
        self.categories = [str(c) for c in (raw.get("categories") or []) if isinstance(c, str)]
        self.region = str(raw.get("region") or "").strip()
        self.class_name = str(raw.get("class_name") or "").strip()
        ad = str(fb.get("auth_domain") or "").strip().lower()
        self.auth_domain = ad or ("%s.firebaseapp.com" % self.project_id if self.project_id else "")
        self.site_url = ("https://%s" % self.auth_domain) if self.auth_domain else ""

    @property
    def teacher_key(self):
        return email_key(self.teacher_email)


def load(required=True):
    """讀 config/class.json（ROOT 底下）。required=False 時找不到回 None。"""
    p = paths.rpath("config", "class.json")
    if not p.exists():
        if not required:
            return None
        raise ConfigError("找不到 config/class.json（這個班的設定）。\n"
                          "  → 還沒裝好的話，照 AGENTS.md 的安裝步驟 3 建立它（從 config/class.example.json 複製）。")
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ConfigError("config/class.json 讀不懂（%s）。\n  → 先跑 python3 scripts/build_config.py --check 看哪裡錯。"
                          % type(e).__name__)
    cfg = ClassConfig(raw)
    problems = []
    if not PROJECT_ID_RE.match(cfg.project_id) or cfg.project_id.startswith("your-"):
        problems.append("firebase.project_id 還沒填好（或格式不對）")
    try:
        cfg.teacher_key
    except ValueError:
        problems.append("teacher.email 不是合法的信箱")
    if problems:
        raise ConfigError("config/class.json 還不能用：%s。\n  → 先跑 python3 scripts/build_config.py --check，照它說的補。"
                          % "；".join(problems))
    return cfg
