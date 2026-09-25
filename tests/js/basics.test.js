// emailKey（共用測試向量）、座號格式、CMW.paths 擋壞參數、validate.js 上限、read-stats.js 的 X/N。
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { load, CORE, ROOT } = require('./helpers/load.js');

const { C } = load(CORE);
const VECTORS = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests', 'fixtures', 'emailkey_vectors.json'), 'utf8'));

// ── emailKey ─────────────────────────────────────────
test('emailKey：共用向量（合法）', () => {
  for (const v of VECTORS.valid) {
    const input = v.in[0] + '@' + v.in[1];
    const want = v.out[0] + '@' + v.out[1];
    assert.equal(C.emailKey(input), want, v.why);
  }
});

test('emailKey：共用向量（不合法）', () => {
  for (const v of VECTORS.invalid) {
    const input = v.in[0] + v.join + v.in[1];
    assert.throws(() => C.emailKey(input), undefined, v.why);
    assert.equal(C.emailKey.isValid(input), false, v.why);
  }
  assert.throws(() => C.emailKey(null));
  assert.throws(() => C.emailKey(42));
});

// ── 座號 ─────────────────────────────────────────────
test('座號：key() 只產生 01–40', () => {
  assert.equal(C.seats.key(1), '01');
  assert.equal(C.seats.key(9), '09');
  assert.equal(C.seats.key(40), '40');
  assert.equal(C.seats.key('7'), '07');
  for (const bad of [0, 41, -1, 1.5, true, false, null, undefined, 'abc', [], {}]) {
    assert.throws(() => C.seats.key(bad), undefined, String(bad));
  }
});

test('座號：parse() 只收 1～2 位數字', () => {
  assert.equal(C.seats.parse(3), '03');
  assert.equal(C.seats.parse('3'), '03');
  assert.equal(C.seats.parse('03'), '03');
  assert.equal(C.seats.parse(' 12 '), '12');
  for (const bad of ['座01', '1.0', '', '001', '41', 'x', null, true, [1]]) {
    assert.throws(() => C.seats.parse(bad), undefined, String(bad));
  }
});

test('座號：valid() 與 DATA-MODEL 的正規式一致', () => {
  for (const ok of ['01', '09', '10', '39', '40']) assert.equal(C.seats.valid(ok), true, ok);
  for (const bad of ['1', '00', '41', '99', '001', ' 01', 1, null]) assert.equal(C.seats.valid(bad), false, String(bad));
});

// ── paths ────────────────────────────────────────────
test('paths：合法參數組出正確路徑', () => {
  const s = '2026-01-02-hello';
  assert.equal(C.paths.post(s), 'posts/' + s);
  assert.equal(C.paths.postContent(s), 'posts/' + s + '/content/main');
  assert.equal(C.paths.thread('private', s), 'private_posts/' + s);
  assert.equal(C.paths.comment(C.paths.thread('post', s), 'abcDEF123'), 'posts/' + s + '/comments/abcDEF123');
  assert.equal(C.paths.receipt(C.paths.thread('post', s), 'parent-a@example.com'), 'posts/' + s + '/reads/parent-a@example.com');
  assert.equal(C.paths.entry('05', '2026-01-02-abcd1234'), 'student_blogs/05/entries/2026-01-02-abcd1234');
  assert.equal(C.paths.thumb('pages/about', '0123456789abcdef'), 'pages/about/thumbs/0123456789abcdef');
  assert.equal(C.paths.image('student_blogs/05/entries/2026-01-02-abcd1234', '2'),
    'student_blogs/05/entries/2026-01-02-abcd1234/images/2');
});

test('paths：壞參數一律丟 StoreError(invalid)', () => {
  const bad = [
    () => C.paths.post('../x'),
    () => C.paths.post('2026-01-02'),
    () => C.paths.post('2026-01-02-UPPER'),
    () => C.paths.post('2026-01-02-a/b'),
    () => C.paths.post('2026-01-02-' + 'a'.repeat(80)),
    () => C.paths.page('About'),
    () => C.paths.page('../x'),
    () => C.paths.thread('posts', '2026-01-02-a'),
    () => C.paths.thread('__proto__', '2026-01-02-a'),
    () => C.paths.comment('posts/../x', 'a'),
    () => C.paths.comment('posts/2026-01-02-a', 'a/b'),
    () => C.paths.receipt('posts/2026-01-02-a', 'Parent@Example.com'),
    () => C.paths.receipt('posts/2026-01-02-a', 'a@b@example.com'),
    () => C.paths.blog('1'),
    () => C.paths.entry('01', '2026-01-02-short'),
    () => C.paths.thumb('users/x', '0'),
    () => C.paths.thumb('pages/about', '3'),
    () => C.paths.thumb('pages/about', 'ZZZZZZZZZZZZZZZZ'),
    () => C.paths.allow('not-an-email'),
  ];
  bad.forEach((fn, i) => {
    assert.throws(fn, (e) => e && e.name === 'StoreError' && e.code === 'invalid', '第 ' + i + ' 個');
  });
});

test('paths：文件與集合路徑的基本檢查', () => {
  assert.equal(C.paths.isDocPath('posts/2026-01-02-a'), true);
  assert.equal(C.paths.isDocPath('posts'), false);
  assert.equal(C.paths.isDocPath('posts/../x/y'), false);
  assert.equal(C.paths.isDocPath('posts//x'), false);
  assert.equal(C.paths.isDocPath('posts/__name__'), false);
  assert.equal(C.paths.isCollectionPath('posts/2026-01-02-a/comments'), true);
  assert.equal(C.paths.isCollectionPath('posts/2026-01-02-a'), false);
  const info = C.paths.parseComment('albums/2026-01-02-a/comments/xyz');
  assert.equal(info.kind, 'album');
  assert.equal(info.thread, 'albums/2026-01-02-a');
  assert.equal(C.paths.parseComment('student_blogs/01/entries/x/blog_comments/y'), null);
});

// ── validate ─────────────────────────────────────────
function comment(extra) {
  return Object.assign({
    authorName: '某某的家長', body: '謝謝老師', role: 'parent', authorAlias: 'abcdefghij12',
    status: 'visible', createdAt: C.SERVER_TIME,
  }, extra || {});
}
const THREAD = 'posts/2026-01-02-a';

test('validate：留言的欄位契約與上限（DATA-MODEL §2.7）', () => {
  assert.ok(C.validate.write('add', THREAD + '/comments', comment()));
  assert.ok(C.validate.write('add', THREAD + '/comments', comment({ body: '字'.repeat(500), authorName: '名'.repeat(20) })));
  assert.ok(C.validate.write('add', THREAD + '/comments', comment({ replyTo: 'abc123' })));
  const bad = [
    comment({ body: '' }),
    comment({ body: '字'.repeat(501) }),
    comment({ authorName: '名'.repeat(21) }),
    comment({ role: 'admin' }),
    comment({ authorAlias: 'UPPER' }),
    comment({ status: 'hidden' }),
    comment({ createdAt: new Date() }),
    comment({ extra: 1 }),
    comment({ replyTo: '../x' }),
  ];
  for (const d of bad) {
    assert.throws(() => C.validate.write('add', THREAD + '/comments', d), (e) => e.code === 'invalid');
  }
  const missing = comment();
  delete missing.body;
  assert.throws(() => C.validate.write('add', THREAD + '/comments', missing));
});

test('validate：只准寫登記的路徑', () => {
  assert.throws(() => C.validate.write('set', THREAD, { title: 'x' }), (e) => e.code === 'invalid');
  assert.throws(() => C.validate.write('add', 'allowlist', { kind: 'teacher' }), (e) => e.code === 'invalid');
  assert.throws(() => C.validate.write('add', 'pages/about/comments', comment()), (e) => e.code === 'invalid');
  assert.ok(C.validate.write('update', THREAD + '/comments/abc', { status: 'hidden' }));
  assert.throws(() => C.validate.write('update', THREAD + '/comments/abc', { status: 'hidden', body: 'x' }));
  assert.ok(C.validate.write('set', THREAD + '/reads/parent-a@example.com', { kind: 'parent', readAt: C.SERVER_TIME }));
  assert.throws(() => C.validate.write('set', THREAD + '/reads/parent-a@example.com', { kind: 'teacher', readAt: C.SERVER_TIME }));
  assert.throws(() => C.validate.write('set', 'albums/2026-01-02-a/reads/parent-a@example.com', { kind: 'parent', readAt: C.SERVER_TIME }));
});

test('validate：部落格批次（1–7 個寫入、照片上限）', () => {
  const entry = 'student_blogs/01/entries/2026-01-02-abcd1234';
  const e = {
    title: '標題', body: '內文', date: '2026-01-02', author: 'parent', authorAlias: 'abcdefghij12',
    photos: [{ pid: '0', w: 1280, h: 960 }], visible: true, createdAt: C.SERVER_TIME,
  };
  const ops = [
    { op: 'set', path: entry, data: e },
    { op: 'set', path: entry + '/thumbs/0', data: { data: 'QUJD', w: 320, h: 240, order: 0 } },
    { op: 'set', path: entry + '/images/0', data: { data: 'QUJD', w: 1280, h: 960 } },
  ];
  assert.ok(C.validate.batch(ops));
  assert.throws(() => C.validate.batch([]));
  assert.throws(() => C.validate.batch(Array(8).fill(ops[0])));
  assert.throws(() => C.validate.write('set', entry + '/thumbs/0', { data: 'A'.repeat(49153), w: 1, h: 1, order: 0 }));
  assert.throws(() => C.validate.write('set', entry + '/thumbs/1', { data: 'QUJD', w: 1, h: 1, order: 0 }));
  assert.throws(() => C.validate.write('set', entry + '/images/0', { data: 'not base64!', w: 1, h: 1 }));
  assert.throws(() => C.validate.write('set', entry, Object.assign({}, e, { photos: [{ pid: '1', w: 1, h: 1 }] })));
  assert.throws(() => C.validate.write('set', entry, Object.assign({}, e, { body: '字'.repeat(10001) })));
});

// ── read-stats ───────────────────────────────────────
test('read-stats：班級紀事 X/N 只算有效的純家長', () => {
  const map = [
    { id: 'a@example.com', data: { kind: 'parent', active: true } },
    { id: 'b@example.com', data: { kind: 'parent', active: true } },
    { id: 'c@example.com', data: { kind: 'parent', active: false } },
    { id: 's@example.com', data: { kind: 'staff', active: true } },
  ];
  const keys = C.readStats.parentKeys(map);
  const reads = [{ id: 'a@example.com' }, { id: 'c@example.com' }, { id: 's@example.com' }, { id: 'a@example.com' }];
  const st = C.readStats.postStats(reads, keys);
  assert.equal(st.x, 1);
  assert.equal(st.n, 2);
  assert.equal(C.readStats.label(st), '已讀 1/2');
  assert.deepEqual(JSON.parse(JSON.stringify(C.readStats.cardStats(5, keys))), { x: 2, n: 2 });
});

test('read-stats：私密紀事分母＝私密名單減掉導師', () => {
  const priv = [{ id: 't@example.com' }, { id: 'a@example.com' }, { id: 'b@example.com' }];
  const st = C.readStats.privateStats(1, priv, 't@example.com');
  assert.equal(st.x, 1);
  assert.equal(st.n, 2);
});
