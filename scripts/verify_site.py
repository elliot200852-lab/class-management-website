#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_site.py — 用本機的無頭 Chrome 把示範站每一頁、每個身分都開一次：截圖、收主控台錯誤、
檢查手機寬度有沒有橫向捲動、確認示範模式沒有連到任何外部網站。

  python3 scripts/verify_site.py            （Windows：py -3 scripts/verify_site.py）
  python3 scripts/verify_site.py --out 目錄  改截圖輸出位置（預設：系統暫存資料夾裡的 cmw-verify/，不在 repo 裡）
  python3 scripts/verify_site.py --clean     只刪掉截圖資料夾然後結束

做什麼：
  1. 在暫存資料夾產生示範站（build_site.py --demo）與單一 HTML 版，本機起一個只聽 127.0.0.1 的小伺服器。
  2. 三種身分（訪客、家長〔座號 01〕、導師）× 每一頁 × 兩種畫面（手機 390px、桌機 1280px）：
     開頁 → 等畫面畫完 → 收主控台錯誤 → 檢查橫向溢出 → 整頁截圖。
     手機寬度用 DevTools 的裝置模擬設定（不用 --window-size，那種做法在窄寬度會出現假的溢出）。
  3. 互動（示範資料存在暫存的瀏覽器裡，跑完就丟）：
     · 家長在單篇紀事送一則留言（含 <script> 與網址）、導師把它收起、點照片開燈箱再按 Esc 關掉
     · 相簿：點縮圖開燈箱、影片預覽框點了只顯示說明（示範站不連任何外部網站）
     · v1.1：座位表（切方案、切方向、點座位）、個人照（並排家長合照）、匯出 PDF（勾選、產生列印版、照片載完才能列印）、
       每日一詩；家長打開導師限定的頁面只看到一句說明
     · 我的孩子：家長發一篇附照片的文章（照片在頁面裡當場做、帶 EXIF 方向與 GPS）→ 驗重新編碼後沒有 APP1、
       沒有 GPS 記號、方向已轉正；在對話串留言、把自己的留言收起；導師的全班格亮起未讀、點進去看過就熄掉；
       同仁只看得到文章、看不到對話串；不是私密讀者的家長看不到私密紀事
  4. 單一 HTML 版用 file:// 直接開，點導覽換頁，確認 #/ 路由可用。
  5. 在截圖資料夾產生 index.html（截圖總覽）與 report.json。

判定：任何一頁有主控台錯誤、手機寬有橫向溢出、或示範模式連到 127.0.0.1 與 Google Fonts 以外的網址 → exit 1。
本機找不到 Chrome → 印「SKIP」並 exit 0（不算失敗）。

截圖是二進位檔，預設放在系統暫存資料夾（不在 repo 裡）：兩個隱私掃描器（scripts/privacy_scan.py 與
維護者自己的私有掃描）都會把 repo 資料夾裡的任何二進位檔當成命中。--out 指到 repo 裡面的話，看完記得刪掉。
"""
import sys
import json
import shutil
import argparse
import tempfile
import threading
import functools
import http.server
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths  # noqa: E402
from lib.console import setup_utf8  # noqa: E402
from lib import cdp  # noqa: E402
import build_site  # noqa: E402

setup_utf8()

PKG = paths.pkg_root()
DEFAULT_OUT = Path(tempfile.gettempdir()) / "cmw-verify"
EXIF_FIXTURE = PKG / "tests" / "fixtures" / "exif-jpeg.js"

VIEWPORTS = {
    "mobile": {"width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": True},
    "desktop": {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False},
}
ROLES = [
    ("guest", "訪客", "CMW.getStore().demoSetRole('signed-out')"),
    ("parent", "家長（座號 01）", "CMW.getStore().demoSetRole('parent', {seat: '01'})"),
    ("teacher", "導師", "CMW.getStore().demoSetRole('teacher')"),
]
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "fonts.googleapis.com", "fonts.gstatic.com")
FONT_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")

# 手機模擬（mobile: true）下，內容一旦比螢幕寬，Chrome 會把版面視窗自動撐大（innerWidth 跟著變），
# 所以不能拿 innerWidth 比，一律拿「設定的螢幕寬度」比。
OVERFLOW_JS = r"""
((vw) => {
  const de = document.documentElement;
  const sw = Math.max(de.scrollWidth, document.body ? document.body.scrollWidth : 0);
  const out = [];
  const describe = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    if (typeof el.className === 'string' && el.className.trim()) s += '.' + el.className.trim().split(/\s+/).join('.');
    return s;
  };
  for (const el of document.body.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) continue;
    if (r.right <= vw + 1 && r.left >= -1) continue;
    let p = el.parentElement, clipped = false;
    while (p && p !== document.body) {
      const cs = getComputedStyle(p);
      if (cs.overflowX !== 'visible' || cs.position === 'fixed') { clipped = true; break; }
      p = p.parentElement;
    }
    if (getComputedStyle(el).position === 'fixed') clipped = clipped || (r.right <= vw + 1);
    if (!clipped) out.push(describe(el) + ' [' + Math.round(r.left) + '→' + Math.round(r.right) + ']');
    if (out.length >= 8) break;
  }
  return { vw: vw, iw: window.innerWidth, sw: sw, overflow: sw > vw + 1 || window.innerWidth > vw + 1, offenders: out };
})
"""


def overflow_js(width):
    return "(%s)(%d)" % (OVERFLOW_JS.strip(), width)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = dict(http.server.SimpleHTTPRequestHandler.extensions_map)
    extensions_map.update({".js": "text/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8",
                           ".txt": "text/plain; charset=utf-8", ".json": "application/json"})

    def log_message(self, *args):
        pass


def serve(directory):
    handler = functools.partial(QuietHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, "http://127.0.0.1:%d/" % httpd.server_address[1]


def collect_problems(events):
    """事件 → (錯誤清單, 外部連線清單, 字型連線失敗清單)"""
    errors, external, font_fail = [], [], []
    for e in events:
        m = e.get("method")
        p = e.get("params", {})
        if m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            ex = d.get("exception", {}) or {}
            errors.append("例外：%s %s" % (d.get("text", ""), ex.get("description", "")[:300]))
        elif m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "assert"):
            args = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
            errors.append("console.error：%s" % args[:300])
        elif m == "Log.entryAdded":
            entry = p.get("entry", {})
            if entry.get("level") == "error":
                url = entry.get("url", "") or ""
                if any(h in url for h in FONT_HOSTS):
                    font_fail.append(url)
                else:
                    errors.append("%s：%s %s" % (entry.get("source"), entry.get("text", "")[:300], url))
        elif m == "Network.requestWillBeSent":
            url = p.get("request", {}).get("url", "")
            if url.startswith(("data:", "about:", "file:", "blob:")):
                continue
            host = url.split("/")[2].split(":")[0] if "://" in url else ""
            if host not in ALLOWED_HOSTS:
                external.append(url[:200])
    return errors, external, font_fail


def goto(page, url):
    """開一個網址。只差在 # 後面的網址（我的孩子的子路由）瀏覽器不會重新載入，所以先回空白頁再開，
    每一次都是完整載入（等畫完的判斷才不會被上一頁的「已畫完」騙到）。"""
    if "#" in url:
        page.send("Page.navigate", {"url": "about:blank"})
        page.wait_for("location.href === 'about:blank'", timeout=10)
    page.send("Page.navigate", {"url": url})


def wait_ready(page, timeout=20):
    return page.wait_for("document.documentElement.getAttribute('data-cmw-ready') === '1'", timeout=timeout)


def open_and_check(page, url, vp_name, shot_path):
    vp = VIEWPORTS[vp_name]
    page.send("Emulation.setDeviceMetricsOverride", vp)
    page.send("Emulation.setTouchEmulationEnabled", {"enabled": bool(vp["mobile"])})
    page.my_events(clear=True)
    goto(page, url)
    ready = page.wait_for("document.documentElement.getAttribute('data-cmw-ready') === '1'", timeout=20)
    try:
        page.evaluate("Promise.race([document.fonts ? document.fonts.ready.then(() => true) : true,"
                      " new Promise(r => setTimeout(() => r(false), 4000))])", timeout=10)
    except cdp.CDPError:
        pass
    # 從頭捲到尾一次：讓 loading="lazy" 的照片都載進來，整頁截圖才看得到（真人往下捲也是這樣）
    try:
        page.evaluate("(async () => { const h = () => document.documentElement.scrollHeight;"
                      " for (let y = 0; y < h(); y += Math.max(200, innerHeight * 0.8)) {"
                      " scrollTo(0, y); await new Promise(r => setTimeout(r, 40)); }"
                      " scrollTo(0, 0); await new Promise(r => setTimeout(r, 150)); return true; })()", timeout=30)
    except cdp.CDPError:
        pass
    page.b.pump(0.3)
    ov = page.evaluate(overflow_js(vp["width"])) or {}
    info = page.evaluate("({page: (document.getElementById('app')||{}).className || '', "
                         "title: document.title, demoBar: !!document.querySelector('.demo-bar'), "
                         "gate: !!document.querySelector('.gate'), fab: !!document.querySelector('.teacher-fab')})") or {}
    if shot_path:
        page.screenshot(str(shot_path), full_page=True)
    errors, external, font_fail = collect_problems(page.my_events(clear=True))
    if not ready:
        errors.append("20 秒內沒有畫完（data-cmw-ready 沒有變成 1）")
    if not info.get("demoBar"):
        errors.append("示範模式橫幅不見了")
    return {
        "url": url, "viewport": vp_name, "ready": ready, "errors": errors, "external": external,
        "fontFailures": font_fail, "overflow": bool(ov.get("overflow")) or bool(ov.get("offenders")),
        "scrollWidth": ov.get("sw"), "viewportWidth": ov.get("vw"), "offenders": ov.get("offenders", []),
        "info": info,
    }


def set_role(page, base, js):
    page.send("Page.navigate", {"url": base + "index.html"})
    page.wait_for("window.CMW && CMW.getStore && document.documentElement.getAttribute('data-cmw-ready') === '1'",
                  timeout=20)
    page.evaluate(js)
    page.wait_for("document.documentElement.getAttribute('data-cmw-ready') === '1'", timeout=20)
    page.my_events(clear=True)


def interaction_check(page, base):
    """家長送留言 → 畫面即時出現；導師收起 → 變成已收起；照片燈箱開關。最後清掉示範資料。"""
    problems = []
    set_role(page, base, "CMW.getStore().demoSetRole('parent', {seat: '01'})")
    slug = page.evaluate("CMW.getStore().info.posts[0]")
    page.send("Page.navigate", {"url": base + "post.html?s=" + quote(slug)})
    if not page.wait_for("document.documentElement.getAttribute('data-cmw-ready') === '1'", timeout=20):
        return ["單篇紀事沒有畫完"]
    page.evaluate("""(() => {
      document.getElementById('comment-name').value = '驗收用署名';
      document.getElementById('comment-body').value = '驗收留言 <script>alert(1)</script> https://example.com/x';
      document.querySelector('.comment-form button[type=submit]').click();
      return true; })()""")
    ok = page.wait_for("Array.from(document.querySelectorAll('.comment-body')).some(p => p.textContent.indexOf('驗收留言') >= 0)",
                       timeout=10)
    if not ok:
        problems.append("送出留言後畫面沒有出現新留言")
    else:
        bad = page.evaluate("document.querySelectorAll('.comment-body script').length")
        if bad:
            problems.append("留言裡的 <script> 被當成元素畫出來了")
        link = page.evaluate("(() => { const a = Array.from(document.querySelectorAll('.comment-body a'))"
                             ".find(x => x.href.indexOf('example.com/x') >= 0); return a ? a.rel : null; })()")
        if not link or "noopener" not in link:
            problems.append("留言裡的網址沒有變成安全連結")
    # 導師把那則留言收起 → 畫面上變成「已收起」
    page.evaluate("CMW.getStore().demoSetRole('teacher')")
    page.wait_for("document.documentElement.getAttribute('data-cmw-ready') === '1'", timeout=20)
    page.evaluate("(() => { const c = Array.from(document.querySelectorAll('.comment'))"
                  ".find(x => x.textContent.indexOf('驗收留言') >= 0);"
                  " const b = c && Array.from(c.querySelectorAll('button')).find(x => x.textContent === '收起');"
                  " if (b) b.click(); return !!b; })()")
    if not page.wait_for("Array.from(document.querySelectorAll('.comment.is-hidden'))"
                         ".some(x => x.textContent.indexOf('驗收留言') >= 0)", timeout=10):
        problems.append("導師收起留言後畫面沒有更新")
    # 關於我們的照片格：點一張 → 燈箱讀大圖 → Esc 關閉
    page.send("Page.navigate", {"url": base + "page.html?id=about"})
    page.wait_for("document.documentElement.getAttribute('data-cmw-ready') === '1'", timeout=20)
    page.evaluate("(() => { const t = document.querySelector('.thumb'); if (t) t.click(); return !!t; })()")
    if not page.wait_for("!!document.querySelector('.lightbox .lightbox-stage img')", timeout=10):
        problems.append("點照片沒有打開燈箱")
    else:
        page.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape",
                                             "windowsVirtualKeyCode": 27})
        if not page.wait_for("!document.querySelector('.lightbox')", timeout=5):
            problems.append("燈箱按 Esc 關不掉")
    page.evaluate("CMW.getStore().demoReset()")
    errors, external, _ = collect_problems(page.my_events(clear=True))
    return problems + errors + ["外部連線：" + u for u in external]


def album_and_video_check(page, base, info):
    """相簿：點縮圖開燈箱、左右換張、Esc 關；影片預覽框點了只出現說明（示範站不連外部）。課程頁的影片同樣。"""
    problems = []
    set_role(page, base, "CMW.getStore().demoSetRole('parent', {seat: '01'})")
    goto(page, base + "album.html?a=" + quote(info["albumWithPhotos"]))
    if not wait_ready(page):
        return ["單本相簿沒有畫完"]
    n = page.evaluate("document.querySelectorAll('.album-photos .thumb img').length")
    if not n or n < 9:
        problems.append("相簿格的縮圖數量不對（%s）" % n)
    page.evaluate("(() => { const t = document.querySelectorAll('.album-photos .thumb')[1]; if (t) t.click(); return !!t; })()")
    if not page.wait_for("!!document.querySelector('.lightbox .lightbox-stage img') && "
                         "document.querySelector('.lightbox-counter').textContent.indexOf('2 /') === 0", timeout=10):
        problems.append("相簿點縮圖沒有打開燈箱（或不是從第 2 張開始）")
    else:
        page.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "ArrowRight", "code": "ArrowRight",
                                             "windowsVirtualKeyCode": 39})
        if not page.wait_for("document.querySelector('.lightbox-counter').textContent.indexOf('3 /') === 0", timeout=5):
            problems.append("燈箱按右鍵沒有換到下一張")
        page.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape",
                                             "windowsVirtualKeyCode": 27})
        if not page.wait_for("!document.querySelector('.lightbox')", timeout=5):
            problems.append("相簿燈箱按 Esc 關不掉")
    if not page.evaluate("!!document.querySelector('.album-link a[rel~=noopener]')"):
        problems.append("外部相簿連結不見了（或不是安全連結）")
    page.evaluate("(() => { const b = document.querySelector('.album-videos .blk-video-play'); if (b) b.click(); return !!b; })()")
    if not page.wait_for("!!document.querySelector('.album-videos .blk-video-demo') && !document.querySelector('iframe')", timeout=5):
        problems.append("示範站的影片預覽框點了之後不是顯示說明")
    goto(page, base + "courses.html")
    if not wait_ready(page):
        problems.append("課程頁沒有畫完")
    else:
        cards = page.evaluate("document.querySelectorAll('.syllabus-card').length")
        if cards != 3:
            problems.append("課程頁的各科大綱卡數量不對（%s）" % cards)
        page.evaluate("(() => { const b = document.querySelector('.courses .blk-video-play'); if (b) b.click(); return !!b; })()")
        if not page.wait_for("!!document.querySelector('.courses .blk-video-demo') && !document.querySelector('iframe')", timeout=5):
            problems.append("課程影片預覽框點了之後不是顯示說明")
    errors, external, _ = collect_problems(page.my_events(clear=True))
    return problems + errors + ["外部連線：" + u for u in external]


def my_child_check(page, base, info):
    """我的孩子：家長發文（照片帶 EXIF）→ 重新編碼的照片沒有 APP1／GPS、方向轉正；對話串留言、收起自己的留言；
    導師全班格的未讀亮起、看過熄掉；同仁看不到對話串；不是私密讀者的家長看不到私密紀事。"""
    problems = []
    fixture = EXIF_FIXTURE.read_text(encoding="utf-8")
    set_role(page, base, "CMW.getStore().demoSetRole('parent', {seat: '01'})")
    goto(page, base + "my-child.html#/new/01")
    if not wait_ready(page):
        return ["寫一篇的頁面沒有畫完"]
    page.evaluate(fixture)
    ok = page.evaluate("""(async () => {
      const f = await CMWTestJpeg.makeFile(2000, 1500, 6);
      const input = document.getElementById('mc-photos');
      const dt = new DataTransfer(); dt.items.add(f);
      input.files = dt.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return true; })()""", timeout=30)
    if not ok or not page.wait_for("!!document.querySelector('.photo-slot img')", timeout=30):
        errs = page.evaluate("Array.from(document.querySelectorAll('.photo-slot')).map(x => x.textContent).join('｜')")
        return ["選了照片之後沒有出現預覽（%s）" % errs]
    page.evaluate("""(() => {
      document.getElementById('mc-title').value = '驗收用文章';
      document.getElementById('mc-body').value = '第一行\\n\\n  第三行前面有兩個空白 <b>不是粗體</b>';
      document.querySelector('.photo-slot input').value = '驗收圖說';
      document.querySelector('.compose-form button[type=submit]').click();
      return true; })()""")
    if not page.wait_for("location.hash.indexOf('#/entry/01/') === 0 && !!document.querySelector('.blog-post')"
                         " && document.documentElement.getAttribute('data-cmw-ready') === '1'", timeout=20):
        msg = page.evaluate("(document.querySelector('.compose-form .form-msg') || {}).textContent || ''")
        return ["發文後沒有跳到文章頁（%s）" % msg]
    check = page.evaluate("""(() => {
      const id = location.hash.split('/')[3];
      const db = CMW.getStore()._db;
      const base = 'student_blogs/01/entries/' + id;
      const entry = db[base], img = db[base + '/images/0'], th = db[base + '/thumbs/0'];
      if (!entry || !img || !th) return { missing: true };
      const bytes = CMWTestJpeg.b64ToBytes(img.data), tb = CMWTestJpeg.b64ToBytes(th.data);
      return {
        imgApp1: CMW.photoEncode.hasMetadata(bytes), thumbApp1: CMW.photoEncode.hasMetadata(tb),
        imgMark: CMWTestJpeg.contains(bytes, CMWTestJpeg.MARK), thumbMark: CMWTestJpeg.contains(tb, CMWTestJpeg.MARK),
        jpeg: bytes[0] === 0xFF && bytes[1] === 0xD8,
        w: img.w, h: img.h, tw: th.w, th: th.h, author: entry.author, caption: entry.photos[0].caption,
        body: entry.body, bodyShown: document.querySelector('.blog-body').textContent,
        bold: document.querySelectorAll('.blog-body b').length
      }; })()""")
    if not check or check.get("missing"):
        problems.append("發出的文章或照片文件不見了")
    else:
        if check["imgApp1"] or check["thumbApp1"]:
            problems.append("重新編碼後的照片還有 APP1（EXIF）區段")
        if check["imgMark"] or check["thumbMark"]:
            problems.append("重新編碼後的照片裡還找得到 GPS 記號")
        if not check["jpeg"]:
            problems.append("顯示圖不是 JPEG")
        if (check["w"], check["h"], check["tw"], check["th"]) != (960, 1280, 240, 320):
            problems.append("照片尺寸或方向不對（顯示圖 %sx%s、縮圖 %sx%s；應該轉正成直的 960x1280、240x320）"
                            % (check["w"], check["h"], check["tw"], check["th"]))
        if check["author"] != "parent" or check["caption"] != "驗收圖說":
            problems.append("文章的作者或圖說不對")
        if "  第三行" not in check["body"] or check["bold"]:
            problems.append("內文沒有逐字保留，或 HTML 被當成元素")
    # 對話串：家長留言 → 收起自己的那一則（兩段確認）→ 家長畫面上消失
    page.evaluate("""(() => { document.getElementById('bc-body').value = '驗收對話 https://example.com/t';
      document.querySelector('.blog-thread button[type=submit]').click(); return true; })()""")
    if not page.wait_for("Array.from(document.querySelectorAll('.bc-item .comment-body')).some(p => p.textContent.indexOf('驗收對話') >= 0)", timeout=10):
        problems.append("對話串送出後沒有出現")
    else:
        page.evaluate("(() => { const b = Array.from(document.querySelectorAll('.bc-item.is-mine button')).find(x => x.textContent.indexOf('收起') === 0); if (b) { b.click(); b.click(); } return !!b; })()")
        if not page.wait_for("!Array.from(document.querySelectorAll('.bc-item .comment-body')).some(p => p.textContent.indexOf('驗收對話') >= 0)", timeout=10):
            problems.append("家長收起自己的留言後，畫面上還看得到")
    # 導師：全班格的座號 01 亮起來 → 點進去 → 回全班格就熄掉
    page.evaluate("CMW.getStore().demoSetRole('teacher')")
    goto(page, base + "my-child.html#/admin")
    if not wait_ready(page):
        problems.append("導師的全班格沒有畫完")
    else:
        if not page.evaluate("!!document.querySelector('.mc-card--new[data-seat=\"01\"]')"):
            problems.append("家長發文後，導師全班格的座號 01 沒有亮起未讀")
        n_cards = page.evaluate("document.querySelectorAll('.mc-grid .mc-card').length")
        if n_cards != 25:
            problems.append("全班格應該有 25 格（實際 %s）" % n_cards)
        page.evaluate("(() => { const a = document.querySelector('.mc-card[data-seat=\"01\"]'); if (a) a.click(); return !!a; })()")
        if not page.wait_for("location.hash.indexOf('#/seat/01') === 0 && document.documentElement.getAttribute('data-cmw-ready') === '1'", timeout=10):
            problems.append("點全班格沒有進到座號 01")
        who = page.evaluate("Array.from(document.querySelectorAll('.mc-identity')).map(x => x.textContent).join('｜')")
        if "學生 A 家長（母）" not in (who or ""):
            problems.append("導師端沒有把作者代號對回「學生 A 家長（母）」（看到：%s）" % who)
        goto(page, base + "my-child.html#/admin")
        wait_ready(page)
        if page.evaluate("!!document.querySelector('.mc-card--new[data-seat=\"01\"]')"):
            problems.append("導師看過座號 01 之後，未讀提示沒有熄掉")
    # 同仁（座號 03）：看得到文章、沒有寫文按鈕、沒有對話串
    page.evaluate("CMW.getStore().demoSetRole('staff')")
    goto(page, base + "my-child.html")
    if not wait_ready(page):
        problems.append("同仁的我的孩子沒有畫完")
    else:
        st = page.evaluate("({ list: document.querySelectorAll('.blog-entry').length, compose: !!document.querySelector('a[href*=\"new/\"]'),"
                           " title: (document.querySelector('.page-title') || {}).textContent || '' })")
        if not st["list"] or st["compose"] or "學生 C" not in st["title"]:
            problems.append("同仁看到的座號 03 列表不對：%s" % st)
        goto(page, base + "my-child.html#/entry/03/" + quote(info["entries"]["03"]))
        wait_ready(page)
        if page.evaluate("!!document.querySelector('.blog-thread')"):
            problems.append("同仁看得到對話串")
    # 不是私密讀者的家長（座號 02）：紀事列表沒有鎖頭卡、私密紀事頁只說「只給私密名單」
    page.evaluate("CMW.getStore().demoSetRole('parent', {seat: '02'})")
    goto(page, base + "blog.html")
    wait_ready(page)
    if page.evaluate("!!document.querySelector('.entry--private')"):
        problems.append("不是私密讀者的家長在紀事列表看到鎖頭卡")
    goto(page, base + "private.html?p=" + quote(info["privatePost"]))
    wait_ready(page)
    if page.evaluate("!!document.querySelector('.post--private') || document.body.textContent.indexOf('給家長的悄悄話') >= 0"):
        problems.append("不是私密讀者的家長看得到私密紀事")
    page.evaluate("CMW.getStore().demoReset()")
    errors, external, _ = collect_problems(page.my_events(clear=True))
    return problems + errors + ["外部連線：" + u for u in external]


def v11_check(page, base, info):
    """v1.1 頁面：座位表（切方案、切方向、點座位）、個人照（格子、並排看大圖、左右換人）、
    匯出 PDF（勾選、產生列印版、照片載完才開放列印；部落格一人一份與全班）、每日一詩（今天、指定哪一天）；
    家長打開導師限定的頁面只看到一句說明。"""
    problems = []
    ready = "document.documentElement.getAttribute('data-cmw-ready') === '1'"
    set_role(page, base, "CMW.getStore().demoSetRole('teacher')")
    # ── 座位表 ──
    goto(page, base + "teacher.html#/seating")
    if not wait_ready(page):
        return ["座位表分頁沒有畫完"]
    st = page.evaluate("""(() => {
      const seats = document.querySelectorAll('.seating-svg .seat-card--seat');
      const board = document.querySelector('.seating-svg .seat-board');
      const desk = document.querySelector('.seating-svg .seat-card--seat .seat-desk');
      return { seats: seats.length, empty: document.querySelectorAll('.seating-svg .seat-card--empty').length,
        plans: document.querySelectorAll('.seating-plan-btn').length,
        title: (document.querySelector('.seating-title') || {}).textContent || '',
        names: document.querySelector('.seating-svg').textContent.indexOf('學生 A') >= 0,
        boardBelow: board && desk ? parseFloat(board.getAttribute('y')) > parseFloat(desk.getAttribute('y')) : null }; })()""")
    if st.get("seats") != 25 or st.get("empty") != 1 or st.get("plans") != 2 or "兩兩一組" not in st.get("title", ""):
        problems.append("座位表預設方案不對（應該是最近起用的「兩兩一組」、25 位、1 個空位、2 個方案）：%s" % st)
    if not st.get("names"):
        problems.append("座位表沒有用名冊的稱呼補上名字")
    if st.get("boardBelow") is not True:
        problems.append("座位表預設應該是老師視角（黑板在下）")
    page.evaluate("document.querySelector('.seating-view-btn[data-view=student]').click()")
    if not page.wait_for("(() => { const b = document.querySelector('.seating-svg .seat-board'),"
                         " d = document.querySelector('.seating-svg .seat-card--seat .seat-desk');"
                         " return b && d && parseFloat(b.getAttribute('y')) < parseFloat(d.getAttribute('y')); })()", timeout=5):
        problems.append("切成學生視角後黑板沒有到上面")
    page.evaluate("document.querySelectorAll('.seating-plan-btn')[1].click()")
    if not page.wait_for("document.querySelector('.seating-title').textContent.indexOf('開學的座位') >= 0"
                         " && document.querySelectorAll('.seating-svg .seat-card--empty').length === 0", timeout=5):
        problems.append("切換座位方案沒有換掉座位表")
    page.evaluate("document.querySelector('.seating-svg .seat-card--seat').dispatchEvent(new MouseEvent('click', {bubbles: true}))")
    if not page.wait_for("!!document.querySelector('.seating-svg .seat-card.is-picked')", timeout=5):
        problems.append("點座位沒有標記起來")
    # ── 個人照 ──
    goto(page, base + "family-photos.html")
    if not wait_ready(page):
        problems.append("個人照沒有畫完")
    else:
        fp = page.evaluate("({ cards: document.querySelectorAll('.fp-card').length,"
                           " imgs: document.querySelectorAll('.fp-card img[src^=\"data:image/\"]').length,"
                           " empty: document.querySelectorAll('.fp-card.is-empty').length })")
        if fp != {"cards": 25, "imgs": 23, "empty": 2}:
            problems.append("個人照格子不對（應該 25 格、23 張照片、2 格還沒有照片）：%s" % fp)
        page.evaluate("document.querySelector('.fp-card[data-seat=\"01\"]').click()")
        if not page.wait_for("document.querySelectorAll('.fp-viewer .fp-pane img').length === 2", timeout=10):
            problems.append("點個人照沒有並排出孩子與家長合照")
        else:
            cap = page.evaluate("[document.querySelector('.fp-viewer-caption').textContent,"
                                " document.querySelector('.fp-viewer-rel').textContent]")
            if "座號 01" not in cap[0] or "母、父" not in cap[1]:
                problems.append("看大圖的說明不對：%s" % cap)
            page.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "ArrowRight", "code": "ArrowRight",
                                                 "windowsVirtualKeyCode": 39})
            if not page.wait_for("document.querySelector('.fp-viewer-caption').textContent.indexOf('座號 02') === 0", timeout=5):
                problems.append("看大圖按右鍵沒有換到下一位")
            page.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape",
                                                 "windowsVirtualKeyCode": 27})
            if not page.wait_for("!document.querySelector('.fp-viewer')", timeout=5):
                problems.append("看大圖按 Esc 關不掉")
    # ── 匯出 PDF：班級紀事 ──
    goto(page, base + "blog-print.html")
    if not wait_ready(page):
        problems.append("匯出（班級紀事）沒有畫完")
    else:
        page.evaluate("Array.from(document.querySelectorAll('.export-list-actions button')).find(b => b.textContent === '全不選').click()")
        if not page.wait_for("document.querySelector('.export-count').textContent === '將匯出 0／3 篇'", timeout=5):
            problems.append("全不選之後的篇數不對")
        page.evaluate("Array.from(document.querySelectorAll('.export-list-actions button')).find(b => b.textContent === '全選').click()")
        page.evaluate("(() => { const i = document.getElementById('ex-from'); i.value = %s;"
                      " i.dispatchEvent(new Event('change', {bubbles: true})); return true; })()" % json.dumps(info["posts"][1][:10]))
        if not page.wait_for("document.querySelector('.export-count').textContent === '將匯出 2／2 篇'", timeout=5):
            problems.append("改起始日期沒有重篩清單：%s" % page.evaluate("document.querySelector('.export-count').textContent"))
        if page.evaluate("!document.querySelector('.export-buttons .btn:not(.btn--primary)').disabled"):
            problems.append("還沒產生列印版就可以按列印")
        page.evaluate("document.querySelector('.export-buttons .btn--primary').click()")
        if not page.wait_for("!!document.querySelector('.print-doc.is-ready')", timeout=20):
            problems.append("產生列印版沒有完成：%s" % page.evaluate("document.querySelector('.export-status').textContent"))
        else:
            pd = page.evaluate("({ items: document.querySelectorAll('.print-doc .print-item').length,"
                               " cover: !!document.querySelector('.print-cover'), toc: document.querySelectorAll('.print-toc li').length,"
                               " figs: document.querySelectorAll('.print-fig img').length,"
                               " loaded: Array.from(document.querySelectorAll('.print-fig img')).every(i => i.complete && i.naturalWidth > 0),"
                               " printable: !document.querySelector('.export-buttons .btn:not(.btn--primary)').disabled,"
                               " video: document.querySelectorAll('.print-video').length })")
            if pd.get("items") != 2 or not pd.get("cover") or pd.get("toc") != 2 or not pd.get("figs") \
                    or not pd.get("loaded") or not pd.get("printable") or not pd.get("video"):
                problems.append("班級紀事列印版內容不對（2 篇、封面、目錄、照片都載完、影片印成文字、可以列印）：%s" % pd)
    # ── 匯出 PDF：學生部落格（一人一份、全班）──
    goto(page, base + "my-child-print.html")
    if not wait_ready(page):
        problems.append("匯出（學生部落格）沒有畫完")
    else:
        if not page.wait_for("document.querySelector('.export-count').textContent === '將匯出 2／2 篇'", timeout=10):
            problems.append("一人一份（座號 01）的清單不對：%s" % page.evaluate("document.querySelector('.export-count').textContent"))
        page.evaluate("document.querySelector('.export-buttons .btn--primary').click()")
        if not page.wait_for("!!document.querySelector('.print-doc.is-ready')", timeout=20):
            problems.append("部落格（一人一份）列印版沒有完成")
        elif page.evaluate("document.querySelectorAll('.print-doc .print-entry').length !== 2"
                           " || document.querySelector('.print-cover-title').textContent.indexOf('學生 A') < 0"
                           " || !!document.querySelector('.print-student-title')"):
            problems.append("部落格（一人一份）列印版內容不對")
        page.evaluate("(() => { const s = document.getElementById('ex-mode'); s.value = 'all';"
                      " s.dispatchEvent(new Event('change', {bubbles: true})); return true; })()")
        if not page.wait_for("document.querySelectorAll('.export-group').length === 25 && !document.querySelector('.print-doc .print-item')",
                             timeout=10):
            problems.append("全班模式的清單沒有依座號分組（或舊的列印版沒有清掉）")
        page.evaluate("document.querySelector('.export-buttons .btn--primary').click()")
        if not page.wait_for("!!document.querySelector('.print-doc.is-ready')", timeout=30):
            problems.append("部落格（全班）列印版沒有完成")
        elif page.evaluate("document.querySelectorAll('.print-doc .print-student').length") != 25:
            problems.append("全班列印版應該每位學生一段（25 段）")
    # ── 每日一詩 ──
    set_role(page, base, "CMW.getStore().demoSetRole('parent', {seat: '01'})")
    goto(page, base + "poem.html")
    if not wait_ready(page):
        problems.append("每日一詩沒有畫完")
    else:
        pm = page.evaluate("({ title: (document.querySelector('.poem-title') || {}).textContent || '',"
                           " today: !!document.querySelector('.poem-date .chip--read'),"
                           " list: document.querySelectorAll('.poem-list li').length,"
                           " text: (document.querySelector('.poem-text') || {}).textContent || '' })")
        if "早晨" not in pm["title"] or not pm["today"] or not pm["list"] or "\n" not in pm["text"]:
            problems.append("每日一詩沒有顯示今天那一首（或正文的換行不見了）：%s" % pm)
        goto(page, base + "poem.html?d=" + quote(info["poemDays"][2]))
        wait_ready(page)
        if "種子" not in page.evaluate("(document.querySelector('.poem-title') || {}).textContent || ''"):
            problems.append("每日一詩指定日期（?d=）沒有換到那一首")
        if page.evaluate("document.querySelector('.poem-text').textContent.indexOf('\\n  它在等') < 0"):
            problems.append("每日一詩的行首空白沒有保留")
    # ── 家長打開導師限定的頁面 ──
    for rel, label in (("teacher.html#/seating", "座位表"), ("family-photos.html", "個人照"),
                       ("blog-print.html", "匯出 PDF"), ("my-child-print.html", "匯出 PDF（部落格）")):
        goto(page, base + rel)
        wait_ready(page)
        if page.evaluate("document.body.textContent.indexOf('這一頁只有導師能用') < 0 || !!document.querySelector('.fp-card, .seating-svg, .export-panel')"):
            problems.append("家長打開%s沒有被擋在「只有導師能用」" % label)
    page.evaluate("CMW.getStore().demoReset()")
    errors, external, _ = collect_problems(page.my_events(clear=True))
    return problems + errors + ["外部連線：" + u for u in external]


def single_file_check(page, html_path, out_dir):
    """單一 HTML：file:// 開、切成導師、點導覽換頁、逐一開幾個 #/ 路由。"""
    results = []
    base = Path(html_path).resolve().as_uri()
    page.send("Emulation.setDeviceMetricsOverride", VIEWPORTS["mobile"])
    page.send("Page.navigate", {"url": base + "#/"})
    page.wait_for("window.CMW && document.documentElement.getAttribute('data-cmw-ready') === '1'", timeout=20)
    page.evaluate("CMW.getStore().demoSetRole('teacher')")
    page.wait_for("document.documentElement.getAttribute('data-cmw-ready') === '1'", timeout=20)
    # 點導覽的「班級紀事」→ 應該換到 #/blog
    page.evaluate("(() => { const a = document.querySelector('.primary-nav .nav-blog a'); if (a) a.click(); return !!a; })()")
    clicked = page.wait_for("location.hash.indexOf('#/blog') === 0 && document.getElementById('app').className.indexOf('page-blog') >= 0"
                            " && document.documentElement.getAttribute('data-cmw-ready') === '1'", timeout=10)
    nav_problem = [] if clicked else ["單一 HTML：點導覽沒有換頁"]
    info = page.evaluate("CMW.getStore().info")
    routes = [("home", "#/"), ("blog", "#/blog"), ("post", "#/post?s=" + quote(info["posts"][0])),
              ("admin", "#/admin"), ("page-about", "#/page?id=about"), ("gallery", "#/gallery"),
              ("my-child-admin", "#/my-child/admin"), ("my-child-seat", "#/my-child/seat/01"),
              ("teacher-seating", "#/teacher/seating"), ("family-photos", "#/family-photos"), ("blog-print", "#/blog-print"),
              ("poem", "#/poem")]
    for name, h in routes:
        shot = out_dir / ("single__%s__teacher__mobile.png" % name)
        r = open_and_check(page, base + h, "mobile", shot)
        r["name"] = "single:" + name
        r["role"] = "teacher"
        r["shot"] = shot.name
        results.append(r)
    page.evaluate("CMW.getStore().demoReset()")
    page.my_events(clear=True)
    return results, nav_problem


def write_index(out_dir, results):
    """截圖總覽（純文字 HTML；圖片用相對路徑）。"""
    rows = []
    for r in results:
        status = "✓" if not (r["errors"] or r["external"] or (r["overflow"] and r["viewport"] == "mobile")) else "✗"
        rows.append((r["name"], r["role"], r["viewport"], r.get("shot"), status))
    parts = ["<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width, initial-scale=1'>",
             "<title>示範站驗收截圖</title><style>body{font-family:sans-serif;margin:16px;background:#edeee6}"
             "section{margin:0 0 28px}h2{font-size:18px;margin:0 0 8px}.row{display:flex;flex-wrap:wrap;gap:12px}"
             "figure{margin:0;background:#fff;padding:6px;box-shadow:0 1px 3px #0003}"
             "figure img{display:block;max-height:420px;width:auto;max-width:100%}"
             "figcaption{font-size:12px;margin-top:4px}</style></head><body>",
             "<h1>示範站驗收截圖</h1><p>頁面 × 身分 × 畫面寬度；✗ 代表那一張有問題（看 report.json）。</p>"]
    by_page = {}
    for row in rows:
        by_page.setdefault(row[0], []).append(row)
    for name in by_page:
        parts.append("<section><h2>%s</h2><div class='row'>" % name)
        for _n, role, vp, shot, status in by_page[name]:
            if shot:
                parts.append("<figure><a href='%s'><img src='%s' loading='lazy' alt=''></a>"
                             "<figcaption>%s %s・%s</figcaption></figure>" % (shot, shot, status, role, vp))
        parts.append("</div></section>")
    parts.append("</body></html>")
    (out_dir / "index.html").write_text("\n".join(parts), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="用無頭 Chrome 驗收示範站：截圖、主控台錯誤、手機寬橫向溢出、零外部連線")
    ap.add_argument("--out", metavar="目錄", help="截圖輸出位置（預設：系統暫存資料夾裡的 cmw-verify/）")
    ap.add_argument("--clean", action="store_true", help="只刪掉截圖資料夾然後結束")
    a = ap.parse_args(argv)
    out_dir = Path(a.out).resolve() if a.out else DEFAULT_OUT

    if a.clean:
        if out_dir.exists():
            shutil.rmtree(str(out_dir))
            print("✓ 已刪除 %s" % out_dir)
        else:
            print("（%s 本來就不存在）" % out_dir)
        return 0

    chrome = cdp.find_chrome()
    if not chrome:
        print("SKIP：找不到 Chrome（或 Chromium）。裝了 Chrome 之後再跑一次；也可以用環境變數 CMW_CHROME 指定執行檔。")
        return 0

    if out_dir.exists():
        shutil.rmtree(str(out_dir))
    out_dir.mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp(prefix="cmw-verify-"))
    httpd = None
    browser = None
    results = []
    extra_problems = []
    try:
        demo_dir = build_site.build_demo(tmp / "demo")
        single = build_site.build_single_file(tmp / "demo-single.html")
        httpd, base = serve(demo_dir)
        browser = cdp.Browser(chrome)
        page = browser.new_page()
        for dom in ("Page", "Runtime", "Log", "Network"):
            page.send(dom + ".enable")
        page.send("Page.navigate", {"url": base + "index.html"})
        page.wait_for("window.CMW && CMW.getStore && document.documentElement.getAttribute('data-cmw-ready') === '1'",
                      timeout=20)
        info = page.evaluate("CMW.getStore().info")
        cats = page.evaluate("SITE_CONFIG.categories")
        pages = [
            ("home", "index.html"),
            ("blog", "blog.html"),
            ("category", "category.html?c=" + quote(cats[0])),
            ("post", "post.html?s=" + quote(info["posts"][0])),
            ("admin", "admin.html"),
            ("page-about", "page.html?id=about"),
            ("page-fun", "page.html?id=fun"),
            ("page-standalone", "page.html?id=family-notes"),
            ("gallery", "gallery.html"),
            ("album", "album.html?a=" + quote(info["albumWithPhotos"])),
            ("album-empty", "album.html?a=" + quote(info["albums"][-1])),
            ("private-list", "private.html"),
            ("private", "private.html?p=" + quote(info["privatePost"])),
            ("my-child", "my-child.html"),
            ("my-child-admin", "my-child.html#/admin"),
            ("my-child-seat", "my-child.html#/seat/01"),
            ("my-child-entry", "my-child.html#/entry/01/" + quote(info["teacherEntry"])),
            ("my-child-new", "my-child.html#/new/01"),
            ("courses", "courses.html"),
            ("teacher", "teacher.html"),
            ("teacher-seating", "teacher.html#/seating"),
            ("poem", "poem.html"),
            ("family-photos", "family-photos.html"),
            ("blog-print", "blog-print.html"),
            ("my-child-print", "my-child-print.html"),
        ]
        total = len(ROLES) * len(pages) * len(VIEWPORTS)
        n = 0
        for role, role_label, js in ROLES:
            set_role(page, base, js)
            for name, rel in pages:
                for vp in VIEWPORTS:
                    n += 1
                    shot = out_dir / ("%s__%s__%s.png" % (name, role, vp))
                    r = open_and_check(page, base + rel, vp, shot)
                    r.update({"name": name, "role": role, "shot": shot.name})
                    results.append(r)
                    bad = r["errors"] or r["external"] or (r["overflow"] and vp == "mobile")
                    print("%s [%d/%d] %-16s %-8s %-7s%s" % ("✗" if bad else "✓", n, total, name, role, vp,
                                                          "" if not bad else "  ← 有問題"))
        print("\n=== 互動：家長送留言、導師收起、燈箱 ===")
        p1 = interaction_check(page, base)
        print("✗ " + "；".join(p1) if p1 else "✓ 留言寫入與即時更新、導師收起留言、燈箱開關都正常；<script> 只是文字、網址是安全連結")
        print("\n=== 互動：相簿燈箱、影片預覽框、課程頁 ===")
        p2 = album_and_video_check(page, base, info)
        print("✗ " + "；".join(p2) if p2 else "✓ 相簿燈箱（點開、換張、Esc）、外部相簿連結、影片點了才載入（示範站只顯示說明）、課程大綱卡")
        print("\n=== 互動：我的孩子（發文照片去 EXIF、對話串、未讀、同仁、私密） ===")
        p3 = my_child_check(page, base, info)
        print("✗ " + "；".join(p3) if p3 else "✓ 家長發文：照片重新編碼後沒有 APP1／GPS、方向已轉正、內文逐字保留；對話串留言與收起；"
              "導師未讀亮起與熄掉、身分對回；同仁看不到對話串；非私密讀者看不到私密紀事")
        print("\n=== 互動：v1.1（座位表、個人照、匯出 PDF、每日一詩、家長被擋在導師限定頁外） ===")
        p4 = v11_check(page, base, info)
        print("✗ " + "；".join(p4) if p4 else "✓ 座位表切方案／切方向／點座位；個人照並排家長合照、左右換人；匯出 PDF 勾選、重篩、"
              "照片載完才開放列印（班級紀事、部落格一人一份與全班）；每日一詩今天與指定日期、行首空白保留；家長打開導師限定頁只看到說明")
        extra_problems += p1 + p2 + p3 + p4
        print("\n=== 單一 HTML（file://） ===")
        single_results, nav_problem = single_file_check(page, single, out_dir)
        extra_problems += nav_problem
        for r in single_results:
            bad = r["errors"] or r["external"] or r["overflow"]
            print("%s %-18s teacher mobile" % ("✗" if bad else "✓", r["name"]))
        results += single_results
        if not nav_problem:
            print("✓ 點導覽可以換頁（#/ 路由）")
    except cdp.CDPError as e:
        extra_problems.append("Chrome 操作失敗：%s" % e)
    finally:
        if browser:
            browser.close()
        if httpd:
            httpd.shutdown()
        shutil.rmtree(str(tmp), ignore_errors=True)

    write_index(out_dir, results)
    report = {"results": results, "problems": extra_problems}
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    failed = [r for r in results if r["errors"] or r["external"] or (r["overflow"] and r["viewport"] == "mobile")]
    desktop_overflow = [r for r in results if r["overflow"] and r["viewport"] == "desktop"]
    fonts = sorted({u for r in results for u in r["fontFailures"]})
    print("\n共 %d 次開頁；有問題 %d；桌機溢出 %d；其他問題 %d" % (len(results), len(failed), len(desktop_overflow),
                                                       len(extra_problems)))
    for r in failed + desktop_overflow:
        print("  ✗ %s／%s／%s" % (r["name"], r["role"], r["viewport"]))
        for e in r["errors"][:5]:
            print("      錯誤：%s" % e)
        for u in r["external"][:5]:
            print("      外部連線：%s" % u)
        if r["overflow"]:
            print("      橫向溢出：scrollWidth=%s、視窗=%s；%s" % (r["scrollWidth"], r["viewportWidth"],
                                                             "、".join(r["offenders"][:5])))
    for p in extra_problems:
        print("  ✗ %s" % p)
    if fonts:
        print("  提醒：Google Fonts 載不到（離線？），畫面改用系統字型：%d 個網址" % len(fonts))
    print("截圖：%s（總覽：index.html）" % out_dir)
    return 1 if (failed or desktop_overflow or extra_problems) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
