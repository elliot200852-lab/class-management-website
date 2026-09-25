#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_seating.py — 座位表：導師專用頁的「座位表」分頁（docs/DATA-MODEL.md §2.18；只有導師看得到）。

  來源：data/seating/<方案代號>.json，一個方案一個檔（寫法見 data/seating/README.md）
        方案代號＝檔名：YYYY-MM-DD（這一天起用）；同一天排了好幾種就 YYYY-MM-DD-2、YYYY-MM-DD-3……
  寫到：seating/<方案代號>

  JSON 只放座號、不放名字（網站用名冊裡的「稱呼」當場補上名字）：
    {
      "title": "十月的座位",
      "date": "2026-10-01",               （可省略；省略＝檔名的日期）
      "note": "一段給自己看的備註",        （可省略）
      "rows": [                            第一排＝最靠黑板；每一排由左到右（學生面向黑板時的左右）
        ["01", "02", "-", "03", "04"],     "-"＝走道（不畫桌子）
        ["05", "",   "-", "07", "08"]      ""＝空位（畫一張空桌子）
      ]
    }
  座號一律寫成兩位數字的文字（"01"–"40"）；名冊（data/roster.csv）裡沒有的座號會被擋下來。

用法：
  python3 scripts/publish_seating.py                        # 預覽 data/seating/ 裡的全部方案
  python3 scripts/publish_seating.py 2026-10-01             # 只預覽這一個方案
  python3 scripts/publish_seating.py 2026-10-01 --publish   # 上線（網站上已經有、內容不一樣的要多加 --update）
  python3 scripts/publish_seating.py --publish              # 全部上線（一樣的會略過）
  python3 scripts/publish_seating.py --remove 2026-09-01             # 看網站上有沒有這個方案
  python3 scripts/publish_seating.py --remove 2026-09-01 --publish   # 從網站拿掉（本機的 json 不動）
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths, classcfg, schema  # noqa: E402
from lib import preview as pv  # noqa: E402
from lib import publishing as pub  # noqa: E402
from lib import multipub as mp  # noqa: E402
from lib.firestore_rest import SERVER_TIME  # noqa: E402
from lib.hostos import PY  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

ALLOWED = ("title", "date", "note", "rows")
AISLE = schema.SEAT_AISLE

PREVIEW_CSS = """
.seat-plan{margin:18px 0 30px}.board{margin:0 auto 10px;max-width:320px;text-align:center;background:#2e3a33;color:#eef2ea;
border-radius:4px;padding:4px 0;letter-spacing:.4em;font-size:.85em}
.seat-grid{display:grid;gap:6px;max-width:100%;overflow-x:auto}
.cell{border:2px solid #a03a5a;border-radius:6px;padding:4px;text-align:center;font-size:.85em;line-height:1.3;min-width:0}
.cell b{display:block;font-size:.8em;color:#a03a5a}.cell.empty{border-style:dashed;border-color:#bbb;color:#999}
.cell.aisle{border:0}
"""


def plan_dir():
    return paths.data_dir() / "seating"


def list_plan_files():
    d = plan_dir()
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".json" and not p.name.startswith("."))


def cell_problem(v, r, c):
    """一格的問題（沒問題回 None）。**不印格子裡的字**：老師可能把名字寫進來了，輸出會進代理的對話紀錄。"""
    where = "第 %d 排第 %d 格" % (r, c)
    if isinstance(v, str):
        if v in ("", AISLE) or schema.SEAT_RE.match(v):
            return None
        t = v.strip()
        if t.isdigit() and len(t) <= 2 and 1 <= int(t) <= 40:
            return "%s：座號要寫成兩位數字，例如 \"%02d\"" % (where, int(t))
        return "%s：只能是座號（\"01\"–\"40\"）、空位（\"\"）或走道（\"-\"）；名字不要寫在這裡（網站會自己補上稱呼）" % where
    if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 40:
        return "%s：座號要寫成兩位數字的文字（前後加引號），例如 \"%02d\"" % (where, v)
    return "%s：只能是座號（\"01\"）、空位（\"\"）或走道（\"-\"）" % where


def load_plan(path, roster):
    """一個方案檔 → (方案代號, 文件, 提醒清單)。任何問題 → PublishError（只印座號、不印名字）。"""
    plan_id = path.stem
    label = pub.rel(path)
    if not schema.PLAN_ID_RE.match(plan_id) or not schema.valid_date(plan_id[:10]):
        raise pub.PublishError("%s：檔名要是方案代號 YYYY-MM-DD（同一天第二個方案寫 YYYY-MM-DD-2）" % label)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError:
        raise pub.PublishError("%s 不是 UTF-8 文字檔" % label)
    except ValueError as e:
        raise pub.PublishError("%s 不是合法的 JSON（第 %s 行附近）：多半是少了逗號或引號" % (label, getattr(e, "lineno", "?")))
    if not isinstance(raw, dict):
        raise pub.PublishError("%s：最外層要是 { … }" % label)
    problems = []
    extra = sorted(set(raw) - set(ALLOWED))
    if extra:
        problems.append("不認得的欄位：%s（只收 %s）" % ("、".join(extra), "、".join(ALLOWED)))
    title = raw.get("title")
    if not isinstance(title, str) or not (1 <= len(title.strip()) <= 60):
        problems.append("title（方案名稱）要 1–60 字")
    date = raw.get("date", plan_id[:10])
    if not schema.valid_date(date):
        problems.append("date 要是 YYYY-MM-DD 的日期")
    note = raw.get("note", "")
    if not isinstance(note, str) or len(note) > 500:
        problems.append("note 最多 500 字")
    rows_in = raw.get("rows")
    rows = []
    if not isinstance(rows_in, list) or not (1 <= len(rows_in) <= schema.SEATING_MAX_ROWS):
        problems.append("rows 要是 1–%d 排" % schema.SEATING_MAX_ROWS)
        rows_in = []
    seen = {}
    for r, row in enumerate(rows_in, 1):
        if isinstance(row, dict) and set(row) == {"seats"}:
            row = row["seats"]
        if not isinstance(row, list) or not (1 <= len(row) <= schema.SEATING_MAX_COLS):
            problems.append("第 %d 排要是 1–%d 格的清單，例如 [\"01\", \"02\"]" % (r, schema.SEATING_MAX_COLS))
            continue
        for c, v in enumerate(row, 1):
            bad = cell_problem(v, r, c)
            if bad:
                problems.append(bad)
            elif v not in ("", AISLE):
                if v in seen:
                    problems.append("座號 %s 出現兩次（第 %d 排和第 %d 排）" % (v, seen[v], r))
                seen[v] = r
        rows.append(list(row))
    if rows_in and not seen and not problems:
        problems.append("座位表裡至少要有一位學生")
    warnings = []
    if roster is not None:
        outside = [s for s in seen if s not in roster]
        if outside:
            problems.append("座號 %s 不在名冊（data/roster.csv）裡：打錯了，還是那位同學已經轉出？" % mp.seat_list(outside))
        missing = [s for s in roster if s not in seen]
        if missing:
            warnings.append("名冊上這幾號沒有排進這個方案：%s（真的沒有他們的位子就不用管）" % mp.seat_list(missing))
    else:
        warnings.append("找不到名冊（data/roster.csv），沒辦法檢查座號是不是都在班上")
    if problems:
        raise pub.PublishError(["%s：%s" % (label, p) for p in problems])
    doc = {"title": title.strip(), "date": date, "rows": [{"seats": row} for row in rows], "note": note.strip(),
           "updatedAt": SERVER_TIME}
    return plan_id, doc, warnings


def ascii_grid(doc):
    out = ["    ［黑板］"]
    for row in doc["rows"]:
        cells = []
        for s in row["seats"]:
            cells.append("    " if s == AISLE else ("[  ]" if s == "" else "[%s]" % s))
        out.append("    " + "".join(cells))
    return out


def counts(doc):
    cells = [s for r in doc["rows"] for s in r["seats"]]
    return (sum(1 for s in cells if s not in ("", AISLE)), sum(1 for s in cells if s == ""),
            sum(1 for s in cells if s == AISLE))


def plan_html(plan_id, doc, names):
    cols = max(len(r["seats"]) for r in doc["rows"])
    cells = []
    for row in doc["rows"]:
        for i in range(cols):
            s = row["seats"][i] if i < len(row["seats"]) else AISLE
            if s == AISLE:
                cells.append('<div class="cell aisle"></div>')
            elif s == "":
                cells.append('<div class="cell empty">空位</div>')
            else:
                cells.append('<div class="cell"><b>%s</b>%s</div>' % (pv.esc(s), pv.esc(names.get(s, ""))))
    n, e, a = counts(doc)
    return ('<section class="seat-plan"><h2>%s</h2><p class="meta">方案代號 %s・%s 起用・學生 %d 位、空位 %d、走道 %d 格</p>'
            '%s<div class="board">黑板</div><div class="seat-grid" style="grid-template-columns:repeat(%d,minmax(0,1fr))">'
            '%s</div></section>'
            % (pv.esc(doc["title"]), pv.esc(plan_id), pv.esc(doc["date"]), n, e, a,
               ('<p class="body-pre">%s</p>' % pv.esc(doc["note"])) if doc["note"] else "", cols, "".join(cells)))


def build(plan_ids=None):
    """回 [(Draft, summary_path)]、預覽 HTML。"""
    files = list_plan_files()
    if plan_ids:
        want = set(plan_ids)
        files = [p for p in files if p.stem in want]
        missing = sorted(want - {p.stem for p in files})
        if missing:
            raise pub.PublishError("data/seating/ 裡找不到：%s.json" % ".json、".join(missing))
    if not files:
        raise pub.PublishError(["data/seating/ 裡還沒有任何方案（.json）。",
                                "寫法見 data/seating/README.md：一個方案一個檔，檔名是起用日期，例如 2026-10-01.json。"])
    roster = mp.roster_seats()
    names = mp.roster_display()
    items, sections, problems = [], [], []
    for path in files:
        try:
            plan_id, doc, warnings = load_plan(path, roster)
        except pub.PublishError as e:
            problems += e.lines
            continue
        n, e, a = counts(doc)
        summary = ["方案 %s：%s（%s 起用）" % (plan_id, doc["title"], doc["date"]),
                   "學生 %d 位、空位 %d、走道 %d 格；%d 排" % (n, e, a, len(doc["rows"]))] + ascii_grid(doc) + \
            ["提醒：" + w for w in warnings]
        owner = "seating/" + plan_id
        draft = pub.Draft("seating", plan_id, None, [], [(owner, doc, "seating")], summary, "")
        items.append((draft, owner))
        sections.append(plan_html(plan_id, doc, names))
    if problems:
        raise pub.PublishError(problems)
    body = "<style>%s</style>%s" % (PREVIEW_CSS, "".join(sections))
    html = pv.page("預覽：座位表", "座位表（%d 個方案）" % len(items), ["只有導師看得到"],
                   ["黑板在上面＝學生面向黑板看過去的樣子；網站上可以切換成老師站在講台看的方向。",
                    "名字是這台電腦名冊裡的「稱呼」；網站上的名字由名冊同步後的資料補上，雲端的座位表只存座號。"], body)
    return items, html


def main(argv=None):
    ap = argparse.ArgumentParser(description="座位表：data/seating/*.json → 導師專用頁（預設只預覽）")
    ap.add_argument("plan", nargs="*", help="方案代號（檔名，不含 .json）；不寫＝全部")
    ap.add_argument("--remove", metavar="方案代號", help="從網站拿掉這個方案（搭 --publish 才真的刪）")
    pub.add_common_args(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)
    try:
        cfg = classcfg.load()
    except classcfg.ConfigError as e:
        return pub.fail([str(e)])
    if a.remove:
        pid = Path(a.remove).stem
        if not schema.PLAN_ID_RE.match(pid):
            return pub.fail("方案代號格式不對：YYYY-MM-DD 或 YYYY-MM-DD-2")
        return mp.remove("seating/" + pid, a, cfg, "座位表方案 %s" % pid,
                         "%s scripts/publish_seating.py --remove %s%s" % (PY, pid, paths.rerun_flags(a)))
    ids = [Path(x).stem for x in a.plan]
    try:
        items, html = build(ids)
        for draft, _ in items:
            draft.validate()
    except pub.PublishError as e:
        return pub.fail(e.lines)
    for draft, _ in items:
        for line in draft.summary:
            print("  " + line)
        print("")
    p = pub.write_preview(mp.PseudoDraft("seating", "-".join(ids) if ids else "all", html), a.open)
    print("  預覽檔：%s" % p)
    cmd = "%s scripts/publish_seating.py%s%s" % (PY, "".join(" " + x for x in ids), paths.rerun_flags(a))
    if not a.publish:
        print("\n這只是預覽，還沒上線。請老師先看預覽檔；確認沒問題、說「上傳」之後再跑：")
        print("  %s --publish" % cmd)
        return 0
    return mp.publish_all(items, a, cfg, cmd, noun="個方案")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
