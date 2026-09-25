#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""名單同步（scripts/access_sync.py、lib/sources.py）：來源解析、安全閘、對帳計畫、代號沿用、輸出不含個資。不連網。"""
import io
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
import access_sync as acc  # noqa: E402
import admin_support as fx  # noqa: E402
from lib import sources, schema  # noqa: E402
from lib import firestore_rest as fr  # noqa: E402
from lib.emailkey import email_key  # noqa: E402


class Cfg(object):
    teacher_email = fx.TEACHER
    teacher_key = email_key(fx.TEACHER)
    teacher_display_name = "示範導師"
    school_name = ""
    students_count = 25
    calendar_ics_url = ""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cmw-acc-"))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def files(self, roster=None, contacts=None, roles=None, enc="utf-8"):
        r = self.tmp / "roster.csv"
        c = self.tmp / "contacts.csv"
        y = self.tmp / "parent-roles.yaml"
        r.write_bytes((roster if roster is not None else fx.roster_csv()).encode(enc))
        c.write_bytes((contacts if contacts is not None else fx.contacts_csv()).encode(enc))
        y.write_bytes((roles if roles is not None else fx.roles_yaml()).encode("utf-8"))
        return r, c, y

    def load(self, **kw):
        r, c, y = self.files(**kw)
        roster, _ = sources.load_roster(r)
        contacts, _ = sources.load_contacts(c)
        roles = sources.load_roles(y)
        return roster, contacts, roles


class TestSources(Base):
    def test_roster_and_contacts(self):
        roster, contacts, roles = self.load()
        self.assertEqual([s.seat for s in roster][:3], ["01", "02", "03"])
        self.assertEqual(roster[0].display, "A")
        staff = [c for c in contacts if c.staff]
        self.assertEqual([c.seat for c in staff], ["01", "03"])
        self.assertTrue(all(c.relation == "" for c in staff))
        self.assertEqual(roles["01"], ["母", "父"])

    def test_bom_and_big5(self):
        r, c, _ = self.files(roster="﻿" + fx.roster_csv(), contacts=fx.contacts_csv(), enc="utf-8")
        self.assertEqual(len(sources.load_roster(r)[0]), 25)
        r, c, _ = self.files(contacts=fx.contacts_csv(), enc="cp950")
        contacts, notes = sources.load_contacts(c)
        self.assertEqual(len(contacts), 30)
        self.assertTrue(notes and "Big5" in notes[0])

    def test_errors_never_show_names_or_emails(self):
        bad = "座號,關係,姓名,Email\n01,母,學生 A 家長,not-an-email\n,母,學生 B 家長,%s\n" % fx.parent_mail(1)
        r, c, _ = self.files(contacts=bad)
        with self.assertRaises(sources.SourceError) as cm:
            sources.load_contacts(c)
        text = "；".join(cm.exception.problems)
        self.assertIn("第 2 列", text)
        self.assertIn("第 3 列", text)
        self.assertNotIn("學生", text)
        self.assertNotIn("@", text)

    def test_missing_empty_header_only(self):
        with self.assertRaises(sources.SourceError):
            sources.load_contacts(self.tmp / "nope.csv")
        r, c, _ = self.files(contacts="")
        with self.assertRaises(sources.SourceError):
            sources.load_contacts(c)
        r, c, _ = self.files(contacts="座號,關係,姓名,Email\n")
        with self.assertRaises(sources.SourceError):
            sources.load_contacts(c)
        r, c, _ = self.files(contacts="seat,name\n01,x\n")
        with self.assertRaises(sources.SourceError) as cm:
            sources.load_contacts(c)
        self.assertIn("表頭", cm.exception.problems[0])

    def test_roster_display_name_required(self):
        r, _, _ = self.files(roster="座號,姓名,稱呼\n1,學生 A,\n")
        with self.assertRaises(sources.SourceError):
            sources.load_roster(r)

    def test_roles_both_styles_and_errors(self):
        y = self.tmp / "r.yaml"
        y.write_text('# 註解\n"01": [母, "父"]\n02:\n  - 母\n  - 祖母  # 行尾註解\n"03": []\n', encoding="utf-8")
        self.assertEqual(sources.load_roles(y), {"01": ["母", "父"], "02": ["母", "祖母"], "03": []})
        for bad in ('"01": [母]\n"01": [父]\n', '"41": [母]\n', '這不是 yaml\n', '"01": [母, 母]\n', ""):
            y.write_text(bad, encoding="utf-8")
            with self.assertRaises(sources.SourceError):
                sources.load_roles(y)


class TestGates(Base):
    def test_floor_comes_from_roles_not_csv(self):
        roster, contacts, roles = self.load(contacts=fx.contacts_csv(drop=range(5, 25)))
        _, probs, _ = acc.source_gates(roster, contacts, roles)
        self.assertTrue(any("下限" in p for p in probs))
        # 同一份截斷的 CSV，parent-roles 也一起縮 → 不擋（下限只看 parent-roles）
        small_roles = "\n".join('"%02d": [%s]' % (i + 1, "母, 父" if i < 3 else "母") for i in range(5))
        roster, contacts, roles = self.load(contacts=fx.contacts_csv(drop=range(5, 25)), roles=small_roles)
        _, probs, _ = acc.source_gates(roster, contacts, roles)
        self.assertEqual(probs, [])

    def test_slack_allows_a_few_missing(self):
        roster, contacts, roles = self.load(contacts=fx.contacts_csv(drop=(10, 11, 12)))
        report, probs, notes = acc.source_gates(roster, contacts, roles)
        self.assertEqual(probs, [])
        self.assertTrue(any("還沒有 email" in n for n in notes))
        roster, contacts, roles = self.load(contacts=fx.contacts_csv(drop=(10, 11, 12, 13)))
        _, probs, _ = acc.source_gates(roster, contacts, roles)
        self.assertTrue(probs)

    def test_undeclared_and_duplicate_are_warnings(self):
        extra = "05,舅舅,某人,%s,,,\n15,母,某人,%s,,,\n" % (fx.mail("uncle"), fx.mail("typo"))
        roster, contacts, roles = self.load(contacts=fx.contacts_csv() + extra)
        _, probs, notes = acc.source_gates(roster, contacts, roles)
        self.assertEqual(probs, [])
        self.assertTrue(any("舅舅" in n for n in notes))
        self.assertTrue(any("座號 15 的「母」有 2 個不同的信箱" in n for n in notes))

    def test_roles_seat_not_in_roster_stops(self):
        roster, contacts, roles = self.load(roster=fx.roster_csv(24))
        _, probs, _ = acc.source_gates(roster, contacts, roles)
        self.assertTrue(any("25" in p for p in probs))


class TestDesiredAndDiff(Base):
    def empty(self):
        return {"allow": {}, "private": {}, "map": {}, "roster": None, "site": None}

    def test_desired_shape(self):
        roster, contacts, roles = self.load()
        d, probs = acc.build_desired(Cfg, roster, contacts)
        self.assertEqual(probs, [])
        self.assertEqual(len(d["allow"]), 30)
        self.assertEqual(d["allow"][Cfg.teacher_key], {"kind": "teacher"})
        self.assertEqual(d["private"], {Cfg.teacher_key, email_key(fx.parent_mail(0))})
        self.assertEqual(d["map"][email_key(fx.mail("staff-1"))],
                         {"seats": ["01", "03"], "kind": "staff", "active": True, "label": "座號 01、03 同仁"})

    def test_teacher_in_contacts_and_parent_staff_conflict(self):
        roster, contacts, roles = self.load(contacts=fx.contacts_csv() + "02,同仁,x,%s,,,\n" % fx.TEACHER)
        _, probs = acc.build_desired(Cfg, roster, contacts)
        self.assertTrue(any("導師自己的信箱" in p for p in probs))
        roster, contacts, roles = self.load(contacts=fx.contacts_csv() + "02,同仁,x,%s,,,\n" % fx.parent_mail(0))
        _, probs = acc.build_desired(Cfg, roster, contacts)
        self.assertTrue(any("不能同時是家長和同仁" in p for p in probs))

    def test_parent_with_two_children(self):
        c = fx.contacts_csv() + "07,母,x,%s,,,\n" % fx.parent_mail(0)
        roster, contacts, roles = self.load(contacts=c, roles=fx.roles_yaml())
        d, probs = acc.build_desired(Cfg, roster, contacts)
        self.assertEqual(probs, [])
        m = d["map"][email_key(fx.parent_mail(0))]
        self.assertEqual(m["seats"], ["01", "07"])
        self.assertEqual(m["label"], "座號 01、07 家長")
        self.assertEqual(schema.problems("parent_child_map", dict(m, updatedAt=fr.SERVER_TIME)), [])

    def test_first_run_then_idempotent(self):
        roster, contacts, roles = self.load()
        d, _ = acc.build_desired(Cfg, roster, contacts)
        plan = acc.diff(d, self.empty())
        self.assertEqual(len(plan["allow"]["create"]), 30)
        self.assertEqual(plan["roster"], "create")
        aliases = [v["alias"] for v in plan["allow"]["create"].values()]
        self.assertEqual(len(set(aliases)), 30)
        self.assertTrue(all(schema.ALIAS_RE.match(a) for a in aliases))
        # 把計畫「寫進去」，再對一次帳 → 零變更、代號不變
        cur = {"allow": {k: dict(v, updatedAt=fr.Timestamp("t")) for k, v in plan["allow"]["create"].items()},
               "private": {k: {"updatedAt": fr.Timestamp("t")} for k in plan["private"]["create"]},
               "map": {k: dict(v, updatedAt=fr.Timestamp("t")) for k, v in plan["map"]["create"].items()},
               "roster": dict(d["roster"], updatedAt=fr.Timestamp("t")),
               "site": dict(d["site"], updatedAt=fr.Timestamp("t"))}
        plan2 = acc.diff(d, cur)
        self.assertEqual(acc.change_count(plan2), 0)
        self.assertEqual(plan2["allow"]["same"], 30)

    def test_alias_is_kept_on_kind_change(self):
        roster, contacts, roles = self.load()
        d, _ = acc.build_desired(Cfg, roster, contacts)
        key = email_key(fx.parent_mail(3))
        cur = self.empty()
        cur["allow"][key] = {"kind": "staff", "alias": "keepmealias1", "updatedAt": fr.Timestamp("t")}
        cur["allow"]["gone@example.com"] = {"kind": "parent", "alias": "goneeeealias", "updatedAt": fr.Timestamp("t")}
        plan = acc.diff(d, cur)
        self.assertEqual(plan["allow"]["update"][key][1], {"kind": "parent", "alias": "keepmealias1"})
        self.assertIn("gone@example.com", plan["allow"]["delete"])
        self.assertEqual(acc.losing_access(plan), {"gone@example.com"})
        self.assertNotIn("keepmealias1", [v["alias"] for v in plan["allow"]["create"].values()])

    def test_new_alias_avoids_collisions(self):
        seq = iter(["dupdupdupdup", "dupdupdupdup", "freshalias01"])
        taken = {"dupdupdupdup"}
        self.assertEqual(acc.new_alias(taken, lambda: next(seq)), "freshalias01")

    def test_write_order_keeps_inclusion(self):
        roster, contacts, roles = self.load()
        d, _ = acc.build_desired(Cfg, roster, contacts)
        cur = self.empty()
        cur["allow"]["old@example.com"] = {"kind": "parent", "alias": "oldoldoldold"}
        cur["private"]["old@example.com"] = {}
        cur["map"]["old@example.com"] = {"seats": ["02"], "kind": "parent", "active": True, "label": "座號 02 家長"}
        plan = acc.diff(d, cur)
        c = fr.Client("demo-cmw", emulator_host="127.0.0.1:1")
        writes = acc.plan_writes(c, d, plan)
        names = [(("D:" + w["delete"]) if "delete" in w else ("U:" + w["update"]["name"])) for w in writes]
        first_delete = min(i for i, n in enumerate(names) if n.startswith("D:"))
        self.assertTrue(all(n.startswith("U:") for n in names[:first_delete]))
        dels = [n.split("/documents/")[1].split("/")[0] for n in names[first_delete:]]
        self.assertEqual(dels, ["parent_child_map", "private_allowlist", "allowlist"])

    def test_inclusion_problems(self):
        tk = Cfg.teacher_key
        cur = {"allow": {tk: {"kind": "teacher", "alias": "teacheralias", "updatedAt": fr.Timestamp("t")}},
               "private": {tk: {}, "x@example.com": {}}, "map": {}, "roster": None, "site": None}
        probs = acc.inclusion_problems(cur, tk)
        self.assertEqual(len(probs), 1)
        self.assertIn("x***@example.com", probs[0])


class TestOutputPrivacy(Base):
    def test_print_plan_masks_everything(self):
        roster, contacts, roles = self.load()
        d, _ = acc.build_desired(Cfg, roster, contacts)
        cur = {"allow": {}, "private": {}, "map": {}, "roster": None, "site": None}
        cur["allow"]["gone@example.com"] = {"kind": "parent", "alias": "goneeeealias"}
        plan = acc.diff(d, cur)
        buf = io.StringIO()
        with redirect_stdout(buf):
            acc.print_plan(plan, d, cur, limit=1000)
        out = buf.getvalue()
        self.assertIn("座號 01 母（p***@example.com）", out)
        for i in range(25):
            self.assertNotIn(fx.parent_mail(i), out)
            self.assertNotIn("學生 %s" % fx.LETTERS[i], out)
        self.assertNotIn("gone@example.com", out)

    def test_mask(self):
        self.assertEqual(acc.mask_email("parent.a@example.com"), "p***@example.com")
        self.assertEqual(acc.mask_email(None), "（沒有信箱）")


class TestMainStopsBeforeCloud(Base):
    """來源檔壞了：連雲端都不連（不需要 gcloud），exit 2。"""

    def test_missing_source_exit_2(self):
        root = fx.make_root(self.tmp / "root", photos=False)
        (root / "data" / "contacts.csv").unlink()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = acc.main(["--root", str(root), "--emulator"])
        self.assertEqual(rc, 2)
        self.assertIn("一筆都沒有寫", buf.getvalue())

    def test_config_missing(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = acc.main(["--root", str(self.tmp)])
        self.assertEqual(rc, 2)
        self.assertIn("config/class.json", buf.getvalue())

    def tearDown(self):
        from lib import paths
        paths.reset_root()
        super().tearDown()


if __name__ == "__main__":
    unittest.main()
