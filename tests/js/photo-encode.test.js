// 瀏覽器端發部落格：照片重新編碼（尺寸、品質階梯、EXIF 清除）、組批次（blog-compose.js）、導師端未讀（seen.js）。
// 照片的「真的 canvas 重新編碼」要在瀏覽器裡跑（scripts/verify_site.py 與 scripts/smoke_emulator.py 用帶 EXIF 的 JPEG 驗）；
// 這裡驗純函式與判斷邏輯：encoder 換成假的，專門吐出「帶 APP1」或「乾淨」的位元組。repo 裡不放任何圖檔。
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { load, CORE, ROOT, makeStorage, plain } = require('./helpers/load.js');
const J = require('../fixtures/exif-jpeg.js');

const FILES = CORE.concat(['core/photo-encode.js', 'core/blog-compose.js']);

/** 一段「結構上是 JPEG」的位元組：SOI、DQT、（可選的額外區段）、SOS、資料、EOI；總長約 size */
function fakeJpeg(size, extra) {
  const head = [0xFF, 0xD8, 0xFF, 0xDB, 0x00, 0x43].concat(new Array(0x41).fill(1));
  const sos = [0xFF, 0xDA, 0x00, 0x08, 1, 1, 0, 0, 0x3F, 0];
  const n = Math.max(0, size - head.length - sos.length - 2);
  let bytes = Uint8Array.from(head.concat(sos, new Array(n).fill(0x55), [0xFF, 0xD9]));
  if (extra) bytes = J.insertApp1(bytes, extra);
  return bytes;
}

// ── 尺寸與 base64 ─────────────────────────────────────
test('fit：等比縮到最長邊、不放大、至少 1', () => {
  const { C } = load(FILES);
  const P = C.photoEncode;
  assert.deepEqual(plain(P.fit(4032, 3024, 1280)), { w: 1280, h: 960 });
  assert.deepEqual(plain(P.fit(3024, 4032, 1280)), { w: 960, h: 1280 });
  assert.deepEqual(plain(P.fit(3024, 4032, 320)), { w: 240, h: 320 });
  assert.deepEqual(plain(P.fit(800, 600, 1280)), { w: 800, h: 600 }, '小照片不放大');
  assert.deepEqual(plain(P.fit(10000, 3, 320)), { w: 320, h: 1 }, '極扁的照片至少 1 像素');
  assert.throws(() => P.fit(0, 100, 320), (e) => e.code === 'invalid');
});

test('參數與 DATA-MODEL §3.3 一致（品質階梯、目標、硬上限）', () => {
  const { C } = load(FILES);
  const S = C.photoEncode.SPEC;
  const md = fs.readFileSync(path.join(ROOT, 'docs', 'DATA-MODEL.md'), 'utf8');
  const ladder = (qs) => qs.map((q) => String(Math.round(q * 100))).join(' → ');
  assert.ok(md.includes(ladder(S.thumb.qualities)), '縮圖階梯 ' + ladder(S.thumb.qualities));
  assert.ok(md.includes(ladder(S.image.qualities)), '顯示圖階梯 ' + ladder(S.image.qualities));
  assert.deepEqual(plain(S.image.sides), [1280, 1024]);
  assert.deepEqual(plain(S.thumb.sides), [320]);
  assert.equal(S.image.target, 400000);
  assert.equal(S.image.hard, C.validate.LIMITS.imageData);
  assert.equal(S.thumb.target, 32768);
  assert.equal(S.thumb.hard, C.validate.LIMITS.thumbData);
  assert.equal(C.photoEncode.MAX_PHOTOS, C.validate.LIMITS.photosPerEntry);
});

test('toBase64：分段轉換結果跟 Buffer 一樣（大檔不會撐爆堆疊）', () => {
  const { C } = load(FILES);
  for (const n of [0, 1, 2, 3, 0x8000 - 1, 0x8000, 0x8000 + 1, 300001]) {
    const bytes = new Uint8Array(n);
    for (let i = 0; i < n; i++) bytes[i] = (i * 131 + 7) & 255;
    assert.equal(C.photoEncode.toBase64(bytes), Buffer.from(bytes).toString('base64'), 'n=' + n);
    assert.equal(C.photoEncode.base64Length(n), Buffer.from(bytes).toString('base64').length);
  }
});

// ── EXIF：以「輸出沒有 APP1 區段」判定 ─────────────────────────
test('segments／hasMetadata：認得 APP1（EXIF）與 APP13；乾淨的 JPEG 通過', () => {
  const { C } = load(FILES);
  const P = C.photoEncode;
  const clean = fakeJpeg(500);
  const segs = plain(P.segments(clean).map((s) => s.marker));
  assert.deepEqual(segs, [0xDB, 0xDA]);
  assert.equal(P.hasMetadata(clean), false);
  const app1 = J.buildApp1(6);
  assert.equal(app1[0], 0xFF);
  assert.equal(app1[1], 0xE1);
  const dirty = fakeJpeg(500, app1);
  assert.deepEqual(plain(P.segments(dirty).map((s) => s.marker)), [0xE1, 0xDB, 0xDA]);
  assert.equal(P.hasMetadata(dirty), true);
  assert.ok(J.contains(dirty, J.MARK), '測試用的 EXIF 真的帶著 GPS 記號');
  const iptc = J.insertApp1(clean, Uint8Array.from([0xFF, 0xED, 0x00, 0x04, 1, 2]));
  assert.equal(P.hasMetadata(iptc), true, 'APP13（IPTC）也算');
  assert.equal(P.segments(Uint8Array.from([0x89, 0x50, 0x4E, 0x47])), null, '不是 JPEG');
  assert.throws(() => P.assertClean(dirty, '照片'), (e) => e.code === 'invalid');
  assert.throws(() => P.assertClean(Uint8Array.from([1, 2, 3, 4]), '照片'), (e) => e.code === 'invalid');
  P.assertClean(clean, '照片');
});

/** 假的 draw／encode：大小＝像素數 × 品質 × k（k 控制「這張照片有多難壓」） */
function fakeDeps(k, opts) {
  opts = opts || {};
  const calls = [];
  return {
    calls,
    draw: (src, sw, sh, w, h) => ({ w, h, from: sw + 'x' + sh }),
    encode: (canvas, q) => {
      calls.push([canvas.w + 'x' + canvas.h, q]);
      const size = Math.round(canvas.w * canvas.h * q * k);
      const app1 = opts.app1When && opts.app1When(canvas, q) ? J.buildApp1(1) : null;
      return Promise.resolve(fakeJpeg(size, app1));
    },
  };
}

test('品質階梯：第一個達標的品質就停；縮圖從顯示圖再縮', async () => {
  const { C } = load(FILES);
  const P = C.photoEncode;
  const deps = fakeDeps(0.3);
  const r = await P.encodeSource({}, 4032, 3024, deps);
  // 1280×960×0.82×0.3 ≈ 302k 位元組 → base64 ≈ 403k > 400k；0.76 → ≈ 280k → 373k ≤ 400k
  assert.equal(r.quality.image, 0.76);
  assert.equal(r.quality.imageSide, 1280);
  assert.deepEqual([r.image.w, r.image.h, r.thumb.w, r.thumb.h], [1280, 960, 320, 240]);
  assert.equal(r.quality.thumb, 0.72);
  assert.deepEqual(deps.calls.slice(0, 2), [['1280x960', 0.82], ['1280x960', 0.76]]);
  assert.match(r.image.data, /^[A-Za-z0-9+/]+={0,2}$/);
  assert.ok(r.image.data.length <= P.SPEC.image.target && r.thumb.data.length <= P.SPEC.thumb.target);
});

test('品質階梯：1280 全部太大 → 改 1024 從頭再試；還是太大但在硬上限內 → 用最小的那一次', async () => {
  const { C } = load(FILES);
  const P = C.photoEncode;
  const deps = fakeDeps(0.6);
  const r = await P.encodeSource({}, 4000, 3000, deps);
  assert.equal(r.quality.imageSide, 1024);
  assert.deepEqual([r.image.w, r.image.h], [1024, 768]);
  const sizes = deps.calls.filter((c) => c[0] !== '320x240');
  assert.deepEqual(sizes.slice(0, 6).map((c) => c[0]), ['1280x960', '1280x960', '1280x960', '1280x960', '1280x960', '1024x768']);
  // k 大到 1024×0.58 也超過目標、但沒超過硬上限 → 接受最後一次
  const deps2 = fakeDeps(0.9);
  const r2 = await P.encodeSource({}, 4000, 3000, deps2);
  assert.equal(r2.quality.image, 0.58);
  assert.equal(r2.quality.imageSide, 1024);
  assert.ok(r2.image.data.length > P.SPEC.image.target && r2.image.data.length <= P.SPEC.image.hard);
});

test('品質階梯：連最小都超過硬上限 → 拒絕；小照片不放大、同尺寸不重跑第二輪', async () => {
  const { C } = load(FILES);
  const P = C.photoEncode;
  await assert.rejects(P.encodeSource({}, 4000, 3000, fakeDeps(1.5)), (e) => e.code === 'invalid' && /太大/.test(e.message));
  const deps = fakeDeps(2.0);
  await assert.rejects(P.encodeSource({}, 900, 700, deps), (e) => e.code === 'invalid');
  assert.equal(deps.calls.filter((c) => c[0] === '900x700').length, 5, '900 寬的照片 1280 與 1024 都是原尺寸，只跑一輪');
});

test('EXIF：編碼器吐出帶 APP1 的位元組 → 拒絕上傳（顯示圖、縮圖都擋）', async () => {
  const { C } = load(FILES);
  const P = C.photoEncode;
  await assert.rejects(P.encodeSource({}, 2000, 1500, fakeDeps(0.1, { app1When: (cv) => cv.w > 320 })),
    (e) => e.code === 'invalid' && /拍攝資訊/.test(e.message));
  await assert.rejects(P.encodeSource({}, 2000, 1500, fakeDeps(0.1, { app1When: (cv) => cv.w <= 320 })),
    (e) => e.code === 'invalid' && /縮圖/.test(e.message));
  const ok = await P.encodeSource({}, 2000, 1500, fakeDeps(0.1));
  const bytes = Buffer.from(ok.image.data, 'base64');
  assert.equal(P.hasMetadata(bytes), false, '輸出沒有 APP1');
  assert.equal(J.contains(bytes, J.MARK), false);
});

test('encodeFile：沒選檔、超過 30 MB、不是圖片 → 直接拒絕（不讀檔）', async () => {
  const { C } = load(FILES);
  const P = C.photoEncode;
  await assert.rejects(P.encodeFile(null), (e) => e.code === 'invalid');
  await assert.rejects(P.encodeFile({ size: 31 * 1024 * 1024, type: 'image/jpeg' }), (e) => /30 MB/.test(e.message));
  await assert.rejects(P.encodeFile({ size: 10, type: 'application/pdf' }), (e) => e.code === 'invalid');
});

// ── 組批次（blog-compose.js） ─────────────────────────
function photo(i) {
  return { image: { data: 'AAAA', w: 1280 - i, h: 960 }, thumb: { data: 'BBBB', w: 320, h: 240 }, caption: i === 1 ? ' 圖說 ' : '' };
}

test('blogCompose.ops：1 篇文章＋每張照片兩份，最多 7 個寫入，過得了前端欄位檢查', () => {
  const { C } = load(FILES);
  const ops = C.blogCompose.ops({
    seat: '04', postId: '2026-01-02-abcd1234', date: '2026-01-02', author: 'parent', authorAlias: 'demoaliasd04',
    title: ' 標題 ', body: '  第一行\n\n第三行  ', photos: [photo(0), photo(1), photo(2)],
  });
  assert.equal(ops.length, 7);
  C.validate.batch(ops);
  const entry = ops[0];
  assert.equal(entry.path, 'student_blogs/04/entries/2026-01-02-abcd1234');
  assert.equal(entry.data.title, '標題', '標題去掉前後空白');
  assert.equal(entry.data.body, '  第一行\n\n第三行  ', '內文逐字保留');
  assert.deepEqual(plain(entry.data.photos), [
    { pid: '0', w: 1280, h: 960 }, { pid: '1', w: 1279, h: 960, caption: '圖說' }, { pid: '2', w: 1278, h: 960 },
  ]);
  assert.ok(C.isServerTime(entry.data.createdAt));
  assert.deepEqual(plain(ops.slice(1).map((o) => o.path.split('/').slice(-2).join('/'))),
    ['images/0', 'thumbs/0', 'images/1', 'thumbs/1', 'images/2', 'thumbs/2']);
  assert.deepEqual(plain(ops.filter((o) => /thumbs/.test(o.path)).map((o) => o.data.order)), [0, 1, 2]);
});

test('blogCompose.check：空標題、空白內文、超過 3 張、照片還沒處理完 → invalid', () => {
  const { C } = load(FILES);
  const base = { title: 't', body: 'b', photos: [] };
  assert.throws(() => C.blogCompose.check(Object.assign({}, base, { title: '   ' })), (e) => e.code === 'invalid');
  assert.throws(() => C.blogCompose.check(Object.assign({}, base, { body: ' \n ' })), (e) => e.code === 'invalid');
  assert.throws(() => C.blogCompose.check(Object.assign({}, base, { body: 'x'.repeat(10001) })), (e) => /10000/.test(e.message));
  assert.throws(() => C.blogCompose.check(Object.assign({}, base, { photos: [photo(0), photo(1), photo(2), photo(3)] })), (e) => /3/.test(e.message));
  assert.throws(() => C.blogCompose.check(Object.assign({}, base, { photos: [{ image: null }] })), (e) => /處理中/.test(e.message));
  assert.equal(C.blogCompose.check(Object.assign({}, base, { body: '  逐字  ' })).body, '  逐字  ');
});

test('blogCompose.submit：每次送出都換新的 postId（重試也是）；身分不對就不送', async () => {
  const { C } = load(FILES);
  const sent = [];
  let fail = true;
  const store = {
    newPostId: () => C.util.newPostId('2026-01-02'),
    batch: (ops) => { sent.push(ops[0].path); if (fail) { fail = false; return Promise.reject(new C.StoreError('unavailable', 'x')); } return Promise.resolve(); },
  };
  const parent = { roles: { teacher: false, seats: ['04'], seatKind: 'parent', alias: 'demoaliasd04' } };
  const input = { seat: '04', title: 't', body: 'b', photos: [photo(0)] };
  await assert.rejects(C.blogCompose.submit(store, parent, input), (e) => e.code === 'unavailable');
  const id = await C.blogCompose.submit(store, parent, input);
  assert.equal(sent.length, 2);
  assert.notEqual(sent[0], sent[1], '重試換了新的文章編號');
  assert.ok(sent[1].endsWith(id));
  // 同仁、別的座號的家長、沒有作者代號 → 不送
  const staff = { roles: { teacher: false, seats: ['04'], seatKind: 'staff', alias: 'demostaff001' } };
  await assert.rejects(C.blogCompose.submit(store, staff, input), (e) => e.code === 'invalid');
  await assert.rejects(C.blogCompose.submit(store, parent, Object.assign({}, input, { seat: '05' })), (e) => e.code === 'invalid');
  await assert.rejects(C.blogCompose.submit(store, { roles: { teacher: true } }, input), (e) => e.code === 'invalid');
  assert.equal(sent.length, 2);
  // 導師：任何座號、author 是 teacher
  const teacherStore = Object.assign({}, store, { batch: (ops) => { sent.push(ops[0].data.author); return Promise.resolve(); } });
  await C.blogCompose.submit(teacherStore, { roles: { teacher: true, alias: 'demoteacher1', seats: [] } }, Object.assign({}, input, { seat: '09' }));
  assert.equal(sent[2], 'teacher');
});

// ── 導師端未讀（seen.js） ─────────────────────────────
function doc(C, p, data) { return C.makeDoc(p, data); }

test('未讀：家長新文與新留言、晚於看過的時間才算；下架的文與收起的留言不算', () => {
  const env = load(FILES);
  const C = env.C;
  const D = (ms) => new env.Date(ms);
  const entries = [
    doc(C, 'student_blogs/01/entries/2026-01-02-aaaaaaa1', { author: 'parent', visible: true, createdAt: D(5000) }),
    doc(C, 'student_blogs/01/entries/2026-01-01-aaaaaaa2', { author: 'parent', visible: true, createdAt: D(1000) }),
    doc(C, 'student_blogs/02/entries/2026-01-02-bbbbbbb1', { author: 'parent', visible: false, createdAt: D(6000) }),
    doc(C, 'student_blogs/03/entries/2026-01-02-ccccccc1', { author: 'teacher', visible: true, createdAt: D(7000) }),
    doc(C, 'student_blogs/04/entries/2026-01-02-ddddddd1', { author: 'parent', visible: true, createdAt: null }),
    doc(C, 'posts/2026-01-02-x', { author: 'parent', visible: true, createdAt: D(9000) }),
  ];
  const comments = [
    doc(C, 'student_blogs/03/entries/2026-01-02-ccccccc1/blog_comments/c1', { role: 'parent', status: 'visible', createdAt: D(8000) }),
    doc(C, 'student_blogs/03/entries/2026-01-02-ccccccc1/blog_comments/c2', { role: 'parent', status: 'hidden', createdAt: D(8100) }),
    doc(C, 'student_blogs/03/entries/2026-01-02-ccccccc1/blog_comments/c3', { role: 'teacher', status: 'visible', createdAt: D(8200) }),
    doc(C, 'student_blogs/01/entries/2026-01-01-aaaaaaa2/blog_comments/c4', { role: 'parent', status: 'visible', createdAt: D(900) }),
  ];
  const none = C.seen.compute(entries, comments, {});
  assert.deepEqual(plain(none.bySeat), { '01': { posts: 2, replies: 1 }, '03': { posts: 0, replies: 1 } });
  assert.deepEqual(plain(none.latest), { '01': 5000, '03': 8000 });
  const seen = C.seen.compute(entries, comments, { '01': 1000, '03': 8000 });
  assert.deepEqual(plain(seen.bySeat), { '01': { posts: 1, replies: 0 } }, '看過的時間之前（含）都不算');
  assert.equal(C.seen.seatOf('student_blogs/41/entries/x'), null);
  assert.equal(C.seen.seatOf('student_blogs/07/entries/x/blog_comments/y'), '07');
});

test('未讀：打開座號＝看過了（只往後推）；localStorage 壞掉畫面照常', () => {
  const storage = makeStorage();
  const { C } = load(FILES, { localStorage: storage });
  assert.equal(C.seen.markSeat('01', 5000), true);
  assert.equal(C.seen.markSeat('01', 4000), false, '不會往回改');
  assert.equal(C.seen.markSeat('01', 0), false);
  assert.equal(C.seen.markSeat('99', 9000), false);
  assert.deepEqual(plain(C.seen.load()), { '01': 5000 });
  C.seen.remember({ '02': 700 });
  C.seen.remember({ '02': 600 });
  assert.equal(C.seen.remembered('02'), 700);
  storage.setItem(C.seen.KEY, '{壞掉的 JSON');
  assert.deepEqual(plain(C.seen.load()), {});
  const broken = { getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); }, removeItem() {} };
  const b = load(FILES, { localStorage: broken });
  assert.deepEqual(plain(b.C.seen.load()), {});
  assert.equal(b.C.seen.markSeat('01', 5000), true);
});
