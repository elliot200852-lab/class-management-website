// 導師身分的各種寫法（DATA-MODEL §1.1、附錄 A 必測清單最後一條）：
// 大小寫、gmail 點號與 googlemail 都認得是導師；email 連結登入、email 未驗證、非 gmail 網域少一個點都不是。
// 第二份規則由 scripts/test_rules.py 用「導師信箱是 gmail」的設定產生（信箱在執行時才從兩段接起來）。
import { readFileSync } from 'node:fs';
import { doc, getDoc } from 'firebase/firestore';
import { AT, World } from '../lib/world.mjs';

async function probe(S, W, label, spec, isTeacher) {
  const db = W.dbFor(label, spec);
  await S.expect(isTeacher ? 'found' : 'deny', `${label}：讀 roster/students`, () => getDoc(doc(db, 'roster', 'students')));
  await S.expect(isTeacher ? 'notfound' : 'deny', `${label}：導師探針 site_access/teacher`,
    () => getDoc(doc(db, 'site_access', 'teacher')));
}

const g = (email, extra = {}) => ({ email, verified: true, provider: 'google.com', ...extra });

export async function run(S, W, { manifest }) {
  const main = manifest.variants.main;
  const [local, domain] = main.teacher;

  S.section('導師身分：example.com 信箱的寫法（主要那份規則）');
  await W.reset();
  await probe(S, W, '設定裡的寫法', g(local + AT + domain), true);
  await probe(S, W, '全部大寫', g((local + AT + domain).toUpperCase()), true);
  await probe(S, W, '前後帶空白', g(`  ${local}${AT}${domain} `), true);
  await probe(S, W, '非 gmail 網域少一個點', g(local.replace(/[.]/g, '') + AT + domain), false);
  await probe(S, W, '同一個信箱但 email 連結登入', g(local + AT + domain, { provider: 'password' }), false);
  await probe(S, W, '同一個信箱但 email 未驗證', g(local + AT + domain, { verified: false }), false);
  await probe(S, W, '同一個 @ 前面、別的網域', g(local + AT + 'example.org'), false);

  const gm = manifest.variants.gmail;
  const [gLocal, gDomain] = gm.teacher;
  const keyLocal = gm.teacherKey.split(AT)[0];
  const W2 = new World({ projectId: manifest.projectId, rules: readFileSync(gm.rulesFile, 'utf8'),
    teacher: { email: gLocal + AT + gDomain, key: gm.teacherKey } });

  S.section('導師身分：gmail 信箱的寫法（第二份規則：導師 email 用 googlemail 大小寫混寫）');
  await W.stop();
  await W2.start();
  try {
    await W2.reset();
    await probe(S, W2, '設定裡的寫法（googlemail、大小寫混合、有點號）', g(gLocal + AT + gDomain), true);
    await probe(S, W2, '去掉點號的 gmail.com', g(keyLocal + AT + 'gmail.com'), true);
    await probe(S, W2, '每個字中間都加點號', g(keyLocal.split('').join('.') + AT + 'gmail.com'), true);
    await probe(S, W2, '全部大寫的 GMAIL.COM', g((keyLocal + AT + 'gmail.com').toUpperCase()), true);
    await probe(S, W2, '同一個信箱但 email 連結登入', g(keyLocal + AT + 'gmail.com', { provider: 'password' }), false);
    await probe(S, W2, '同一個信箱但 email 未驗證', g(keyLocal + AT + 'gmail.com', { verified: false }), false);
    await probe(S, W2, 'gmail 的子網域（點號不拿掉）', g(keyLocal + AT + 'mail.gmail.com'), false);
    await probe(S, W2, '主要那份規則的導師信箱（這份規則裡不是導師）', g(local + AT + domain), false);
  } finally {
    await W2.stop();
    await W.start();
  }
}
