/* exif-jpeg.js — 測試用：當場做一張「帶 EXIF（拍攝方向＋GPS）」的 JPEG。repo 裡不放任何圖檔，
   需要的照片一律在測試執行時由程式產生。

   用在三個地方：
     · tests/js/photo-encode.test.js（Node）：buildApp1()、insertApp1() 造出帶 APP1 的位元組，驗「有 APP1 就擋」
     · scripts/verify_site.py（示範站）與 scripts/smoke_emulator.py（模擬器）：把這支注入頁面，用 makeFile()
       在瀏覽器畫一張圖、存成 JPEG、插入 EXIF，交給發文表單——驗網頁重新編碼後的照片「沒有 APP1、沒有 GPS 記號、
       方向已經轉正」。
   EXIF 內容：IFD0 有 Orientation（預設 6＝要順時針轉 90°）與 GPSInfo 指標；GPS IFD 有 GPSLatitudeRef＝'N'，
   以及一段 ASCII 記號（MARK）——輸出裡只要還找得到這段記號，就代表拍攝資訊沒清乾淨。 */
(function (g) {
  'use strict';

  var MARK = 'CMW-EXIF-GPS-TEST';

  function u16(v) { return [(v >> 8) & 255, v & 255]; }
  function u32(v) { return [(v >>> 24) & 255, (v >>> 16) & 255, (v >>> 8) & 255, v & 255]; }

  /** APP1（Exif）區段的完整位元組（含 FF E1 與長度） */
  function buildApp1(orientation) {
    var markBytes = Array.from(MARK).map(function (c) { return c.charCodeAt(0); });
    var ifd0Count = 2;
    var gpsOffset = 8 + 2 + ifd0Count * 12 + 4;
    var gpsCount = 2;
    var dataOffset = gpsOffset + 2 + gpsCount * 12 + 4;
    var tiff = [0x4D, 0x4D, 0x00, 0x2A].concat(u32(8)); // "MM"（大端序）、42、IFD0 在第 8 個位元組
    tiff = tiff.concat(u16(ifd0Count));
    tiff = tiff.concat(u16(0x0112), u16(3), u32(1), u16(orientation || 1), u16(0)); // Orientation（SHORT）
    tiff = tiff.concat(u16(0x8825), u16(4), u32(1), u32(gpsOffset));               // GPSInfo 指標（LONG）
    tiff = tiff.concat(u32(0));
    tiff = tiff.concat(u16(gpsCount));
    tiff = tiff.concat(u16(0x0001), u16(2), u32(2), [0x4E, 0x00, 0x00, 0x00]);      // GPSLatitudeRef = 'N'
    tiff = tiff.concat(u16(0x001B), u16(7), u32(markBytes.length), u32(dataOffset)); // GPSProcessingMethod＝記號
    tiff = tiff.concat(u32(0));
    tiff = tiff.concat(markBytes);
    var payload = [0x45, 0x78, 0x69, 0x66, 0x00, 0x00].concat(tiff); // "Exif\0\0"
    return new Uint8Array([0xFF, 0xE1].concat(u16(payload.length + 2), payload));
  }

  /** JPEG 位元組（FF D8 開頭）→ 在 SOI 後面插入一段區段 */
  function insertApp1(jpeg, app1) {
    var out = new Uint8Array(jpeg.length + app1.length);
    out.set(jpeg.subarray(0, 2), 0);
    out.set(app1, 2);
    out.set(jpeg.subarray(2), 2 + app1.length);
    return out;
  }

  /** 位元組裡有沒有這段 ASCII 文字 */
  function contains(bytes, text) {
    var pat = Array.from(text).map(function (c) { return c.charCodeAt(0); });
    outer:
    for (var i = 0; i + pat.length <= bytes.length; i++) {
      for (var k = 0; k < pat.length; k++) {
        if (bytes[i + k] !== pat[k]) continue outer;
      }
      return true;
    }
    return false;
  }

  function b64ToBytes(b64) {
    var s = g.atob(b64);
    var out = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
    return out;
  }

  /** 瀏覽器：畫一張 w×h 的圖（左紅右藍、上方一條黃，轉正後認得出來；顏色取自 site/css/site.css 的色票）→ JPEG → 插入 EXIF → File */
  function makeFile(w, h, orientation, name) {
    var d = g.document;
    var c = d.createElement('canvas');
    c.width = w;
    c.height = h;
    var x = c.getContext('2d');
    x.fillStyle = '#a03a5a';
    x.fillRect(0, 0, w / 2, h);
    x.fillStyle = '#34487f';
    x.fillRect(w / 2, 0, w / 2, h);
    x.fillStyle = '#c4a03c';
    x.fillRect(0, 0, w, Math.round(h / 8));
    for (var i = 0; i < 60; i++) { // 一點點細節，讓壓縮後的大小比較像照片
      x.fillStyle = 'rgba(' + ((i * 37) % 255) + ',' + ((i * 71) % 255) + ',' + ((i * 13) % 255) + ',.5)';
      x.beginPath();
      x.arc((i * 97) % w, (i * 53) % h, 10 + (i % 7) * 6, 0, Math.PI * 2);
      x.fill();
    }
    return new Promise(function (resolve) { c.toBlob(resolve, 'image/jpeg', 0.92); })
      .then(function (blob) { return blob.arrayBuffer(); })
      .then(function (buf) {
        var bytes = insertApp1(new Uint8Array(buf), buildApp1(orientation === undefined ? 6 : orientation));
        return new g.File([bytes], name || 'IMG_0001.jpg', { type: 'image/jpeg' });
      });
  }

  var api = { MARK: MARK, buildApp1: buildApp1, insertApp1: insertApp1, contains: contains, b64ToBytes: b64ToBytes, makeFile: makeFile };
  g.CMWTestJpeg = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
