// 查詢形狀：templates/queries.json 登記的每一個查詢，用它 who 裡的每一種角色在模擬器實際跑一次（要通過），
// 再用不該有的角色、或拿掉成員條件跑一次（要被拒）——「規則不是過濾器」要真的驗（DATA-MODEL §0.6、§4）。
// 模擬器不檢查複合索引（那一項由 tests/test_build_indexes.py 管）。
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  collection, collectionGroup, endBefore, getCountFromServer, getDocs, limit, limitToLast, onSnapshot, orderBy,
  query, startAfter, Timestamp, where,
} from 'firebase/firestore';
import { assert } from '../lib/harness.mjs';
import { CATEGORY, ENTRY, PAGE, SLUG } from '../lib/world.mjs';

// 查詢登記表的角色 → 測試裡的登入身分
const IDENTITIES = {
  teacher: ['teacher'],
  reader: ['reader'],
  privateReader: ['private'],
  seatReader: ['parent', 'staff'],
  seatParent: ['parent'],
};

const E01 = `student_blogs/01/entries/${ENTRY.e01}`;
const E01H = `student_blogs/01/entries/${ENTRY.e01Hidden}`;
const E02 = `student_blogs/02/entries/${ENTRY.e02}`;

// 路徑參數的實際值（依角色）：非導師只給他有門票的主人；導師另外加下架的、別人座號的
const PARAMS = {
  thread: {
    reader: [`posts/${SLUG.post}`, `albums/${SLUG.album}`],
    privateReader: [`private_posts/${SLUG.priv}`],
    teacher: [`posts/${SLUG.post}`, `albums/${SLUG.album}`, `private_posts/${SLUG.priv}`, `posts/${SLUG.postHidden}`],
  },
  owner: {
    reader: [`posts/${SLUG.post}`, `albums/${SLUG.album}`, `pages/${PAGE.home}`],
    privateReader: [`private_posts/${SLUG.priv}`],
    seatReader: [E01],
    teacher: [`posts/${SLUG.post}`, `albums/${SLUG.albumHidden}`, `private_posts/${SLUG.privHidden}`, `pages/${PAGE.hidden}`, E01H, E02],
  },
  entry: { seatParent: [E01], teacher: [E01, E01H, E02] },
  seat: { seatReader: ['01'], teacher: ['01', '02'] },
};
// 被拒那一面用的「這個角色沒有門票」的主人
const OTHER = {
  thread: { reader: `private_posts/${SLUG.priv}`, privateReader: `private_posts/${SLUG.privHidden}` },
  owner: { reader: `private_posts/${SLUG.priv}`, privateReader: E02, seatReader: E02 },
  entry: { seatParent: E02 },
  seat: { seatReader: '02' },
};

const CURSOR = {
  date: '2026-09-02',
  createdAt: Timestamp.fromDate(new Date('2026-09-01T12:00:00Z')),
  order: 0,
  sendAfter: Timestamp.fromDate(new Date('2026-09-01T12:00:00Z')),
};

function paramValue(v) {
  if (typeof v !== 'string' || !v.startsWith(':')) return v;
  const name = v.slice(1);
  if (name === 'category') return CATEGORY;
  if (name === 'kind') return 'about';
  if (name === 'now') return Timestamp.now();
  throw new Error(`queries.json 用了測試不認得的參數 :${name}（在 suites/queries.mjs 的 paramValue 補一個值）`);
}

function placeholderOf(q) {
  const m = (q.path || '').match(/\{(\w+)\}/);
  return m ? m[1] : null;
}

function collectionId(q) {
  if (q.group) return q.group;
  const parts = q.path.split('/');
  return parts[parts.length - 1];
}

function build(db, q, path, { dropMember = null } = {}) {
  const ref = q.group ? collectionGroup(db, q.group) : collection(db, path);
  const cons = [];
  for (const w of q.where || []) {
    if (dropMember && w[0] === dropMember[0] && w[1] === dropMember[1] && w[2] === dropMember[2]) continue;
    cons.push(where(w[0], w[1], paramValue(w[2])));
  }
  for (const [field, dir] of q.orderBy || []) cons.push(orderBy(field, dir));
  if (q.cursor) {
    const field = q.orderBy[0][0];
    if (!(field in CURSOR)) throw new Error(`游標欄位 ${field} 沒有測試值（在 CURSOR 補一個）`);
    cons.push(q.cursor === 'startAfter' ? startAfter(CURSOR[field]) : endBefore(CURSOR[field]));
  }
  if (!q.count) cons.push(q.limitToLast ? limitToLast(q.limit) : limit(q.limit));
  return query(ref, ...cons);
}

const exec = (q, qry) => (q.count ? getCountFromServer(qry) : getDocs(qry));

function listenOnce(qry) {
  return new Promise((resolve, reject) => {
    let done = false;
    const unsub = onSnapshot(qry, (snap) => {
      if (done) return;
      done = true;
      setTimeout(() => unsub(), 0);
      resolve(snap);
    }, (err) => {
      done = true;
      reject(err);
    });
  });
}

function pathsFor(q, role) {
  const ph = placeholderOf(q);
  if (!ph) return [q.path || null];
  let values = (PARAMS[ph] || {})[role];
  // 回條只在紀事與私密紀事底下（相簿沒有回條，DATA-MODEL §2.8）
  if (values && ph === 'thread' && collectionId(q) === 'reads') values = values.filter((v) => !v.startsWith('albums/'));
  if (!values) throw new Error(`查詢 ${q.path} 的 {${ph}} 沒有給角色 ${role} 的測試值`);
  return values.map((v) => q.path.replace(`{${ph}}`, v));
}

export async function run(S, W, { repoRoot }) {
  const reg = JSON.parse(readFileSync(join(repoRoot, 'templates', 'queries.json'), 'utf8'));
  const names = Object.keys(reg.queries).sort();
  const ran = new Set();

  S.section(`查詢形狀：templates/queries.json 的 ${names.length} 個查詢（規則不是過濾器）`);
  await W.reset();

  for (const name of names) {
    const q = reg.queries[name];
    const where_ = q.group ? `群組 ${q.group}` : q.path;

    // ① 允許的那一面：who 裡的每個角色 × 每個路徑參數值
    for (const who of q.who) {
      if (who === 'functions') {
        await S.check(`${name}｜v1.1 Functions（管理身分，不經規則；只驗查詢形狀跑得動）`, async () => {
          await W.admin(async (db) => { await exec(q, build(db, q, q.path)); });
        });
        ran.add(name);
        continue;
      }
      for (const role of IDENTITIES[who]) {
        for (const path of pathsFor(q, who)) {
          const label = `${name}｜${W.label(role)}｜${q.group ? where_ : path}`;
          const ok = await S.expect('allow', label, () => exec(q, build(W.db(role), q, path)));
          if (q.watch) await S.expect('allow', `${label}（即時 onSnapshot）`, () => listenOnce(build(W.db(role), q, path)));
          if (ok) ran.add(name);
        }
      }
    }

    // ② 被拒的那一面
    const member = (reg.collections[collectionId(q)] || {}).memberFilter;
    const nonTeacher = q.who.filter((w) => w !== 'teacher' && w !== 'functions');
    if (member && (q.where || []).some((w) => w[0] === member[0] && w[1] === member[1] && w[2] === member[2])) {
      for (const who of nonTeacher) {
        const role = IDENTITIES[who][0];
        const path = pathsFor(q, who)[0];
        await S.expect('deny', `${name}｜${W.label(role)}｜拿掉 ${member.join(' ')} 條件${path && path !== q.path ? `｜${path}` : ''}`,
          () => exec(q, build(W.db(role), q, path, { dropMember: member })));
      }
    }
    if (nonTeacher.length === 0) {
      // 只給導師（或 Functions）的查詢：換成讀者、座號家長一定被拒
      const path = q.group ? null : (placeholderOf(q) ? pathsFor(q, 'teacher')[0] : q.path);
      for (const role of ['reader', 'parent']) {
        await S.expect('deny', `${name}｜${W.label(role)}（只給導師）｜${q.group ? where_ : path}`,
          () => exec(q, build(W.db(role), q, path)));
      }
    }
    const ph = placeholderOf(q);
    for (const who of ph ? nonTeacher : []) {
      // 沒有門票的主人：座號家長對別人的座號、班網讀者對私密紀事的串……
      const other = (OTHER[ph] || {})[who];
      if (!other) throw new Error(`OTHER.${ph}.${who} 沒有給「沒有門票」的測試值`);
      const role = IDENTITIES[who][0];
      const path = q.path.replace(`{${ph}}`, other);
      await S.expect('deny', `${name}｜${W.label(role)}｜沒有門票的 ${path}`, () => exec(q, build(W.db(role), q, path)));
    }
    if (q.who.includes('seatParent') && !q.who.includes('seatReader')) {
      const path = pathsFor(q, 'seatParent')[0];
      await S.expect('deny', `${name}｜${W.label('staff')}（對話串只給家長）｜${path}`, () => exec(q, build(W.db('staff'), q, path)));
    }
    if (q.who.includes('reader') || q.who.includes('privateReader')) {
      const who = q.who.includes('reader') ? 'reader' : 'privateReader';
      const path = pathsFor(q, who)[0];
      await S.expect('deny', `${name}｜${W.label('outsider')}｜${path}`, () => exec(q, build(W.db('outsider'), q, path)));
    }
  }

  await S.check('每個登記的查詢都至少用一個角色實際跑通過', async () => {
    const missing = names.filter((n) => !ran.has(n));
    assert(missing.length === 0, `沒跑通過的查詢：${missing.join('、')}`);
  });
}
