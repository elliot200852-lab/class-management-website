// query-eval.js：照 CMW.QUERIES 的形狀在記憶體裡跑查詢（示範模式用）。語意要跟 Firestore 一樣。
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { load, CORE } = require('./helpers/load.js');

const { C, Date: D } = load(CORE);
const Q = C.queryEval;

function post(slug, date, extra) {
  return { path: 'posts/' + slug, data: Object.assign({ title: slug, date, visible: true, category: '甲' }, extra || {}) };
}

const DOCS = [
  post('2026-01-05-e', '2026-01-05'),
  post('2026-01-04-d', '2026-01-04', { visible: false }),
  post('2026-01-03-c', '2026-01-03', { category: '乙' }),
  post('2026-01-02-b', '2026-01-02'),
  post('2026-01-02-a', '2026-01-02'),
  post('2026-01-01-x', '2026-01-01', { visible: 'true' }),      // 型別不對：不等於 true
  { path: 'posts/2026-01-06-nodate', data: { title: 'x', visible: true } }, // 沒有 date：orderBy 排除
  { path: 'posts/2026-01-05-e/comments/c1', data: { status: 'visible', createdAt: new D(3000) } },
  { path: 'posts/2026-01-05-e/comments/c2', data: { status: 'hidden', createdAt: new D(2000) } },
  { path: 'albums/2026-01-05-al/comments/c3', data: { status: 'visible', createdAt: new D(1000) } },
  { path: 'student_blogs/01/entries/2026-01-02-abcd1234/blog_comments/c4', data: { status: 'visible', createdAt: new D(4000), role: 'parent' } },
  { path: 'albums/2026-01-01-a1', data: { title: 'a1', date: '2026-01-01', order: 1, visible: true } },
  { path: 'albums/2026-01-02-a2', data: { title: 'a2', date: '2026-01-02', order: 1, visible: true } },
  { path: 'albums/2026-01-03-a3', data: { title: 'a3', date: '2026-01-03', order: 0, visible: true } },
  { path: 'albums/2026-01-04-a4', data: { title: 'a4', date: '2026-01-04', visible: true } },
];

function ids(res) { return res.items.map((d) => d.path.split('/').pop()); }

test('沒登記的查詢名 → invalid', () => {
  assert.throws(() => Q.run(DOCS, 'posts.all', {}), (e) => e.code === 'invalid');
  assert.throws(() => Q.run(DOCS, '__proto__', {}), (e) => e.code === 'invalid');
});

test('posts.recent：只拿 visible == true（型別要一樣）、日期新到舊、同日期依文件路徑', () => {
  const res = Q.run(DOCS, 'posts.recent', {});
  assert.deepEqual(ids(res), ['2026-01-05-e', '2026-01-03-c', '2026-01-02-b', '2026-01-02-a']);
  assert.equal(res.next, null);
});

test('limit 只能調小；游標 startAfter 接著讀', () => {
  assert.throws(() => Q.run(DOCS, 'posts.recent', { limit: 21 }), (e) => e.code === 'invalid');
  assert.throws(() => Q.run(DOCS, 'posts.recent', { limit: 0 }), (e) => e.code === 'invalid');
  const p1 = Q.run(DOCS, 'posts.recent', { limit: 2 });
  assert.deepEqual(ids(p1), ['2026-01-05-e', '2026-01-03-c']);
  assert.ok(p1.next);
  const p2 = Q.run(DOCS, 'posts.recent', { limit: 2 }, { after: p1.next });
  assert.deepEqual(ids(p2), ['2026-01-02-b', '2026-01-02-a']);
  const p3 = Q.run(DOCS, 'posts.recent', { limit: 2 }, { after: p2.next });
  assert.deepEqual(ids(p3), []);
});

test('上一篇／下一篇：startAfter＋limit 1、endBefore＋limitToLast 1', () => {
  const cur = DOCS[2]; // 2026-01-03-c
  const older = Q.run(DOCS, 'posts.recent', { limit: 1 }, { after: cur });
  assert.deepEqual(ids(older), ['2026-01-02-b']);
  const newer = Q.run(DOCS, 'posts.newer', {}, { before: cur });
  assert.deepEqual(ids(newer), ['2026-01-05-e']);
  const newestNewer = Q.run(DOCS, 'posts.newer', {}, { before: DOCS[0] });
  assert.deepEqual(ids(newestNewer), []);
  // 同一天的兩篇：前後也走得到、不會打轉
  assert.deepEqual(ids(Q.run(DOCS, 'posts.recent', { limit: 1 }, { after: DOCS[3] })), ['2026-01-02-a']);
  assert.deepEqual(ids(Q.run(DOCS, 'posts.newer', {}, { before: DOCS[4] })), ['2026-01-02-b']);
  // 導師版看得到下架的
  assert.deepEqual(ids(Q.run(DOCS, 'posts.newer.teacher', {}, { before: cur })), ['2026-01-04-d']);
  // 游標方向不對 → invalid
  assert.throws(() => Q.run(DOCS, 'posts.recent', {}, { before: cur }), (e) => e.code === 'invalid');
});

test('where 參數：posts.byCategory 少了 :category → invalid', () => {
  assert.throws(() => Q.run(DOCS, 'posts.byCategory', {}), (e) => e.code === 'invalid');
  assert.deepEqual(ids(Q.run(DOCS, 'posts.byCategory', { category: '乙' })), ['2026-01-03-c']);
});

test('路徑參數：{thread} 要是 CMW.paths 產生的文件路徑', () => {
  const res = Q.run(DOCS, 'comments.thread', { thread: 'posts/2026-01-05-e' });
  assert.deepEqual(ids(res), ['c1']);
  const t = Q.run(DOCS, 'comments.thread.teacher', { thread: 'posts/2026-01-05-e' });
  assert.deepEqual(ids(t), ['c1', 'c2']);
  for (const bad of ['posts/../x', 'posts', 'users/2026-01-05-e', '']) {
    assert.throws(() => Q.run(DOCS, 'comments.thread', { thread: bad }), (e) => e.code === 'invalid', bad);
  }
});

test('集合群組：comments.admin 收三種留言、不收部落格對話串，時間新到舊', () => {
  assert.deepEqual(ids(Q.run(DOCS, 'comments.admin', {})), ['c1', 'c2', 'c3']);
});

test('count：只算符合條件的筆數；沒登記 count 的查詢不能 count', () => {
  assert.equal(Q.count(DOCS, 'comments.count', { thread: 'posts/2026-01-05-e' }), 1);
  assert.throws(() => Q.count(DOCS, 'posts.recent', {}), (e) => e.code === 'invalid');
  assert.throws(() => Q.run(DOCS, 'comments.count', { thread: 'posts/2026-01-05-e' }), (e) => e.code === 'invalid');
});

test('sortClient：order 小的在前、同 order 日期新到舊、沒有 order 的排最後', () => {
  assert.deepEqual(ids(Q.run(DOCS, 'albums.list', {})), ['2026-01-03-a3', '2026-01-02-a2', '2026-01-01-a1', '2026-01-04-a4']);
});

test('watch 只准登記了 watch 的查詢', () => {
  assert.doesNotThrow(() => Q.checkWatch('comments.thread'));
  assert.throws(() => Q.checkWatch('posts.recent'), (e) => e.code === 'invalid');
});

test('每一個登記的查詢都跑得起來（參數齊全時）', () => {
  const params = {
    thread: 'posts/2026-01-05-e', owner: 'pages/about', entry: 'student_blogs/01/entries/2026-01-02-abcd1234',
    seat: '01', category: '甲', kind: 'fun', now: new D(5000),
  };
  for (const name of Object.keys(C.QUERIES)) {
    const spec = C.QUERIES[name];
    if (spec.count) assert.equal(typeof Q.count(DOCS, name, params), 'number', name);
    else assert.ok(Array.isArray(Q.run(DOCS, name, params).items), name);
  }
});
