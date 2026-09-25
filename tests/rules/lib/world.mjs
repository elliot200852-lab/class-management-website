// 測試世界：角色（登入身分）、種子資料、模擬器連線。
//
// 所有信箱都是 example.com（導師那一份由 scripts/test_rules.py 給；gmail 寫法只在執行時從兩段接起來）。
// 名單文件的 doc id（email 鍵）這裡直接寫明，不在測試裡另寫一份正規化函式：
// email 鍵的正規化只有規則與 scripts/lib/emailkey.py 兩個實作在比，測試只負責拿向量去撞。
import { initializeTestEnvironment } from '@firebase/rules-unit-testing';
import { Timestamp, doc, setDoc } from 'firebase/firestore';

export const AT = '@';
export const mail = (local, domain = 'example.com') => local + AT + domain;

// ── 內容的 id（格式照 DATA-MODEL §0.4）───────────────────────────────
export const SLUG = {
  post: '2026-09-01-open',
  post2: '2026-09-02-open',
  postHidden: '2026-09-03-closed',
  postMissing: '2026-09-09-missing',
  album: '2026-09-01-trip',
  albumHidden: '2026-09-05-closed',
  albumMissing: '2026-09-09-missing',
  priv: '2026-09-01-note',
  priv2: '2026-09-02-note',
  privHidden: '2026-09-04-draft',
  privMissing: '2026-09-09-missing',
};
export const PAGE = { home: 'home', about: 'about', hidden: 'old-notice', missing: 'no-such-page' };
export const ENTRY = {
  e01: '2026-09-01-aaaa1111',
  e01Hidden: '2026-09-02-bbbb2222',
  e02: '2026-09-01-cccc3333',
  missing: '2026-09-09-dddd4444',
};
export const PID = 'a1b2c3d4e5f60718';   // 腳本寫的照片 pid（16 碼十六進位）
export const CATEGORY = '班級生活';

// ── 角色 ────────────────────────────────────────────────────────────
// 每張權限表的每一格都對這 14 個角色各跑一次（允許與拒絕兩面）。
export const ROLES = [
  'anon', 'anonymous', 'outsider', 'unverified', 'removed', 'reader', 'inactive',
  'parent', 'staff', 'private', 'emailLink', 'teacher', 'teacherUnverified', 'teacherLink',
];

const LABELS = {
  anon: '未登入',
  anonymous: '匿名登入（沒有 email）',
  outsider: '非名單登入者',
  unverified: '在名單但 email 未驗證',
  removed: '被移出名單的家長（座號對應還在）',
  reader: '班網讀者',
  inactive: '座號暫停的家長（active=false）',
  parent: '座號家長（01）',
  staff: '同仁逐座號閱讀（01、03）',
  private: '私密讀者',
  emailLink: 'email 連結登入的名單者（對應座號 01）',
  teacher: '導師',
  teacherUnverified: 'email 未驗證的導師 email',
  teacherLink: 'email 連結登入的導師 email',
};

// 允許集合的簡寫（DATA-MODEL §0.7：座號家長、同仁、私密讀者一定也是讀者）
export const R = ['reader', 'inactive', 'parent', 'staff', 'private', 'emailLink', 'teacherLink'];   // 班網讀者
export const RT = [...R, 'teacher'];                                                                   // 讀者＋導師
export const P = ['private', 'teacherLink'];                                                           // 私密讀者（非導師）
export const PT = [...P, 'teacher'];
export const WRITERS = ['reader', 'inactive', 'parent', 'staff', 'private', 'emailLink'];              // 能以自己身分留言／簽回條的讀者
export const T = ['teacher'];

function tokenFor(spec) {
  return {
    email: spec.email,
    email_verified: spec.verified !== false,
    firebase: { sign_in_provider: spec.provider || 'google.com', identities: {} },
  };
}

export function identities(teacher) {
  // teacher：{ email（登入時的寫法）, key（email 鍵） }
  return {
    anon: null,
    anonymous: { token: { firebase: { sign_in_provider: 'anonymous', identities: {} } } },
    outsider: { email: mail('visitor.x'), key: mail('visitor.x') },
    unverified: { email: mail('parent.unverified'), key: mail('parent.unverified'), verified: false,
      allow: { kind: 'parent', alias: 'unverifalias' } },
    removed: { email: mail('parent.removed'), key: mail('parent.removed'),
      map: { seats: ['01'], kind: 'parent', active: true, relation: '父', label: '座號 01 家長' } },
    reader: { email: mail('reader.plain'), key: mail('reader.plain'),
      allow: { kind: 'parent', alias: 'readeralias1' } },
    inactive: { email: mail('parent.paused'), key: mail('parent.paused'),
      allow: { kind: 'parent', alias: 'pausedalias1' },
      map: { seats: ['01'], kind: 'parent', active: false, relation: '祖母', label: '座號 01 家長' } },
    // 登入寫法刻意大小寫混合：規則要先轉小寫才對得上名單
    parent: { email: 'Parent.One' + AT + 'Example.com', key: mail('parent.one'),
      allow: { kind: 'parent', alias: 'parentalias1' },
      map: { seats: ['01'], kind: 'parent', active: true, relation: '母', label: '座號 01 家長' } },
    staff: { email: mail('staff.member'), key: mail('staff.member'),
      allow: { kind: 'staff', alias: 'staffalias01' },
      map: { seats: ['01', '03'], kind: 'staff', active: true, label: '座號 01 同仁' } },
    private: { email: mail('private.reader'), key: mail('private.reader'),
      allow: { kind: 'parent', alias: 'privatealias' }, private: true },
    emailLink: { email: mail('link.parent'), key: mail('link.parent'), provider: 'password',
      allow: { kind: 'parent', alias: 'linkalias001' },
      map: { seats: ['01'], kind: 'parent', active: true, relation: '父', label: '座號 01 家長' } },
    teacher: { email: teacher.email, key: teacher.key,
      allow: { kind: 'teacher', alias: 'teacheralias' }, private: true },
    // 這兩個跟導師同一個信箱（同一份名單文件）；寫入時用導師的 kind 與代號去試，才是最強的冒用嘗試
    teacherUnverified: { email: teacher.email, key: teacher.key, verified: false, as: 'teacher' },
    teacherLink: { email: teacher.email, key: teacher.key, provider: 'password', as: 'teacher' },
  };
}

const ts = (iso) => Timestamp.fromDate(new Date(iso));
const THUMB = { data: 'dGh1bWI=', w: 320, h: 240, order: 0 };
const IMAGE = { data: 'aW1hZ2U=', w: 1280, h: 960 };

export class World {
  constructor({ projectId, rules, teacher, verbose }) {
    this.projectId = projectId;
    this.rules = rules;
    this.teacher = teacher;
    this.verbose = verbose;
    this.ids = identities(teacher);
    this.roles = ROLES;
    this.env = null;
    this._dbs = new Map();
  }

  async start(rules = this.rules) {
    if (this.env) await this.env.cleanup();
    this._dbs.clear();
    this.env = await initializeTestEnvironment({ projectId: this.projectId, firestore: { rules } });
  }

  async stop() {
    if (this.env) await this.env.cleanup();
    this.env = null;
    this._dbs.clear();
  }

  label(role) {
    return LABELS[role] || role;
  }

  // 自訂身分（emailKey 向量、gmail 導師那一段用）
  dbFor(name, spec) {
    const k = `custom:${name}`;
    if (!this._dbs.has(k)) {
      this._dbs.set(k, this.env.authenticatedContext(`u-${name}`, spec.token || tokenFor(spec)).firestore());
    }
    return this._dbs.get(k);
  }

  db(role) {
    if (!this._dbs.has(role)) {
      const spec = this.ids[role];
      const ctx = spec === null ? this.env.unauthenticatedContext()
        : this.env.authenticatedContext(`u-${role}`, spec.token || tokenFor(spec));
      this._dbs.set(role, ctx.firestore());
    }
    return this._dbs.get(role);
  }

  key(role) {
    return this.ids[role].key;
  }

  // 「自己的 email 鍵」：未登入／匿名沒有，就拿班網讀者的（拿別人的一樣要被拒）
  keyOf(role) {
    const s = this.ids[role];
    return s && s.key ? s.key : this.key('reader');
  }

  // 「別人的 email 鍵」
  otherKey(role) {
    return this.keyOf(role) === this.key('reader') ? this.key('staff') : this.key('reader');
  }

  _allowOf(role) {
    const s = this.ids[role];
    if (!s) return null;
    if (s.as) return this.ids[s.as].allow;
    return s.allow || null;
  }

  // 這個角色寫東西時會填的作者代號與 kind（沒有名單文件的人用一個假的）
  alias(role) {
    const a = this._allowOf(role);
    return a ? a.alias : 'nobodyalias1';
  }

  kind(role) {
    const a = this._allowOf(role);
    return a ? a.kind : 'parent';
  }

  async admin(fn) {
    await this.env.withSecurityRulesDisabled(async (ctx) => fn(ctx.firestore()));
  }

  async reset() {
    await this.env.clearFirestore();
    await this.admin((db) => seed(db, this.ids));
  }
}

// ── 種子資料（繞過規則寫入，等於管理腳本）──────────────────────────────
export async function seed(db, ids) {
  const put = (path, data) => setDoc(doc(db, path), data);
  const now = ts('2026-09-01T08:00:00Z');
  const jobs = [];

  for (const spec of Object.values(ids)) {
    if (!spec || !spec.key) continue;
    if (spec.allow) jobs.push(put(`allowlist/${spec.key}`, { ...spec.allow, updatedAt: now }));
    if (spec.private) jobs.push(put(`private_allowlist/${spec.key}`, { updatedAt: now }));
    if (spec.map) jobs.push(put(`parent_child_map/${spec.key}`, { ...spec.map, updatedAt: now }));
  }

  jobs.push(put('config/site', { teacherDisplayName: '王老師', schoolName: '', studentsCount: 25,
    calendarIcsUrl: '', updatedAt: now }));
  jobs.push(put('config/notify', { enabled: false, phase: 'dryrun', updatedAt: now }));
  jobs.push(put('roster/students', { students: [{ seat: '01', name: '示範學生一', displayName: '小一' }], updatedAt: now }));
  jobs.push(put('roster/links', { recordsKitUrl: '', classDocsIndexUrl: '', updatedAt: now }));
  jobs.push(put('ops/backup_status', { nightly: { lastRunAt: now, ok: true }, weekly: { lastRunAt: now, ok: true } }));

  const postBase = (title, date, visible) => ({
    title, date, category: CATEGORY, excerpt: '摘要', coverPid: PID, coverThumb: null,
    photoCount: 1, visible, publishedAt: now, updatedAt: now,
  });
  const comment = (who, status, alias, extra = {}) => ({
    authorName: who, body: '留言內容', role: 'parent', authorAlias: alias, status,
    createdAt: ts('2026-09-01T09:00:00Z'), ...extra,
  });

  // 班級紀事
  for (const [slug, visible, date] of [[SLUG.post, true, '2026-09-01'], [SLUG.post2, true, '2026-09-02'],
    [SLUG.postHidden, false, '2026-09-03']]) {
    jobs.push(put(`posts/${slug}`, postBase(`紀事 ${slug}`, date, visible)));
    jobs.push(put(`posts/${slug}/content/main`, { blocks: [{ t: 'p', text: '正文' }], updatedAt: now }));
    jobs.push(put(`posts/${slug}/thumbs/${PID}`, THUMB));
    jobs.push(put(`posts/${slug}/images/${PID}`, IMAGE));
    jobs.push(put(`posts/${slug}/comments/c-visible`, comment('家長 A', 'visible', 'readeralias1')));
    jobs.push(put(`posts/${slug}/comments/c-hidden`, comment('家長 B', 'hidden', 'parentalias1')));
  }
  jobs.push(put(`posts/${SLUG.post}/reads/${ids.reader.key}`, { kind: 'parent', readAt: now }));

  // 相簿
  for (const [slug, visible] of [[SLUG.album, true], [SLUG.albumHidden, false]]) {
    jobs.push(put(`albums/${slug}`, { title: `相簿 ${slug}`, date: '2026-09-01', order: 1, coverPid: PID,
      coverThumb: null, photoCount: 1, videos: [], visible, updatedAt: now }));
    jobs.push(put(`albums/${slug}/thumbs/${PID}`, THUMB));
    jobs.push(put(`albums/${slug}/images/${PID}`, IMAGE));
    jobs.push(put(`albums/${slug}/comments/c-visible`, comment('家長 A', 'visible', 'readeralias1')));
    jobs.push(put(`albums/${slug}/comments/c-hidden`, comment('家長 B', 'hidden', 'parentalias1')));
  }

  // 私密紀事
  for (const [slug, visible, date] of [[SLUG.priv, true, '2026-09-01'], [SLUG.priv2, true, '2026-09-02'],
    [SLUG.privHidden, false, '2026-09-04']]) {
    jobs.push(put(`private_posts/${slug}`, { title: `私密 ${slug}`, date, excerpt: '摘要', blocks: [],
      coverPid: null, coverThumb: null, photoCount: 1, visible, publishedAt: now, updatedAt: now }));
    jobs.push(put(`private_posts/${slug}/thumbs/${PID}`, THUMB));
    jobs.push(put(`private_posts/${slug}/images/${PID}`, IMAGE));
    jobs.push(put(`private_posts/${slug}/comments/c-visible`, comment('家長 C', 'visible', 'privatealias')));
    jobs.push(put(`private_posts/${slug}/comments/c-hidden`, comment('家長 C', 'hidden', 'privatealias')));
  }
  jobs.push(put(`private_posts/${SLUG.priv}/reads/${ids.private.key}`, { kind: 'parent', readAt: now }));

  // 單頁
  for (const [id, kind, visible] of [[PAGE.home, 'home', true], [PAGE.about, 'about', true],
    [PAGE.hidden, 'standalone', false]]) {
    jobs.push(put(`pages/${id}`, { title: `單頁 ${id}`, kind, blocks: [], order: 1, visible, updatedAt: now }));
    jobs.push(put(`pages/${id}/thumbs/${PID}`, THUMB));
    jobs.push(put(`pages/${id}/images/${PID}`, IMAGE));
  }

  // 部落格
  for (const seat of ['01', '02', '03']) {
    jobs.push(put(`student_blogs/${seat}`, { seat, displayName: `孩子${seat}`, avatar: null, updatedAt: now }));
  }
  const entry = (seat, id, visible, author, alias) => {
    const base = `student_blogs/${seat}/entries/${id}`;
    jobs.push(put(base, { title: '文章', body: '內文', date: id.slice(0, 10), author, authorAlias: alias,
      photos: [{ pid: '0', w: 1280, h: 960 }], visible, createdAt: ts(`${id.slice(0, 10)}T10:00:00Z`) }));
    jobs.push(put(`${base}/thumbs/0`, THUMB));
    jobs.push(put(`${base}/images/0`, IMAGE));
    const bc = (cid, role, a, status) => put(`${base}/blog_comments/${cid}`,
      { body: '對話', role, authorAlias: a, status, createdAt: ts(`${id.slice(0, 10)}T11:00:00Z`) });
    jobs.push(bc('bc-teacher', 'teacher', 'teacheralias', 'visible'));
    jobs.push(bc('bc-parent', 'parent', 'parentalias1', 'visible'));
    jobs.push(bc('bc-hidden', 'parent', 'parentalias1', 'hidden'));
  };
  entry('01', ENTRY.e01, true, 'parent', 'parentalias1');
  entry('01', ENTRY.e01Hidden, false, 'teacher', 'teacheralias');
  entry('02', ENTRY.e02, true, 'teacher', 'teacheralias');

  // v1.1
  jobs.push(put('pages/poems-2026-09', { title: '每日一詩（2026 年 9 月）', kind: 'poem', order: 0, visible: true, updatedAt: now,
    data: { month: '2026-09', items: [{ date: '2026-09-01', title: '示範', author: '示範文字', text: '一行\n兩行' }] } }));
  jobs.push(put('seating/2026-09-01', { title: '九月座位', date: '2026-09-01', rows: [{ seats: ['01', '', '03'] }],
    note: '', updatedAt: now }));
  jobs.push(put('parent_photo_display/01', { relations: ['母'], note: '', photoPids: [PID], updatedAt: now }));
  jobs.push(put(`parent_photo_display/01/thumbs/${PID}`, THUMB));
  jobs.push(put('personal_photos/01', { photoPids: [PID], updatedAt: now }));
  jobs.push(put(`personal_photos/01/images/${PID}`, IMAGE));
  jobs.push(put('blog_notify_queue/01__q1', { state: 'pending', sendAfter: ts('2026-09-01T09:30:00Z') }));
  jobs.push(put('blog_notify_queue/01__q1/sent/h1', { sentAt: now }));

  await Promise.all(jobs);
}
