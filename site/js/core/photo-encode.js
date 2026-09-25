/* photo-encode.js — 家長在網頁上發部落格時，照片在瀏覽器裡先重新編碼（docs/ARCHITECTURE.md §5.6、
   docs/DATA-MODEL.md §3.3）。

   為什麼：手機拍的照片原檔帶著 EXIF（拍攝時間、手機型號，常常還有 GPS 位置）。原檔**不上傳**：
   照片先畫到 canvas 上、再由 canvas 輸出新的 JPEG——canvas 輸出的檔本來就不帶任何 EXIF。
   為了不只靠「應該會這樣」，輸出後還會逐段檢查 JPEG：只要還有 APP1（EXIF／XMP）或 APP13（IPTC）區段就拒絕上傳。

   每張照片產兩份（參數與腳本端 Pillow 同一套，正本在 DATA-MODEL §3.3）：
     顯示圖 images：最長邊 1280，品質 0.82 → 0.58；還太大就改 1024 再從 0.82 試一輪；目標 base64 ≤ 400,000 字元，硬上限 716,800
     縮圖   thumbs：由顯示圖再縮成最長邊 320，品質 0.72 → 0.48；目標 ≤ 32,768 字元，硬上限 49,152
   方向：createImageBitmap(file, { imageOrientation: 'from-image' }) 依 EXIF 轉正；不支援時退回 <img>
   （現代瀏覽器把 <img> 畫到 canvas 時也會依 EXIF 轉正）。瀏覽器解不開的格式（例如非 Safari 開 HEIC）→ 請他改用 JPEG。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var SPEC = {
    image: { sides: [1280, 1024], qualities: [0.82, 0.76, 0.70, 0.64, 0.58], target: 400000, hard: 716800 },
    thumb: { sides: [320], qualities: [0.72, 0.64, 0.56, 0.48], target: 32768, hard: 49152 }
  };
  var MAX_FILE_BYTES = 30 * 1024 * 1024;
  var MAX_PHOTOS = 3;
  // 不准出現在輸出裡的 JPEG 區段：APP1（EXIF、XMP）、APP13（IPTC／Photoshop）
  var FORBIDDEN_MARKERS = [0xE1, 0xED];

  function invalid(msg) { return new C.StoreError('invalid', msg); }

  /** 等比縮到最長邊 ≤ side（不放大）；回傳整數 { w, h }，至少 1。 */
  function fit(w, h, side) {
    if (!(w > 0) || !(h > 0) || !(side > 0)) throw invalid('照片的尺寸讀不出來');
    var s = Math.min(1, side / Math.max(w, h));
    return { w: Math.max(1, Math.round(w * s)), h: Math.max(1, Math.round(h * s)) };
  }

  /** n 個位元組的 base64 長度（base64 全是 ASCII：字元數＝位元組數，DATA-MODEL §3.2） */
  function base64Length(n) {
    return 4 * Math.ceil(n / 3);
  }

  /** 位元組 → base64（分段轉，大照片不會把呼叫堆疊撐爆） */
  function toBase64(bytes) {
    var CHUNK = 0x8000;
    var parts = [];
    for (var i = 0; i < bytes.length; i += CHUNK) {
      parts.push(String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK)));
    }
    return g.btoa(parts.join(''));
  }

  /** JPEG 位元組 → 區段清單 [{ marker, offset, length }]，讀到 SOS（影像資料開始）或 EOI 為止。
      開頭不是 FF D8（不是 JPEG）→ null。 */
  function segments(bytes) {
    if (!bytes || bytes.length < 4 || bytes[0] !== 0xFF || bytes[1] !== 0xD8) return null;
    var out = [];
    var i = 2;
    while (i + 1 < bytes.length) {
      if (bytes[i] !== 0xFF) break; // 格式亂掉就停在這裡
      var marker = bytes[i + 1];
      if (marker === 0xFF) { i++; continue; } // 填充位元組
      if (marker === 0xD9) { out.push({ marker: marker, offset: i, length: 0 }); break; }
      if ((marker >= 0xD0 && marker <= 0xD7) || marker === 0x01) { i += 2; continue; }
      if (i + 3 >= bytes.length) break;
      var len = (bytes[i + 2] << 8) | bytes[i + 3];
      out.push({ marker: marker, offset: i, length: len });
      if (marker === 0xDA) break; // SOS：後面是壓縮後的影像資料，不再有中繼資料區段
      i += 2 + len;
    }
    return out;
  }

  /** 輸出裡有沒有帶拍攝資訊的區段（APP1／APP13） */
  function hasMetadata(bytes) {
    var segs = segments(bytes);
    if (!segs) return false;
    return segs.some(function (s) { return FORBIDDEN_MARKERS.indexOf(s.marker) >= 0; });
  }

  /** 上傳前的最後檢查：一定是 JPEG、一定沒有 APP1／APP13。不合就丟 invalid。 */
  function assertClean(bytes, label) {
    if (!segments(bytes)) throw invalid(label + '轉檔失敗（輸出不是 JPEG）');
    if (hasMetadata(bytes)) throw invalid(label + '轉檔後還帶著拍攝資訊，為了安全不上傳');
  }

  /** 品質階梯：sides 依序試（跟上一個尺寸一樣大就跳過），每個尺寸的品質由高往低，
      第一個 base64 ≤ target 就停；全部走完仍超過 → 用最後一次（最小）的結果，只要 ≤ hard；否則回 null。
      render(side) → { canvas, w, h }（可以是 Promise）；encode(canvas, q) → Promise<Uint8Array> */
  function ladder(spec, render, encode) {
    var last = null;
    var prevDim = '';
    function trySide(si) {
      if (si >= spec.sides.length) {
        return Promise.resolve(last && base64Length(last.bytes.length) <= spec.hard ? last : null);
      }
      return Promise.resolve(render(spec.sides[si])).then(function (r) {
        var dim = r.w + 'x' + r.h;
        if (dim === prevDim) return trySide(si + 1);
        prevDim = dim;
        function tryQ(qi) {
          if (qi >= spec.qualities.length) return trySide(si + 1);
          var q = spec.qualities[qi];
          return Promise.resolve(encode(r.canvas, q)).then(function (bytes) {
            last = { bytes: bytes, w: r.w, h: r.h, q: q, side: spec.sides[si], canvas: r.canvas };
            if (base64Length(bytes.length) <= spec.target) return last;
            return tryQ(qi + 1);
          });
        }
        return tryQ(0);
      });
    }
    return trySide(0);
  }

  /** 已經解開的來源（ImageBitmap／<img>／canvas，寬 sw 高 sh）→ { image, thumb }，兩份都是 { data(base64), w, h }。
      deps.draw(src, sw, sh, w, h) → canvas；deps.encode(canvas, q) → Promise<Uint8Array>（測試可以換成假的）。 */
  function encodeSource(src, sw, sh, deps) {
    var draw = deps.draw;
    var encode = deps.encode;
    return ladder(SPEC.image, function (side) {
      var dim = fit(sw, sh, side);
      return { canvas: draw(src, sw, sh, dim.w, dim.h), w: dim.w, h: dim.h };
    }, encode).then(function (img) {
      if (!img) throw invalid('這張照片壓縮後還是太大，請換一張，或先在手機上裁小一點。');
      assertClean(img.bytes, '照片');
      return ladder(SPEC.thumb, function (side) {
        var dim = fit(img.w, img.h, side);
        return { canvas: draw(img.canvas, img.w, img.h, dim.w, dim.h), w: dim.w, h: dim.h };
      }, encode).then(function (th) {
        if (!th) throw invalid('這張照片的縮圖壓不下來，請換一張。');
        assertClean(th.bytes, '縮圖');
        return {
          image: { data: toBase64(img.bytes), w: img.w, h: img.h },
          thumb: { data: toBase64(th.bytes), w: th.w, h: th.h },
          quality: { image: img.q, imageSide: img.side, thumb: th.q }
        };
      });
    });
  }

  // ── 瀏覽器端的實作（canvas） ─────────────────────────────
  function blobBytes(blob) {
    if (typeof blob.arrayBuffer === 'function') {
      return blob.arrayBuffer().then(function (b) { return new Uint8Array(b); });
    }
    return new Promise(function (resolve, reject) {
      var fr = new g.FileReader();
      fr.onload = function () { resolve(new Uint8Array(fr.result)); };
      fr.onerror = function () { reject(invalid('照片讀不出來')); };
      fr.readAsArrayBuffer(blob);
    });
  }

  function canvasEncode(canvas, q) {
    return new Promise(function (resolve, reject) {
      canvas.toBlob(function (blob) {
        if (!blob) { reject(invalid('照片轉檔失敗，請換一張再試')); return; }
        blobBytes(blob).then(resolve, reject);
      }, 'image/jpeg', q);
    });
  }

  /** 畫到新的 canvas：一次最多縮一半（一口氣縮很多倍會有鋸齒），透明背景填白（PNG 轉 JPEG 不會變黑）。 */
  function canvasDraw(src, sw, sh, w, h) {
    var d = g.document;
    var cur = src;
    var cw = sw;
    var ch = sh;
    while (cw / 2 >= w && ch / 2 >= h && cw > 2 && ch > 2) {
      var half = d.createElement('canvas');
      half.width = Math.max(1, Math.round(cw / 2));
      half.height = Math.max(1, Math.round(ch / 2));
      var hc = half.getContext('2d');
      hc.imageSmoothingEnabled = true;
      hc.imageSmoothingQuality = 'high';
      hc.drawImage(cur, 0, 0, cw, ch, 0, 0, half.width, half.height);
      cur = half;
      cw = half.width;
      ch = half.height;
    }
    var out = d.createElement('canvas');
    out.width = w;
    out.height = h;
    var ctx = out.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, w, h);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(cur, 0, 0, cw, ch, 0, 0, w, h);
    return out;
  }

  var FORMAT_HELP = '這張照片的格式瀏覽器打不開（例如 HEIC）。請改用 JPEG：iPhone 可以到「設定 → 相機 → 格式」選「最相容」，或先把照片轉成 JPEG 再上傳。';

  function decodeWithImg(file) {
    return new Promise(function (resolve, reject) {
      var url;
      try { url = g.URL.createObjectURL(file); } catch (e) { reject(invalid(FORMAT_HELP)); return; }
      var img = new g.Image();
      img.onload = function () {
        resolve({ src: img, w: img.naturalWidth, h: img.naturalHeight, done: function () { g.URL.revokeObjectURL(url); } });
      };
      img.onerror = function () {
        g.URL.revokeObjectURL(url);
        reject(invalid(FORMAT_HELP));
      };
      img.src = url;
    });
  }

  /** 檔案 → { src, w, h, done }（已依 EXIF 方向轉正） */
  function decode(file) {
    if (typeof g.createImageBitmap === 'function') {
      return g.createImageBitmap(file, { imageOrientation: 'from-image' }).then(function (bmp) {
        return { src: bmp, w: bmp.width, h: bmp.height, done: function () { if (bmp.close) bmp.close(); } };
      }, function () { return decodeWithImg(file); });
    }
    return decodeWithImg(file);
  }

  /** 使用者選的一個檔案 → { image, thumb }（都已經重新編碼、沒有 EXIF）。 */
  function encodeFile(file) {
    if (!file || typeof file.size !== 'number') return Promise.reject(invalid('沒有選到照片'));
    if (file.size > MAX_FILE_BYTES) return Promise.reject(invalid('照片太大（超過 30 MB），請換一張。'));
    if (file.type && !/^image\//.test(file.type)) return Promise.reject(invalid('只能上傳照片檔。'));
    return decode(file).then(function (dec) {
      if (!(dec.w > 0 && dec.h > 0)) {
        dec.done();
        throw invalid(FORMAT_HELP);
      }
      return encodeSource(dec.src, dec.w, dec.h, { draw: canvasDraw, encode: canvasEncode }).then(function (r) {
        dec.done();
        return r;
      }, function (err) {
        dec.done();
        throw err;
      });
    });
  }

  C.photoEncode = {
    SPEC: SPEC,
    MAX_FILE_BYTES: MAX_FILE_BYTES,
    MAX_PHOTOS: MAX_PHOTOS,
    fit: fit,
    base64Length: base64Length,
    toBase64: toBase64,
    segments: segments,
    hasMetadata: hasMetadata,
    assertClean: assertClean,
    ladder: ladder,
    encodeSource: encodeSource,
    encodeFile: encodeFile
  };
})(typeof window !== 'undefined' ? window : globalThis);
