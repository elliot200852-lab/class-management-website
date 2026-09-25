#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""照片處理（scripts/lib/images.py）。沒裝 Pillow 就整組略過（CI 會裝 Pillow 跑到）。

測試用的照片**執行時才畫**，寫進 GPS 與方向 EXIF 後存在暫存資料夾；repo 裡不放任何圖檔。
"""
import io
import sys
import base64
import shutil
import hashlib
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
from lib import images  # noqa: E402

HAVE = images.have_pillow()


def decode(enc):
    return base64.b64decode(enc.data)


@unittest.skipUnless(HAVE, "沒裝 Pillow（CI 會裝）")
class TestImages(unittest.TestCase):
    def setUp(self):
        import admin_support as fx
        self.fx = fx
        self.tmp = Path(tempfile.mkdtemp(prefix="cmw-img-"))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def test_exif_gps_removed_and_rotated(self):
        from PIL import Image
        src = self.fx.make_jpeg(self.tmp / "a.jpg", (1600, 1200), orientation=6, gps=True)
        with Image.open(str(src)) as im:
            self.assertTrue(im.getexif().get_ifd(0x8825))      # 原檔真的有 GPS
        ph = images.process(src)
        for enc in (ph.image, ph.thumb):
            raw = decode(enc)
            self.assertEqual(images.metadata_markers(raw), [])
            with Image.open(io.BytesIO(raw)) as im:
                self.assertEqual(len(im.getexif()), 0)
                self.assertNotIn("icc_profile", im.info)
                self.assertEqual(im.size, (enc.w, enc.h))
                self.assertLess(im.size[0], im.size[1], "方向 6 的橫拍要轉成直的")
                self.assertTrue(im.info.get("progressive") or im.info.get("progression"))
        self.assertEqual((ph.image.w, ph.image.h), (960, 1280))
        self.assertEqual(max(ph.thumb.w, ph.thumb.h), 320)

    def test_limits_and_pid(self):
        src = self.fx.make_jpeg(self.tmp / "b.jpg", (3000, 2000), orientation=1)
        ph = images.process(src)
        self.assertLessEqual(len(ph.image.data), images.DISPLAY["hard"])
        self.assertLessEqual(len(ph.thumb.data), images.THUMB["hard"])
        self.assertLessEqual(len(ph.inline()["data"]), images.INLINE["hard"])
        self.assertEqual(ph.pid, hashlib.sha256(decode(ph.image)).hexdigest()[:16])
        self.assertEqual(images.process(src).pid, ph.pid, "同一張照片重處理要得到同一個 pid")
        self.assertEqual(ph.src_md5, hashlib.md5(src.read_bytes()).hexdigest())

    def test_small_image_not_upscaled(self):
        src = self.fx.make_jpeg(self.tmp / "c.jpg", (200, 150), orientation=1)
        ph = images.process(src)
        self.assertEqual((ph.image.w, ph.image.h), (200, 150))

    def test_png_with_alpha(self):
        from PIL import Image
        p = self.tmp / "d.png"
        Image.new("RGBA", (500, 400), (255, 0, 0, 0)).save(str(p))
        ph = images.process(p)
        with Image.open(io.BytesIO(decode(ph.image))) as im:
            self.assertEqual(im.mode, "RGB")
            self.assertEqual(im.getpixel((10, 10)), (255, 255, 255))

    def test_quality_ladder_steps_down(self):
        from PIL import Image
        p = self.tmp / "noise.png"
        Image.effect_noise((1280, 1280), 120).convert("RGB").save(str(p))
        ph = images.process(p)
        self.assertLess(ph.image.quality, images.DISPLAY["ladder"][0])
        self.assertLessEqual(len(ph.image.data), images.DISPLAY["hard"])

    def test_hard_limit_rejects(self):
        from PIL import Image
        spec = dict(images.THUMB, target=100, hard=200)
        im = Image.effect_noise((400, 400), 120).convert("RGB")
        with self.assertRaises(images.ImageError) as cm:
            images.encode(im, spec, "測試圖")
        self.assertIn("測試圖", str(cm.exception))

    def test_broken_file(self):
        p = self.tmp / "e.jpg"
        p.write_bytes(b"not a jpeg")
        with self.assertRaises(images.ImageError):
            images.process(p)

    def test_heic_without_plugin(self):
        try:
            import pillow_heif  # noqa: F401
            self.skipTest("這台有 pillow-heif")
        except ImportError:
            pass
        p = self.tmp / "f.HEIC"
        p.write_bytes(b"x")
        with self.assertRaises(images.ImageError) as cm:
            images.process(p)
        self.assertIn("最相容", str(cm.exception))


class TestMarkers(unittest.TestCase):
    """不需要 Pillow：直接組 JPEG 標記段。"""

    def test_marker_walk(self):
        soi, sos = b"\xff\xd8", b"\xff\xda\x00\x02"
        app0 = b"\xff\xe0\x00\x04ab"
        app1 = b"\xff\xe1\x00\x04ab"
        app2 = b"\xff\xe2\x00\x04ab"
        self.assertEqual(images.metadata_markers(soi + app0 + sos), [])
        self.assertEqual(len(images.metadata_markers(soi + app0 + app1 + app2 + sos)), 2)
        self.assertEqual(images.metadata_markers(b"GIF89a"), ["不是 JPEG"])

    def test_pillow_help_has_official_link_and_no_installer(self):
        text = images.pillow_help()
        self.assertIn(images.PILLOW_URL, text)
        self.assertIn("pip install --user Pillow", text)
        self.assertNotIn("brew", text)

    def test_is_photo_file(self):
        self.assertTrue(images.is_photo_file(Path("A.JPG")))
        self.assertFalse(images.is_photo_file(Path(".hidden.jpg")))
        self.assertFalse(images.is_photo_file(Path("notes.txt")))


if __name__ == "__main__":
    unittest.main()
