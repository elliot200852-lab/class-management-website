// v1.1 通知信模組的純函式（functions/lib/pure.js、functions/lib/config.js）：不需要任何 npm 套件，check.py 三個平台都跑。
// Firestore 觸發、佇列延遲與取消、逐人台帳的模擬器測試在 tests/functions/（python3 scripts/test_functions.py）。
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..', '..');
const P = require(path.join(ROOT, 'functions', 'lib', 'pure.js'));
const config = require(path.join(ROOT, 'functions', 'lib', 'config.js'));
const VECTORS = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests', 'fixtures', 'emailkey_vectors.json'), 'utf8'));
const AT = '@';
const NOW = Date.parse('2026-10-01T12:00:00Z');
const MIN = 60 * 1000;

function settings(over) {
  return P.normalizeSettings(Object.assign({
    phase: 'live', notifyFloor: new Date(NOW - 24 * 60 * MIN), teacherEmail: 'teacher' + AT + 'example.com',
    teacherKey: 'teacher' + AT + 'example.com', fromEmail: 'teacher' + AT + 'example.com',
    senderName: '王老師（測試班）', signature: '測試班 王老師', className: '測試班',
  }, over || {}));
}

test('emailKey：與 Python、前端、規則同一套共用向量', () => {
  for (const v of VECTORS.valid) assert.equal(P.emailKey(v.in[0] + AT + v.in[1]), v.out[0] + AT + v.out[1], v.why);
  for (const v of VECTORS.invalid) assert.throws(() => P.emailKey(v.in[0] + v.join + v.in[1]), undefined, v.why);
});

test('設定：缺欄位、型別不對一律往「不寄」倒', () => {
  assert.equal(P.normalizeSettings(null).phase, 'off');
  assert.equal(P.normalizeSettings({ phase: 'LIVE' }).phase, 'off');
  const noFloor = P.normalizeSettings({ phase: 'live', teacherEmail: 't' + AT + 'example.com', fromEmail: 't' + AT + 'example.com' });
  assert.equal(noFloor.phase, 'off');
  assert.ok(noFloor.problems.some((p) => p.includes('notifyFloor')));
  const s = settings();
  assert.equal(s.phase, 'live');
  assert.equal(s.teacherMail && s.parentMail && s.digest, true);
  assert.equal(settings({ parentMail: false }).parentMail, false);
  assert.equal(settings({ senderName: '王老師\r\nBcc: x' + AT + 'example.com' }).senderName.includes('\n'), false, '標頭注入');
});

test('三道閘：時間讀不懂不寄、早於起始線不寄、觸發時已經是 2 小時以前的內容不寄', () => {
  const s = settings();
  assert.deepEqual(P.gateContent(s, null, NOW), { ok: false, reason: 'no-createdAt' });
  assert.deepEqual(P.gateContent(s, NOW - 25 * 60 * MIN, NOW), { ok: false, reason: 'before-floor' });
  assert.deepEqual(P.gateContent(settings({ notifyFloor: new Date(NOW - 48 * 60 * MIN) }), NOW - 3 * 60 * MIN, NOW),
    { ok: false, reason: 'stale-event' });
  assert.deepEqual(P.gateContent(s, NOW - MIN, NOW), { ok: true });
});

test('給家長的模式：入列時 live、現在 live、家長信開著，三個都成立才真的寄', () => {
  const live = settings();
  assert.equal(P.parentModeFor({ phaseAtEnqueue: 'live' }, live), 'live');
  assert.equal(P.parentModeFor({ phaseAtEnqueue: 'dryrun' }, live), 'dryrun', 'dryrun 期間排的，切 live 也不補寄');
  assert.equal(P.parentModeFor({ phaseAtEnqueue: 'live' }, settings({ phase: 'dryrun' })), 'dryrun', '窗內切回 dryrun＝煞車');
  assert.equal(P.parentModeFor({ phaseAtEnqueue: 'live' }, settings({ parentMail: false })), 'dryrun');
});

test('收件人：只收這個座號、kind=parent、active、還在班網名單上的', () => {
  const k = (n) => n + AT + 'example.com';
  const docs = [
    { id: k('mom'), data: { kind: 'parent', active: true, seats: ['03'] } },
    { id: k('dad'), data: { kind: 'parent', active: true, seats: ['03', '07'] } },
    { id: k('staff'), data: { kind: 'staff', active: true, seats: ['03'] } },
    { id: k('paused'), data: { kind: 'parent', active: false, seats: ['03'] } },
    { id: k('gone'), data: { kind: 'parent', active: true, seats: ['03'] } },
    { id: k('other'), data: { kind: 'parent', active: true, seats: ['04'] } },
  ];
  const allow = new Set([k('mom'), k('dad'), k('staff'), k('paused'), k('other')]);
  assert.deepEqual(P.recipientsFrom(docs, '03', allow), [k('dad'), k('mom')]);
});

test('信的內容：只有座號、標題、連結；不夾正文、不寫姓名；一位一封', () => {
  const s = settings();
  const site = 'https://my-class-2026.firebaseapp.com';
  const c = P.teacherCommentMail(s, site, { parent: 'posts', slug: '2026-10-01-walk', title: '秋天的散步', role: 'parent' });
  assert.match(c.subject, /紀事〈秋天的散步〉/);
  assert.match(c.text, /post\.html\?s=2026-10-01-walk/);
  const pc = P.teacherCommentMail(s, site, { parent: 'private_posts', slug: '2026-10-01-talk', title: '私密標題', role: 'parent' });
  assert.equal(pc.subject.includes('私密標題') || pc.text.includes('私密標題'), false, '私密紀事的標題不進信');
  const a = P.teacherCommentMail(s, site, { parent: 'albums', slug: '2026-10-01-trip', title: '遠足', role: 'staff' });
  assert.match(a.text, /album\.html\?a=2026-10-01-trip/);
  assert.match(a.text, /^同仁/);
  const e = P.teacherEntryMail(s, site, { seat: '03', postId: '2026-10-01-abcdefgh', title: '週末', photoCount: 2 });
  assert.match(e.text, /my-child\.html#\/entry\/03\/2026-10-01-abcdefgh/);
  const pm = P.parentMail(s, site, { kind: 'post', seat: '03', postId: '2026-10-01-abcdefgh', title: '今天的課堂' });
  assert.match(pm.subject, /座號 03/);
  assert.match(pm.text, /測試班 王老師$/, '署名從 config/notify 來');
  const env = P.envelope(s, 'mom' + AT + 'example.com');
  assert.equal(env.to, 'mom' + AT + 'example.com', '一封只寄一位');
  assert.deepEqual(env.from, { name: '王老師（測試班）', address: 'teacher' + AT + 'example.com' });
  assert.equal(env.replyTo, undefined);
  const env2 = P.envelope(settings({ fromEmail: 'class.mail' + AT + 'example.com' }), 'x' + AT + 'example.com');
  assert.equal(env2.replyTo, 'teacher' + AT + 'example.com', '寄件信箱不是導師時，回信回到導師');
});

test('錯誤訊息落地前遮掉信箱', () => {
  const t = P.maskEmails('550 mailbox unavailable <someone.parent' + AT + 'example.com> and x' + AT + 'example.org');
  assert.equal(t.includes('someone.parent' + AT), false);
  assert.match(t, /s\*\*\*@example\.com/);
});

test('名單包含關係：與 access_sync.py 的判斷一致', () => {
  const T = 'teacher' + AT + 'example.com';
  const P1 = 'p1' + AT + 'example.com';
  const ok = P.inclusionProblems({ [T]: { kind: 'teacher', alias: 'aaaaaaaaaaaa' }, [P1]: { kind: 'parent', alias: 'bbbbbbbbbbbb' } },
    { [T]: {} }, { [P1]: { seats: ['01'] } }, T);
  assert.deepEqual(ok, []);
  const bad = P.inclusionProblems({ [P1]: { kind: 'teacher', alias: 'cccccccccccc' } }, { [P1]: {}, x: {} }, { y: {} }, T);
  assert.ok(bad.some((p) => p.includes('導師不在班網名單')));
  assert.ok(bad.some((p) => p.includes('私密讀者不在班網名單')));
  assert.ok(bad.some((p) => p.includes('座號對應的帳號不在班網名單')));
  assert.ok(bad.some((p) => p.includes('不是導師的帳號被標成導師')));
  assert.equal(bad.join('').includes('p1' + AT), false, '信箱要遮');
});

test('備份心跳：門檻跟 status.py 一樣（7／14 天），一週備份一次的班不誤報', () => {
  const day = 24 * 60 * MIN;
  const at = (d) => new Date(NOW - d * day);
  let r = P.backupReport({ weekly: { lastRunAt: at(6), ok: true }, nightly: { lastRunAt: at(6.5), ok: true } }, NOW, 7, 14);
  assert.deepEqual(r.problems, [], '六天前備份過：不叫');
  r = P.backupReport({ weekly: { lastRunAt: at(8), ok: true }, nightly: { lastRunAt: at(1), ok: false } }, NOW, 7, 14);
  assert.equal(r.problems.length, 2);
  assert.ok(r.problems[0].includes('8 天'));
  assert.ok(r.problems[1].includes('沒有成功'));
  r = P.backupReport({ weekly: { lastRunAt: at(15), ok: true } }, NOW, 7, 14);
  assert.ok(r.problems[0].includes('超過 14 天'));
  assert.ok(r.problems[1].includes('還沒有成功過'));
});

test('通知線健康：排程停了、失敗、卡住才叫；off 時不看排程', () => {
  const s = settings();
  assert.deepEqual(P.notifyProblems({ settings: s, status: { lastRunAt: new Date(NOW - 5 * MIN) }, nowMs: NOW, failed: 0, stuck: 0 }), []);
  const p = P.notifyProblems({ settings: s, status: { lastRunAt: new Date(NOW - 3 * 60 * MIN), lastError: 'boom x' + AT + 'example.com' },
    nowMs: NOW, failed: 2, stuck: 1 });
  assert.equal(p.length, 4);
  assert.equal(p.join('').includes('x' + AT + 'example.com'), false);
  assert.deepEqual(P.notifyProblems({ settings: settings({ phase: 'off' }), status: null, nowMs: NOW, failed: 0, stuck: 0 }), []);
});

test('每日摘要：有新東西或要處理的事才寄；內容不含留言正文', () => {
  const empty = { comments: [], entries: [], threads: [], problems: [], backupLines: [], notifyLine: '' };
  assert.equal(P.digestWorthSending(empty), false);
  const data = Object.assign({}, empty, {
    comments: [{ parent: 'posts', slug: '2026-10-01-walk', title: '散步', counts: { parent: 2, staff: 1 } }],
    entries: [{ seat: '05', postId: '2026-10-01-abcdefgh', title: '週末' }],
    problems: ['名單：導師不在私密名單（private_allowlist）'],
    backupLines: ['網站資料庫備份：3 天前，正常'],
  });
  assert.equal(P.digestWorthSending(data), true);
  const m = P.digestMail(settings(), { siteUrl: 'https://my-class-2026.firebaseapp.com', timeZone: 'Asia/Taipei' }, NOW, data);
  assert.match(m.subject, /留言 3、部落格 1、對話 0｜要處理 1 項/);
  assert.match(m.text, /家長 2、同仁 1/);
  assert.match(m.text, /20:00/, '用設定的時區（台北）：UTC 12:00＝台北 20:00');
});

test('部署設定檔的檢查（config.js）', () => {
  const good = { format: 1, projectId: 'my-class-2026', region: 'asia-east1', siteUrl: 'https://my-class-2026.firebaseapp.com',
    timeZone: 'Asia/Taipei', digestHour: 7, backupRemindDays: 7, backupUrgentDays: 14 };
  assert.deepEqual(config.validate(good), []);
  assert.deepEqual(config.validate(Object.assign({}, good, { region: 'nowhere', digestHour: 25 })), ['region', 'digestHour']);
  assert.ok(config.validate(null).length > 0);
  // 產生檔的樣板跟 config.js 讀的欄位要一致（樣板在 templates/，由 build_config.py 渲染）
  const tmpl = fs.readFileSync(path.join(ROOT, 'templates', 'functions-config.json.tmpl'), 'utf8');
  for (const k of Object.keys(good)) assert.ok(tmpl.includes('"' + k + '"'), k);
  assert.equal(tmpl.includes('EMAIL'), false, '樣板不放任何信箱');
});
