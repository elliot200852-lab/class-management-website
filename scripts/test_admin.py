#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_admin.py — 管理腳本的模擬器整合測試（開發與 CI 用；老師的電腦不需要跑這支）。

作者不開任何真雲端測試專案，所以管理腳本「真的寫得進資料庫、寫的形狀規則吃得下」只能在模擬器驗：

  1. 在暫存資料夾建一個虛構的班（學生 A～Y、@example.com 信箱；照片用 Pillow 當場畫，
     故意帶 GPS 與「要轉 90 度」的 EXIF）。
  2. 找 Java 21＋、Node.js 20＋（跟 scripts/test_rules.py 同一套，只找、不代裝），tests/rules 裡 npm ci。
  3. 用隨機的空閒埠啟動 Firestore 模擬器（專案 demo-cmw：保證不連任何真雲端），在裡面照老師的用法
     一支一支跑腳本：access_sync（預覽、--apply 兩次＝冪等、三道安全閘）、open_blogs、publish_post
     （預覽、--publish、沒加 --update 被擋、--update 保留 publishedAt、拿掉照片會刪舊照片）、
     publish_album、publish_blog（重複發文被擋、--update）、publish_private、publish_page；
     v1.1 的 publish_seating、publish_poems、publish_personal_photos、publish_parent_photo（預覽、--publish、略過、
     --update、--remove；家長合照也從部落格文章挑一張）。
  4. 每一份寫出來的文件都過 lib/schema.py（DATA-MODEL 欄位白名單）；每一張照片解回 JPEG，
     確認沒有 EXIF／GPS、直拍的真的轉正了。
  5. tests/rules/admin/readback.mjs：載入 build_config.py 產生的規則，用真的 Firebase JS SDK 以家長、
     同仁、私密讀者、導師身分讀回來，並用導師身分在瀏覽器端重建一篇腳本發的文章（規則放行＝形狀一致）。

用法：
  python3 scripts/test_admin.py            （Windows：py -3 scripts/test_admin.py）
  python3 scripts/test_admin.py --verbose  每一項都印
  python3 scripts/test_admin.py --keep     保留暫存資料夾（除錯用）
"""
import os
import sys
import json
import base64
import shutil
import socket
import tempfile
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))

from lib.console import setup_utf8  # noqa: E402

setup_utf8()

PROJECT = "demo-cmw"
POST = "2026-10-01-autumn-walk"
ALBUM = "2026-10-02-sports-day"
PRIVATE = "2026-10-04-note"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ════════════════════════════════════════════════════════════════════════
# 外層：準備資料、啟動模擬器
# ════════════════════════════════════════════════════════════════════════

def outer(a):
    import test_rules as tr
    import admin_support as fx
    from lib import images

    java, java_v, _ = tr.find_tool("java", tr.java_major, tr.MIN_JAVA)
    node, node_v, _ = tr.find_tool("node", tr.node_major, tr.MIN_NODE)
    if not java:
        tr.print_missing("java", java_v)
    if not node:
        tr.print_missing("node", node_v)
    if not java or not node:
        return 1
    npm = shutil.which("npm", path=os.path.dirname(node)) or shutil.which("npm")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([os.path.dirname(java), os.path.dirname(node), env.get("PATH", "")])
    for k in ("FIRESTORE_EMULATOR_HOST", "CMW_EMULATOR", "CMW_ROOT"):
        env.pop(k, None)
    if not npm or not tr.ensure_node_modules(npm, env, False):
        return 1
    firebase_js = tr.RULES_DIR / "node_modules" / "firebase-tools" / "lib" / "bin" / "firebase.js"
    if not firebase_js.exists():
        print("✗ 找不到 firebase-tools（npm ci 沒裝好？跑 python3 scripts/test_rules.py --reinstall）")
        return 1

    photos = images.have_pillow()
    if not photos:
        print("！ 沒裝 Pillow：照片相關的步驟略過（CI 會裝 Pillow 跑到）")
    tmp = Path(tempfile.mkdtemp(prefix="cmw-admin-"))
    try:
        root = fx.make_root(tmp / "root", photos=photos)
        r = subprocess.run([sys.executable, str(REPO / "scripts" / "build_config.py"), "--root", str(root)],
                           cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            print("✗ build_config.py 產生規則失敗")
            return 1
        fb = tmp / "fb"
        fb.mkdir()
        ports = {"firestore": free_port(), "hub": free_port(), "logging": free_port(), "ws": free_port()}
        (fb / "firebase.json").write_text(json.dumps({
            "firestore": {},
            "emulators": {"firestore": {"host": "127.0.0.1", "port": ports["firestore"], "websocketPort": ports["ws"]},
                          "hub": {"host": "127.0.0.1", "port": ports["hub"]},
                          "logging": {"host": "127.0.0.1", "port": ports["logging"]},
                          "ui": {"enabled": False}},
        }), encoding="utf-8")
        inner_cmd = '"%s" "%s" --inner --root "%s" --node "%s"%s%s' % (
            sys.executable, str(Path(__file__).resolve()), str(root), node,
            " --verbose" if a.verbose else "", "" if photos else " --no-photos")
        cmd = [node, str(firebase_js), "emulators:exec", "--only", "firestore", "--project", PROJECT, inner_cmd]
        print("… 啟動 Firestore 模擬器（專案 %s、埠 %d）並跑管理腳本整合測試" % (PROJECT, ports["firestore"]))
        sys.stdout.flush()
        r = subprocess.run(cmd, cwd=str(fb), env=env)
        if r.returncode != 0:
            print("\n✗ 管理腳本整合測試沒有全部通過（exit %d）。%s"
                  % (r.returncode, "暫存資料夾：%s" % tmp if a.keep else "加 --keep 可以保留暫存資料夾除錯。"))
            return 1
        print("\n✓ 管理腳本整合測試全部通過。")
        return 0
    finally:
        if a.keep:
            print("（保留暫存資料夾：%s）" % tmp)
        else:
            shutil.rmtree(str(tmp), ignore_errors=True)


# ════════════════════════════════════════════════════════════════════════
# 內層：在模擬器裡跑（emulators:exec 會設好 FIRESTORE_EMULATOR_HOST）
# ════════════════════════════════════════════════════════════════════════

class Runner(object):
    def __init__(self, root, verbose):
        self.root = Path(root)
        self.verbose = verbose
        self.passed = 0
        self.failed = 0

    def check(self, label, cond, detail=""):
        if cond:
            self.passed += 1
            if self.verbose:
                print("   ✓ %s" % label)
        else:
            self.failed += 1
            print("   ✗ %s%s" % (label, ("　→ " + detail) if detail else ""))
        return cond

    def run(self, script, *args, root=None):
        argv = [sys.executable, str(REPO / "scripts" / script)] + list(args) + ["--root", str(root or self.root)]
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        out = (r.stdout or "") + (r.stderr or "")
        if self.verbose:
            print("   $ %s %s" % (script, " ".join(args)))
            for line in out.splitlines()[-6:]:
                print("     | " + line)
        return r.returncode, out


def inner(a):
    from lib import schema, images, paths
    from lib import firestore_rest as fr
    from lib.emailkey import email_key
    import admin_support as fx

    host = os.environ.get("FIRESTORE_EMULATOR_HOST")
    if not host:
        print("✗ 沒有 FIRESTORE_EMULATOR_HOST：這一段只能在 emulators:exec 裡跑")
        return 2
    paths.set_root(a.root)
    photos = not a.no_photos
    R = Runner(a.root, a.verbose)
    c = fr.Client(PROJECT, emulator_host=host)
    all_mails = [fx.parent_mail(i) for i in range(25)] + [fx.mail("staff-1"), fx.TEACHER]
    names = ["學生 %s" % x for x in fx.LETTERS]

    def no_pii(out):
        return not any(m in out for m in all_mails) and not any(n in out for n in names)

    def snapshot(coll):
        return {d.id: (d.data, d.update_time) for d in c.list_docs(coll)}

    # ── 名單同步 ─────────────────────────────────────────────────────
    print("── access_sync.py")
    rc, out = R.run("access_sync.py")
    R.check("預覽 exit 0", rc == 0, out[-300:])
    R.check("預覽不寫任何東西", len(c.list_docs("allowlist")) == 0)
    R.check("輸出不含任何完整 email 或學生姓名", no_pii(out))
    rc, out = R.run("access_sync.py", "--apply")
    R.check("--apply exit 0", rc == 0, out[-400:])
    R.check("--apply 輸出不含 email／姓名", no_pii(out))
    allow = snapshot("allowlist")
    R.check("allowlist 30 人（25 母＋3 父＋同仁＋導師）", len(allow) == 30, str(len(allow)))
    aliases = [d.get("alias") for d, _ in allow.values()]
    R.check("每個人都有 12 碼代號、不重複", all(schema.ALIAS_RE.match(x or "") for x in aliases) and len(set(aliases)) == 30)
    tk = email_key(fx.TEACHER)
    R.check("導師 kind＝teacher、在私密名單", allow.get(tk, ({}, 0))[0].get("kind") == "teacher"
            and c.get("private_allowlist/" + tk) is not None)
    R.check("private_allowlist＝導師＋座號 01 的母", len(c.list_docs("private_allowlist")) == 2)
    cmap = snapshot("parent_child_map")
    R.check("parent_child_map 29 份（28 位家長＋同仁）", len(cmap) == 29, str(len(cmap)))
    staff = cmap.get(email_key(fx.mail("staff-1")), ({}, 0))[0]
    R.check("同仁對應座號 01、03、kind staff、沒有 relation",
            staff.get("seats") == ["01", "03"] and staff.get("kind") == "staff" and "relation" not in staff)
    pa = cmap.get(email_key(fx.parent_mail(0)), ({}, 0))[0]
    R.check("家長對應：seats [01]、relation 母、label 不含姓名",
            pa.get("seats") == ["01"] and pa.get("relation") == "母" and pa.get("label") == "座號 01 家長")
    ros = c.get("roster/students")
    R.check("roster/students 25 位", ros is not None and len(ros.data.get("students", [])) == 25)
    R.check("config/site 有導師稱呼", (c.get("config/site") or fr.Doc("", {})).data.get("teacherDisplayName") == "示範導師")

    rc, out = R.run("access_sync.py", "--apply")
    R.check("第二次 --apply：零變更", rc == 0 and "已經跟本機一致" in out, out[-300:])
    R.check("第二次之後名單文件一份都沒被改寫（代號沿用）", snapshot("allowlist") == allow)
    rc, out = R.run("access_sync.py", "--check")
    R.check("--check 包含關係成立", rc == 0 and "成立" in out, out[-300:])

    # 安全閘：用另一份 root（同一個 config、同一個資料庫）
    g = Path(a.root).parent / "gate"
    shutil.copytree(str(Path(a.root) / "config"), str(g / "config"))
    shutil.copytree(str(Path(a.root) / "data"), str(g / "data"),
                    ignore=shutil.ignore_patterns("*.jpg", "class-posts", "albums", "blog-drafts"))
    fx.write(g / "data" / "contacts.csv", fx.contacts_csv(drop=range(5, 25)))
    rc, out = R.run("access_sync.py", "--apply", root=g)
    R.check("contacts.csv 被截斷 → 停下（exit 2）", rc == 2 and "下限" in out, out[-300:])
    R.check("截斷時一筆都沒動", snapshot("allowlist") == allow)
    (g / "data" / "contacts.csv").unlink()
    rc, out = R.run("access_sync.py", "--apply", root=g)
    R.check("contacts.csv 不見了 → 停下（不當成全部刪除）", rc == 2 and snapshot("allowlist") == allow, out[-300:])
    fx.write(g / "data" / "contacts.csv", fx.contacts_csv() + "05,舅舅,某人,%s,,,\n" % fx.mail("uncle-e")
             + "15,母,某人,%s,,,\n" % fx.mail("typo-e"))
    rc, out = R.run("access_sync.py", root=g)
    R.check("預覽列出「沒宣告的稱謂」與「同座號同稱謂兩個信箱」提醒", rc == 0 and "沒有寫在 parent-roles.yaml" in out
            and "座號 15 的「母」有 2 個不同的信箱" in out and snapshot("allowlist") == allow, out[-400:])
    drop = (20, 21, 22, 23)
    fx.write(g / "data" / "contacts.csv", fx.contacts_csv(drop=drop))
    roles = fx.roles_yaml().replace('"21": [母]', '"21": []').replace('"22": [母]', '"22": []') \
        .replace('"23": [母]', '"23": []').replace('"24": [母]', '"24": []')
    fx.write(g / "data" / "parent-roles.yaml", roles)
    rc, out = R.run("access_sync.py", "--apply", root=g)
    R.check("一次要讓 4 人失去權限（上限 3）→ 停下", rc == 2 and "--max-deletes 4" in out and snapshot("allowlist") == allow,
            out[-300:])
    rc, out = R.run("access_sync.py", "--apply", "--max-deletes", "4", root=g)
    after = snapshot("allowlist")
    R.check("明示 --max-deletes 4 才移除 4 人", rc == 0 and len(after) == 26, out[-300:])
    R.check("其他人的代號都沒變", all(after[k][0]["alias"] == allow[k][0]["alias"] for k in after))
    hist = (g / "data" / "ledgers" / "alias-history.jsonl")
    R.check("被移除的人的代號記進本機台帳", hist.exists() and len(hist.read_text(encoding="utf-8").splitlines()) == 4)
    rc, out = R.run("access_sync.py", "--apply")
    R.check("恢復原名單", rc == 0 and len(c.list_docs("allowlist")) == 30, out[-300:])
    teacher_alias = c.get("allowlist/" + tk).data["alias"]
    pa_alias = c.get("allowlist/" + email_key(fx.parent_mail(0))).data["alias"]

    # ── 開部落格 ─────────────────────────────────────────────────────
    print("── open_blogs.py")
    rc, out = R.run("open_blogs.py")
    R.check("預覽不寫", rc == 0 and len(c.list_docs("student_blogs")) == 0, out[-300:])
    R.check("輸出不含學生姓名", no_pii(out))
    rc, out = R.run("open_blogs.py", "--apply")
    R.check("--apply 開 25 個", rc == 0 and len(c.list_docs("student_blogs")) == 25, out[-300:])
    rc, out = R.run("open_blogs.py", "--apply")
    R.check("再跑一次：都開好了", rc == 0 and "都開好了" in out, out[-300:])

    # ── 班級紀事 ─────────────────────────────────────────────────────
    print("── publish_post.py")
    md = Path(a.root) / "data" / "class-posts" / (POST + ".md")
    rc, out = R.run("publish_post.py", POST)
    R.check("預覽 exit 0、產生預覽檔、不寫", rc == 0 and (Path(a.root) / "exports" / "preview" / ("post-%s.html" % POST)).exists()
            and c.get("posts/" + POST) is None, out[-300:])
    rc, out = R.run("publish_post.py", POST, "--publish")
    s1 = c.get("posts/" + POST)
    R.check("--publish 上線", rc == 0 and s1 is not None and s1.data.get("visible") is True, out[-400:])
    rc, out = R.run("publish_post.py", POST, "--publish")
    R.check("已上線再發、沒加 --update → 擋下", rc == 2 and "--update" in out, out[-300:])
    md.write_text(md.read_text(encoding="utf-8").replace("title: 秋天的散步", "title: 秋天的散步（改）"), encoding="utf-8")
    rc, out = R.run("publish_post.py", POST, "--publish", "--update")
    s2 = c.get("posts/" + POST)
    R.check("--update 改標題", rc == 0 and s2.data.get("title") == "秋天的散步（改）", out[-300:])
    R.check("--update 保留第一次的 publishedAt", s2.data.get("publishedAt") == s1.data.get("publishedAt"))
    if photos:
        cover = s1.data.get("coverPid")
        R.check("有封面縮圖、照片 1 張", cover and s1.data.get("coverThumb") and s1.data.get("photoCount") == 1)
        text = md.read_text(encoding="utf-8")
        md.write_text(text.replace("![落葉堆](leaves.jpg)\n", ""), encoding="utf-8")
        rc, out = R.run("publish_post.py", POST, "--publish", "--update")
        R.check("拿掉照片再發：舊照片兩份都刪掉", rc == 0 and not c.list_docs("posts/%s/thumbs" % POST)
                and not c.list_docs("posts/%s/images" % POST) and c.get("posts/" + POST).data.get("coverPid") is None, out[-300:])
        md.write_text(text, encoding="utf-8")
        rc, out = R.run("publish_post.py", POST, "--publish", "--update")
        R.check("放回照片：同一張照片得到同一個 pid", rc == 0 and c.get("posts/" + POST).data.get("coverPid") == cover, out[-300:])
    R.check("本機索引 index.md 有這篇", POST in (Path(a.root) / "data" / "class-posts" / "index.md").read_text(encoding="utf-8"))

    # ── 相簿 ─────────────────────────────────────────────────────────
    print("── publish_album.py")
    rc, out = R.run("publish_album.py", ALBUM, "--publish")
    alb = c.get("albums/" + ALBUM)
    R.check("相簿上線", rc == 0 and alb is not None and len(alb.data.get("videos", [])) == 1, out[-400:])
    if photos:
        th = sorted((d.data for d in c.list_docs("albums/%s/thumbs" % ALBUM)), key=lambda x: x["order"])
        R.check("2 張、order 0/1、第一張有圖說", [t["order"] for t in th] == [0, 1] and th[0].get("caption") == "起跑"
                and "caption" not in th[1])

    # ── 部落格（導師替座號 01 發）─────────────────────────────────────
    print("── publish_blog.py")
    rc, out = R.run("publish_blog.py", "--seat", "1", "math-day", "--publish")
    ents = c.list_docs("student_blogs/01/entries")
    R.check("發文成功、postId 格式對", rc == 0 and len(ents) == 1 and schema.POST_ID_RE.match(ents[0].id), out[-400:])
    entry = ents[0] if ents else fr.Doc("x/y", {})
    R.check("正文逐字保留（段內縮排與空行）", entry.data.get("body") == "今天他在數學課上\n  很專心。\n\n謝謝！")
    R.check("作者＝導師、代號＝導師的 alias", entry.data.get("author") == "teacher" and entry.data.get("authorAlias") == teacher_alias)
    rc, out = R.run("publish_blog.py", "--seat", "1", "math-day", "--publish")
    R.check("同一份草稿再發 → 擋下", rc == 2 and len(c.list_docs("student_blogs/01/entries")) == 1, out[-300:])
    bmd = Path(a.root) / "data" / "blog-drafts" / "01" / "math-day.md"
    bmd.write_text(bmd.read_text(encoding="utf-8").replace("謝謝！", "謝謝大家！"), encoding="utf-8")
    rc, out = R.run("publish_blog.py", "--seat", "1", "math-day", "--publish", "--update")
    e2 = c.get(entry.path)
    R.check("--update 只改正文、同一篇", rc == 0 and e2 and e2.data["body"].endswith("謝謝大家！")
            and isinstance(e2.data.get("updatedAt"), fr.Timestamp), out[-300:])
    ledger = Path(a.root) / "data" / "ledgers" / "blog-posts.jsonl"
    saved = ledger.read_text(encoding="utf-8")
    ledger.unlink()
    rc, out = R.run("publish_blog.py", "--seat", "1", "math-day", "--publish")
    R.check("本機台帳不見了也擋得住重複發文（查雲端同標題同日期）", rc == 2 and len(c.list_docs("student_blogs/01/entries")) == 1,
            out[-300:])
    ledger.write_text(saved, encoding="utf-8")
    rc, out = R.run("publish_blog.py", "--seat", "2", "no-such-draft")
    R.check("找不到草稿 → 停下", rc == 2, out[-200:])

    # ── 私密紀事、單頁 ───────────────────────────────────────────────
    print("── publish_private.py、publish_page.py")
    rc, out = R.run("publish_private.py", PRIVATE, "--publish")
    R.check("私密紀事上線", rc == 0 and c.get("private_posts/" + PRIVATE) is not None, out[-300:])
    rc, out = R.run("publish_private.py", "--viewers")
    R.check("--viewers 唯讀：私密讀者 1 位", rc == 0 and "私密讀者 1 位" in out, out[-300:])
    for pid in ("about", "fun"):
        rc, out = R.run("publish_page.py", pid, "--publish")
        R.check("單頁 %s 上線" % pid, rc == 0 and c.get("pages/" + pid) is not None, out[-300:])
    fun = c.get("pages/fun")
    R.check("專題活動：2 張卡片", fun and len(fun.data.get("data", {}).get("cards", [])) == 2)

    # ── v1.1：座位表、個人照、家長合照、每日一詩 ───────────────────────
    v11 = v11_scripts(R, c, a.root, fx, photos, entry)

    # ── 每一份文件過欄位白名單、每一張照片沒有 EXIF ───────────────────
    print("── 欄位白名單與照片檢查")
    probs = []

    def chk(kind, d, **kw):
        for p in schema.problems(kind, d.data, **kw):
            probs.append("%s：%s" % (d.path, p))

    for coll, kind in (("allowlist", "allowlist"), ("private_allowlist", "private_allowlist"),
                       ("parent_child_map", "parent_child_map"), ("student_blogs", "student_blog"),
                       ("posts", "post"), ("albums", "album"), ("private_posts", "private_post"), ("pages", "page"),
                       ("seating", "seating"), ("personal_photos", "personal_photos"),
                       ("parent_photo_display", "parent_photo_display")):
        for d in c.list_docs(coll):
            chk(kind, d)
    chk("roster_students", c.get("roster/students"))
    chk("config_site", c.get("config/site"))
    chk("post_content", c.get("posts/%s/content/main" % POST))
    owners = ["posts/" + POST, "albums/" + ALBUM, "private_posts/" + PRIVATE, "pages/fun", "pages/about"]
    owners += [d.path for d in c.list_docs("personal_photos")] + [d.path for d in c.list_docs("parent_photo_display")]
    photo_docs = []
    for o in owners:
        for d in c.list_docs(o + "/thumbs"):
            chk("thumb", d)
            photo_docs.append(d)
        for d in c.list_docs(o + "/images"):
            chk("image", d)
            photo_docs.append(d)
    for e in c.list_docs("student_blogs/01/entries"):
        chk("entry", fr.Doc(e.path, dict(e.data, visible=True)))
        for d in c.list_docs(e.path + "/thumbs"):
            chk("blog_thumb", d, pid=d.id)
            photo_docs.append(d)
        for d in c.list_docs(e.path + "/images"):
            chk("blog_image", d)
            photo_docs.append(d)
    R.check("每一份文件都符合 DATA-MODEL 欄位白名單（%d 項問題）" % len(probs), not probs, "；".join(probs[:5]))
    if photos:
        bad = []
        from PIL import Image
        import io
        for d in photo_docs:
            raw = base64.b64decode(d.data["data"])
            if images.metadata_markers(raw):
                bad.append(d.path)
                continue
            with Image.open(io.BytesIO(raw)) as im:
                if len(im.getexif()) or im.info.get("icc_profile") or (im.size != (d.data["w"], d.data["h"])):
                    bad.append(d.path)
        R.check("每一張照片（%d 份）都沒有 EXIF／GPS／ICC，尺寸欄位正確" % len(photo_docs), photo_docs and not bad, "、".join(bad[:3]))
        cover = c.get("posts/" + POST).data["coverPid"]
        img = c.get("posts/%s/images/%s" % (POST, cover)).data
        R.check("直拍（EXIF 方向 6）的照片轉正成直的 960×1280", (img["w"], img["h"]) == (960, 1280), "%sx%s" % (img["w"], img["h"]))
        bimg = c.get(entry.path + "/images/0").data
        R.check("EXIF 方向 8 的照片也轉正（800×1000）", (bimg["w"], bimg["h"]) == (800, 1000), "%sx%s" % (bimg["w"], bimg["h"]))

    # ── 真規則＋真 SDK 讀回 ─────────────────────────────────────────
    print("── 真規則＋真 Firebase JS SDK 讀回（tests/rules/admin/readback.mjs）")
    manifest = {
        "projectId": PROJECT, "rulesFile": str(Path(a.root) / "firestore.rules"), "verbose": a.verbose,
        "teacher": fx.TEACHER, "parentA": fx.parent_mail(0), "parentY": fx.parent_mail(24), "staff": fx.mail("staff-1"),
        "parentAKey": email_key(fx.parent_mail(0)), "parentYKey": email_key(fx.parent_mail(24)),
        "parentAAlias": pa_alias, "teacherAlias": teacher_alias,
        "post": POST, "postCover": c.get("posts/" + POST).data.get("coverPid"), "album": ALBUM,
        "albumPhotos": len(c.list_docs("albums/%s/thumbs" % ALBUM)), "private": PRIVATE, "entryId": entry.id,
        "v11": v11,
    }
    mpath = Path(a.root).parent / "readback.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([a.node, str(REPO / "tests" / "rules" / "admin" / "readback.mjs")],
                       env=dict(os.environ, CMW_READBACK_MANIFEST=str(mpath)),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("\n".join("   " + ln for ln in (r.stdout + r.stderr).strip().splitlines()[-25:]))
    R.check("讀回檢查全過", r.returncode == 0)

    # ── 備份、還原、資料退場（tests/emulator_backup.py；接在上面種好的虛構班級後面）─────────
    import emulator_backup
    emulator_backup.run(R, c, a.root, fx, host, photos=photos, verbose=a.verbose)
    if photos:
        # 上面的資料退場（座號 03 轉出）也要處理 v1.1 的本機照片（檔名只用座號）
        pp = Path(a.root) / "data" / "personal-photos"
        R.check("資料退場（座號 03）：本機 data/personal-photos/03.jpg 移到垃圾桶、其他座號的照片沒動",
                not (pp / "03.jpg").exists() and (pp / "01.jpg").exists() and (pp / "2.jpg").exists())

    print("\n管理腳本整合測試：通過 %d、失敗 %d" % (R.passed, R.failed))
    return 0 if R.failed == 0 and R.passed > 0 else 1


SEATING = {"title": "十月的座位", "note": "第一排靠黑板",
           "rows": [["01", "02", "-", "03", "04"], ["05", "", "-", "06", "07"]]}
POEM_MD = """---
date: %s
title: %s
author: 示範文字
source: 示範用自寫短句
rights: 自己寫的
---
第一行
  第二行（前面兩個空白）

## 導讀
示範導讀。
"""


def v11_scripts(R, c, root, fx, photos, entry):
    """v1.1 的四支腳本：預覽不寫、--publish、一樣的略過、改過要 --update、拿掉。回給讀回檢查用的資訊。"""
    root = Path(root)
    d = root / "data"
    print("── publish_seating.py")
    fx.write(d / "seating" / "2026-10-01.json", json.dumps(SEATING, ensure_ascii=False))
    rc, out = R.run("publish_seating.py")
    R.check("座位表預覽 exit 0、不寫、輸出只有座號", rc == 0 and not c.list_docs("seating") and "[01][02]" in out
            and "學生 A" not in out, out[-300:])
    rc, out = R.run("publish_seating.py", "--publish")
    plan = c.get("seating/2026-10-01")
    R.check("座位表上線：rows 包一層 {seats}、走道與空位照寫", rc == 0 and plan is not None
            and plan.data.get("rows") == [{"seats": r} for r in SEATING["rows"]], out[-300:])
    rc, out = R.run("publish_seating.py", "--publish")
    R.check("再發一次一樣的：略過", rc == 0 and "已經是最新的" in out, out[-200:])
    fx.write(d / "seating" / "2026-10-01.json", json.dumps(dict(SEATING, title="十月（改）"), ensure_ascii=False))
    rc, out = R.run("publish_seating.py", "--publish")
    R.check("改過沒加 --update → 擋下", rc == 2 and c.get("seating/2026-10-01").data["title"] == "十月的座位", out[-200:])
    rc, out = R.run("publish_seating.py", "--publish", "--update")
    R.check("--update 改好", rc == 0 and c.get("seating/2026-10-01").data["title"] == "十月（改）", out[-200:])
    fx.write(d / "seating" / "2026-11-01.json", json.dumps({"title": "要拿掉的", "rows": [["01"]]}, ensure_ascii=False))
    R.run("publish_seating.py", "2026-11-01", "--publish")
    rc, out = R.run("publish_seating.py", "--remove", "2026-11-01", "--publish")
    R.check("--remove 從網站拿掉一個方案（本機的檔不動）", rc == 0 and c.get("seating/2026-11-01") is None
            and (d / "seating" / "2026-11-01.json").exists(), out[-200:])
    (d / "seating" / "2026-11-01.json").unlink()

    print("── publish_poems.py")
    fx.write(d / "poems" / "2026-10-01.md", POEM_MD % ("2026-10-01", "早晨（示範）"))
    fx.write(d / "poems" / "2026-10-02.md", (POEM_MD % ("2026-10-02", "雨（示範）")).replace("rights: 自己寫的\n", ""))
    rc, out = R.run("publish_poems.py", "2026-10", "--publish")
    R.check("有一首 rights 空白 → 擋下、不寫", rc == 2 and c.get("pages/poems-2026-10") is None, out[-300:])
    fx.write(d / "poems" / "2026-10-02.md", POEM_MD % ("2026-10-02", "雨（示範）"))
    rc, out = R.run("publish_poems.py", "2026-10", "--publish")
    pg = c.get("pages/poems-2026-10")
    items = (pg.data.get("data") or {}).get("items", []) if pg else []
    R.check("每日一詩上線：一個月一份、2 首、正文逐字（行首空白）、有導讀", rc == 0 and len(items) == 2
            and items[0]["text"] == "第一行\n  第二行（前面兩個空白）" and items[0].get("guide") == "示範導讀。", out[-300:])

    info = {"seating": "2026-10-01", "poemPage": "poems-2026-10"}
    if not photos:
        return info
    print("── publish_personal_photos.py")
    pp = d / "personal-photos"
    fx.make_jpeg(pp / "01.jpg", (1200, 1600), orientation=1, seed=11)
    fx.make_jpeg(pp / "2.jpg", (1600, 1200), orientation=6, seed=12, gps=True)
    fx.make_jpeg(pp / "03.jpg", (900, 1200), orientation=1, seed=13)
    rc, out = R.run("publish_personal_photos.py")
    R.check("個人照預覽 exit 0、不寫", rc == 0 and not c.list_docs("personal_photos"), out[-300:])
    rc, out = R.run("publish_personal_photos.py", "--publish")
    docs = {x.id: x.data for x in c.list_docs("personal_photos")}
    R.check("個人照上線 3 位（檔名 2.jpg → 座號 02）", rc == 0 and sorted(docs) == ["01", "02", "03"], out[-300:])
    img = c.get("personal_photos/02/images/" + docs.get("02", {}).get("photoPids", ["x"])[0]) if "02" in docs else None
    R.check("EXIF 方向 6 的個人照轉正成直的 960×1280", img is not None and (img.data["w"], img.data["h"]) == (960, 1280))
    rc, out = R.run("publish_personal_photos.py", "--publish")
    R.check("再發一次：3 位都略過", rc == 0 and "已經是最新的" in out, out[-200:])
    fx.make_jpeg(pp / "01.jpg", (1000, 1000), orientation=1, seed=14)
    rc, out = R.run("publish_personal_photos.py", "--publish")
    R.check("換了照片沒加 --update → 擋下", rc == 2, out[-200:])
    old = docs["01"]["photoPids"][0]
    rc, out = R.run("publish_personal_photos.py", "--publish", "--update")
    new = c.get("personal_photos/01").data["photoPids"][0]
    R.check("--update 換照片：新 pid、舊的兩份刪掉", rc == 0 and new != old
            and c.get("personal_photos/01/images/" + old) is None and c.get("personal_photos/01/thumbs/" + old) is None,
            out[-200:])

    print("── publish_parent_photo.py")
    src = fx.make_jpeg(d / "parent-photos" / "01.jpg", (1600, 1200), orientation=3, seed=15)
    rc, out = R.run("publish_parent_photo.py", "--seat", "1", "--from-file", str(src), "--publish")
    pdoc = c.get("parent_photo_display/01")
    R.check("家長合照上線：稱謂取自 parent-roles.yaml（母、父），不存姓名", rc == 0 and pdoc is not None
            and pdoc.data.get("relations") == ["母", "父"] and "names" not in pdoc.data, out[-300:])
    rc, out = R.run("publish_parent_photo.py", "--seat", "1", "--from-blog", entry.id, "--who", "母", "--note", "取自部落格",
                    "--publish", "--update")
    p2 = c.get("parent_photo_display/01")
    R.check("從部落格文章挑一張（重新處理、清中繼資料）＋ --who 只標母", rc == 0 and p2.data.get("relations") == ["母"]
            and p2.data.get("note") == "取自部落格" and p2.data["photoPids"] != pdoc.data["photoPids"], out[-300:])
    info.update({"personalSeat": "01", "parentSeat": "01"})
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description="管理腳本的模擬器整合測試（需要 Java 21＋、Node.js 20＋）")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--keep", action="store_true", help="保留暫存資料夾")
    ap.add_argument("--inner", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--root", help=argparse.SUPPRESS)
    ap.add_argument("--node", help=argparse.SUPPRESS)
    ap.add_argument("--no-photos", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.inner:
        return inner(a)
    return outer(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
