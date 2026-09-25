// 模擬器測試共用：連 Firestore 模擬器的管理身分、清空資料庫、種一個虛構的班級。
// 只在 firebase emulators:exec 裡跑（FIRESTORE_EMULATOR_HOST 由它設好）；專案一律 demo- 開頭，碰不到任何真的雲端。
'use strict';

const path = require('node:path');
const { createRequire } = require('node:module');

const ROOT = path.resolve(__dirname, '..', '..');
const FUNCTIONS = path.join(ROOT, 'functions');
const fnRequire = createRequire(path.join(FUNCTIONS, 'index.js'));   // firebase-admin 從 functions/node_modules 拿（與正式同一份）
const { initializeApp, getApps } = fnRequire('firebase-admin/app');
const { getFirestore, Timestamp, FieldValue } = fnRequire('firebase-admin/firestore');

const PROJECT = process.env.GCLOUD_PROJECT || process.env.CMW_TEST_PROJECT || 'demo-cmw-fn';
const HOST = process.env.FIRESTORE_EMULATOR_HOST;
if (!HOST || !/^(127\.0\.0\.1|localhost|\[::1\]):\d+$/.test(HOST)) {
  throw new Error('這組測試只准連本機模擬器（FIRESTORE_EMULATOR_HOST），請用 python3 scripts/test_functions.py 跑');
}
if (!PROJECT.startsWith('demo-')) throw new Error('測試專案一定要 demo- 開頭');

if (!getApps().length) initializeApp({ projectId: PROJECT });
const db = getFirestore();

const AT = '@';
const mail = (n) => n + AT + 'example.com';
const T = mail('class.teacher');
const PEOPLE = {
  teacher: T,
  mom3: mail('mom.three'),
  dad3: mail('dad.three'),           // 兩個孩子（03、07）的家長
  staff3: mail('staff.one'),          // 同仁，對應 03 但不是家長
  paused3: mail('paused.three'),      // 暫停
  ghost3: mail('ghost.three'),        // 座號對應還在、但已經不在班網名單
  mom4: mail('mom.four'),
};

const CFG = Object.freeze({
  format: 1, projectId: PROJECT, region: 'asia-east1', siteUrl: `https://${PROJECT}.firebaseapp.com`,
  timeZone: 'Asia/Taipei', digestHour: 7, backupRemindDays: 7, backupUrgentDays: 14,
});

async function clearAll() {
  const url = `http://${HOST}/emulator/v1/projects/${PROJECT}/databases/(default)/documents`;
  const r = await fetch(url, { method: 'DELETE' });
  if (!r.ok) throw new Error('清空模擬器失敗：' + r.status);
}

function notifyDoc(over) {
  return Object.assign({
    phase: 'live', teacherMail: true, parentMail: true, digest: true,
    notifyFloor: Timestamp.fromMillis(Date.now() - 24 * 3600 * 1000),
    teacherEmail: T, teacherKey: T, fromEmail: T,
    senderName: '王老師（測試班）', signature: '測試班 王老師', className: '測試班',
    updatedAt: FieldValue.serverTimestamp(),
  }, over || {});
}

/** 虛構班級：名單、座號對應、03 號的部落格。 */
async function seedClass(notify) {
  const b = db.batch();
  b.set(db.doc('config/notify'), notifyDoc(notify));
  const allow = [[T, 'teacher', 'aaaaaaaaaaa1'], [PEOPLE.mom3, 'parent', 'aaaaaaaaaaa2'], [PEOPLE.dad3, 'parent', 'aaaaaaaaaaa3'],
    [PEOPLE.staff3, 'staff', 'aaaaaaaaaaa4'], [PEOPLE.paused3, 'parent', 'aaaaaaaaaaa5'], [PEOPLE.mom4, 'parent', 'aaaaaaaaaaa6']];
  for (const [k, kind, alias] of allow) b.set(db.doc(`allowlist/${k}`), { kind, alias, updatedAt: FieldValue.serverTimestamp() });
  b.set(db.doc(`private_allowlist/${T}`), { updatedAt: FieldValue.serverTimestamp() });
  const map = [[PEOPLE.mom3, ['03'], 'parent', true], [PEOPLE.dad3, ['03', '07'], 'parent', true],
    [PEOPLE.staff3, ['03'], 'staff', true], [PEOPLE.paused3, ['03'], 'parent', false],
    [PEOPLE.ghost3, ['03'], 'parent', true], [PEOPLE.mom4, ['04'], 'parent', true]];
  for (const [k, seats, kind, active] of map) {
    b.set(db.doc(`parent_child_map/${k}`), { seats, kind, active, label: `座號 ${seats[0]} ${kind === 'staff' ? '同仁' : '家長'}`,
      updatedAt: FieldValue.serverTimestamp() });
  }
  b.set(db.doc('student_blogs/03'), { seat: '03', displayName: '小甲', avatar: null, updatedAt: FieldValue.serverTimestamp() });
  b.set(db.doc('student_blogs/04'), { seat: '04', displayName: '小乙', avatar: null, updatedAt: FieldValue.serverTimestamp() });
  await b.commit();
}

let n = 0;
function postId() {
  n += 1;
  return `2026-10-01-${String(n).padStart(4, '0')}${Math.random().toString(36).slice(2, 6).padEnd(4, 'x')}`.slice(0, 19);
}

function entryDoc(author, createdMs, over) {
  return Object.assign({
    title: author === 'teacher' ? '今天的課堂' : '週末去爬山', body: '這是正文，不可以出現在任何信裡。',
    date: '2026-10-01', author, authorAlias: author === 'teacher' ? 'aaaaaaaaaaa1' : 'aaaaaaaaaaa2', photos: [], visible: true,
    createdAt: Timestamp.fromMillis(createdMs),
  }, over || {});
}

async function waitFor(fn, ms, what) {
  const until = Date.now() + (ms || 20000);
  let last;
  while (Date.now() < until) {
    last = await fn();
    if (last) return last;
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error('等太久：' + (what || ''));
}

module.exports = { db, Timestamp, FieldValue, PROJECT, CFG, PEOPLE, T, mail, clearAll, seedClass, notifyDoc, postId, entryDoc, waitFor,
  FUNCTIONS };
