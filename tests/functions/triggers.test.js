// 觸發器接線（Firestore 模擬器 → Functions 模擬器 → functions/index.js）：寫一份文件，看對的那支 Function 有沒有被叫到、
// 做對的事。模擬器裡的郵差一律是假的（functions/lib/mailer.js：寫進 _emulator_outbox），**絕不連任何郵件伺服器**。
// 佇列延遲、取消、台帳這些時間相關的細節在 core.test.js（可以把時間往後撥）。
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const S = require('./support');

const { db, FieldValue, Timestamp, PEOPLE } = S;

async function outbox() {
  const s = await db.collection('_emulator_outbox').get();
  return s.docs.map((d) => d.data());
}

async function waitMail(pred, what) {
  return S.waitFor(async () => (await outbox()).find(pred), 30000, what);
}

function comment(role, body) {
  return { body, role, authorAlias: role === 'teacher' ? 'aaaaaaaaaaa1' : 'aaaaaaaaaaa2', authorName: 'A 的媽媽',
    status: 'visible', createdAt: FieldValue.serverTimestamp() };
}

test('觸發器接線：留言、部落格、對話串', { timeout: 240000 }, async (t) => {
  await S.clearAll();
  await S.seedClass({ phase: 'dryrun', notifyFloor: Timestamp.fromMillis(Date.now() - 60 * 60 * 1000) });

  await t.test('紀事的家長留言 → 寄導師（不夾留言正文）；導師自己的留言不寄', async () => {
    await db.doc('posts/2026-10-01-walk').set({ title: '秋天的散步', visible: true });
    await db.collection('posts/2026-10-01-walk/comments').add(comment('teacher', '導師自己的回覆'));
    await db.collection('posts/2026-10-01-walk/comments').add(comment('parent', '家長留言的正文'));
    const m = await waitMail((x) => /紀事〈秋天的散步〉/.test(x.subject), '紀事留言通知');
    assert.deepEqual(m.to, [S.T]);
    assert.equal(m.text.includes('家長留言的正文'), false);
    assert.match(m.text, /post\.html\?s=2026-10-01-walk/);
  });

  await t.test('相簿與私密紀事的留言也會寄；私密紀事不寫標題', async () => {
    await db.doc('albums/2026-10-01-trip').set({ title: '遠足', visible: true });
    await db.doc('private_posts/2026-10-01-talk').set({ title: '私密的標題', visible: true });
    await db.collection('albums/2026-10-01-trip/comments').add(comment('parent', 'x'));
    await db.collection('private_posts/2026-10-01-talk/comments').add(comment('parent', 'y'));
    const a = await waitMail((x) => /相簿〈遠足〉/.test(x.subject), '相簿留言通知');
    assert.match(a.text, /album\.html\?a=2026-10-01-trip/);
    const p = await waitMail((x) => /私密紀事（2026-10-01-talk）/.test(x.subject), '私密紀事留言通知');
    assert.equal(p.subject.includes('私密的標題') || p.text.includes('私密的標題'), false);
  });

  let te = null;
  await t.test('家長發部落格 → 寄導師；導師發文 → 排進佇列（dryrun 期間排的，標記 dryrun）', async () => {
    const pe = S.postId();
    await db.doc(`student_blogs/03/entries/${pe}`).set(Object.assign(S.entryDoc('parent', Date.now()),
      { createdAt: FieldValue.serverTimestamp() }));
    const m = await waitMail((x) => x.subject.includes(`座號 03 的家長發了一篇部落格`), '家長發文通知');
    assert.equal(m.text.includes('這是正文'), false);
    te = S.postId();
    await db.doc(`student_blogs/03/entries/${te}`).set(Object.assign(S.entryDoc('teacher', Date.now()),
      { createdAt: FieldValue.serverTimestamp() }));
    const q = await S.waitFor(async () => {
      const s = await db.doc(`blog_notify_queue/03__${te}`).get();
      return s.exists ? s.data() : null;
    }, 30000, '導師發文入列');
    assert.equal(q.state, 'pending');
    assert.equal(q.phaseAtEnqueue, 'dryrun');
    assert.equal(q.sendAfter.toMillis() - q.contentCreatedAt.toMillis(), 30 * 60 * 1000);
    const mails = await outbox();
    assert.equal(mails.some((x) => x.to.includes(PEOPLE.mom3) || x.to.includes(PEOPLE.dad3)), false, '觸發器不直接寄給家長');

  });

  await t.test('對話串：家長回話寄導師；導師回覆排進佇列', async () => {
    assert.ok(te, '上一段要先建好導師的文章');
    await db.doc(`student_blogs/03/entries/${te}/blog_comments/r1`).set(comment('parent', '家長回話的正文'));
    const r = await waitMail((x) => /家長在〈今天的課堂〉回了一則/.test(x.subject), '對話串通知');
    assert.equal(r.text.includes('家長回話的正文'), false);
    await db.doc(`student_blogs/03/entries/${te}/blog_comments/r2`).set(comment('teacher', '老師的回覆'));
    const q2 = await S.waitFor(async () => {
      const s2 = await db.doc(`blog_notify_queue/03__${te}__r2`).get();
      return s2.exists ? s2.data() : null;
    }, 30000, '導師回覆入列');
    assert.equal(q2.kind, 'comment');
    assert.equal(q2.cid, 'r2');
  });

  await t.test('off：留言不寄、導師發文不排', async () => {
    await db.doc('config/notify').update({ phase: 'off' });
    const before = (await outbox()).length;
    await db.collection('posts/2026-10-01-walk/comments').add(comment('parent', '關掉之後的留言'));
    const te = S.postId();
    await db.doc(`student_blogs/03/entries/${te}`).set(Object.assign(S.entryDoc('teacher', Date.now()),
      { createdAt: FieldValue.serverTimestamp() }));
    // 關著的時候什麼都看不到（本來就該這樣），只能等：模擬器的觸發通常一秒內就跑完，這裡等 8 秒
    await new Promise((r) => setTimeout(r, 8000));
    const after = await outbox();
    assert.equal(after.length, before, '關著的時候那一則留言沒有寄');
    assert.equal((await db.doc(`blog_notify_queue/03__${te}`).get()).exists, false, '關著的時候導師發文沒有排');
  });
});
