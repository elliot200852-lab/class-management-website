// Firestore 安全規則的模擬器測試（入口）。
//
// 不要直接跑這支：用 `python3 scripts/test_rules.py`（Windows：`py -3 scripts\test_rules.py`）。
// 那支會先用 scripts/build_config.py 產生規則（測試用設定）、做存取次數靜態檢查、
// 再用 firebase emulators:exec（專案 demo-cmw，保證不連真的雲端）跑這支，並用環境變數
// CMW_RULES_MANIFEST 告訴它規則檔在哪。
//
// 每一段（section）都會先清空模擬器、重種同一份資料，段與段之間互不影響。
import { readFileSync } from 'node:fs';
import { setLogLevel } from 'firebase/firestore';
import { Suite, describe } from './lib/harness.mjs';
import { World } from './lib/world.mjs';
import * as lists from './suites/lists.mjs';
import * as content from './suites/content.mjs';
import * as threads from './suites/threads.mjs';
import * as blogs from './suites/blogs.mjs';
import * as misc from './suites/misc.mjs';
import * as fields from './suites/fields.mjs';
import * as special from './suites/special.mjs';
import * as queries from './suites/queries.mjs';
import * as teacher from './suites/teacher.mjs';
import * as canaries from './suites/canaries.mjs';

const manifestPath = process.env.CMW_RULES_MANIFEST;
if (!manifestPath) {
  console.error('✗ 請用 python3 scripts/test_rules.py 跑（它會產生規則、設定 CMW_RULES_MANIFEST、啟動模擬器）。');
  process.exit(2);
}
if (!process.env.FIRESTORE_EMULATOR_HOST) {
  console.error('✗ 找不到 Firestore 模擬器（FIRESTORE_EMULATOR_HOST 沒設）。請用 python3 scripts/test_rules.py 跑。');
  process.exit(2);
}

// 被拒的寫入 SDK 會自己在主控台印一大串 PERMISSION_DENIED；結果由這裡的執行器判斷與列印
setLogLevel('silent');

const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
const main = manifest.variants.main;
const rules = readFileSync(main.rulesFile, 'utf8');
const S = new Suite({ verbose: manifest.verbose });
const W = new World({
  projectId: manifest.projectId,
  rules,
  teacher: { email: main.teacher.join('@'), key: main.teacherKey },
});
const ctx = { repoRoot: manifest.repoRoot, rules, manifest };

console.log(`規則測試：專案 ${manifest.projectId}（模擬器 ${process.env.FIRESTORE_EMULATOR_HOST}）`);
console.log('每個案例一行只在失敗時印；加 --verbose 全部印。');

let crashed = 0;
await W.start();
try {
  for (const suite of [lists, content, threads, blogs, misc, fields, special, queries, teacher, canaries]) {
    try {
      await suite.run(S, W, ctx);
    } catch (e) {
      crashed += 1;
      if (!S.cur) S.section('（中途出錯）');
      S.cur.fail += 1;
      S.cur.failures.push('這一段中途出錯');
      console.log(`   ✗ 這一段中途出錯，後面的案例沒有跑：${describe(e)}`);
      if (e && e.stack) console.log(e.stack.split('\n').slice(1, 6).join('\n'));
    }
  }
} finally {
  await W.stop();
}

const { pass, fail } = S.summary();
if (crashed) console.log(`（有 ${crashed} 段中途出錯）`);
process.exit(fail === 0 && pass > 0 ? 0 : 1);
