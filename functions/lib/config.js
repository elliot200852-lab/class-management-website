/* config.js — 讀部署時的設定 functions/cmw.generated.json（由 scripts/build_config.py 從 config/class.json 產生，
   被 .gitignore 擋住、不手寫）。裡面**沒有任何信箱**：收件人、寄件人、署名在資料庫的 config/notify
   （scripts/notify_config.py 寫，改了不用重新部署）。

   模擬器（FUNCTIONS_EMULATOR）裡可以用環境變數 CMW_FUNCTIONS_CONFIG 指到測試用的設定檔；正式環境不看這個變數。 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const GENERATED = path.join(__dirname, '..', 'cmw.generated.json');
const REGION_RE = /^[a-z]+(-[a-z]+)+[0-9]+$/;
const TZ_RE = /^[A-Za-z_]+(\/[A-Za-z0-9_+-]+)*$/;

function validate(c) {
  const bad = [];
  if (!c || c.format !== 1) bad.push('format');
  if (!/^[a-z][a-z0-9-]{5,29}$/.test(String(c && c.projectId))) bad.push('projectId');
  if (!REGION_RE.test(String(c && c.region))) bad.push('region');
  if (!/^https:\/\/[a-z0-9.-]+$/.test(String(c && c.siteUrl))) bad.push('siteUrl');
  if (!TZ_RE.test(String(c && c.timeZone))) bad.push('timeZone');
  if (!Number.isInteger(c && c.digestHour) || c.digestHour < 0 || c.digestHour > 23) bad.push('digestHour');
  for (const k of ['backupRemindDays', 'backupUrgentDays']) {
    if (!Number.isInteger(c && c[k]) || c[k] < 1 || c[k] > 60) bad.push(k);
  }
  return bad;
}

function load(env) {
  const e = env || process.env;
  const file = e.FUNCTIONS_EMULATOR === 'true' && e.CMW_FUNCTIONS_CONFIG ? e.CMW_FUNCTIONS_CONFIG : GENERATED;
  let raw;
  try {
    raw = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^﻿/, ''));
  } catch (err) {
    throw new Error('找不到或讀不懂 functions/cmw.generated.json：先跑 build_config.py（Mac：python3 scripts/build_config.py；'
      + 'Windows：py -3 scripts/build_config.py），再部署。');
  }
  const bad = validate(raw);
  if (bad.length) {
    throw new Error('functions/cmw.generated.json 的這幾欄不對：' + bad.join('、') + '。重跑 build_config.py 重新產生（不要手改）。');
  }
  return Object.freeze(raw);
}

module.exports = { load, validate, GENERATED };
