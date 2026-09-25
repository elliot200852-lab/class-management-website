/* mailer.js — 寄信的出口，只有兩種：
     · 正式：Gmail SMTP（smtp.gmail.com:465），帳號＝config/notify.fromEmail，密碼＝Secret Manager 裡的 Gmail 應用程式密碼
     · 模擬器：一律寫進模擬器資料庫的 _emulator_outbox 集合（測試讀它），**絕不連任何郵件伺服器**
   是不是模擬器由 Functions 執行環境決定（FUNCTIONS_EMULATOR），不是由設定檔決定——設定寫錯也寄不出真的信。 */
'use strict';

function inEmulator(env) {
  const e = env || process.env;
  return e.FUNCTIONS_EMULATOR === 'true' || !!e.FIRESTORE_EMULATOR_HOST;
}

/** 測試與模擬器用：把信寫進 _emulator_outbox（只存測試要比對的欄位）。 */
function outboxMailer(db) {
  return {
    kind: 'outbox',
    async send(msg) {
      const to = Array.isArray(msg.to) ? msg.to : [msg.to];
      await db.collection('_emulator_outbox').add({
        to, from: msg.from, replyTo: msg.replyTo || null, subject: msg.subject, text: msg.text, at: new Date(),
      });
    },
  };
}

/** 陣列版的假郵差（node --test 直接呼叫 core.js 時用）。fail(msg) 回 true 就假裝寄失敗。 */
function memoryMailer(fail) {
  const sent = [];
  return {
    kind: 'memory',
    sent,
    async send(msg) {
      if (fail && fail(msg)) throw new Error('假的寄信失敗：550 mailbox unavailable <' + (Array.isArray(msg.to) ? msg.to[0] : msg.to) + '>');
      sent.push(msg);
    },
  };
}

/** 正式：Gmail SMTP。登入帳號一律＝信的寄件地址（config/notify.fromEmail）：應用程式密碼是那個帳號的，
    From 用別的地址會被 Gmail 改寫或被收件端當成偽造。 */
function smtpMailer(pass) {
  const nodemailer = require('nodemailer');
  const transports = new Map();
  return {
    kind: 'smtp',
    async send(msg) {
      const user = msg.from && msg.from.address;
      if (!user) throw new Error('信沒有寄件地址（config/notify.fromEmail）');
      if (!transports.has(user)) {
        transports.set(user, nodemailer.createTransport({
          host: 'smtp.gmail.com', port: 465, secure: true, auth: { user, pass },
        }));
      }
      await transports.get(user).sendMail({
        from: msg.from, to: msg.to, replyTo: msg.replyTo, subject: msg.subject, text: msg.text,
      });
    },
  };
}

/** index.js 用：模擬器一律 outbox；正式環境才用 SMTP（密碼在呼叫時才從 Secret Manager 拿）。 */
function pick({ db, secret, env }) {
  if (inEmulator(env)) return outboxMailer(db);
  const pass = secret ? String(secret.value() || '').replace(/\s+/g, '') : '';
  if (!pass) {
    return { kind: 'none', async send() { throw new Error('Secret Manager 裡沒有 Gmail 應用程式密碼（CMW_GMAIL_APP_PASSWORD）'); } };
  }
  return smtpMailer(pass);
}

module.exports = { inEmulator, outboxMailer, memoryMailer, smtpMailer, pick };
