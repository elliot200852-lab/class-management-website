/* pure.js — 通知信模組的純函式（不載入任何 Firebase 套件，tests/js/ 用 Node 內建測試直接跑）。

   這裡只做「判斷」與「組信」：
     · 設定正規化（config/notify → settings）
     · 三道閘：時間戳讀不懂就不寄（fail-closed）、早於起始線（notifyFloor）不寄、
       觸發時已經是很久以前的內容不寄（還原備份時舊內容一次湧進來的保險）
     · 給家長的信用哪一種模式（live／dryrun）
     · 收件人篩選、email 鍵（與 scripts/lib/emailkey.py、site/js/core/emailkey.js 同一套規則，共用測試向量）
     · 信的內容：**只有座號、標題、連結**，不夾正文、不寫姓名（docs/ARCHITECTURE.md §10）
     · 每日摘要的內容與「需要處理」清單（名單包含關係、備份心跳、通知線健康）
   寫 Firestore、真的寄信都在 core.js／mailer.js。 */
'use strict';

const crypto = require('node:crypto');

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const C = Object.freeze({
  DELAY_MS: 30 * MINUTE,          // 導師發文或回覆之後，隔這麼久才寄信給家長；在那之前老師還能修改或撤下
  MAX_EVENT_AGE_MS: 2 * HOUR,     // 觸發時內容已經建立超過這麼久＝還原備份或批次回填，不寄
  SWEEP_LIMIT: 30,                // 每一輪最多處理幾筆佇列（查詢登記表 notifyQueue.due 的上限是 50）
  MAX_ATTEMPTS: 5,                // 同一筆連續寄失敗幾次就放棄（轉 failed，每日摘要會列出來）
  SEND_GAP_MS: 400,               // 逐位寄信之間的間隔
  LEASE_MS: 5 * MINUTE,           // 一筆佇列被某一輪拿去處理時的租約（排程重疊也不會兩輪同時寄）
  SWEEP_STALE_MS: 60 * MINUTE,    // 排程每 10 分鐘一輪；超過 1 小時沒心跳＝停了
  STUCK_MS: 2 * HOUR,             // 該寄的時間過了 2 小時還在排隊＝卡住
  RETENTION_MS: 30 * DAY,         // 佇列與寄信台帳留 30 天就清掉（只剩座號與雜湊，但沒必要一直留）
  DIGEST_WINDOW_MS: DAY,
  CLEAN_LIMIT: 100,
});

const PHASES = ['off', 'dryrun', 'live'];

const RE = Object.freeze({
  seat: /^(0[1-9]|[1-3][0-9]|40)$/,
  slug: /^[0-9]{4}-[0-9]{2}-[0-9]{2}(-[a-z0-9]+)+$/,
  postId: /^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]{8}$/,
  cid: /^[A-Za-z0-9]{1,64}$/,
  email: /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/,
});

// ── email 鍵（docs/DATA-MODEL.md §0.3；共用向量 tests/fixtures/emailkey_vectors.json）────────────
function emailKey(raw) {
  if (typeof raw !== 'string') throw new Error('email 必須是文字');
  const e = raw.trim().toLowerCase();
  if (e.split('@').length !== 2) throw new Error('email 必須剛好有一個 @');
  let [local, domain] = e.split('@');
  if (!local || !domain) throw new Error('email 的 @ 前後都不能是空的');
  if (!RE.email.test(e)) throw new Error('email 含有不允許的字元或格式不對');
  if (domain === 'gmail.com' || domain === 'googlemail.com') {
    local = local.replace(/\./g, '');
    if (!local) throw new Error('gmail 信箱去掉點號後是空的');
    domain = 'gmail.com';
  }
  return local + '@' + domain;
}

function isEmail(raw) {
  try { emailKey(raw); return true; } catch (e) { return false; }
}

/** 遮住信箱：p***@gmail.com（與管理腳本的遮法一致） */
function maskEmail(e) {
  const s = String(e || '');
  const i = s.indexOf('@');
  if (i < 1) return '（沒有）';
  return s.slice(0, 1) + '***' + s.slice(i);
}

/** 錯誤訊息落地（記錄、Firestore、摘要信）之前，把裡面看起來像信箱的字串全部遮掉（SMTP 退信常把收件人原文帶回來）。 */
function maskEmails(text) {
  return String(text == null ? '' : text).replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, (m) => maskEmail(m));
}

/** 寄信台帳的 doc id：email 鍵的 SHA-256 前 32 碼（不存信箱原文）。 */
function ledgerId(key) {
  return crypto.createHash('sha256').update(String(key)).digest('hex').slice(0, 32);
}

/** 即時通知的「只寄一次」鍵（觸發器偶爾會重送同一個事件）。 */
function onceId(kind, path) {
  return crypto.createHash('sha256').update(String(kind) + ':' + String(path)).digest('hex').slice(0, 32);
}

/** 標頭用的一行字：去掉換行與控制字元（擋標頭注入），限制長度。 */
function oneLine(s, max) {
  const t = String(s == null ? '' : s).replace(/[\u0000-\u001f\u007f\u2028\u2029]+/g, ' ').replace(/\s+/g, ' ').trim();
  return t.length > (max || 120) ? t.slice(0, (max || 120) - 1) + '…' : t;
}

/** Firestore Timestamp／Date／ISO 字串／毫秒 → 毫秒；讀不懂回 null。 */
function toMillis(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v.toMillis === 'function') {
    const n = v.toMillis();
    return Number.isFinite(n) ? n : null;
  }
  if (v instanceof Date) {
    const n = v.getTime();
    return Number.isFinite(n) ? n : null;
  }
  if (typeof v === 'string') {
    const n = Date.parse(v);
    return Number.isNaN(n) ? null : n;
  }
  return null;
}

// ── 設定（config/notify，只有 scripts/notify_config.py 寫）────────────────────────────

/** config/notify → settings。欄位缺了或型別不對一律往「不寄」那邊倒。 */
function normalizeSettings(raw) {
  const d = raw || {};
  const problems = [];
  let phase = PHASES.includes(d.phase) ? d.phase : 'off';
  if (raw && d.phase !== undefined && !PHASES.includes(d.phase)) problems.push('phase 不是 off／dryrun／live，當成 off');
  const floorMs = toMillis(d.notifyFloor);
  const teacherEmail = isEmail(d.teacherEmail) ? String(d.teacherEmail).trim() : '';
  const fromEmail = isEmail(d.fromEmail) ? String(d.fromEmail).trim() : '';
  let teacherKey = '';
  if (typeof d.teacherKey === 'string' && isEmail(d.teacherKey)) teacherKey = emailKey(d.teacherKey);
  if (phase !== 'off') {
    if (floorMs === null) problems.push('沒有通知起始線（notifyFloor），當成 off');
    if (!teacherEmail) problems.push('沒有導師收件信箱（teacherEmail），當成 off');
    if (!fromEmail) problems.push('沒有寄件信箱（fromEmail），當成 off');
    if (problems.length) phase = 'off';
  }
  return {
    exists: !!raw,
    phase,
    teacherMail: d.teacherMail !== false,
    parentMail: d.parentMail !== false,
    digest: d.digest !== false,
    floorMs,
    teacherEmail,
    teacherKey,
    fromEmail,
    senderName: oneLine(d.senderName || '', 40) || '班級網站',
    signature: String(d.signature || '').replace(/\r\n?/g, '\n').slice(0, 300).trim(),
    className: oneLine(d.className || '', 40) || '班級網站',
    problems,
  };
}

/** 內容能不能拿來寄信：回 { ok: true } 或 { ok: false, reason }。 */
function gateContent(settings, createdMs, nowMs) {
  if (createdMs === null || createdMs === undefined) return { ok: false, reason: 'no-createdAt' };
  if (settings.floorMs === null || settings.floorMs === undefined) return { ok: false, reason: 'no-floor' };
  if (createdMs < settings.floorMs) return { ok: false, reason: 'before-floor' };
  if (nowMs - createdMs > C.MAX_EVENT_AGE_MS) return { ok: false, reason: 'stale-event' };
  return { ok: true };
}

/** 佇列裡這一筆要真的寄給家長（live），還是只記錄（dryrun）。
    入列當下是 live、現在也是 live、給家長的信也開著，三個都成立才 live——
    dryrun 期間排進來的，事後切 live 也不會補寄；live 期間排進來的，窗內切回 dryrun／off 就不寄。 */
function parentModeFor(item, settings) {
  return item && item.phaseAtEnqueue === 'live' && settings.phase === 'live' && settings.parentMail ? 'live' : 'dryrun';
}

/** parent_child_map 的文件 → 這個座號的家長收件人（email 鍵）。只收 kind=parent、active=true、而且還在班網名單上的。 */
function recipientsFrom(mapDocs, seat, allowKeys) {
  const out = [];
  for (const m of mapDocs || []) {
    const d = m.data || {};
    if (d.kind !== 'parent' || d.active !== true) continue;
    if (!Array.isArray(d.seats) || !d.seats.includes(seat)) continue;
    if (allowKeys && !allowKeys.has(m.id)) continue;
    if (!isEmail(m.id)) continue;
    out.push(m.id);
  }
  return Array.from(new Set(out)).sort();
}

// ── 網址（站內頁面與參數名見 site/js/core/route.js）──────────────────────────────

function urls(siteUrl) {
  const base = String(siteUrl || '').replace(/\/+$/, '');
  const q = (v) => encodeURIComponent(String(v));
  return {
    post: (slug) => `${base}/post.html?s=${q(slug)}`,
    album: (slug) => `${base}/album.html?a=${q(slug)}`,
    private: (slug) => `${base}/private.html?p=${q(slug)}`,
    entry: (seat, postId) => `${base}/my-child.html#/entry/${q(seat)}/${q(postId)}`,
    admin: () => `${base}/admin.html`,
    myChildAdmin: () => `${base}/my-child.html#/admin`,
    teacher: () => `${base}/teacher.html`,
  };
}

const PARENT_LABEL = { posts: '紀事', albums: '相簿', private_posts: '私密紀事' };
const ROLE_LABEL = { parent: '家長', staff: '同仁', teacher: '導師' };

function footer(settings) {
  return settings.signature ? '\n\n' + settings.signature : '';
}

// ── 給導師的即時信 ──────────────────────────────────────────────────────────

/** 紀事／相簿／私密紀事的新留言。私密紀事不寫標題（標題本身就是私密內容），只寫 slug。 */
function teacherCommentMail(settings, siteUrl, { parent, slug, title, role }) {
  const u = urls(siteUrl);
  const kind = PARENT_LABEL[parent] || '內容';
  const where = parent === 'private_posts' ? `${kind}（${slug}）` : `${kind}〈${oneLine(title || slug, 60)}〉`;
  const link = parent === 'albums' ? u.album(slug) : parent === 'private_posts' ? u.private(slug) : u.post(slug);
  const who = ROLE_LABEL[role] || '讀者';
  return {
    subject: oneLine(`〈${settings.className}〉新留言：${where}`, 150),
    text: `${who}在${where}留了一則新留言。\n\n打開那一篇：${link}\n留言後台：${u.admin()}\n\n`
      + '（信裡不附留言內容，請登入網站查看。）',
  };
}

/** 家長在「我的孩子」發了一篇文。 */
function teacherEntryMail(settings, siteUrl, { seat, postId, title, photoCount }) {
  const u = urls(siteUrl);
  const pics = photoCount ? `（附 ${photoCount} 張照片）` : '';
  return {
    subject: oneLine(`〈${settings.className}〉座號 ${seat} 的家長發了一篇部落格〈${oneLine(title, 60)}〉`, 150),
    text: `座號 ${seat} 的家長在「我的孩子」發了一篇新文章${pics}：〈${oneLine(title, 80)}〉\n\n`
      + `打開那一篇：${u.entry(seat, postId)}\n全班總覽：${u.myChildAdmin()}\n\n（信裡不附文章內容，請登入網站查看。）`,
  };
}

/** 家長在部落格文章底下回了一則（導師與家長的對話串）。 */
function teacherThreadMail(settings, siteUrl, { seat, postId, title }) {
  const u = urls(siteUrl);
  return {
    subject: oneLine(`〈${settings.className}〉座號 ${seat} 的家長在〈${oneLine(title, 60)}〉回了一則`, 150),
    text: `座號 ${seat} 的家長在〈${oneLine(title, 80)}〉底下回了一則。\n\n`
      + `打開那一篇：${u.entry(seat, postId)}\n\n（信裡不附對話內容：那是你和這個家庭之間的話，請登入網站查看。）`,
  };
}

// ── 給家長的信（延遲 30 分鐘、一位一封）────────────────────────────────────────

function parentMail(settings, siteUrl, { kind, seat, postId, title }) {
  const u = urls(siteUrl);
  const t = oneLine(title || '（無標題）', 80);
  const what = kind === 'comment'
    ? `老師在座號 ${seat} 的部落格文章〈${t}〉底下回覆了一則。`
    : `老師在座號 ${seat} 的部落格發了一篇新文章〈${t}〉。`;
  return {
    subject: oneLine(kind === 'comment'
      ? `〈${settings.className}〉座號 ${seat} 的部落格有老師的新回覆`
      : `〈${settings.className}〉座號 ${seat} 的部落格有一篇老師的新文章`, 150),
    text: `${what}\n\n請登入班級網站查看：${u.entry(seat, postId)}\n`
      + '（內容只放在網站上，信裡不附內文；要用你登記在班上的 Google 帳號登入。）' + footer(settings),
  };
}

/** 寄件人／回信地址：From 一定是登入寄信的那個 Gmail（別的地址會被當成偽造）；導師收件信箱不同時放 Reply-To。 */
function envelope(settings, to) {
  const msg = {
    from: { name: settings.senderName, address: settings.fromEmail },
    to,
  };
  if (settings.teacherEmail && emailKeyOrNull(settings.teacherEmail) !== emailKeyOrNull(settings.fromEmail)) {
    msg.replyTo = settings.teacherEmail;
  }
  return msg;
}

function emailKeyOrNull(e) {
  try { return emailKey(e); } catch (err) { return null; }
}

// ── 每日摘要：「需要處理」的判斷 ─────────────────────────────────────────────────

/** 名單包含關係（與 scripts/access_sync.py 的 inclusion_problems() 同一套，只少了欄位格式檢查）。 */
function inclusionProblems(allow, priv, map, teacherKey) {
  const p = [];
  const t = allow[teacherKey];
  if (!teacherKey) p.push('config/notify 沒有導師的 email 鍵（重跑 notify_config.py --sync --apply）');
  else if (!t || t.kind !== 'teacher') p.push('導師不在班網名單（allowlist），或身分不是導師');
  if (teacherKey && !Object.prototype.hasOwnProperty.call(priv, teacherKey)) p.push('導師不在私密名單（private_allowlist）');
  for (const key of Object.keys(priv)) {
    if (!Object.prototype.hasOwnProperty.call(allow, key)) p.push(`有私密讀者不在班網名單（${maskEmail(key)}）`);
  }
  for (const key of Object.keys(map)) {
    if (!Object.prototype.hasOwnProperty.call(allow, key)) p.push(`有座號對應的帳號不在班網名單（${maskEmail(key)}）`);
  }
  for (const [key, d] of Object.entries(allow)) {
    if (d && d.kind === 'teacher' && key !== teacherKey) p.push(`班網名單裡有一個不是導師的帳號被標成導師（${maskEmail(key)}）`);
  }
  const aliases = Object.values(allow).map((d) => d && d.alias).filter(Boolean);
  if (aliases.length !== new Set(aliases).size) p.push('班網名單裡有兩個人的作者代號一樣');
  return p;
}

const BACKUP_LINES = [
  ['weekly', '網站資料庫備份（backup.py firestore）'],
  ['nightly', '學生部落格備份（backup.py blogs）'],
];

/** ops/backup_status → { lines: [文字], problems: [文字] }。門檻跟 scripts/status.py 一樣（REMIND_DAYS／URGENT_DAYS），
    由 build_config.py 寫進 functions/cmw.generated.json——兩邊不會各自漂。 */
function backupReport(status, nowMs, remindDays, urgentDays) {
  const lines = [];
  const problems = [];
  for (const [key, label] of BACKUP_LINES) {
    const rec = (status || {})[key] || null;
    const t = rec ? toMillis(rec.lastRunAt) : null;
    if (t === null) {
      lines.push(`${label}：還沒有紀錄`);
      problems.push(`${label}還沒有成功過：跟 AI 助理說「備份」（playbooks/backup.md）`);
      continue;
    }
    const days = Math.floor((nowMs - t) / DAY);
    if (rec.ok === false) {
      lines.push(`${label}：上一次（${days} 天前）沒有成功`);
      problems.push(`${label}上一次沒有成功：跟 AI 助理說「備份」，照它印的「→」處理`);
    } else if (days >= urgentDays) {
      lines.push(`${label}：${days} 天前`);
      problems.push(`${label}已經 ${days} 天沒有成功了（超過 ${urgentDays} 天）：今天就跟 AI 助理說「備份」`);
    } else if (days >= remindDays) {
      lines.push(`${label}：${days} 天前`);
      problems.push(`${label} ${days} 天沒有備份了（超過 ${remindDays} 天）：跟 AI 助理說「備份」`);
    } else {
      lines.push(`${label}：${days} 天前，正常`);
    }
  }
  return { lines, problems };
}

/** 通知線的健康：排程心跳、失敗、卡住、上一輪的錯誤、即時信的錯誤。 */
function notifyProblems({ settings, status, nowMs, failed, stuck }) {
  const p = [];
  const st = status || {};
  if (settings.phase !== 'off' && settings.parentMail) {
    const last = toMillis(st.lastRunAt);
    if (last === null) p.push('給家長的通知排程從來沒有跑過：通知信模組可能沒部署成功（跟 AI 助理說「通知信健檢」）');
    else if (nowMs - last > C.SWEEP_STALE_MS) p.push(`給家長的通知排程已經 ${Math.floor((nowMs - last) / HOUR)} 小時沒有執行（平常每 10 分鐘會跑一次）`);
    if (failed > 0) p.push(`過去 24 小時有 ${failed} 筆給家長的通知寄不出去`);
    if (stuck > 0) p.push(`有 ${stuck} 筆給家長的通知過了預定時間 2 小時還在排隊`);
    if (st.lastError) p.push(`通知排程上一輪有錯誤：${maskEmails(st.lastError).slice(0, 200)}`);
  }
  const ie = toMillis(st.lastInstantErrorAt);
  if (ie !== null && nowMs - ie < C.DIGEST_WINDOW_MS && st.lastInstantError) {
    p.push(`給你的即時通知有寄不出去的：${maskEmails(st.lastInstantError).slice(0, 200)}`);
  }
  for (const s of settings.problems || []) p.push(`通知設定：${s}`);
  return p;
}

// ── 每日摘要：組信 ─────────────────────────────────────────────────────────────

function fmtWhen(ms, timeZone) {
  try {
    return new Intl.DateTimeFormat('zh-TW', {
      timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
    }).format(new Date(ms));
  } catch (e) {
    return new Date(ms).toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
  }
}

/** data：{ comments:[{parent, slug, title, counts:{parent,staff}}], entries:[{seat, postId, title}],
            threads:[{seat, postId, title, n}], queue:{done, dryrun, cancelled, failed, pending, skipped},
            notifyLine:'', backupLines:[], problems:[] } */
function digestMail(settings, cfg, nowMs, data) {
  const u = urls(cfg.siteUrl);
  const nComments = data.comments.reduce((a, c) => a + c.counts.parent + c.counts.staff, 0);
  const nThreadMsgs = data.threads.reduce((a, t) => a + t.n, 0);
  const out = [];
  out.push(`〈${settings.className}〉每日摘要（${fmtWhen(nowMs, cfg.timeZone)}，過去 24 小時）`);
  if (data.problems.length) {
    out.push('', `■ 需要處理（${data.problems.length} 項）`);
    data.problems.forEach((p, i) => out.push(`${i + 1}. ${p}`));
  }
  out.push('', `■ 新留言：${nComments} 則${data.comments.length ? `（${data.comments.length} 篇）` : ''}`);
  for (const c of data.comments) {
    const where = c.parent === 'private_posts' ? `私密紀事（${c.slug}）` : `${PARENT_LABEL[c.parent]}〈${oneLine(c.title || c.slug, 60)}〉`;
    const parts = [];
    if (c.counts.parent) parts.push(`家長 ${c.counts.parent}`);
    if (c.counts.staff) parts.push(`同仁 ${c.counts.staff}`);
    const link = c.parent === 'albums' ? u.album(c.slug) : c.parent === 'private_posts' ? u.private(c.slug) : u.post(c.slug);
    out.push(`・${where}：${parts.join('、')}`, `  ${link}`);
  }
  if (data.moreComments) out.push('・（留言太多，只列出最新的 200 則；其餘請到留言後台看）');
  out.push('', `■ 家長發的部落格：${data.entries.length} 篇`);
  for (const e of data.entries) out.push(`・座號 ${e.seat}〈${oneLine(e.title, 60)}〉`, `  ${u.entry(e.seat, e.postId)}`);
  out.push('', `■ 部落格對話（家長留的話）：${nThreadMsgs} 則${data.threads.length ? `（${data.threads.length} 篇）` : ''}`);
  for (const t of data.threads) out.push(`・座號 ${t.seat}〈${oneLine(t.title, 60)}〉：${t.n} 則`, `  ${u.entry(t.seat, t.postId)}`);
  if (data.notifyLine) out.push('', '■ 給家長的通知信', data.notifyLine);
  out.push('', '■ 備份', ...data.backupLines.map((l) => '・' + l));
  out.push('', `（信裡不附留言與文章內容，請登入網站查看。留言後台：${u.admin()}　導師專用頁：${u.teacher()}）`);
  const bits = [`留言 ${nComments}`, `部落格 ${data.entries.length}`, `對話 ${nThreadMsgs}`];
  const subject = `〈${settings.className}〉每日摘要：${bits.join('、')}` + (data.problems.length ? `｜要處理 ${data.problems.length} 項` : '');
  return { subject: oneLine(subject, 150), text: out.join('\n') };
}

/** 摘要要不要寄：有新東西、或有要處理的事才寄（沒事就不寄空信）。 */
function digestWorthSending(data) {
  return data.problems.length > 0 || data.comments.length > 0 || data.entries.length > 0 || data.threads.length > 0;
}

module.exports = {
  C, PHASES, RE, emailKey, isEmail, maskEmail, maskEmails, ledgerId, onceId, oneLine, toMillis,
  normalizeSettings, gateContent, parentModeFor, recipientsFrom, urls,
  teacherCommentMail, teacherEntryMail, teacherThreadMail, parentMail, envelope,
  inclusionProblems, backupReport, notifyProblems, digestMail, digestWorthSending, fmtWhen,
};
