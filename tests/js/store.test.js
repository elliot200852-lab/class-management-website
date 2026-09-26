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

// ── 真站 Store 的登入方式、共用電腦、照片快取（審查 H1、M2、L2；不載 Firebase SDK，用假的 SDK 物件）──
const AT = '@';
const PARENT_MAIL = 'p.one' + AT + 'example.com';
const B64 = 'aGVsbG8=';

function fakeSdk({ server = {}, cache = {}, denied = [] } = {}) {
  const calls = [];
  const snap = (path, data, fromCache) => ({
    ref: { path }, metadata: { fromCache },
    exists: () => data !== undefined && data !== null,
    data: () => data, get: (k) => (data ? data[k] : undefined),
  });
  const fromServer = (kind) => async (ref) => {
    calls.push([kind, ref.path]);
    if (denied.includes(ref.path)) throw Object.assign(new Error('denied'), { code: 'permission-denied' });
    return snap(ref.path, server[ref.path], false);
  };
  const F = {
    doc: (db, path) => ({ path }),
    getDoc: fromServer('server'),
    getDocFromServer: fromServer('fromServer'),
    getDocFromCache: async (ref) => {
      calls.push(['cache', ref.path]);
      if (!(ref.path in cache)) throw new Error('not in cache');
      return snap(ref.path, cache[ref.path], true);
    },
    setDoc: async (ref) => { calls.push(['set', ref.path]); },
    serverTimestamp: () => 'SERVER_TIME',
  };
  return { F, AU: {}, db: {}, auth: {}, calls };
}

function liveWith(C, sdk) {
  const live = new C.FirestoreStore({ firebase: {} }, { demo: false, reason: 'live' });
  live._sdk = Promise.resolve(sdk);
  return live;
}

const userWith = (provider) => ({
  uid: 'u-1', email: PARENT_MAIL, emailVerified: true,
  getIdTokenResult: async () => ({ claims: { firebase: { sign_in_provider: provider } } }),
});

test('登入方式看 ID token 的 sign_in_provider（與規則同源），不看 providerData', () => {
  const { C } = load(ALL);
  const p = C.FirestoreStore.providerOf;
  assert.equal(p({ firebase: { sign_in_provider: 'google.com' } }), 'google.com');
  assert.equal(p({ firebase: { sign_in_provider: 'password' } }), 'emailLink');
  assert.equal(p({ firebase: {} }), 'emailLink');
  assert.equal(p(null), 'emailLink', '讀不到就當 email 連結（只能讀）');
  assert.equal(p({ firebase: { sign_in_provider: 'google.com ' } }), 'emailLink');
});

test('CMW.readOnlyLogin：email 連結登入的非導師＝只能讀；Google、導師、未就緒都不是', () => {
  const { C } = load(ALL);
  const s = (provider, teacher = false, state = 'ready') => ({ state, user: { provider }, roles: { teacher } });
  assert.equal(C.readOnlyLogin(s('emailLink')), true);
  assert.equal(C.readOnlyLogin(s('google.com')), false);
  assert.equal(C.readOnlyLogin(s('emailLink', true)), false);
  assert.equal(C.readOnlyLogin(s('emailLink', false, 'loading')), false);
  assert.equal(C.readOnlyLogin(null), false);
  assert.match(C.READ_ONLY_LOGIN_MSG, /Google 登入/);
});

test('CMW.sharedDevice：記在 sessionStorage；storage 壞掉一律當沒勾', () => {
  const a = load(ALL);
  assert.equal(a.C.sharedDevice.get(), false);
  assert.equal(a.C.sharedDevice.set(true), true);
  assert.equal(a.ctx.sessionStorage.getItem(a.C.sharedDevice.KEY), '1');
  assert.equal(a.C.sharedDevice.set(false), false);
  assert.equal(a.ctx.sessionStorage.getItem(a.C.sharedDevice.KEY), null);
  const b = load(ALL);
  b.ctx.sessionStorage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() {} };
  assert.equal(b.C.sharedDevice.set(true), false, '記不住就回 false（真站不會因此一直重新載入）');
});

test('Session：email 連結登入就算在私密名單也不是私密讀者，也不發座號、私密、導師三個請求', async () => {
  const { C } = load(ALL);
  const key = C.emailKey(PARENT_MAIL);
  const server = {
    [C.paths.allow(key)]: { kind: 'parent', alias: 'abcdefabcdef' },
    [C.paths.privateAllow(key)]: { updatedAt: null },
    [C.paths.parentMap(key)]: { kind: 'parent', active: true, seats: ['01'] },
  };
  const sdk = fakeSdk({ server, denied: [C.paths.teacherProbe()] });
  const s = await liveWith(C, sdk)._resolveSession(sdk, userWith('password'));
  assert.equal(s.state, 'ready');
  assert.equal(s.user.provider, 'emailLink');
  assert.equal(s.roles.reader, true);
  assert.equal(s.roles.privateReader, false);
  assert.deepEqual(plain(s.roles.seats), []);
  assert.deepEqual(plain(sdk.calls), [['server', C.paths.allow(key)]]);
  assert.equal(C.readOnlyLogin(s), true);

  const b = load(ALL);
  const sdk2 = fakeSdk({ server, denied: [b.C.paths.teacherProbe()] });
  const g2 = await liveWith(b.C, sdk2)._resolveSession(sdk2, userWith('google.com'));
  assert.equal(g2.user.provider, 'google.com');
  assert.equal(g2.roles.privateReader, true);
  assert.deepEqual(plain(g2.roles.seats), ['01']);
  assert.equal(g2.roles.teacher, false);
});

test('markRead：email 連結登入不簽回條（規則不准，免得每頁都被拒一次）', async () => {
  const { C } = load(ALL);
  const sdk = fakeSdk();
  const live = liveWith(C, sdk);
  live._session = { state: 'ready', user: { provider: 'emailLink', emailKey: C.emailKey(PARENT_MAIL) },
    roles: { teacher: false, kind: 'parent' } };
  await live.markRead('posts/2026-09-01-open');
  assert.equal(sdk.calls.length, 0);
});

test('photoSrc：快取命中時，主人文件要這一頁從伺服器讀成功過才顯示', async () => {
  const { C } = load(ALL);
  const owner = 'posts/2026-09-01-open';
  const thumb = C.paths.thumb(owner, 'a1b2c3d4e5f60718');
  // ① 主人文件伺服器拒絕（被撤權限或已下架）→ 快取裡的照片不吐出來
  const sdk1 = fakeSdk({ cache: { [thumb]: { data: B64 } }, denied: [owner] });
  assert.equal(await liveWith(C, sdk1).photoSrc(owner, 'a1b2c3d4e5f60718', 'thumb'), null);
  assert.deepEqual(plain(sdk1.calls), [['cache', thumb], ['fromServer', owner]]);
  // ② 主人文件先用 get() 從伺服器讀到了 → 快取命中直接顯示，不再多問伺服器
  const sdk2 = fakeSdk({ cache: { [thumb]: { data: B64 } }, server: { [owner]: { visible: true } } });
  const live2 = liveWith(C, sdk2);
  await live2.get(owner);
  assert.equal(await live2.photoSrc(owner, 'a1b2c3d4e5f60718', 'thumb'), 'data:image/jpeg;base64,' + B64);
  assert.deepEqual(plain(sdk2.calls), [['server', owner], ['cache', thumb]]);
  // ③ 快取沒有 → 照舊上網讀照片（規則當場把關），不另外讀主人
  const sdk3 = fakeSdk({ server: { [thumb]: { data: B64 } } });
  assert.equal(await liveWith(C, sdk3).photoSrc(owner, 'a1b2c3d4e5f60718', 'thumb'), 'data:image/jpeg;base64,' + B64);
  assert.deepEqual(plain(sdk3.calls), [['cache', thumb], ['server', thumb]]);
});

test('部落格發文：date 等於 postId 的前 10 碼（規則會比對）', async () => {
  const { C } = load(ALL.concat(['core/photo-encode.js', 'core/blog-compose.js']));
  let sent = null;
  const store = { newPostId: (d) => C.util.newPostId(d), batch: async (ops) => { sent = ops; } };
  const session = { roles: { teacher: false, alias: 'abcdefabcdef', seatKind: 'parent', seats: ['01'] } };
  const postId = await C.blogCompose.submit(store, session, { seat: '01', title: '標題', body: '內文', photos: [] });
  assert.equal(sent[0].data.date, postId.slice(0, 10));
  assert.equal(sent[0].path, C.paths.entry('01', postId));
});

test('留言卡：作者代號短碼（前 4 碼）；格式不對不畫', () => {
  const { C } = load(ALL.concat(['core/comments.js']));
  const t = C.comments.aliasTag('abcd12345678');
  assert.equal(t.textContent, '#abcd');
  assert.match(t.getAttribute('title'), /代號/);
  assert.equal(C.comments.aliasTag('ABCD'), null);
  assert.equal(C.comments.aliasTag(undefined), null);
});
