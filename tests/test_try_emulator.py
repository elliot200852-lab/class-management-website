#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""先試玩（scripts/try_emulator.py）不啟動模擬器的部分：色塊 JPEG、找 Java（Mac 的空殼不跑）、模擬器本體放哪裡
（假的 HOME）、試玩資料夾的記號與安全、虛構班級的設定與名單檔、示範內容轉成資料庫文件、缺工具時只印官方連結。
全部在暫存資料夾裡做，不碰這份 repo 的 try/、不碰真的個人資料夾。"""
import io
import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import try_emulator as te  # noqa: E402
from lib import sources, paths  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402


def sof_size(data):
    """從 JPEG 的 SOF0 讀寬高。"""
    i = data.index(b"\xff\xc0")
    return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cmw-try-test-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        paths.reset_root()
        shutil.rmtree(str(self.tmp), ignore_errors=True)


class TestJpeg(unittest.TestCase):
    def test_shape_and_markers(self):
        for w, h in ((320, 240), (240, 320), (1280, 960), (17, 9)):
            b = te.jpeg_scene(w, h, 3)
            self.assertTrue(b.startswith(b"\xff\xd8") and b.endswith(b"\xff\xd9"))
            self.assertEqual(sof_size(b), (w, h))
        self.assertEqual(te.jpeg_scene(320, 240, 1), te.jpeg_scene(320, 240, 1), "同樣的輸入同樣的圖")
        self.assertNotEqual(te.jpeg_scene(320, 240, 1), te.jpeg_scene(320, 240, 2))

    def test_decodes_with_pillow_when_available(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("沒裝 Pillow")
        im = Image.open(io.BytesIO(te.jpeg_scene(320, 240, 0)))
        im.load()
        self.assertEqual(im.size, (320, 240))
        sky = im.convert("RGB").getpixel((2, 2))
        self.assertTrue(all(abs(a - b) <= 6 for a, b in zip(sky, te._PALETTES[0][0])), sky)


class TestFindTools(Tmp):
    def test_mac_stub_java_is_not_run(self):
        ran = []
        found = [("/usr/bin/java", True), ("/opt/homebrew/opt/openjdk/bin/java", False)]

        def major(path):
            ran.append(path)
            return 21
        import test_rules as tr
        with mock.patch.object(te.hostos, "OS", "mac"), \
                mock.patch.object(te.hostos, "find_exe_all", return_value=found), \
                mock.patch.object(te, "_mac_has_jdk", return_value=False), \
                mock.patch.object(tr, "java_major", side_effect=major):
            path, v = te.find_java()
        self.assertEqual(path, "/opt/homebrew/opt/openjdk/bin/java")
        self.assertEqual(ran, ["/opt/homebrew/opt/openjdk/bin/java"], "沒裝 JDK 時不跑 /usr/bin/java（會跳視窗）")

    def test_too_old_java_reported(self):
        import test_rules as tr
        with mock.patch.object(te.hostos, "OS", "linux"), \
                mock.patch.object(te.hostos, "find_exe_all", return_value=[("/x/java", True)]), \
                mock.patch.object(tr, "java_major", return_value=17):
            path, seen = te.find_java()
        self.assertIsNone(path)
        self.assertIn("太舊", seen[0])

    def test_emulator_cache_uses_fake_home(self):
        info = te.RULES_DIR / "node_modules" / "firebase-tools" / "lib" / "emulator" / "downloadableEmulatorInfo.json"
        if not info.is_file():
            self.assertEqual(te.emulator_cache(self.home), te.RULES_DIR / "node_modules" / ".cmw-emulators")
            return
        rel = json.loads(info.read_text(encoding="utf-8"))["firestore"]["downloadPathRelativeToCacheDir"]
        self.assertEqual(te.emulator_cache(self.home), te.RULES_DIR / "node_modules" / ".cmw-emulators",
                         "個人資料夾沒有 → 下載到這個資料夾裡")
        jar = self.home / ".cache" / "firebase" / "emulators" / rel
        jar.parent.mkdir(parents=True)
        jar.write_bytes(b"x")
        self.assertIsNone(te.emulator_cache(self.home), "個人資料夾已經有同一版 → 直接用")

    def test_check_prints_official_links_only(self):
        buf = io.StringIO()
        with mock.patch.object(te, "find_java", return_value=(None, [])), \
                mock.patch.object(te, "find_node", return_value=(None, [])), \
                mock.patch.object(te, "tools_ready", return_value=False), \
                mock.patch.object(te, "port_busy", return_value=False), redirect_stdout(buf):
            rc = te.main(["--check"])
        out = buf.getvalue()
        self.assertEqual(rc, te.EXIT_STOPPED)
        self.assertIn("https://adoptium.net/", out)
        self.assertIn("https://nodejs.org/en/download", out)
        self.assertNotIn("npm install -g", out.replace("不用 npm install -g", ""))

    def test_start_stops_before_download_without_consent(self):
        buf = io.StringIO()
        with mock.patch.object(te, "find_java", return_value=("/j/java", 21)), \
                mock.patch.object(te, "find_node", return_value=("/n/node", 22)), \
                mock.patch.object(te.shutil, "which", return_value="/n/npm"), \
                mock.patch.object(te, "tools_ready", return_value=False), \
                mock.patch.object(te, "make_root", side_effect=AssertionError("還沒同意下載就不該建資料夾")), \
                mock.patch.object(te, "download_tools", side_effect=AssertionError("沒加 --download 不下載")), \
                redirect_stdout(buf):
            rc = te.main(["--no-open"])
        self.assertEqual(rc, te.EXIT_STOPPED)
        self.assertIn("--download", buf.getvalue())
        self.assertIn("不會安裝到電腦的其他地方", buf.getvalue())

    def test_start_stops_when_ports_busy(self):
        buf = io.StringIO()
        with mock.patch.object(te, "find_java", return_value=("/j/java", 21)), \
                mock.patch.object(te, "find_node", return_value=("/n/node", 22)), \
                mock.patch.object(te.shutil, "which", return_value="/n/npm"), \
                mock.patch.object(te, "tools_ready", return_value=True), \
                mock.patch.object(te, "port_busy", return_value=True), \
                mock.patch.object(te, "make_root", side_effect=AssertionError("埠被占用就不該建資料夾")), \
                redirect_stdout(buf):
            rc = te.main(["--no-open"])
        self.assertEqual(rc, te.EXIT_STOPPED)
        self.assertIn("--status", buf.getvalue())


class TestTryFolder(Tmp):
    def test_marker_protects_foreign_folder(self):
        root = self.tmp / "try"
        root.mkdir()
        (root / "mine.txt").write_text("老師自己的", encoding="utf-8")
        with self.assertRaises(te.Stop):
            te.make_root(root)
        self.assertTrue((root / "mine.txt").exists(), "不是試玩建的資料夾不動")
        te.remove_root(root)
        self.assertTrue(root.exists(), "沒有記號就不刪")
        shutil.rmtree(str(root))
        te.make_root(root)
        (root / "left-over.txt").write_text("x", encoding="utf-8")
        te.make_root(root)
        self.assertFalse((root / "left-over.txt").exists(), "上次沒收乾淨的試玩資料夾整個重建")
        te.remove_root(root)
        self.assertFalse(root.exists())

    def test_prepare_and_class_files(self):
        root = te.make_root(self.tmp / "try")
        cfg, www = te.prepare(root)
        self.assertTrue(cfg["firebase"]["project_id"].startswith("demo-"))
        gen = (www / "js" / "site-config.js").read_text(encoding="utf-8")
        self.assertIn("emulator: true", gen)
        self.assertIn('"%s"' % te.PROJECT_ID, gen)
        self.assertTrue((www / "index.html").is_file())
        self.assertTrue((root / "firestore.rules").is_file())
        fb = json.loads((root / "firebase.json").read_text(encoding="utf-8"))
        self.assertEqual(fb["emulators"]["firestore"]["port"], 8080)
        self.assertEqual(fb["emulators"]["auth"]["port"], 9099)
        self.assertTrue(fb["emulators"]["singleProjectMode"])
        self.assertFalse((REPO / "site" / "js" / "site-config.js").exists()
                         and "emulator: true" in (REPO / "site" / "js" / "site-config.js").read_text(encoding="utf-8"),
                         "絕不寫進 repo 本身的網站設定")
        data = te.class_files(root)
        roster, _ = sources.load_roster(data / "roster.csv")
        contacts, _ = sources.load_contacts(data / "contacts.csv")
        roles = sources.load_roles(data / "parent-roles.yaml")
        self.assertEqual([s.seat for s in roster], ["%02d" % i for i in range(1, 26)])
        self.assertEqual(roster[0].display, "學生 A")
        parents = [c for c in contacts if not c.staff]
        self.assertEqual(len(parents), 25)
        self.assertTrue(all(c.key.endswith("@example.com") for c in contacts))
        self.assertEqual([c.seat for c in contacts if c.private], ["01"])
        self.assertEqual(roles["01"], ["母"])
        self.assertEqual(roles["02"], ["父"])

    def test_demo_docs_become_firestore_docs(self):
        import test_rules as tr
        node, _v, _p = tr.find_tool("node", tr.node_major, tr.MIN_NODE)
        if not node:
            self.skipTest("沒有 Node.js")
        docs, info = te.demo_docs(node, "2026-10-20", ["班級生活", "學習活動"], self.tmp)
        by = dict(docs)
        self.assertIn("allowlist/" + te.TEACHER_EMAIL, by)
        self.assertEqual(by["allowlist/" + te.TEACHER_EMAIL]["kind"], "teacher")
        n = te.fill_photos(docs)
        photos = [(p, d) for p, d in docs if p.split("/")[-2] in ("images", "thumbs")]
        self.assertEqual(n, len(photos))
        self.assertTrue(photos)
        for p, d in photos[:5]:
            import base64
            self.assertEqual(sof_size(base64.b64decode(d["data"])), (d["w"], d["h"]), p)
        post = by["posts/" + info["posts"][0]]
        self.assertTrue(post["coverPid"] and isinstance(post["coverThumb"], dict) and post["coverThumb"]["data"],
                        "封面縮圖照正式網站的形狀補上（coverPid 與 coverThumb 同時有）")
        conv = te.to_fs(post)
        self.assertIsInstance(conv["publishedAt"], fr.Timestamp)
        self.assertEqual(conv["title"], post["title"])
        emails = json.dumps(docs, ensure_ascii=False)
        self.assertNotRegex(emails, r"@(?!example\.com)[a-z0-9.-]+\.[a-z]{2,}", "示範內容只有 example.com 信箱")


class TestUsage(unittest.TestCase):
    def test_usage_mentions_root_and_emulator(self):
        text = "\n".join(te.usage_lines("http://127.0.0.1:8765/"))
        self.assertIn("--root try --emulator", text)
        self.assertIn("http://127.0.0.1:8765/", text)
        self.assertIn("Ctrl-C", text)
        for _, email, name, _ in te.ACCOUNTS:
            self.assertIn(email, text)
            self.assertTrue(email.endswith("@example.com"))


if __name__ == "__main__":
    unittest.main()
