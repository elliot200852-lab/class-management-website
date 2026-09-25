/* demo-art.js — 示範模式的「照片」：依路徑雜湊，用程式當場畫一張水彩感的剪影（SVG data URL）。

   示範站沒有任何圖檔：山丘、太陽、樹、幾個小小的人形剪影，顏色取自網站的三色點綴。
   個人照（personal_photos/…）畫一張直式的半身剪影；家長合照（parent_photo_display/…）畫兩大一小的半身剪影。
   同一個路徑永遠畫出同一張，所以縮圖與大圖對得上。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var PAL = {
    paper: '#f7f7f2', paper2: '#edeee6', paper3: '#dfe1d5',
    pop1: '#a03a5a', pop2: '#1f6f6b', pop3: '#7a6010', gold: '#c4a03c', ink: '#434956'
  };
  var SKIES = ['#d4d8dd', '#eee4e3', '#d4e1dc', '#f0ebd9', '#edeee6']; // 紙色（sheet）混一點主色與三色點綴
  var FIGS = [PAL.pop1, PAL.pop2, PAL.pop3, PAL.gold, PAL.ink];

  function hash(str) {
    var h = 2166136261;
    for (var i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h >>> 0;
  }

  function rng(seed) {
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function n(v) { return Math.round(v * 10) / 10; }

  function hill(r, baseY, amp, color, op) {
    var y1 = baseY - amp * (0.4 + r());
    var y2 = baseY - amp * (0.2 + r());
    var cx1 = 60 + r() * 100;
    var cx2 = 240 + r() * 100;
    return '<path d="M0 ' + n(baseY) + ' Q' + n(cx1) + ' ' + n(y1 - amp) + ' 200 ' + n(y2) +
      ' T400 ' + n(baseY - amp * r()) + ' V300 H0 Z" fill="' + color + '" fill-opacity="' + op + '"/>';
  }

  function tree(r, x, groundY) {
    var h = 34 + r() * 26;
    var col = r() < 0.5 ? PAL.pop3 : PAL.pop2;
    return '<rect x="' + n(x - 2.5) + '" y="' + n(groundY - h * 0.45) + '" width="5" height="' + n(h * 0.45) +
      '" fill="' + PAL.ink + '" fill-opacity=".55"/>' +
      '<circle cx="' + n(x) + '" cy="' + n(groundY - h * 0.6) + '" r="' + n(h * 0.33) + '" fill="' + col + '" fill-opacity=".72"/>';
  }

  function figure(r, x, groundY, scale) {
    var col = FIGS[Math.floor(r() * FIGS.length)];
    var s = scale;
    var headR = 8 * s;
    var bodyH = 30 * s;
    var bodyW = 16 * s;
    var top = groundY - bodyH - headR * 2 - 2;
    var armY = top + headR * 2 + 8 * s;
    var wave = r() < 0.4;
    return '<g fill="' + col + '" fill-opacity=".86">' +
      '<circle cx="' + n(x) + '" cy="' + n(top + headR) + '" r="' + n(headR) + '"/>' +
      '<rect x="' + n(x - bodyW / 2) + '" y="' + n(top + headR * 2 + 1) + '" width="' + n(bodyW) + '" height="' + n(bodyH) + '" rx="' + n(bodyW / 2.4) + '"/>' +
      '</g>' +
      '<path d="M' + n(x - bodyW / 2) + ' ' + n(armY) + ' L' + n(x - bodyW - 4 * s) + ' ' + n(wave ? armY - 14 * s : armY + 12 * s) +
      ' M' + n(x + bodyW / 2) + ' ' + n(armY) + ' L' + n(x + bodyW + 4 * s) + ' ' + n(armY + 12 * s) + '" stroke="' + col +
      '" stroke-opacity=".86" stroke-width="' + n(3.2 * s) + '" stroke-linecap="round" fill="none"/>';
  }

  function scene(seed) {
    var r = rng(seed);
    var parts = [];
    parts.push('<rect width="400" height="300" fill="' + SKIES[Math.floor(r() * SKIES.length)] + '"/>');
    // 水彩暈染：幾個很淡的大圓
    for (var i = 0; i < 3; i++) {
      parts.push('<circle cx="' + n(r() * 400) + '" cy="' + n(r() * 180) + '" r="' + n(60 + r() * 90) + '" fill="' +
        FIGS[Math.floor(r() * 3)] + '" fill-opacity=".07"/>');
    }
    parts.push('<circle cx="' + n(50 + r() * 300) + '" cy="' + n(45 + r() * 40) + '" r="' + n(18 + r() * 14) +
      '" fill="' + PAL.gold + '" fill-opacity=".62"/>');
    parts.push(hill(r, 205, 40, PAL.pop2, 0.28));
    parts.push(hill(r, 235, 30, PAL.pop3, 0.5));
    var groundY = 262;
    parts.push('<rect y="' + groundY + '" width="400" height="38" fill="' + PAL.paper3 + '"/>');
    var trees = Math.floor(r() * 3);
    for (var t = 0; t < trees; t++) parts.push(tree(r, 20 + r() * 360, groundY));
    var people = 1 + Math.floor(r() * 4);
    var start = 70 + r() * 60;
    var gap = (260 - start) / Math.max(1, people);
    for (var p = 0; p < people; p++) {
      parts.push(figure(r, start + p * gap + r() * 20, groundY + 2, 0.9 + r() * 0.5));
    }
    parts.push('<rect x="2" y="2" width="396" height="296" fill="none" stroke="' + PAL.paper + '" stroke-width="4"/>');
    return parts.join('');
  }

  /** 半身剪影：頭＋肩膀（cx 中心、base 肩膀底線、s 大小） */
  function bust(cx, base, s, col) {
    var headR = 34 * s;
    var headY = base - 92 * s - headR;
    return '<g fill="' + col + '" fill-opacity=".85">' +
      '<circle cx="' + n(cx) + '" cy="' + n(headY) + '" r="' + n(headR) + '"/>' +
      '<path d="M' + n(cx - 70 * s) + ' ' + n(base) + ' Q' + n(cx - 66 * s) + ' ' + n(base - 88 * s) + ' ' + n(cx) + ' ' +
      n(base - 90 * s) + ' Q' + n(cx + 66 * s) + ' ' + n(base - 88 * s) + ' ' + n(cx + 70 * s) + ' ' + n(base) + ' Z"/>' +
      '</g>';
  }

  /** 個人照：直式 300×400、一個半身剪影 */
  function portrait(seed) {
    var r = rng(seed);
    return '<rect width="300" height="400" fill="' + SKIES[Math.floor(r() * SKIES.length)] + '"/>' +
      '<circle cx="' + n(60 + r() * 180) + '" cy="' + n(60 + r() * 80) + '" r="' + n(70 + r() * 50) + '" fill="' +
      FIGS[Math.floor(r() * 3)] + '" fill-opacity=".08"/>' +
      bust(150, 400, 1.35, FIGS[Math.floor(r() * FIGS.length)]) +
      '<rect x="2" y="2" width="296" height="396" fill="none" stroke="' + PAL.paper + '" stroke-width="4"/>';
  }

  /** 家長合照：橫式 400×300、兩位大人＋一位孩子 */
  function family(seed) {
    var r = rng(seed);
    return '<rect width="400" height="300" fill="' + SKIES[Math.floor(r() * SKIES.length)] + '"/>' +
      hill(r, 250, 30, PAL.pop3, 0.35) +
      bust(115, 300, 1.05, PAL.pop2) + bust(290, 300, 1.0, PAL.pop1) + bust(203, 300, 0.72, PAL.gold) +
      '<rect x="2" y="2" width="396" height="296" fill="none" stroke="' + PAL.paper + '" stroke-width="4"/>';
  }

  /** 主人文件路徑＋pid＋尺寸 → SVG data URL */
  function src(owner, pid, size) {
    var o = String(owner);
    var seed = hash(o + '|' + String(pid));
    var big = size === 'image';
    var svg;
    if (o.indexOf('personal_photos/') === 0) {
      svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 400" width="' + (big ? 960 : 240) + '" height="' +
        (big ? 1280 : 320) + '">' + portrait(seed) + '</svg>';
    } else {
      svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300" width="' + (big ? 1280 : 320) + '" height="' +
        (big ? 960 : 240) + '">' + (o.indexOf('parent_photo_display/') === 0 ? family(seed) : scene(seed)) + '</svg>';
    }
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  }

  C.demoArt = { src: src, hash: hash };
})(typeof window !== 'undefined' ? window : globalThis);
