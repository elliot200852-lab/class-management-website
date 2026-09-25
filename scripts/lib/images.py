#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""images.py — 照片處理（Pillow）：轉正、清掉 EXIF（含 GPS）、兩種尺寸、JPEG、base64（docs/DATA-MODEL.md §3.3）。

Pillow 是整個專案**唯一**的 Python 第三方套件，也只有處理照片的腳本會用到它。沒裝的時候
印官方安裝說明與一行指令（PILLOW_HELP），**不代裝**——請老師自己貼那一行（AGENTS.md 鐵則 10）。

每張照片的處理：
  1. 開檔 → 依 EXIF 方向轉正（ImageOps.exif_transpose）。
  2. 轉成 sRGB 的 RGB（有 ICC 描述檔先轉色；透明的地方鋪白底）；之後用「只有像素」的新影像，
     原檔的 EXIF、XMP、ICC 一概不帶。
  3. 顯示圖：最長邊 1280，品質 82→76→70→64→58，還太大就改 1024 再從 82 試一輪；
     縮圖：最長邊 320，品質 72→64→56→48。JPEG 漸進式、4:2:0、optimize。
  4. 每一份輸出都重新檢查：JPEG 的標記段裡沒有 APP1（EXIF／XMP）、APP2（ICC）、APP13（IPTC），
     Pillow 重新開檔也讀不到 EXIF——任何一項不過就不寫。
  5. base64 長度超過硬上限 → 拒絕，並說是哪一張。
  6. pid＝顯示圖 JPEG 位元組 SHA-256 的前 16 碼（同一張照片重發得到同一個 pid，不同照片不會同名）。
"""
import io
import base64
import hashlib

from . import hostos

PILLOW_URL = "https://pillow.readthedocs.io/en/stable/installation/basic-installation.html"
HEIF_URL = "https://pypi.org/project/pillow-heif/"

DISPLAY = {"side": 1280, "ladder": (82, 76, 70, 64, 58), "target": 400000, "hard": 716800, "fallback": 1024}
THUMB = {"side": 320, "ladder": (72, 64, 56, 48), "target": 32768, "hard": 49152, "fallback": 240}
INLINE = {"side": 320, "ladder": (72, 64, 56, 48), "target": 32768, "hard": 32768, "fallback": 200}

PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif", ".tif", ".tiff", ".bmp")
HEIF_EXT = (".heic", ".heif")


class ImageError(Exception):
    pass


def pillow_help():
    py = hostos.PY
    return "\n".join([
        "✗ 處理照片需要 Pillow（Python 的影像套件），這台電腦還沒裝。",
        "  → 官方安裝說明：%s" % PILLOW_URL,
        "  → 請老師自己在終端機貼這一行（只要裝一次）：",
        "       %s -m pip install --user Pillow" % py,
        "  → 裝完再跑一次剛才的指令。這個專案不會替你安裝任何東西。",
    ])


def have_pillow():
    try:
        import PIL  # noqa: F401
        from PIL import Image, ImageOps  # noqa: F401
        return True
    except ImportError:
        return False


def _pil():
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ImageError(pillow_help())
    return Image, ImageOps


def _enable_heif(name):
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        raise ImageError("\n".join([
            "✗ %s 是 iPhone 的 HEIC 格式，這台電腦讀不了。兩個辦法擇一：" % name,
            "  1. 裝 HEIC 支援（官方頁：%s），請老師自己貼：%s -m pip install --user pillow-heif" % (HEIF_URL, hostos.PY),
            "  2. 手機改用相容格式：iPhone「設定 → 相機 → 格式 → 最相容」，之後拍的照片就是 JPEG；"
            "或把照片先用「照片」App 匯出成 JPEG。"]))
    register_heif_opener()


class Encoded(object):
    __slots__ = ("jpeg", "data", "w", "h", "quality")

    def __init__(self, jpeg, w, h, quality):
        self.jpeg = jpeg
        self.data = base64.b64encode(jpeg).decode("ascii")
        self.w = w
        self.h = h
        self.quality = quality

    def as_inline(self):
        return {"data": self.data, "w": self.w, "h": self.h}


class Photo(object):
    """處理好的一張照片。src＝本機檔（不上雲）；pid 在建立時算好（或由呼叫端指定 '0'–'2'）。"""

    __slots__ = ("src", "pid", "image", "thumb", "small", "src_md5", "caption", "order")

    def __init__(self, src, image, thumb, small, src_md5):
        self.src = src
        self.image = image
        self.thumb = thumb
        self.small = small
        self.src_md5 = src_md5
        self.pid = hashlib.sha256(image.jpeg).hexdigest()[:16]
        self.caption = ""
        self.order = 0
        # 算完 pid 就只留 base64（一本相簿幾百張時，記憶體少一半）
        for enc in (image, thumb, small):
            enc.jpeg = None

    def inline(self):
        """coverThumb／avatar 用的內嵌小縮圖（≤ 32,768 字元）。"""
        return self.small.as_inline()


# ── JPEG 標記檢查（不靠 Pillow：直接看檔案裡有哪些段）────────────────────

_FORBIDDEN_MARKERS = {0xE1: "APP1（EXIF／XMP）", 0xE2: "APP2（ICC）", 0xED: "APP13（IPTC）"}


def metadata_markers(jpeg):
    """回 JPEG 在影像資料開始（SOS）之前出現的「帶中繼資料」標記名稱清單。"""
    found = []
    if jpeg[:2] != b"\xff\xd8":
        return ["不是 JPEG"]
    i = 2
    n = len(jpeg)
    while i + 4 <= n:
        if jpeg[i] != 0xFF:
            return found + ["標記段格式不對"]
        marker = jpeg[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker == 0xDA:          # SOS：之後是影像資料
            return found
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seglen = (jpeg[i + 2] << 8) | jpeg[i + 3]
        if marker in _FORBIDDEN_MARKERS:
            found.append(_FORBIDDEN_MARKERS[marker])
        i += 2 + seglen
    return found


def assert_clean(jpeg, name):
    bad = metadata_markers(jpeg)
    if bad:
        raise ImageError("✗ %s 處理後仍帶著中繼資料（%s），不寫進資料庫。" % (name, "、".join(bad)))
    Image, _ = _pil()
    with Image.open(io.BytesIO(jpeg)) as im:
        if im.info.get("exif") or len(im.getexif()) or im.info.get("icc_profile") or im.info.get("xmp"):
            raise ImageError("✗ %s 處理後仍讀得到 EXIF／ICC／XMP，不寫進資料庫。" % name)


# ── 處理 ─────────────────────────────────────────────────────────────────

def _to_srgb_pixels(im):
    """任何模式 → 只有像素的 RGB 影像（info 是空的：不帶 EXIF／ICC／XMP）。"""
    Image, _ = _pil()
    icc = im.info.get("icc_profile")
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        bg.alpha_composite(rgba)
        im = bg
    if icc:
        try:
            from PIL import ImageCms
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            base = im if im.mode in ("RGB", "CMYK", "L") else im.convert("RGB")
            im = ImageCms.profileToProfile(base, src, dst, outputMode="RGB")
        except Exception:  # 描述檔壞掉或 Pillow 沒帶 littleCMS：直接轉 RGB（顏色可能略偏，但照樣能用）
            im = im.convert("RGB")
    else:
        im = im.convert("RGB")
    clean = Image.frombytes("RGB", im.size, im.tobytes())
    return clean


def _resize(im, side):
    Image, _ = _pil()
    w, h = im.size
    if max(w, h) <= side:
        return im.copy()
    if w >= h:
        nw, nh = side, max(1, round(h * side / float(w)))
    else:
        nw, nh = max(1, round(w * side / float(h))), side
    return im.resize((nw, nh), Image.LANCZOS)


def _jpeg(im, q):
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=q, progressive=True, optimize=True, subsampling=2)
    return buf.getvalue()


def _b64len(n):
    return 4 * ((n + 2) // 3)


def encode(rgb, spec, name):
    """照品質階梯壓，第一個 base64 長度 ≤ 目標的就停；都不行就換小一點的邊長再走一輪；
    最後還超過硬上限就丟 ImageError。"""
    last = None
    for side in (spec["side"], spec["fallback"]):
        im = _resize(rgb, side)
        for q in spec["ladder"]:
            jpeg = _jpeg(im, q)
            last = (jpeg, im.size, q)
            if _b64len(len(jpeg)) <= spec["target"]:
                assert_clean(jpeg, name)
                return Encoded(jpeg, im.size[0], im.size[1], q)
    jpeg, size, q = last
    if _b64len(len(jpeg)) > spec["hard"]:
        raise ImageError("✗ %s 壓到最小還是太大（%d 字元，上限 %d）：換一張照片，或先裁小一點。"
                         % (name, _b64len(len(jpeg)), spec["hard"]))
    assert_clean(jpeg, name)
    return Encoded(jpeg, size[0], size[1], q)


def process(path, display_name=None):
    """處理一張本機照片 → Photo。display_name 是錯誤訊息裡怎麼稱呼這張（預設檔名）。"""
    Image, ImageOps = _pil()
    name = display_name or getattr(path, "name", str(path))
    suffix = str(path).lower().rsplit(".", 1)[-1] if "." in str(path) else ""
    if "." + suffix in HEIF_EXT:
        _enable_heif(name)
    try:
        with open(str(path), "rb") as fh:
            raw = fh.read()
    except OSError:
        raise ImageError("✗ 讀不到照片：%s" % name)
    return process_bytes(raw, name, src=path)


def process_bytes(raw, name, src=None):
    """跟 process() 同一套處理，來源是記憶體裡的位元組（例如從資料庫讀回來的部落格照片）。
    name 只用在錯誤訊息；src 記在 Photo.src（沒有本機檔就是 None）。"""
    Image, ImageOps = _pil()
    md5 = hashlib.md5(raw).hexdigest()
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if getattr(im, "format", "") == "JPEG":
                im.draft("RGB", (DISPLAY["side"] * 2, DISPLAY["side"] * 2))
            im.load()
            im = ImageOps.exif_transpose(im)
            rgb = _to_srgb_pixels(im)
    except ImageError:
        raise
    except Exception as e:  # Pillow 對壞檔丟的例外種類很多
        raise ImageError("✗ %s 打不開（%s）：可能不是照片、或檔案壞了。" % (name, type(e).__name__))
    image = encode(rgb, DISPLAY, name)
    thumb = encode(rgb, THUMB, name)
    # 內嵌小縮圖的上限比縮圖文件嚴（32,768）：縮圖本身放得下就共用，放不下才另外壓一份
    small = thumb if len(thumb.data) <= INLINE["hard"] else encode(rgb, INLINE, name)
    del rgb   # 原尺寸像素很大，處理完就放掉（一本相簿幾十張不能全留在記憶體）
    return Photo(src, image, thumb, small, md5)


def is_photo_file(path):
    n = getattr(path, "name", str(path)).lower()
    return n.endswith(PHOTO_EXT) and not n.startswith(".")
