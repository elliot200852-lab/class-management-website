// 規則測試的小型執行器：分段、每個案例一行預期（允許／拒絕／讀到文件／找不到），最後印每一段的統計。
//
// 預期的意思：
//   allow    請求成功（寫入成功、查詢成功）
//   found    單筆讀取成功，而且文件存在
//   notfound 單筆讀取成功，但文件不存在（前端顯示「找不到」；DATA-MODEL §1.5）
//   deny     被規則拒絕（錯誤碼一定要是 permission-denied；其他錯誤不算數，會被當成失敗）
import { assertFails, assertSucceeds } from '@firebase/rules-unit-testing';

export class Suite {
  constructor({ verbose = false } = {}) {
    this.verbose = verbose;
    this.sections = [];
    this.cur = null;
  }

  section(title) {
    this.cur = { title, pass: 0, fail: 0, failures: [] };
    this.sections.push(this.cur);
    console.log(`\n── ${title}`);
  }

  _record(ok, expect, label, detail) {
    const s = this.cur;
    if (ok) {
      s.pass += 1;
      if (this.verbose) console.log(`   ✓ [${expect}] ${label}`);
    } else {
      s.fail += 1;
      s.failures.push(label);
      console.log(`   ✗ [預期 ${expect}] ${label}${detail ? `　→ ${detail}` : ''}`);
    }
  }

  // fn：回傳 Promise 的函式（讀、寫、查詢）
  async expect(expect, label, fn) {
    let ok = false;
    let detail = '';
    try {
      if (expect === 'deny') {
        await assertFails(fn());
        ok = true;
      } else {
        const res = await assertSucceeds(fn());
        if (expect === 'found' || expect === 'notfound') {
          const exists = res && typeof res.exists === 'function' ? res.exists() : undefined;
          ok = expect === 'found' ? exists === true : exists === false;
          if (!ok) detail = exists === undefined ? '回傳的不是單筆文件' : `允許了，但文件${exists ? '存在' : '不存在'}`;
        } else {
          ok = true;
        }
      }
    } catch (e) {
      detail = describe(e);
    }
    this._record(ok, expect, label, detail);
    return ok;
  }

  // 自訂斷言：fn 丟例外＝失敗
  async check(label, fn) {
    let ok = false;
    let detail = '';
    try {
      await fn();
      ok = true;
    } catch (e) {
      detail = describe(e);
    }
    this._record(ok, 'check', label, detail);
    return ok;
  }

  // 一格權限表：spec 列出允許的角色（found／notfound／allow 三種），其他角色一律預期 deny。
  // op(db, role) 回傳 Promise。
  async grid(world, label, spec, op, roles = world.roles) {
    for (const r of roles) {
      let exp = 'deny';
      if (spec.found && spec.found.includes(r)) exp = 'found';
      else if (spec.notfound && spec.notfound.includes(r)) exp = 'notfound';
      else if (spec.allow && spec.allow.includes(r)) exp = 'allow';
      await this.expect(exp, `${label}｜${world.label(r)}`, () => op(world.db(r), r));
    }
  }

  summary() {
    let pass = 0;
    let fail = 0;
    console.log('\n══ 每一段的結果 ══════════════════════════════════════════════');
    for (const s of this.sections) {
      pass += s.pass;
      fail += s.fail;
      const mark = s.fail === 0 ? '✓' : '✗';
      console.log(`${mark} ${String(s.pass + s.fail).padStart(4)} 案例　${s.fail === 0 ? '全過' : `失敗 ${s.fail}`}　${s.title}`);
    }
    console.log(`\n合計 ${pass + fail} 個案例：通過 ${pass}、失敗 ${fail}`);
    return { pass, fail };
  }
}

export function describe(e) {
  if (!e) return String(e);
  const code = e.code ? `${e.code}：` : '';
  const msg = String(e.message || e).split('\n')[0];
  return (code + msg).slice(0, 300);
}

// 自訂斷言用
export function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}
