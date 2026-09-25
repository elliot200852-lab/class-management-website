/* core.js — 通知信模組碰 Firestore 的部分（觸發器、佇列掃描、每日摘要、清舊資料）。

   每個函式都吃同一包 deps：{ db, mailer, cfg, now, log, sleep }
     db      firebase-admin 的 Firestore（正式＝管理身分，不受安全規則管；測試＝連模擬器）
     mailer  { send(msg) }：正式＝Gmail SMTP；模擬器與測試＝假的（寫進 _emulator_outbox 或記在陣列），絕不真的寄
     cfg     functions/cmw.generated.json（build_config.py 產生：專案、地區、網址、時區、備份門檻）
     now     () => 毫秒（測試可以把時間往後撥，驗 30 分鐘的延遲）
   index.js 只負責把它們接到觸發器與排程上。集合形狀見 docs/DATA-MODEL.md §2.18。 */
'use strict';

const { FieldValue, Timestamp } = require('firebase-admin/firestore');
const P = require('./pure');

const C = P.C;

function defaults(deps) {
  return Object.assign({
    now: () => Date.now(),
    sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
    log: { info() {}, warn() {}, error() {} },
  }, deps);
}

function isAlreadyExists(err) {
  return !!err && (err.code === 6 || err.code === 'already-exists' || /ALREADY_EXISTS/i.test(String(err.message || err)));
}

async function loadSettings(db) {
  const snap = await db.doc('config/notify').get();
  return P.normalizeSettings(snap.exists ? snap.data() : null);
}

/** 即時信寄不出去時記在 ops/notify_status（每日摘要會列出來）；信箱一律遮掉。 */
async function recordInstantError(d, where, err) {
  const msg = P.maskEmails(String((err && err.message) || err)).slice(0, 300);
  d.log.error('即時通知寄不出去', { where, err: msg });
  try {
    await d.db.doc('ops/notify_status').set({
      lastInstantError: `${where}：${msg}`,
      lastInstantErrorAt: FieldValue.serverTimestamp(),
    }, { merge: true });
  } catch (e) {
    d.log.error('寫 ops/notify_status 失敗', { err: String(e) });
  }
}

/** 給導師的即時信：同一個事件只寄一次（notify_once 先佔位再寄）。 */
async function sendTeacherOnce(d, settings, kind, path, mail) {
  const ref = d.db.collection('notify_once').doc(P.onceId(kind, path));
  try {
    await ref.create({ kind, at: FieldValue.serverTimestamp() });
  } catch (err) {
    if (isAlreadyExists(err)) {
      d.log.info('這個事件已經通知過（觸發器重送），略過', { kind });
      return 'duplicate';
    }
    throw err;
  }
  try {
    await d.mailer.send(Object.assign(P.envelope(settings, settings.teacherEmail), mail));
    await d.db.doc('ops/notify_status').set({ lastInstantAt: FieldValue.serverTimestamp() }, { merge: true });
    return 'sent';
  } catch (err) {
    await recordInstantError(d, kind, err);
    return 'error';
  }
}

function teacherGate(d, settings, data, what) {
  if (settings.phase === 'off' || !settings.teacherMail) return 'off';
  const g = P.gateContent(settings, P.toMillis(data && data.createdAt), d.now());
  if (!g.ok) {
    d.log.info('不寄（' + g.reason + '）', { what });
    return g.reason;
  }
  return null;
}

// ── 觸發器 1：紀事、相簿、私密紀事的新留言 → 導師 ──────────────────────────────

async function onComment(deps, { parent, slug, cid }, data) {
  const d = defaults(deps);
  if (!['posts', 'albums', 'private_posts'].includes(parent) || !P.RE.slug.test(String(slug)) || !P.RE.cid.test(String(cid))) {
    return 'bad-path';
  }
  if (!data || data.status !== 'visible') return 'not-visible';
  if (data.role === 'teacher') return 'teacher-self';           // 導師自己的留言不用寄給自己
  const settings = await loadSettings(d.db);
  const stop = teacherGate(d, settings, data, 'comment');
  if (stop) return stop;
  let title = '';
  if (parent !== 'private_posts') {
    const ps = await d.db.doc(`${parent}/${slug}`).get();
    title = ps.exists ? String((ps.data() || {}).title || '') : '';
  }
  const mail = P.teacherCommentMail(settings, d.cfg.siteUrl, { parent, slug, title, role: data.role });
  return sendTeacherOnce(d, settings, 'comment', `${parent}/${slug}/comments/${cid}`, mail);
}

// ── 觸發器 2：部落格文章 → 家長發的寄導師；導師發的排進佇列（30 分鐘後寄家長）────────────

async function enqueue(d, settings, { kind, seat, postId, cid, createdMs }) {
  if (settings.phase === 'off' || !settings.parentMail) return 'off';
  const g = P.gateContent(settings, createdMs, d.now());
  if (!g.ok) {
    d.log.info('不排進家長通知佇列（' + g.reason + '）', { seat, kind });
    return g.reason;
  }
  const id = kind === 'comment' ? `${seat}__${postId}__${cid}` : `${seat}__${postId}`;
  const doc = {
    kind, seat, postId,
    state: 'pending',
    phaseAtEnqueue: settings.phase,
    attempts: 0,
    enqueuedAt: FieldValue.serverTimestamp(),
    contentCreatedAt: Timestamp.fromMillis(createdMs),
    sendAfter: Timestamp.fromMillis(createdMs + C.DELAY_MS),
  };
  if (kind === 'comment') doc.cid = cid;
  try {
    await d.db.collection('blog_notify_queue').doc(id).create(doc);
    return 'queued';
  } catch (err) {
    if (isAlreadyExists(err)) return 'duplicate';               // 觸發器重送：doc id 固定，天然只排一次
    throw err;
  }
}

async function onEntry(deps, { seat, postId }, data) {
  const d = defaults(deps);
  if (!P.RE.seat.test(String(seat)) || !P.RE.postId.test(String(postId))) return 'bad-path';
  if (!data) return 'no-data';
  const settings = await loadSettings(d.db);
  if (data.author === 'teacher') {
    return enqueue(d, settings, { kind: 'post', seat, postId, createdMs: P.toMillis(data.createdAt) });
  }
  if (data.author !== 'parent') return 'unknown-author';
  if (data.visible !== true) return 'not-visible';
  const stop = teacherGate(d, settings, data, 'entry');
  if (stop) return stop;
  const mail = P.teacherEntryMail(settings, d.cfg.siteUrl, {
    seat, postId, title: data.title || '（無標題）', photoCount: Array.isArray(data.photos) ? data.photos.length : 0,
  });
  return sendTeacherOnce(d, settings, 'entry', `student_blogs/${seat}/entries/${postId}`, mail);
}

// ── 觸發器 3：部落格對話串 → 家長的話寄導師；導師的回覆排進佇列 ─────────────────────────

async function onBlogComment(deps, { seat, postId, cid }, data) {
  const d = defaults(deps);
  if (!P.RE.seat.test(String(seat)) || !P.RE.postId.test(String(postId)) || !P.RE.cid.test(String(cid))) return 'bad-path';
  if (!data || data.status !== 'visible') return 'not-visible';
  const settings = await loadSettings(d.db);
  if (data.role === 'teacher') {
    return enqueue(d, settings, { kind: 'comment', seat, postId, cid, createdMs: P.toMillis(data.createdAt) });
  }
  if (data.role !== 'parent') return 'unknown-role';
  const stop = teacherGate(d, settings, data, 'thread');
  if (stop) return stop;
  const es = await d.db.doc(`student_blogs/${seat}/entries/${postId}`).get();
  if (!es.exists) return 'entry-missing';
  const mail = P.teacherThreadMail(settings, d.cfg.siteUrl, { seat, postId, title: (es.data() || {}).title || '（無標題）' });
  return sendTeacherOnce(d, settings, 'thread', `student_blogs/${seat}/entries/${postId}/blog_comments/${cid}`, mail);
}

// ── 排程 1：每 10 分鐘掃一次佇列 ─────────────────────────────────────────────────

/** 拿租約：同一筆不會被兩輪同時處理（排程重疊、手動多跑一次都安全）。 */
async function takeLease(d, ref) {
  return d.db.runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    if (!snap.exists) return null;
    const q = snap.data() || {};
    if (q.state !== 'pending') return null;
    const lease = P.toMillis(q.leaseUntil);
    if (lease !== null && lease > d.now()) return null;
    tx.update(ref, { leaseUntil: Timestamp.fromMillis(d.now() + C.LEASE_MS) });
    return q;
  });
}

async function finish(ref, fields) {
  await ref.update(Object.assign({ leaseUntil: FieldValue.delete(), doneAt: FieldValue.serverTimestamp() }, fields));
}

async function recipientsForSeat(d, seat) {
  const snap = await d.db.collection('parent_child_map').where('seats', 'array-contains', seat).get();
  const docs = snap.docs.map((x) => ({ id: x.id, data: x.data() }));
  const allow = new Set();
  const refs = docs.map((x) => d.db.doc(`allowlist/${x.id}`));
  if (refs.length) {
    const got = await d.db.getAll(...refs);
    got.forEach((g) => { if (g.exists) allow.add(g.id); });
  }
  return P.recipientsFrom(docs, seat, allow);
}

async function processItem(d, settings, ref, q) {
  const seat = String(q.seat || '');
  const postId = String(q.postId || '');
  const kind = q.kind === 'comment' ? 'comment' : 'post';
  const cid = String(q.cid || '');
  if (!P.RE.seat.test(seat) || !P.RE.postId.test(postId) || (kind === 'comment' && !P.RE.cid.test(cid))) {
    await finish(ref, { state: 'failed', reason: 'bad-item' });
    return 'failed';
  }
  // 1. 重讀文章（與回覆）：30 分鐘的修正窗靠這一步生效——窗內刪掉、下架、收起，就整筆取消
  const es = await d.db.doc(`student_blogs/${seat}/entries/${postId}`).get();
  if (!es.exists) { await finish(ref, { state: 'cancelled', reason: 'entry-deleted' }); return 'cancelled'; }
  const entry = es.data() || {};
  if (entry.visible !== true) { await finish(ref, { state: 'cancelled', reason: 'entry-hidden' }); return 'cancelled'; }
  if (kind === 'post' && entry.author !== 'teacher') { await finish(ref, { state: 'cancelled', reason: 'not-teacher' }); return 'cancelled'; }
  let createdMs = P.toMillis(entry.createdAt);
  if (kind === 'comment') {
    const cs = await d.db.doc(`student_blogs/${seat}/entries/${postId}/blog_comments/${cid}`).get();
    if (!cs.exists) { await finish(ref, { state: 'cancelled', reason: 'reply-deleted' }); return 'cancelled'; }
    const c = cs.data() || {};
    if (c.role !== 'teacher') { await finish(ref, { state: 'cancelled', reason: 'not-teacher' }); return 'cancelled'; }
    if (c.status !== 'visible') { await finish(ref, { state: 'cancelled', reason: 'reply-hidden' }); return 'cancelled'; }
    createdMs = P.toMillis(c.createdAt);
  }
  // 2. 回填閘：一定 fail-closed（時間讀不懂就不寄）。這裡不看「觸發時多久以前」：佇列本來就是 30 分鐘後才寄。
  if (createdMs === null) { await finish(ref, { state: 'failed', reason: 'no-createdAt' }); return 'failed'; }
  if (settings.floorMs === null || createdMs < settings.floorMs) {
    await finish(ref, { state: 'skipped', reason: 'before-floor' });
    return 'skipped';
  }
  // 3. 收件人
  const recipients = await recipientsForSeat(d, seat);
  const mode = P.parentModeFor(q, settings);
  if (mode === 'dryrun') {
    await finish(ref, { state: 'done', mode: 'dryrun', recipientCount: recipients.length, sentCount: 0, lastError: '' });
    return 'dryrun';
  }
  if (recipients.length === 0) {
    await finish(ref, { state: 'done', mode: 'live', reason: 'no-recipients', recipientCount: 0, sentCount: 0, lastError: '' });
    return 'done';
  }
  // 4. live：一位一封（併寄會讓家長互相看到信箱），逐位記台帳
  const mail = P.parentMail(settings, d.cfg.siteUrl, { kind, seat, postId, title: entry.title });
  let sent = 0;
  const errors = [];
  for (let i = 0; i < recipients.length; i += 1) {
    if (i > 0) await d.sleep(C.SEND_GAP_MS);
    const key = recipients[i];
    const ledger = ref.collection('sent').doc(P.ledgerId(key));
    try {
      await ledger.create({ state: 'sending', at: FieldValue.serverTimestamp() });
    } catch (err) {
      if (isAlreadyExists(err)) { sent += 1; continue; }     // 上一輪已經寄過（或寄到一半斷掉）：寧可少寄，不重寄
      throw err;
    }
    try {
      await d.mailer.send(Object.assign(P.envelope(settings, key), mail));
      await ledger.update({ state: 'sent', sentAt: FieldValue.serverTimestamp() });
      sent += 1;
    } catch (err) {
      errors.push(P.maskEmails(String((err && err.message) || err)).slice(0, 200));
      await ledger.delete().catch(() => {});                 // 沒寄出去：拿掉佔位，下一輪可以再試這一位
    }
  }
  if (errors.length) {
    const attempts = (Number(q.attempts) || 0) + 1;
    const give = attempts >= C.MAX_ATTEMPTS;
    const upd = {
      attempts, lastError: errors.join(' | ').slice(0, 500), recipientCount: recipients.length, sentCount: sent,
      leaseUntil: FieldValue.delete(),
    };
    if (give) Object.assign(upd, { state: 'failed', reason: 'send-failed', doneAt: FieldValue.serverTimestamp() });
    await ref.update(upd);
    return give ? 'failed' : 'retry';
  }
  await finish(ref, { state: 'done', mode: 'live', recipientCount: recipients.length, sentCount: sent, lastError: '' });
  return 'sent';
}

async function sweepOnce(deps) {
  const d = defaults(deps);
  const stats = { processed: 0, sent: 0, dryrun: 0, cancelled: 0, skipped: 0, failed: 0, retry: 0, done: 0 };
  let settings = null;
  let lastError = '';
  try {
    settings = await loadSettings(d.db);
    if (settings.phase === 'off' || !settings.parentMail) {
      // 關掉＝煞車：排隊中的一律取消（不會積到下次打開時一次補寄）
      const pend = await d.db.collection('blog_notify_queue').where('state', '==', 'pending').limit(200).get();
      for (const doc of pend.docs) {
        await finish(doc.ref, { state: 'cancelled', reason: 'notify-off' });
        stats.cancelled += 1;
      }
    } else {
      const due = await d.db.collection('blog_notify_queue')
        .where('state', '==', 'pending')
        .where('sendAfter', '<=', Timestamp.fromMillis(d.now()))
        .orderBy('sendAfter', 'asc')
        .limit(C.SWEEP_LIMIT)
        .get();
      for (const doc of due.docs) {
        try {
          const q = await takeLease(d, doc.ref);
          if (!q) continue;
          stats.processed += 1;
          const r = await processItem(d, settings, doc.ref, q);
          stats[r] = (stats[r] || 0) + 1;
        } catch (err) {
          lastError = P.maskEmails(String((err && err.message) || err)).slice(0, 300);
          d.log.error('處理佇列單筆失敗（下一輪再試）', { id: doc.id, err: lastError });
        }
      }
    }
  } catch (err) {
    lastError = P.maskEmails(String((err && err.message) || err)).slice(0, 300);
    d.log.error('掃佇列整輪失敗', { err: lastError });
  }
  // 心跳：就算上面整輪失敗也要寫（每日摘要與 notify_config.py 靠它知道排程還活著）
  try {
    let pending = null;
    try {
      const agg = await d.db.collection('blog_notify_queue').where('state', '==', 'pending').count().get();
      pending = agg.data().count;
    } catch (e) { /* 心跳其他欄位照寫 */ }
    await d.db.doc('ops/notify_status').set(Object.assign({
      lastRunAt: FieldValue.serverTimestamp(),
      phase: settings ? settings.phase : 'unknown',
      pending,
      lastError,
    }, stats), { merge: true });
  } catch (err) {
    d.log.error('寫心跳失敗', { err: String(err) });
  }
  return stats;
}

// ── 排程 2：每日摘要（寄給導師自己）＋清掉 30 天以前的佇列與台帳 ─────────────────────────

function sinceOk(v, sinceMs) {
  const t = P.toMillis(v);
  return t !== null && t >= sinceMs;
}

async function titlesOf(d, paths) {
  const out = {};
  const uniq = Array.from(new Set(paths));
  for (let i = 0; i < uniq.length; i += 100) {
    const refs = uniq.slice(i, i + 100).map((p) => d.db.doc(p));
    if (!refs.length) continue;
    const got = await d.db.getAll(...refs);
    got.forEach((g) => { out[g.ref.path] = g.exists ? String((g.data() || {}).title || '') : ''; });
  }
  return out;
}

async function collectDigest(d, settings) {
  const now = d.now();
  const since = now - C.DIGEST_WINDOW_MS;
  // 新留言：查詢登記表的 comments.admin（集合群組、createdAt 由新到舊），時間窗在程式裡切
  const cs = await d.db.collectionGroup('comments').orderBy('createdAt', 'desc').limit(200).get();
  const byThread = new Map();
  let inWindow = 0;
  for (const doc of cs.docs) {
    const c = doc.data() || {};
    if (!sinceOk(c.createdAt, since)) continue;
    inWindow += 1;
    if (c.status !== 'visible' || c.role === 'teacher') continue;
    const parentRef = doc.ref.parent.parent;
    if (!parentRef) continue;
    const parent = parentRef.parent.id;
    if (!['posts', 'albums', 'private_posts'].includes(parent)) continue;
    const k = parentRef.path;
    if (!byThread.has(k)) byThread.set(k, { parent, slug: parentRef.id, title: '', counts: { parent: 0, staff: 0 } });
    const t = byThread.get(k);
    if (c.role === 'staff') t.counts.staff += 1; else t.counts.parent += 1;
  }
  const titled = await titlesOf(d, Array.from(byThread.keys()).filter((k) => !k.startsWith('private_posts/')));
  const comments = Array.from(byThread.entries()).map(([k, v]) => Object.assign(v, { title: titled[k] || '' }));
  // 家長發的部落格：entries.recentParent
  const es = await d.db.collectionGroup('entries').where('author', '==', 'parent').orderBy('createdAt', 'desc').limit(100).get();
  const entries = [];
  for (const doc of es.docs) {
    const e = doc.data() || {};
    if (!sinceOk(e.createdAt, since)) continue;
    const seat = doc.ref.parent.parent ? doc.ref.parent.parent.id : '';
    entries.push({ seat, postId: doc.id, title: e.title || '（無標題）' });
  }
  // 家長在對話串留的話：blogComments.recentParent
  const bs = await d.db.collectionGroup('blog_comments').where('role', '==', 'parent').orderBy('createdAt', 'desc').limit(200).get();
  const threads = new Map();
  for (const doc of bs.docs) {
    const c = doc.data() || {};
    if (!sinceOk(c.createdAt, since) || c.status !== 'visible') continue;
    const entryRef = doc.ref.parent.parent;
    if (!entryRef) continue;
    const seat = entryRef.parent.parent ? entryRef.parent.parent.id : '';
    if (!threads.has(entryRef.path)) threads.set(entryRef.path, { seat, postId: entryRef.id, title: '', n: 0 });
    threads.get(entryRef.path).n += 1;
  }
  const tt = await titlesOf(d, Array.from(threads.keys()));
  const threadList = Array.from(threads.entries()).map(([k, v]) => Object.assign(v, { title: tt[k] || '（無標題）' }));

  // 需要處理：名單包含關係
  const problems = [];
  const [al, pl, pm] = await Promise.all([
    d.db.collection('allowlist').limit(500).get(),
    d.db.collection('private_allowlist').limit(500).get(),
    d.db.collection('parent_child_map').limit(500).get(),
  ]);
  const toObj = (snap) => { const o = {}; snap.docs.forEach((x) => { o[x.id] = x.data(); }); return o; };
  problems.push(...P.inclusionProblems(toObj(al), toObj(pl), toObj(pm), settings.teacherKey).map((x) => '名單：' + x));

  // 備份心跳（門檻跟 status.py 一樣）
  const bk = await d.db.doc('ops/backup_status').get();
  const backup = P.backupReport(bk.exists ? bk.data() : null, now, d.cfg.backupRemindDays, d.cfg.backupUrgentDays);
  problems.push(...backup.problems);

  // 給家長的通知線
  const ns = await d.db.doc('ops/notify_status').get();
  const qs = await d.db.collection('blog_notify_queue').where('enqueuedAt', '>=', Timestamp.fromMillis(since)).limit(500).get();
  const tally = { done: 0, dryrun: 0, cancelled: 0, failed: 0, pending: 0, skipped: 0 };
  for (const doc of qs.docs) {
    const q = doc.data() || {};
    if (q.state === 'done' && q.mode === 'dryrun') tally.dryrun += 1;
    else if (Object.prototype.hasOwnProperty.call(tally, q.state)) tally[q.state] += 1;
  }
  const stuckSnap = await d.db.collection('blog_notify_queue')
    .where('state', '==', 'pending').where('sendAfter', '<=', Timestamp.fromMillis(now - C.STUCK_MS))
    .orderBy('sendAfter', 'asc').limit(50).get();
  problems.push(...P.notifyProblems({
    settings, status: ns.exists ? ns.data() : null, nowMs: now, failed: tally.failed, stuck: stuckSnap.size,
  }));
  let notifyLine = '';
  if (settings.parentMail && settings.phase !== 'off') {
    notifyLine = `模式 ${settings.phase === 'live' ? 'live（真的寄給家長）' : 'dryrun（只記錄、不寄給家長）'}｜`
      + `寄出 ${tally.done} 篇、只記錄 ${tally.dryrun}、取消 ${tally.cancelled}、失敗 ${tally.failed}、排隊中 ${tally.pending}`;
  }
  return {
    comments, entries, threads: threadList, problems, backupLines: backup.lines, notifyLine,
    moreComments: cs.size >= 200 && inWindow >= 200,
  };
}

async function housekeeping(d) {
  const cutoff = Timestamp.fromMillis(d.now() - C.RETENTION_MS);
  let removed = 0;
  const old = await d.db.collection('blog_notify_queue').where('enqueuedAt', '<', cutoff).limit(C.CLEAN_LIMIT).get();
  for (const doc of old.docs) {
    const q = doc.data() || {};
    if (q.state === 'pending') continue;
    const sent = await doc.ref.collection('sent').limit(50).get();
    const batch = d.db.batch();
    sent.docs.forEach((s) => batch.delete(s.ref));
    batch.delete(doc.ref);
    await batch.commit();
    removed += 1;
  }
  const once = await d.db.collection('notify_once').where('at', '<', cutoff).limit(C.CLEAN_LIMIT * 2).get();
  if (!once.empty) {
    const batch = d.db.batch();
    once.docs.forEach((s) => batch.delete(s.ref));
    await batch.commit();
    removed += once.size;
  }
  return removed;
}

async function runDigest(deps) {
  const d = defaults(deps);
  const settings = await loadSettings(d.db);
  const beat = { lastRunAt: FieldValue.serverTimestamp(), sent: false, problems: 0, lastError: '' };
  try {
    try {
      beat.cleaned = await housekeeping(d);
    } catch (err) {
      d.log.warn('清舊佇列失敗（不影響摘要）', { err: String(err) });
    }
    if (settings.phase === 'off' || !settings.digest) {
      beat.skipped = 'off';
    } else {
      const data = await collectDigest(d, settings);
      beat.problems = data.problems.length;
      if (P.digestWorthSending(data)) {
        const mail = P.digestMail(settings, d.cfg, d.now(), data);
        await d.mailer.send(Object.assign(P.envelope(settings, settings.teacherEmail), mail));
        beat.sent = true;
      }
    }
  } catch (err) {
    beat.lastError = P.maskEmails(String((err && err.message) || err)).slice(0, 300);
    d.log.error('每日摘要失敗', { err: beat.lastError });
  }
  await d.db.doc('ops/digest_status').set(beat, { merge: true });
  return beat;
}

module.exports = { loadSettings, onComment, onEntry, onBlogComment, sweepOnce, runDigest, collectDigest, housekeeping };
