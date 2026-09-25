/* 班級網站 v1.1 選配：通知信模組（Cloud Functions 第 2 代）。預設不部署；要 Blaze 方案。
   怎麼裝、怎麼關：playbooks/notify.md。設計：docs/ARCHITECTURE.md §10；集合：docs/DATA-MODEL.md §2.18。

   五個觸發器＋兩個排程，全部部署在 config/class.json 的 region（跟資料庫同一區）：
     cmwCommentPost／cmwCommentAlbum／cmwCommentPrivate   紀事、相簿、私密紀事的新留言 → 即時寄導師（導師自己的不寄）
     cmwBlogEntry                                        家長發部落格 → 即時寄導師；導師發 → 排進佇列
     cmwBlogComment                                      家長在對話串回話 → 即時寄導師；導師回覆 → 排進佇列
     cmwNotifySweep（每 10 分鐘）                         佇列到期（30 分鐘修正窗過了）→ 逐位寄給那個座號的家長
     cmwDailyDigest（每天一次）                           每日摘要＋看門狗（名單包含關係、備份心跳、通知線健康）→ 寄導師

   開關與階段（off／dryrun／live）在資料庫 config/notify，只有 scripts/notify_config.py 改得動（網頁寫不進去）。
   信裡只有座號、標題、連結；不夾正文、不寫姓名。 */
'use strict';

const { onDocumentCreated } = require('firebase-functions/v2/firestore');
const { onSchedule } = require('firebase-functions/v2/scheduler');
const { defineSecret } = require('firebase-functions/params');
const logger = require('firebase-functions/logger');
const { initializeApp } = require('firebase-admin/app');
const { getFirestore } = require('firebase-admin/firestore');

const config = require('./lib/config');
const core = require('./lib/core');
const mailer = require('./lib/mailer');

initializeApp();
const db = getFirestore();
const cfg = config.load();

// Gmail 應用程式密碼：老師自己在終端機跑 firebase functions:secrets:set CMW_GMAIL_APP_PASSWORD 貼進去（AI 代理不經手）。
const GMAIL_APP_PASSWORD = defineSecret('CMW_GMAIL_APP_PASSWORD');
// 模擬器裡不掛秘密：不讓模擬器去問雲端的 Secret Manager；模擬器也一律用假的郵差（lib/mailer.js）。
const IN_EMULATOR = mailer.inEmulator();

const BASE = {
  region: cfg.region,
  secrets: IN_EMULATOR ? [] : [GMAIL_APP_PASSWORD],
  retry: false,
  memory: '256MiB',
  maxInstances: 2,
};

function deps() {
  return {
    db,
    cfg,
    mailer: mailer.pick({ db, secret: IN_EMULATOR ? null : GMAIL_APP_PASSWORD }),
    log: logger,
  };
}

function trigger(document, handler) {
  return onDocumentCreated(Object.assign({}, BASE, { document }), async (event) => {
    const snap = event.data;
    if (!snap) return;
    const r = await handler(deps(), event.params, snap.data());
    logger.info('處理完成', { document, result: r });
  });
}

exports.cmwCommentPost = trigger('posts/{slug}/comments/{cid}',
  (d, p, data) => core.onComment(d, { parent: 'posts', slug: p.slug, cid: p.cid }, data));
exports.cmwCommentAlbum = trigger('albums/{slug}/comments/{cid}',
  (d, p, data) => core.onComment(d, { parent: 'albums', slug: p.slug, cid: p.cid }, data));
exports.cmwCommentPrivate = trigger('private_posts/{slug}/comments/{cid}',
  (d, p, data) => core.onComment(d, { parent: 'private_posts', slug: p.slug, cid: p.cid }, data));
exports.cmwBlogEntry = trigger('student_blogs/{seat}/entries/{postId}',
  (d, p, data) => core.onEntry(d, { seat: p.seat, postId: p.postId }, data));
exports.cmwBlogComment = trigger('student_blogs/{seat}/entries/{postId}/blog_comments/{cid}',
  (d, p, data) => core.onBlogComment(d, { seat: p.seat, postId: p.postId, cid: p.cid }, data));

exports.cmwNotifySweep = onSchedule(Object.assign({}, BASE, {
  schedule: 'every 10 minutes', timeZone: cfg.timeZone, timeoutSeconds: 300, maxInstances: 1,
}), async () => {
  const stats = await core.sweepOnce(deps());
  logger.info('佇列掃描完成', stats);
});

exports.cmwDailyDigest = onSchedule(Object.assign({}, BASE, {
  schedule: `0 ${cfg.digestHour} * * *`, timeZone: cfg.timeZone, timeoutSeconds: 300, maxInstances: 1,
}), async () => {
  const beat = await core.runDigest(deps());
  logger.info('每日摘要完成', { sent: beat.sent, problems: beat.problems });
});
