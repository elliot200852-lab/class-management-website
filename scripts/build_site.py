#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_site.py — 把 site/ 組成可以部署的網站資料夾（Mac／Windows 都能跑，只用標準庫）。

三種輸出：
  python3 scripts/build_site.py
      正式網站 → build/site/
      讀 config/class.json（跟 build_config.py 同一套檢查，範本值拒跑），把公開設定寫進
      build/site/js/site-config.js；每一頁確認有 noindex、放 robots.txt（Disallow: /）。

  python3 scripts/build_site.py --demo
      示範站 → build/demo/（給 GitHub Pages 示範站用）
      不需要 config/class.json、**不含任何 Firebase 設定**、不放 store-firestore.js（示範模式完全不載 SDK）。
      學生 A～Y 共 25 位虛構資料都在瀏覽器裡當場產生；寫入只存在看的人自己的瀏覽器。

  python3 scripts/build_site.py --demo-single-file <輸出.html>
      把示範站打包成「單一 HTML」：CSS 與全部 JS 內聯，換頁用 #/ 路由，除了 Google Fonts 之外
      零外部相依（加 --no-webfonts 連字型也不連，退回系統字型），直接用 file:// 開也能用。

其他：
  --out 目錄              改輸出位置（預設 build/site 或 build/demo）
  --allow-placeholders    正式網站模式下，範本值降成提醒（只給測試用）

輸出資料夾都被 .gitignore 擋住，不進 git。載入順序只寫在 site/js/boot.js 的 FILES 那一段，
這支照同一份清單打包，兩邊不會分岔。
"""
import re
import sys
import json
import shutil
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths  # noqa: E402
from lib.console import setup_utf8  # noqa: E402

setup_utf8()

PKG = paths.pkg_root()
SITE = PKG / "site"
DEFAULT_OUT = {"live": PKG / "build" / "site", "demo": PKG / "build" / "demo"}

ROBOTS = "User-agent: *\nDisallow: /\n"
NOINDEX_META = '<meta name="robots" content="noindex, nofollow">'
FILES_RE = re.compile(r"/\* files:begin \*/(.*?)/\* files:end \*/", re.S)
# 示範輸出裡不准出現的字樣（任何一個出現＝示範站會去連 Firebase）
SDK_MARKERS = ("gstatic.com/firebasejs", "firebaseio.com", "identitytoolkit.googleapis.com",
               "firestore.googleapis.com")
WEBFONT_IMPORT_RE = re.compile(r"^@import url\('https://fonts\.googleapis\.com/[^']*'\);\s*$", re.M)


class BuildError(Exception):
    pass


def load_file_lists():
    """讀 site/js/boot.js 裡 FILES 那一段（嚴格 JSON）。"""
    text = (SITE / "js" / "boot.js").read_text(encoding="utf-8")
    m = FILES_RE.search(text)
    if not m:
        raise BuildError("site/js/boot.js 找不到 /* files:begin */ … /* files:end */ 那一段")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise BuildError("site/js/boot.js 的 FILES 不是合法 JSON：%s" % e)


def ordered_scripts(files, demo=True):
    """單一 HTML 用：ns → core → 示範（或真站）→ 全部 views（去重）→ always"""
    out = []
    for group in ("first", "core"):
        out += files[group]
    out += files["demo"] if demo else files["live"]
    for page in sorted(files["views"]):
        for v in files["views"][page]:
            if v not in out:
                out.append(v)
    for v in files["always"]:
        if v not in out:
            out.append(v)
    return out


def _read_version():
    try:
        return (PKG / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def demo_config(single_file=False):
    """示範站的公開設定：沒有任何 Firebase 值。頁面開關與分類取 config/class.example.json。"""
    example = json.loads((PKG / "config" / "class.example.json").read_text(encoding="utf-8"))
    cfg = {
        "className": "示範班級",
        "siteUrl": "",
        "firebase": {},
        "pages": example.get("pages") or {},
        "categories": example.get("categories") or [],
        "version": _read_version(),
        "demo": True,
    }
    if single_file:
        cfg["singleFile"] = True
    return cfg


def config_js(cfg, header):
    return "/* %s */\nwindow.SITE_CONFIG = %s;\n" % (header, json.dumps(cfg, ensure_ascii=False, indent=2))


def live_config_js(allow_placeholders):
    """正式網站的 site-config.js：跟 build_config.py 同一套檢查與樣板。"""
    import build_config as bc
    source_label, cfg = bc._load_config()
    problems, notes = [], []
    bc.validate(cfg, problems, notes, allow_placeholders=allow_placeholders)
    if problems:
        lines = ["設定還不能用（來源：%s）" % source_label]
        for msg, fix in problems:
            lines.append("  ✗ %s" % msg)
            lines.append("    → %s" % fix)
        raise BuildError("\n".join(lines))
    values = bc.compute_values(cfg)
    values_json = {k: json.dumps(v, ensure_ascii=False) for k, v in values.items()}
    tmpl = (PKG / "templates" / "site-config.js.tmpl").read_text(encoding="utf-8")
    leaks = bc.check_public_templates({"templates": [{"src": "site-config.js.tmpl", "public": True}]},
                                      lambda _name: tmpl)
    if leaks:
        raise BuildError("公開樣板用了不准公開的欄位：%s" % leaks)
    return bc.render_template(tmpl, values_json), notes


def _safe_to_clear(out):
    """只清得掉「看起來是這支產生的輸出」或 repo 的 build/ 底下的資料夾。"""
    out = out.resolve()
    if not out.exists():
        return True
    try:
        out.relative_to((PKG / "build").resolve())
        return True
    except ValueError:
        pass
    if (out / "index.html").exists() and (out / "js" / "boot.js").exists():
        return True
    return not any(out.iterdir())


def prepare_out(out):
    out = Path(out)
    if out.exists():
        if not out.is_dir():
            raise BuildError("輸出位置是一個檔案，不是資料夾：%s" % out)
        if not _safe_to_clear(out):
            raise BuildError("輸出資料夾不是空的、看起來也不是這支產生的，為了安全不清它：%s" % out)
        shutil.rmtree(str(out))
    out.mkdir(parents=True)
    return out


def ensure_noindex(html):
    if 'name="robots"' in html and "noindex" in html:
        return html
    if "<head>" not in html:
        raise BuildError("HTML 沒有 <head>，無法加上 noindex")
    return html.replace("<head>", "<head>\n" + NOINDEX_META, 1)


def copy_site(out, skip):
    """site/ → out（略過 skip 裡的相對路徑）；每個 .html 確認有 noindex；寫 robots.txt。"""
    for src in sorted(SITE.rglob("*")):
        rel = src.relative_to(SITE).as_posix()
        if src.is_dir() or rel in skip or "__pycache__" in rel or rel.endswith(".DS_Store"):
            continue
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".html":
            _write(dest, ensure_noindex(src.read_text(encoding="utf-8")))
        else:
            shutil.copyfile(str(src), str(dest))
    _write(out / "robots.txt", ROBOTS)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def check_demo_output(root):
    """示範輸出不得含任何 Firebase SDK／API 網址。"""
    bad = []
    for p in sorted(Path(root).rglob("*")) if Path(root).is_dir() else [Path(root)]:
        if p.is_file() and p.suffix in (".js", ".html", ".css", ".json"):
            text = p.read_text(encoding="utf-8")
            for marker in SDK_MARKERS:
                if marker in text:
                    bad.append("%s：%s" % (p.name, marker))
    if bad:
        raise BuildError("示範輸出裡出現 Firebase 網址（示範模式不准連 Firebase）：" + "、".join(bad))


def build_live(out, allow_placeholders=False):
    js, notes = live_config_js(allow_placeholders)
    out = prepare_out(out)
    copy_site(out, skip={"js/site-config.js"})
    _write(out / "js" / "site-config.js", js)
    return out, notes


def build_demo(out):
    out = prepare_out(out)
    copy_site(out, skip={"js/site-config.js", "js/core/store-firestore.js"})
    _write(out / "js" / "site-config.js",
           config_js(demo_config(), "由 scripts/build_site.py --demo 產生：示範站設定，不含任何 Firebase 值"))
    _write(out / ".nojekyll", "")
    check_demo_output(out)
    return out


def build_single_file(out_file, webfonts=True):
    files = load_file_lists()
    css = (SITE / "css" / "site.css").read_text(encoding="utf-8")
    if not webfonts:
        css = WEBFONT_IMPORT_RE.sub("", css)
    if re.search(r"</style", css, re.I):
        raise BuildError("site.css 裡有 </style 字樣，不能內聯")
    parts = []
    cfg_js = config_js(demo_config(single_file=True), "單一 HTML 示範版的設定：不含任何 Firebase 值")
    parts.append(cfg_js)
    for rel in ordered_scripts(files, demo=True):
        src = SITE / rel
        text = src.read_text(encoding="utf-8")
        if re.search(r"</script", text, re.I):
            raise BuildError("%s 裡有 </script 字樣，不能內聯" % rel)
        parts.append("/* ── %s ── */\n%s" % (rel, text))
    parts.append("CMW.app.start();\n")
    scripts = "\n".join("<script>\n%s</script>" % p for p in parts)
    html = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
%s
<title>示範班級｜班級網站示範</title>
<link rel="icon" href="data:,">
<style>
%s
</style>
</head>
<body data-page="home">
<header id="site-header"></header>
<main id="app"></main>
<footer id="site-footer"></footer>
%s
</body>
</html>
""" % (NOINDEX_META, css, scripts)
    out_file = Path(out_file)
    _write(out_file, html)
    check_demo_output(out_file)
    return out_file


def main(argv=None):
    ap = argparse.ArgumentParser(description="把 site/ 組成可部署的網站資料夾（正式網站、示範站、單一 HTML 示範版）")
    ap.add_argument("--demo", action="store_true", help="產生示範站（build/demo/，不含任何 Firebase 設定）")
    ap.add_argument("--demo-single-file", metavar="輸出.html", help="把示範站打包成單一 HTML")
    ap.add_argument("--no-webfonts", action="store_true", help="單一 HTML 不連 Google Fonts，改用系統字型")
    ap.add_argument("--out", metavar="目錄", help="輸出資料夾（預設 build/site 或 build/demo）")
    ap.add_argument("--allow-placeholders", action="store_true", help="正式網站模式下範本值降成提醒（只給測試）")
    paths.add_root_arg(ap)
    a = ap.parse_args(argv)
    paths.apply_root(a)

    try:
        if a.demo_single_file:
            out = build_single_file(a.demo_single_file, webfonts=not a.no_webfonts)
            print("✓ 單一 HTML 示範版：%s（%d KB）" % (out, out.stat().st_size // 1024))
            return 0
        if a.demo:
            out = build_demo(a.out or DEFAULT_OUT["demo"])
            print("✓ 示範站：%s" % out)
            print("  本機預覽：python3 -m http.server --directory %s 8000 → 瀏覽器開 http://localhost:8000/" % out)
            return 0
        out, notes = build_live(a.out or DEFAULT_OUT["live"], allow_placeholders=a.allow_placeholders)
        print("✓ 正式網站：%s" % out)
        for n in notes:
            print("  提醒：%s" % n)
        return 0
    except BuildError as e:
        print("✗ %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
