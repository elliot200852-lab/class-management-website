// v1.1 前台的純函式：座位表幾何（兩種方向）、今天用哪個方案、每日一詩挑哪一首、匯出的日期範圍、
// 新路徑（個人照、家長合照、每月的詩）、示範資料的形狀、示範照片（直式剪影）。
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { load, CORE, plain } = require('./helpers/load.js');

const { C } = load(CORE.concat(['core/demo-art.js', 'core/demo-data.js', 'core/store-demo.js',
  'views/seating.js', 'views/poem.js', 'views/print.js']));

test('座位表：學生視角黑板在上、每一排置中、走道不佔桌子', () => {
  const L = C.seating.layout([['01', '02', '-', '03'], ['04', '']], false);
  assert.equal(L.cells.length, 5);
  assert.ok(L.board.y < Math.min(...L.cells.map((c) => c.y)), '黑板在最上面');
  const first = L.cells.find((c) => c.seat === '01');
  const short = L.cells.find((c) => c.seat === '04');
  assert.ok(short.x > first.x, '人數少的那一排置中（往右偏）');
  assert.equal(L.cells.filter((c) => c.kind === 'empty').length, 1);
  assert.ok(L.cells.every((c) => c.x >= 0 && c.x + L.cw <= L.w && c.y >= 0 && c.y + L.ch <= L.h), '全部在畫布裡');
});

test('座位表：老師視角＝轉 180 度（黑板在下、左右對調）', () => {
  const rows = [['01', '02', '03'], ['04', '05', '06']];
  const S = C.seating.layout(rows, false);
  const T = C.seating.layout(rows, true);
  assert.ok(T.board.y > Math.max(...T.cells.map((c) => c.y)), '黑板在最下面');
  const s01 = S.cells.find((c) => c.seat === '01');
  const t01 = T.cells.find((c) => c.seat === '01');
  assert.equal(t01.x, S.w - s01.x - S.cw);
  assert.equal(t01.y, S.h - s01.y - S.ch);
  const t03 = T.cells.find((c) => c.seat === '03');
  assert.ok(t03.x < t01.x, '老師看過去，學生的左手邊在右邊');
});

test('座位表：今天用哪個方案（起用日期 ≤ 今天的最新一個；都還沒到就拿最早的）', () => {
  const plans = [{ id: 'c', data: { date: '2026-12-01' } }, { id: 'b', data: { date: '2026-10-01' } },
    { id: 'a', data: { date: '2026-09-01' } }];
  assert.equal(C.seating.pickCurrent(plans, '2026-10-15').id, 'b');
  assert.equal(C.seating.pickCurrent(plans, '2026-12-01').id, 'c');
  assert.equal(C.seating.pickCurrent(plans, '2026-08-01').id, 'a');
  assert.equal(C.seating.pickCurrent([], '2026-08-01'), null);
  assert.deepEqual(plain(C.seating.counts({ rows: [{ seats: ['01', '', '-', '02'] }] })), { seats: 2, empty: 1 });
});

test('每日一詩：今天那一首；沒有就今天以前最後一首；讀者看不到還沒到的', () => {
  const items = [
    { date: '2026-10-03', title: 'c', author: 'x', text: 't' },
    { date: '2026-10-01', title: 'a', author: 'x', text: 't' },
    { date: '2026-10-05', title: 'e', author: 'x', text: 't' },
    { date: 'bad', title: 'z', author: 'x', text: 't' },
  ];
  let r = C.poem.pick(items, '2026-10-03', null, false);
  assert.equal(r.chosen.title, 'c');
  assert.deepEqual(r.list.map((x) => x.title), ['a', 'c']);
  r = C.poem.pick(items, '2026-10-04', null, false);
  assert.equal(r.chosen.title, 'c');
  r = C.poem.pick(items, '2026-10-04', '2026-10-05', false);
  assert.equal(r.chosen.title, 'c', '讀者用網址指定未來的日子也看不到');
  r = C.poem.pick(items, '2026-10-04', '2026-10-05', true);
  assert.equal(r.chosen.title, 'e', '導師看得到');
  r = C.poem.pick(items, '2026-10-04', '2026-10-01', false);
  assert.equal(r.chosen.title, 'a');
  assert.equal(C.poem.pick([], '2026-10-04', null, false).chosen, null);
  assert.equal(C.poem.shiftMonth('2026-01', -1), '2025-12');
  assert.equal(C.poem.shiftMonth('2026-12', 1), '2027-01');
});

test('匯出：日期範圍與排序', () => {
  const P = C.printExport;
  assert.ok(P.inRange('2026-10-02', '2026-10-01', '2026-10-31'));
  assert.ok(!P.inRange('2026-09-30', '2026-10-01', ''));
  assert.ok(P.inRange('2026-09-30', '', ''));
  const xs = [{ id: 'b', date: '2026-10-02' }, { id: 'a', date: '2026-10-02' }, { id: 'c', date: '2026-10-01' }];
  assert.deepEqual(xs.sort(P.byDateAsc).map((x) => x.id), ['c', 'a', 'b']);
  assert.equal(P.rangeText('', ''), '全部日期');
});

test('路徑：個人照、家長合照、每月的詩；照片主人接受這兩種', () => {
  assert.equal(C.paths.personalPhoto('01'), 'personal_photos/01');
  assert.equal(C.paths.parentPhoto('25'), 'parent_photo_display/25');
  assert.equal(C.paths.poemMonth('2026-10'), 'pages/poems-2026-10');
  assert.throws(() => C.paths.poemMonth('2026-13'));
  assert.throws(() => C.paths.personalPhoto('1'));
  assert.equal(C.paths.thumb('personal_photos/01', '0123456789abcdef'), 'personal_photos/01/thumbs/0123456789abcdef');
  assert.equal(C.paths.image('parent_photo_display/02', '0123456789abcdef'), 'parent_photo_display/02/images/0123456789abcdef');
  assert.throws(() => C.paths.thumb('personal_photos/1', '0123456789abcdef'));
  assert.throws(() => C.paths.thumb('seating/2026-10-01', '0123456789abcdef'));
});

test('示範資料：2 個座位方案、23 張個人照、8 張家長合照（只有稱謂）、10 首示範詩', () => {
  const b = C.demoData.build('2026-10-03');
  const db = Object.fromEntries(b.docs);
  const plans = Object.keys(db).filter((k) => /^seating\/[^/]+$/.test(k));
  assert.equal(plans.length, 2);
  plans.forEach((k) => {
    const seats = db[k].rows.flatMap((r) => r.seats).filter((s) => s && s !== '-');
    assert.equal(new Set(seats).size, 25, k);
  });
  assert.equal(Object.keys(db).filter((k) => /^personal_photos\/\d\d$/.test(k)).length, 23);
  const parents = Object.keys(db).filter((k) => /^parent_photo_display\/\d\d$/.test(k));
  assert.equal(parents.length, 8);
  parents.forEach((k) => assert.deepEqual(Object.keys(db[k]).sort(), ['note', 'photoPids', 'relations', 'updatedAt']));
  const poems = Object.keys(db).filter((k) => k.startsWith('pages/poems-')).flatMap((k) => db[k].data.items);
  assert.equal(poems.length, 10);
  poems.forEach((p) => {
    assert.equal(p.author, '示範文字');
    assert.ok(p.title.endsWith('（示範）'));
  });
  assert.equal(b.info.poemDays[0], '2026-10-03');
});

test('示範照片：個人照是直式、家長合照是橫式（都是程式畫的 SVG）', () => {
  const dec = (u) => decodeURIComponent(u.slice(u.indexOf(',') + 1));
  const p = dec(C.demoArt.src('personal_photos/01', '0123456789abcdef', 'image'));
  assert.match(p, /viewBox="0 0 300 400" width="960" height="1280"/);
  const f = dec(C.demoArt.src('parent_photo_display/01', '0123456789abcdef', 'thumb'));
  assert.match(f, /viewBox="0 0 400 300" width="320" height="240"/);
  assert.equal(C.demoArt.src('personal_photos/01', 'x', 'thumb'), C.demoArt.src('personal_photos/01', 'x', 'thumb'));
});

test('示範模式的查詢：seating.all、personalPhotos.all、parentPhotos.all 照登記表跑', async () => {
  const store = new C.DemoStore({ demo: true, reason: 'demo' });
  const s = await store.query('seating.all');
  assert.equal(s.items.length, 2);
  assert.ok(s.items[0].data.date >= s.items[1].data.date, '依日期新的在前（sortClient）');
  assert.equal((await store.query('personalPhotos.all')).items.length, 23);
  assert.equal((await store.query('parentPhotos.all')).items.length, 8);
  const src = await store.photoSrc('personal_photos/01', (await store.get('personal_photos/01')).data.photoPids[0], 'thumb');
  assert.match(src, /^data:image\/svg\+xml/);
});
