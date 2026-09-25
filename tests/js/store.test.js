// Store 契約：兩個實作的方法清單與 docs/ARCHITECTURE.md §2.3 完全一致（不執行 Firebase SDK）；
// DemoStore 的行為：角色切換、寫入存 localStorage、localStorage 壞掉也照常、欄位檢查、照片剪影。
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { load, CORE, ROOT, makeStorage, plain } = require('./helpers/load.js');

const ALL = CORE.concat(['core/store-firestore.js', 'core/demo-art.js', 'core/demo-data.js', 'core/store-demo.js']);

function docMethods() {
  const md = fs.readFileSync(path.join(ROOT, 'docs', 'ARCHITECTURE.md'), 'utf8');
  const start = md.indexOf('### 2.3');
  const end = md.indexOf('### 2.4');
  const section = md.slice(start, end);
  const names = [];
  const re = /^\| (\d+) \| `([a-zA-Z]+)/gm;
  let m;
  while ((m = re.exec(section)) !== null) names.push([Number(m[1]), m[2]]);
  return names.sort((a, b) => a[0] - b[0]).map((x) => x[1]);
}

test('方法清單：文件 §2.3、CMW.STORE_METHODS、兩個實作三邊一致（20 個）', () => {
  const { C } = load(ALL);
  const fromDoc = docMethods();
  assert.equal(fromDoc.length, 20, '文件 §2.3 應該剛好 20 個方法');
  assert.deepEqual(plain(C.STORE_METHODS), fromDoc);
  const demo = new C.DemoStore({ demo: true, reason: 'demo' });
  const live = new C.FirestoreStore({ firebase: {} }, { demo: false, reason: 'live' });
  for (const name of fromDoc) {
    if (name === 'isDemo') {
      assert.equal(demo.isDemo, true);
      assert.equal(live.isDemo, false);
      continue;
    }
    assert.equal(typeof demo[name], 'function', 'DemoStore 少了 ' + name);
    assert.equal(typeof live[name], 'function', 'FirestoreStore 少了 ' + name);
  }
});

test('真站 Store：示範專用方法一律 invalid；建立時不載 SDK', () => {
  const { C } = load(ALL);
  const live = new C.FirestoreStore({ firebase: {} }, { demo: false, reason: 'live' });
  assert.throws(() => live.demoSetRole('teacher'), (e) => e.code === 'invalid');
  assert.throws(() => live.demoReset(), (e) => e.code === 'invalid');
  assert.equal(live._sdk, null);
  assert.equal(C.FirestoreStore.SDK_VERSION.split('.').length, 3, 'SDK 版本要寫死成完整版本號');
});

test('CMW.getStore：示範設定 → DemoStore；沒填 apiKey → 也是 DemoStore（尚未設定）', () => {
  const a = load(ALL, { config: { demo: true } });
  assert.equal(a.C.getStore().isDemo, true);
  const b = load(ALL, { config: { firebase: { apiKey: '請填入你的 Firebase apiKey', projectId: 'x' } } });
  assert.equal(b.C.detectMode().reason, 'unconfigured');
  assert.equal(b.C.getStore().isDemo, true);
  const c = load(ALL, { config: { firebase: { apiKey: 'k-123', projectId: 'my-class-2026' } } });
  assert.equal(c.C.detectMode().demo, false);
  assert.equal(c.C.getStore().isDemo, false);
});

test('DemoStore：25 位學生、角色切換只改 Session', async () => {
  const { C } = load(ALL);
  const s = new C.DemoStore();
  const blogs = await s.query('blogs.all');
  assert.equal(blogs.items.length, 25);
  assert.equal(blogs.items[0].data.displayName, '學生 A');
  assert.equal(blogs.items[24].data.displayName, '學生 Y');
  s.demoSetRole('teacher');
  assert.equal(s.getSession().roles.teacher, true);
  s.demoSetRole('parent', { seat: '05' });
  const ses = s.getSession();
  assert.equal(ses.roles.teacher, false);
  assert.deepEqual(plain(ses.roles.seats), ['05']);
  assert.equal(ses.user.email, 'parent-e@example.com');
  s.demoSetRole('signed-out');
  assert.equal(s.getSession().state, 'signed-out');
  assert.throws(() => s.demoSetRole('owner'), (e) => e.code === 'invalid');
  // 不模擬拒絕：訪客照樣讀得到（畫面由登入閘擋，不是 Store）
  const posts = await s.query('posts.recent');
  assert.equal(posts.items.length, 3);
});

test('DemoStore：留言寫入存進 localStorage，重新建立後還在；demoReset 清掉', async () => {
  const storage = makeStorage();
  const env = load(ALL, { localStorage: storage });
  const C = env.C;
  const s = new C.DemoStore();
  const slug = s.info.posts[0];
  const thread = C.paths.thread('post', slug);
  const before = await s.count('comments.count', { thread });
  const id = await s.add(thread + '/comments', {
    authorName: '測試', body: '你好', role: 'parent', authorAlias: 'demoaliasa01', status: 'visible', createdAt: C.SERVER_TIME,
  });
  assert.match(id, /^[A-Za-z0-9]{20}$/);
  assert.equal(await s.count('comments.count', { thread }), before + 1);
  const again = new C.DemoStore();
  assert.equal(await again.count('comments.count', { thread }), before + 1);
  const saved = await again.get(C.paths.comment(thread, id));
  assert.ok(saved.data.createdAt instanceof env.Date, '伺服器時間在示範模式換成 Date，存取後仍是 Date');
  again.demoReset();
  assert.equal(await again.count('comments.count', { thread }), before);
  assert.equal(storage.getItem('cmw-demo-v2:writes'), null);
});

test('DemoStore：寫入照同一套欄位檢查（不合就 invalid）', async () => {
  const { C } = load(ALL);
  const s = new C.DemoStore();
  const thread = C.paths.thread('post', s.info.posts[0]);
  await assert.rejects(s.add(thread + '/comments', { body: 'x' }), (e) => e.code === 'invalid');
  await assert.rejects(s.set(C.paths.post(s.info.posts[0]), { title: 'x' }), (e) => e.code === 'invalid');
  await assert.rejects(s.get('../etc'), (e) => e.code === 'invalid');
  await assert.rejects(s.query('not.registered'), (e) => e.code === 'invalid');
});

test('DemoStore：localStorage 每一次存取都丟錯，畫面照常（只存在記憶體）', async () => {
  const broken = {
    getItem() { throw new Error('blocked'); },
    setItem() { throw new Error('blocked'); },
    removeItem() { throw new Error('blocked'); },
  };
  const { C } = load(ALL, { localStorage: broken });
  const s = new C.DemoStore();
  const thread = C.paths.thread('post', s.info.posts[0]);
  await s.add(thread + '/comments', {
    authorName: '測試', body: '你好', role: 'parent', authorAlias: 'demoaliasa01', status: 'visible', createdAt: C.SERVER_TIME,
  });
  s.demoSetRole('teacher');
  s.demoReset();
  assert.equal(s.getSession().state, 'ready');
});

test('DemoStore：照片是程式畫的 SVG；不存在的回 null；photoSrc 不接受壞路徑', async () => {
  const { C } = load(ALL);
  const s = new C.DemoStore();
  const owner = C.paths.post(s.info.posts[0]);
  const cover = (await s.get(owner)).data.coverPid;
  const u = await s.photoSrc(owner, cover, 'thumb');
  assert.match(u, /^data:image\/svg\+xml;charset=utf-8,/);
  assert.equal(await s.photoSrc(owner, cover, 'image') === u, false, '大圖與縮圖尺寸不同');
  assert.equal(await s.photoSrc(owner, 'ffffffffffffffff', 'thumb'), null);
  assert.equal(await s.photoSrc('../x', cover, 'thumb'), null);
});

test('示範資料：3 篇紀事、每種區塊至少一次、2 本空相簿＋1 本有照片、1 篇私密紀事、每個座號至少一篇部落格', async () => {
  const { C } = load(ALL);
  const s = new C.DemoStore();
  s.demoSetRole('teacher');
  const posts = await s.query('posts.recent.teacher');
  assert.equal(posts.items.length, 3);
  const types = new Set();
  for (const p of posts.items) {
    const c = await s.get(C.paths.postContent(p.id));
    c.data.blocks.forEach((b) => { assert.ok(C.blocks.validBlock(b), JSON.stringify(b)); types.add(b.t); });
  }
  assert.deepEqual([...types].sort(), ['h', 'hr', 'img', 'list', 'p', 'quote', 'video']);
  const albums = await s.query('albums.list.teacher');
  assert.equal(albums.items.length, 3);
  const empty = albums.items.filter((a) => a.data.photoCount === 0);
  assert.equal(empty.length, 2, '兩本空卡（尚未設定相簿連結）');
  empty.forEach((a) => { assert.equal(a.data.linkUrl, undefined); assert.equal(a.data.videos.length, 0); });
  const full = albums.items.find((a) => a.data.photoCount > 0);
  assert.equal(full.id, s.info.albumWithPhotos);
  const thumbs = await s.query('photos.thumbs', { owner: full.path });
  assert.equal(thumbs.items.length, full.data.photoCount, '相簿的縮圖數量＝photoCount');
  assert.match(await s.photoSrc(full.path, thumbs.items[0].id, 'image'), /^data:image\/svg\+xml/);
  assert.equal((await s.query('private.list.teacher')).items.length, 1);
  // 每個座號的部落格至少一篇；家長文的作者代號就是那個座號家長的代號
  const blogs = await s.query('blogs.all');
  assert.equal(blogs.items.length, 25);
  for (const b of blogs.items) {
    const entries = await s.query('entries.bySeat.teacher', { seat: b.id });
    assert.ok(entries.items.length >= 1, '座號 ' + b.id + ' 沒有文章');
    entries.items.forEach((e) => {
      assert.match(e.id, /^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]{8}$/);
      (e.data.photos || []).forEach((p, i) => assert.equal(p.pid, String(i)));
    });
  }
  // 家長稱謂只用「母／父」這種字樣（導師端顯示「學生 A 家長（母）」）
  const maps = await s.query('parentMap.all');
  maps.items.filter((m) => m.data.kind === 'parent').forEach((m) => assert.match(m.data.relation, /^(母|父)$/));
  // 信箱一律 example.com、作者代號 12 碼
  const allow = await s.query('allowlist.all');
  allow.items.forEach((d) => {
    assert.match(d.id, /@example\.com$/);
    assert.match(d.data.alias, /^[a-z0-9]{12}$/);
  });
});
