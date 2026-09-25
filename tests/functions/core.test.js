// 通知信模組的核心流程（functions/lib/core.js）直接接 Firestore 模擬器跑：佇列 30 分鐘延遲與取消、回填閘、
// dryrun 不寄給家長、逐人台帳冪等、重試、兩輪同時掃、給導師的即時信、每日摘要、清舊佇列。
// 時間用注入的 now() 往後撥；寄信用假的郵差（記在陣列），**絕不真的寄信**。
// 觸發器本身接不接得上（Firestore → Functions 模擬器）在 triggers.test.js。
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const S = require('./support');

const core = require(path.join(S.FUNCTIONS, 'lib', 'core.js'));
const mailer = require(path.join(S.FUNCTIONS, 'lib', 'mailer.js'));
const P = require(path.join(S.FUNCTIONS, 'lib', 'pure.js'));
const { db, Timestamp, PEOPLE } = S;
const MIN = 60 * 1000;

function deps(now, m) {
  return { db, cfg: S.CFG, mailer: m || mailer.memoryMailer(), now: () => now, sleep: async () => {} };
}

async function teacherEntry(seat, createdMs, over) {
  const id = S.postId();
  await db.doc(`student_blogs/${seat}/entries/${id}`).set(S.entryDoc('teacher', createdMs, over));
  return id;
}

async function queueDoc(id) {
  const s = await db.doc(`blog_notify_queue/${id}`).get();
  return s.exists ? s.data() : null;
}

function bodyLeak(msgs) {
  return msgs.some((m) => String(m.text).includes('這是正文'));
}

test.beforeEach(async () => { await S.clearAll(); });

const T_OPTS = { timeout: 60000 };

test('導師發文：30 分鐘內不寄、之後一位家長一封（同仁、暫停、已不在名單、別的座號都不寄）', T_OPTS, async () => {
  await S.seedClass();
  const t0 = Date.now();
  const id = await teacherEntry('03', t0 - MIN);
  const data = (await db.doc(`student_blogs/03/entries/${id}`).get()).data();
  assert.equal(await core.onEntry(deps(t0), { seat: '03', postId: id }, data), 'queued');
  const q = await queueDoc(`03__${id}`);
  assert.equal(q.state, 'pending');
  assert.equal(q.phaseAtEnqueue, 'live');
  assert.equal(q.sendAfter.toMillis(), t0 - MIN + 30 * MIN, '延遲從內容建立的時間算 30 分鐘');
  assert.equal(await core.onEntry(deps(t0), { seat: '03', postId: id }, data), 'duplicate', '觸發器重送只排一次');

  const early = mailer.memoryMailer();
  const st1 = await core.sweepOnce(deps(t0 + 20 * MIN, early));
  assert.equal(st1.processed, 0);
  assert.equal(early.sent.length, 0, '修正窗內一封都不寄');

  const m = mailer.memoryMailer();
  const st2 = await core.sweepOnce(deps(t0 + 31 * MIN, m));
  assert.equal(st2.sent, 1);
  assert.deepEqual(m.sent.map((x) => x.to).sort(), [PEOPLE.dad3, PEOPLE.mom3].sort());
  for (const x of m.sent) {
    assert.equal(typeof x.to, 'string', '一封只寄一位，家長互相看不到信箱');
    assert.match(x.subject, /座號 03/);
    assert.match(x.text, /今天的課堂/);
    assert.match(x.text, new RegExp(`my-child\\.html#/entry/03/${id}`));
  }
  assert.equal(bodyLeak(m.sent), false, '信裡不夾正文');
  const done = await queueDoc(`03__${id}`);
  assert.equal(done.state, 'done');
  assert.equal(done.mode, 'live');
  assert.equal(done.sentCount, 2);
  const ledger = await db.collection(`blog_notify_queue/03__${id}/sent`).get();
  assert.deepEqual(ledger.docs.map((d) => d.id).sort(), [PEOPLE.dad3, PEOPLE.mom3].map((k) => P.ledgerId(k)).sort());
  assert.ok(ledger.docs.every((d) => d.data().state === 'sent'));
  assert.equal(JSON.stringify(ledger.docs.map((d) => d.data())).includes('example.com'), false, '台帳不存信箱原文');

  const again = mailer.memoryMailer();
  await core.sweepOnce(deps(t0 + 50 * MIN, again));
  assert.equal(again.sent.length, 0, '寄完不會再寄');
  const hb = (await db.doc('ops/notify_status').get()).data();
  assert.ok(hb.lastRunAt, '每一輪都寫心跳');
  assert.equal(hb.phase, 'live');
});

test('修正窗內下架、刪掉、收起回覆：整筆取消，一封都不寄', T_OPTS, async () => {
  await S.seedClass();
  const t0 = Date.now();
  const hidden = await teacherEntry('03', t0);
  const deleted = await teacherEntry('03', t0);
  const withReply = await teacherEntry('03', t0);
  for (const id of [hidden, deleted, withReply]) {
    const data = (await db.doc(`student_blogs/03/entries/${id}`).get()).data();
    await core.onEntry(deps(t0), { seat: '03', postId: id }, data);
  }
  const cid = 'reply0001';
  const reply = { body: '老師的回覆', role: 'teacher', authorAlias: 'aaaaaaaaaaa1', status: 'visible', createdAt: Timestamp.fromMillis(t0) };
  await db.doc(`student_blogs/03/entries/${withReply}/blog_comments/${cid}`).set(reply);
  assert.equal(await core.onBlogComment(deps(t0), { seat: '03', postId: withReply, cid }, reply), 'queued');
  // 窗內改主意
  await db.doc(`student_blogs/03/entries/${hidden}`).update({ visible: false });
  await db.doc(`student_blogs/03/entries/${deleted}`).delete();
  await db.doc(`student_blogs/03/entries/${withReply}/blog_comments/${cid}`).update({ status: 'hidden' });
  const m = mailer.memoryMailer();
  await core.sweepOnce(deps(t0 + 31 * MIN, m));
  assert.equal((await queueDoc(`03__${hidden}`)).reason, 'entry-hidden');
  assert.equal((await queueDoc(`03__${deleted}`)).reason, 'entry-deleted');
  assert.equal((await queueDoc(`03__${withReply}__${cid}`)).reason, 'reply-hidden');
  // 導師那篇文章本身沒有下架：照寄
  assert.equal((await queueDoc(`03__${withReply}`)).state, 'done');
  assert.equal(m.sent.length, 2, '只有那篇沒被撤的文章寄給兩位家長');
});

test('dryrun：給家長的信只記錄不寄；dryrun 期間排的，切 live 也不補寄；live 排的窗內切回 dryrun 就煞住', T_OPTS, async () => {
  await S.seedClass({ phase: 'dryrun' });
  const t0 = Date.now();
  const a = await teacherEntry('03', t0);
  await core.onEntry(deps(t0), { seat: '03', postId: a }, (await db.doc(`student_blogs/03/entries/${a}`).get()).data());
  assert.equal((await queueDoc(`03__${a}`)).phaseAtEnqueue, 'dryrun');
  await db.doc('config/notify').update({ phase: 'live' });
  const b = await teacherEntry('03', t0);
  await core.onEntry(deps(t0), { seat: '03', postId: b }, (await db.doc(`student_blogs/03/entries/${b}`).get()).data());
  await db.doc('config/notify').update({ phase: 'dryrun' });
  const m = mailer.memoryMailer();
  const st = await core.sweepOnce(deps(t0 + 31 * MIN, m));
  assert.equal(m.sent.length, 0, 'dryrun 一封都不寄給家長');
  assert.equal(st.dryrun, 2);
  const qa = await queueDoc(`03__${a}`);
  assert.equal(qa.mode, 'dryrun');
  assert.equal(qa.recipientCount, 2, '記錄「如果上線會寄給幾位」');
  assert.equal((await queueDoc(`03__${b}`)).mode, 'dryrun');
});

test('off：不排新的；排隊中的一律取消（不會積到下次打開時補寄）', T_OPTS, async () => {
  await S.seedClass();
  const t0 = Date.now();
  const a = await teacherEntry('03', t0);
  await core.onEntry(deps(t0), { seat: '03', postId: a }, (await db.doc(`student_blogs/03/entries/${a}`).get()).data());
  await db.doc('config/notify').update({ phase: 'off' });
  const b = await teacherEntry('03', t0);
  assert.equal(await core.onEntry(deps(t0), { seat: '03', postId: b }, (await db.doc(`student_blogs/03/entries/${b}`).get()).data()), 'off');
  assert.equal(await queueDoc(`03__${b}`), null);
  const m = mailer.memoryMailer();
  const st = await core.sweepOnce(deps(t0 + 5 * MIN, m));
  assert.equal(st.cancelled, 1);
  assert.equal((await queueDoc(`03__${a}`)).reason, 'notify-off');
  await db.doc('config/notify').update({ phase: 'live' });
  await core.sweepOnce(deps(t0 + 40 * MIN, m));
  assert.equal(m.sent.length, 0, '重新打開也不補寄');
});

test('回填閘：起始線之前的內容、觸發時已經是 2 小時前的內容、沒有時間的內容，一律不寄', T_OPTS, async () => {
  const t0 = Date.now();
  await S.seedClass({ notifyFloor: Timestamp.fromMillis(t0 - 10 * 60 * MIN) });
  const old = await teacherEntry('03', t0 - 11 * 60 * MIN);
  const stale = await teacherEntry('03', t0 - 3 * 60 * MIN);
  const noTime = await teacherEntry('03', t0, { createdAt: null });
  const get = async (id) => (await db.doc(`student_blogs/03/entries/${id}`).get()).data();
  assert.equal(await core.onEntry(deps(t0), { seat: '03', postId: old }, await get(old)), 'before-floor');
  assert.equal(await core.onEntry(deps(t0), { seat: '03', postId: stale }, await get(stale)), 'stale-event', '還原備份的舊文');
  assert.equal(await core.onEntry(deps(t0), { seat: '03', postId: noTime }, await get(noTime)), 'no-createdAt');
  // 佇列裡被塞了一筆起始線以前的內容（例如從別處搬來）：掃到時也擋
  await db.doc(`blog_notify_queue/03__${old}`).set({ kind: 'post', seat: '03', postId: old, state: 'pending', phaseAtEnqueue: 'live',
    attempts: 0, sendAfter: Timestamp.fromMillis(t0 - MIN), enqueuedAt: Timestamp.fromMillis(t0) });
  const m = mailer.memoryMailer();
  await core.sweepOnce(deps(t0, m));
  assert.equal((await queueDoc(`03__${old}`)).state, 'skipped');
  assert.equal(m.sent.length, 0);
  // 給導師的即時信同一套閘
  const c = { body: '舊留言', role: 'parent', authorAlias: 'aaaaaaaaaaa2', authorName: 'A 的媽媽', status: 'visible',
    createdAt: Timestamp.fromMillis(t0 - 11 * 60 * MIN) };
  assert.equal(await core.onComment(deps(t0, m), { parent: 'posts', slug: '2026-10-01-walk', cid: 'c1' }, c), 'before-floor');
});

test('逐人台帳：寄到一半斷掉，重跑只補沒寄的那一位；寄失敗會重試、錯誤訊息遮掉信箱', T_OPTS, async () => {
  await S.seedClass();
  const t0 = Date.now();
  const a = await teacherEntry('03', t0);
  await core.onEntry(deps(t0), { seat: '03', postId: a }, (await db.doc(`student_blogs/03/entries/${a}`).get()).data());
  // 模擬「媽媽那封寄出去了，但還沒記完就斷電」：台帳只剩佔位
  await db.doc(`blog_notify_queue/03__${a}/sent/${P.ledgerId(PEOPLE.mom3)}`).set({ state: 'sending' });
  const failing = mailer.memoryMailer((msg) => msg.to === PEOPLE.dad3);
  const st = await core.sweepOnce(deps(t0 + 31 * MIN, failing));
  assert.equal(st.retry, 1);
  assert.equal(failing.sent.length, 0, '媽媽已經有台帳（寧可少寄不重寄）；爸爸這次失敗');
  const q1 = await queueDoc(`03__${a}`);
  assert.equal(q1.state, 'pending');
  assert.equal(q1.attempts, 1);
  assert.equal(q1.lastError.includes(PEOPLE.dad3), false, '退信訊息裡的信箱要遮掉');
  assert.equal((await db.doc(`blog_notify_queue/03__${a}/sent/${P.ledgerId(PEOPLE.dad3)}`).get()).exists, false,
    '失敗的那位不留佔位，下一輪才能再試');
  const ok = mailer.memoryMailer();
  await core.sweepOnce(deps(t0 + 45 * MIN, ok));
  assert.deepEqual(ok.sent.map((x) => x.to), [PEOPLE.dad3]);
  const q2 = await queueDoc(`03__${a}`);
  assert.equal(q2.state, 'done');
  assert.equal(q2.sentCount, 2);
});

test('寄失敗 5 次就放棄（failed），每日摘要會列出來', T_OPTS, async () => {
  await S.seedClass();
  const t0 = Date.now();
  const a = await teacherEntry('03', t0);
  await core.onEntry(deps(t0), { seat: '03', postId: a }, (await db.doc(`student_blogs/03/entries/${a}`).get()).data());
  const bad = mailer.memoryMailer(() => true);
  for (let i = 0; i < 5; i += 1) await core.sweepOnce(deps(t0 + (31 + i * 10) * MIN, bad));
  const q = await queueDoc(`03__${a}`);
  assert.equal(q.state, 'failed');
  assert.equal(q.attempts, 5);
});

test('兩輪同時掃（排程重疊）：每一筆只處理一次、每位家長只收一封', T_OPTS, async () => {
  await S.seedClass();
  const t0 = Date.now();
  const ids = [];
  for (let i = 0; i < 3; i += 1) {
    const id = await teacherEntry('03', t0);
    ids.push(id);
    await core.onEntry(deps(t0), { seat: '03', postId: id }, (await db.doc(`student_blogs/03/entries/${id}`).get()).data());
  }
  const m = mailer.memoryMailer();
  await Promise.all([core.sweepOnce(deps(t0 + 31 * MIN, m)), core.sweepOnce(deps(t0 + 31 * MIN, m))]);
  assert.equal(m.sent.length, 6, '三篇 × 兩位家長');
  const pairs = m.sent.map((x) => x.to + '|' + x.text);
  assert.equal(new Set(pairs).size, pairs.length, '沒有任何一封寄兩次');
});

test('給導師的即時信：家長留言、家長發文、家長回話寄；導師自己的不寄；同一個事件只寄一次；私密紀事不寫標題', T_OPTS, async () => {
  await S.seedClass({ phase: 'dryrun' });
  const t0 = Date.now();
  await db.doc('posts/2026-10-01-walk').set({ title: '秋天的散步', visible: true });
  await db.doc('private_posts/2026-10-01-talk').set({ title: '私密的標題', visible: true });
  const m = mailer.memoryMailer();
  const c = (role, body) => ({ body, role, authorAlias: 'aaaaaaaaaaa2', authorName: 'A 的媽媽', status: 'visible',
    createdAt: Timestamp.fromMillis(t0) });
  assert.equal(await core.onComment(deps(t0, m), { parent: 'posts', slug: '2026-10-01-walk', cid: 'c1' }, c('parent', '留言正文甲')), 'sent');
  assert.equal(await core.onComment(deps(t0, m), { parent: 'posts', slug: '2026-10-01-walk', cid: 'c1' }, c('parent', '留言正文甲')),
    'duplicate');
  assert.equal(await core.onComment(deps(t0, m), { parent: 'posts', slug: '2026-10-01-walk', cid: 'c2' }, c('teacher', '導師自己')),
    'teacher-self');
  assert.equal(await core.onComment(deps(t0, m), { parent: 'private_posts', slug: '2026-10-01-talk', cid: 'c3' }, c('parent', '私密留言')),
    'sent');
  const pe = S.postId();
  const entry = S.entryDoc('parent', t0);
  await db.doc(`student_blogs/03/entries/${pe}`).set(entry);
  assert.equal(await core.onEntry(deps(t0, m), { seat: '03', postId: pe }, entry), 'sent');
  assert.equal(await core.onBlogComment(deps(t0, m), { seat: '03', postId: pe, cid: 'r1' }, c('parent', '對話正文')), 'sent');
  assert.equal(m.sent.length, 4);
  assert.ok(m.sent.every((x) => x.to === S.T), '全部寄給導師（dryrun 也照寄導師自己）');
  assert.match(m.sent[0].subject, /紀事〈秋天的散步〉/);
  assert.equal(m.sent[1].subject.includes('私密的標題') || m.sent[1].text.includes('私密的標題'), false);
  assert.match(m.sent[1].subject, /2026-10-01-talk/);
  for (const x of m.sent) {
    for (const leak of ['留言正文甲', '私密留言', '對話正文', '這是正文']) assert.equal(x.text.includes(leak), false, leak);
  }
  await db.doc('config/notify').update({ teacherMail: false });
  assert.equal(await core.onComment(deps(t0, m), { parent: 'posts', slug: '2026-10-01-walk', cid: 'c9' }, c('parent', 'x')), 'off');
});

test('每日摘要：過去 24 小時的留言、家長發文、對話；名單與備份的問題；沒事就不寄；off 不寄', T_OPTS, async () => {
  const t0 = Date.now();
  await S.seedClass({ phase: 'dryrun' });
  await db.doc('posts/2026-10-01-walk').set({ title: '秋天的散步', visible: true });
  const cm = (role, status, ago) => ({ body: '摘要裡不該出現的留言正文', role, status, authorAlias: 'aaaaaaaaaaa2', authorName: 'x',
    createdAt: Timestamp.fromMillis(t0 - ago) });
  await db.doc('posts/2026-10-01-walk/comments/a').set(cm('parent', 'visible', 60 * MIN));
  await db.doc('posts/2026-10-01-walk/comments/b').set(cm('staff', 'visible', 2 * 60 * MIN));
  await db.doc('posts/2026-10-01-walk/comments/c').set(cm('teacher', 'visible', 60 * MIN));
  await db.doc('posts/2026-10-01-walk/comments/d').set(cm('parent', 'hidden', 60 * MIN));
  await db.doc('posts/2026-10-01-walk/comments/e').set(cm('parent', 'visible', 30 * 60 * MIN));
  const pe = S.postId();
  await db.doc(`student_blogs/03/entries/${pe}`).set(S.entryDoc('parent', t0 - 3 * 60 * MIN));
  await db.doc(`student_blogs/03/entries/${pe}/blog_comments/r1`).set(cm('parent', 'visible', 10 * MIN));
  await db.doc('ops/backup_status').set({ weekly: { lastRunAt: Timestamp.fromMillis(t0 - 3 * 24 * 60 * MIN), ok: true },
    nightly: { lastRunAt: Timestamp.fromMillis(t0 - 10 * 24 * 60 * MIN), ok: true } });
  await db.doc('private_allowlist/' + S.mail('not.in.allowlist')).set({ updatedAt: Timestamp.fromMillis(t0) });
  await db.doc('ops/notify_status').set({ lastRunAt: Timestamp.fromMillis(t0 - 5 * MIN) });
  const m = mailer.memoryMailer();
  const beat = await core.runDigest(deps(t0, m));
  assert.equal(beat.sent, true);
  assert.equal(m.sent.length, 1);
  const x = m.sent[0];
  assert.equal(x.to, S.T);
  assert.match(x.subject, /留言 2、部落格 1、對話 1｜要處理 3 項/);
  assert.match(x.text, /紀事〈秋天的散步〉：家長 1、同仁 1/);
  assert.match(x.text, /學生部落格備份（backup\.py blogs） 10 天沒有備份了/);
  assert.match(x.text, /私密讀者不在班網名單（n\*\*\*@example\.com）/);
  assert.equal(x.text.includes('摘要裡不該出現的留言正文') || x.text.includes('這是正文'), false);
  assert.equal(x.text.includes('not.in.allowlist'), false);
  assert.match(x.text, /座號對應的帳號不在班網名單（g\*\*\*@example\.com）/);
  assert.equal((await db.doc('ops/digest_status').get()).data().problems, 3);

  // 沒有新東西、也沒有問題：不寄空信（但心跳照寫）
  await S.clearAll();
  await S.seedClass({ phase: 'dryrun' });
  await db.doc('ops/backup_status').set({ weekly: { lastRunAt: Timestamp.fromMillis(t0 - 60 * MIN), ok: true },
    nightly: { lastRunAt: Timestamp.fromMillis(t0 - 60 * MIN), ok: true } });
  await db.doc('ops/notify_status').set({ lastRunAt: Timestamp.fromMillis(t0 - 5 * MIN) });
  await db.doc(`allowlist/${PEOPLE.ghost3}`).set({ kind: 'parent', alias: 'aaaaaaaaaaa7' });
  const quietM = mailer.memoryMailer();
  const b2 = await core.runDigest(deps(t0, quietM));
  assert.equal(quietM.sent.length, 0, JSON.stringify(b2));
  assert.equal((await db.doc('ops/digest_status').get()).data().sent, false);

  await db.doc('config/notify').update({ phase: 'off' });
  const b3 = await core.runDigest(deps(t0, quietM));
  assert.equal(b3.skipped, 'off');
});

test('清舊資料：30 天以前、已經結束的佇列連同台帳刪掉；還在排隊的不動', T_OPTS, async () => {
  await S.seedClass({ phase: 'off' });
  const t0 = Date.now();
  const old = Timestamp.fromMillis(t0 - 31 * 24 * 60 * MIN);
  await db.doc('blog_notify_queue/03__old-done').set({ state: 'done', enqueuedAt: old });
  await db.doc('blog_notify_queue/03__old-done/sent/abc').set({ state: 'sent' });
  await db.doc('blog_notify_queue/03__old-pending').set({ state: 'pending', enqueuedAt: old });
  await db.doc('blog_notify_queue/03__new-done').set({ state: 'done', enqueuedAt: Timestamp.fromMillis(t0) });
  await db.doc('notify_once/oldclaim').set({ kind: 'comment', at: old });
  await core.runDigest(deps(t0));
  assert.equal((await db.doc('blog_notify_queue/03__old-done').get()).exists, false);
  assert.equal((await db.doc('blog_notify_queue/03__old-done/sent/abc').get()).exists, false);
  assert.equal((await db.doc('blog_notify_queue/03__old-pending').get()).exists, true);
  assert.equal((await db.doc('blog_notify_queue/03__new-done').get()).exists, true);
  assert.equal((await db.doc('notify_once/oldclaim').get()).exists, false);
});
