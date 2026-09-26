#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部署（scripts/deploy.py）與雲端唯讀檢查（lib/cloudcheck.py）：不連網、不跑 firebase，全部用假的。"""
import io
import sys
import unittest
from pathlib import Path
from unittest import mock
from contextlib import redirect_stdout

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import deploy  # noqa: E402
from lib import cloudcheck as cc  # noqa: E402


class Cfg(object):
    project_id = "my-class-2026"
    teacher_email = "teacher" + "@" + "example.com"
    api_key = "k"
    app_id = "1:2:web:3"
    region = "asia-east1"
    site_url = "https://my-class-2026.firebaseapp.com"
    teacher_key = "teacher" + "@" + "example.com"


def quiet(fn, *a, **kw):
    buf = io.StringIO()
    with redirect_stdout(buf):
        r = fn(*a, **kw)
    return r, buf.getvalue()


class TestDeployPlan(unittest.TestCase):
    def test_never_force(self):
        for step in ("rules", "indexes", "hosting"):
            argv = deploy.firebase_argv("firebase", step, "my-class-2026")
            self.assertNotIn("--force", argv)
            self.assertEqual(argv[1:4], ["deploy", "--only", deploy.TARGETS[step]])
            self.assertIn("--non-interactive", argv)
            self.assertEqual(argv[argv.index("--project") + 1], "my-class-2026")
        src = (REPO / "scripts" / "deploy.py").read_text(encoding="utf-8")
        self.assertNotIn('"--force"]', src)

    def test_order_is_fixed(self):
        self.assertEqual(deploy.STEPS, ("check", "build", "rules", "indexes", "functions", "hosting", "verify"))

    def test_without_yes_nothing_runs(self):
        with mock.patch.object(deploy.classcfg, "load", return_value=Cfg()), \
                mock.patch.object(deploy.fr, "emulator_host_from_env", return_value=None), \
                mock.patch.object(deploy, "Deployer", side_effect=AssertionError("不該執行")), \
                mock.patch.object(deploy.subprocess, "Popen", side_effect=AssertionError("不該執行")):
            rc, out = quiet(deploy.main, [])
        self.assertEqual(rc, 0)
        self.assertIn("--yes", out)
        self.assertIn("不加 --force", out)

    def test_refuses_emulator_env(self):
        with mock.patch.object(deploy.fr, "emulator_host_from_env", return_value="127.0.0.1:8080"):
            rc, out = quiet(deploy.main, ["--yes"])
        self.assertEqual(rc, 2)


class FakeIdxClient(object):
    def __init__(self, seq):
        self.seq = list(seq)

    def list_indexes(self):
        return self.seq.pop(0) if len(self.seq) > 1 else self.seq[0]

    def list_field_overrides(self):
        return []


LOCAL = {"indexes": [{"collectionGroup": "posts", "queryScope": "COLLECTION",
                      "fields": [{"fieldPath": "visible", "order": "ASCENDING"}, {"fieldPath": "date", "order": "DESCENDING"}]}],
         "fieldOverrides": []}


def remote(state):
    return [{"name": "projects/p/databases/(default)/collectionGroups/posts/indexes/abc", "queryScope": "COLLECTION",
             "fields": [{"fieldPath": "visible", "order": "ASCENDING"}, {"fieldPath": "date", "order": "DESCENDING"},
                        {"fieldPath": "__name__", "order": "DESCENDING"}], "state": state}]


class TestDeployRun(unittest.TestCase):
    def deployer(self, client, runner, clock=None, max_wait=1200):
        sleeps = []
        d = deploy.Deployer(Cfg(), client, "firebase", runner=runner, sleep=sleeps.append,
                            clock=clock or (lambda: 0), max_wait=max_wait)
        return d, sleeps

    def test_stops_at_first_failure(self):
        calls = []

        def runner(argv, cwd):
            calls.append(argv)
            return (1, ["Error: Failed to authenticate, have you run firebase login?"]) if "firestore:rules" in argv else (0, [])
        d, _ = self.deployer(FakeIdxClient([remote("READY")]), runner)
        rc, out = quiet(d.run, ["rules", "indexes", "hosting"])
        self.assertEqual(rc, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("firebase login", out)
        self.assertIn("後面的步驟都沒有做", out)

    def test_waits_for_indexes(self):
        calls = []

        def runner(argv, cwd):
            calls.append(argv[3])
            return 0, []
        client = FakeIdxClient([[], remote("CREATING"), remote("READY")])
        with mock.patch.object(cc, "local_indexes", return_value=LOCAL):
            d, sleeps = self.deployer(client, runner)
            rc, out = quiet(d.run, ["indexes", "hosting"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(calls, ["firestore:indexes", "hosting"])
        self.assertEqual(sleeps, [deploy.POLL_SECONDS, deploy.POLL_SECONDS])

    def test_index_timeout_stops_before_hosting(self):
        calls = []
        t = [0]

        def clock():
            t[0] += 600
            return t[0]

        def runner(argv, cwd):
            calls.append(argv[3])
            return 0, []
        with mock.patch.object(cc, "local_indexes", return_value=LOCAL):
            d, _ = self.deployer(FakeIdxClient([remote("CREATING")]), runner, clock=clock, max_wait=1200)
            rc, out = quiet(d.run, ["indexes", "hosting"])
        self.assertEqual(rc, 1)
        self.assertEqual(calls, ["firestore:indexes"])
        self.assertIn("--only indexes", out)

    def test_hints(self):
        self.assertIn("firebase login", deploy.hint_for(["Error: Failed to authenticate"]))
        self.assertIn("啟用", deploy.hint_for(["API has not been used in project 1 before or it is disabled"]))

    def test_hint_no_hosting_site(self):
        # firebase-tools 非互動模式的原文（commands/deploy.js）；也不能被「not found／404」那條搶走
        for line in ("Error: Unable to deploy to Hosting as there is no Hosting site. Use firebase hosting:sites:create "
                     "to create a site.", "Error: Could not determine the default site for the project. (404 not found)"):
            h = deploy.hint_for([line])
            self.assertIn("Hosting", h)
            self.assertIn("開始使用", h)
            self.assertIn("--only hosting --yes", h)
            self.assertIn("不要跑 firebase hosting:sites:create", h)

    # ── 第 4 步：通知信模組（v1.1 選配）──────────────────────────────────────
    def test_functions_step_skipped_when_disabled(self):
        calls = []
        d, _ = self.deployer(FakeIdxClient([remote("READY")]), lambda argv, cwd: (calls.append(argv), (0, []))[1])
        rc, out = quiet(d.run, ["functions"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertIn("略過", out)

    def _enabled_deployer(self, runner):
        cfg = Cfg()
        cfg.raw = {"notifications": {"enabled": True}}
        return deploy.Deployer(cfg, FakeIdxClient([remote("READY")]), "firebase", runner=runner, sleep=lambda s: None,
                               clock=lambda: 0)

    def test_functions_first_deploy_sets_cleanup_policy_without_force(self):
        calls = []

        def runner(argv, cwd):
            calls.append(list(argv))
            if argv[1] == "deploy":
                return 2, ["✔ functions: Successfully created function cmwNotifySweep", "Error: Functions successfully "
                           "deployed but could not set up cleanup policy in location asia-east1. Pass the --force option to "
                           "automatically set up a cleanup policy or run 'firebase functions:artifacts:setpolicy' to "
                           "manually set up a cleanup policy."]
            return 0, ["i  Repository does not exist in Artifact Registry." if len(calls) == 1 else "✔ Successfully set up"]
        d = self._enabled_deployer(runner)
        with mock.patch.object(deploy.notify, "functions_not_ready", return_value=None):
            rc, out = quiet(d.run, ["functions"])
        self.assertEqual(rc, 0, out)
        self.assertEqual([c[1] for c in calls], ["functions:artifacts:setpolicy", "deploy", "functions:artifacts:setpolicy"])
        for c in calls:
            self.assertNotIn("--force", c)
            self.assertNotIn("-f", c)
            self.assertIn("--non-interactive", c)
            self.assertEqual(c[c.index("--project") + 1], "my-class-2026")
        self.assertEqual(calls[0][calls[0].index("--location") + 1], "asia-east1")
        self.assertEqual(calls[1][1:4], ["deploy", "--only", "functions"])
        self.assertIn("清理政策設好了", out)

    def test_functions_other_failures_explained(self):
        def runner(argv, cwd):
            if argv[1] == "deploy":
                return 1, ["Error: Failed to validate secret versions: secret CMW_GMAIL_APP_PASSWORD not found"]
            return 0, []
        d = self._enabled_deployer(runner)
        with mock.patch.object(deploy.notify, "functions_not_ready", return_value=None):
            rc, out = quiet(d.run, ["functions", "hosting"])
        self.assertEqual(rc, 1)
        self.assertIn("functions:secrets:set", out)
        self.assertIn("後面的步驟都沒有做", out)

    def test_functions_not_ready_stops_before_cli(self):
        calls = []
        d = self._enabled_deployer(lambda argv, cwd: (calls.append(argv), (0, []))[1])
        with mock.patch.object(deploy.notify, "installed_ok", return_value=False):
            rc, out = quiet(d.run, ["functions"])
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [])
        self.assertIn("npm ci --prefix", out)
        self.assertIn("老師在他自己的終端機", out)

    def test_notify_argv_never_force(self):
        from lib import notify
        for argv in (notify.deploy_argv("firebase", "p-123456"), notify.setpolicy_argv("firebase", "p-123456", "asia-east1")):
            self.assertNotIn("--force", argv)
        with self.assertRaises(RuntimeError):
            notify._no_force(["firebase", "deploy", "--force"])


class TestCloudEval(unittest.TestCase):
    def test_accounts(self):
        t = Cfg.teacher_email
        self.assertTrue(cc.eval_accounts(t, t, [t]).ok)
        other = "someone" + "@" + "example.com"
        item = cc.eval_accounts(t, other, [t])
        self.assertFalse(item.ok)
        self.assertNotIn(other, item.detail + " ".join(item.hints))
        self.assertFalse(cc.eval_accounts(t, t, None).ok)
        self.assertFalse(cc.eval_accounts(t, "", [t]).ok)

    def test_database(self):
        items = cc.eval_database(200, {"locationId": "asia-east1", "type": "FIRESTORE_NATIVE"}, "", "asia-east1")
        self.assertTrue(all(i.ok for i in items))
        items = cc.eval_database(200, {"locationId": "us-central1", "type": "DATASTORE_MODE"}, "", "asia-east1")
        self.assertFalse(items[1].ok)
        self.assertEqual(len(items[1].hints), 2)
        items = cc.eval_database(403, None, "denied", "asia-east1")
        self.assertFalse(items[0].ok)
        self.assertIsNone(items[1].ok)

    def test_database_edition(self):
        base = {"locationId": "asia-east1", "type": "FIRESTORE_NATIVE"}
        for edition in ("STANDARD", "DATABASE_EDITION_UNSPECIFIED", ""):
            items = cc.eval_database(200, dict(base, databaseEdition=edition), "", "asia-east1")
            self.assertTrue(items[1].ok, edition)
        items = cc.eval_database(200, dict(base, databaseEdition="ENTERPRISE"), "", "asia-east1")
        self.assertFalse(items[1].ok)
        self.assertEqual(items[1].phase, "pre", "Enterprise 要在部署前就擋下來")
        self.assertIn("Standard", " ".join(items[1].hints))
        self.assertIn("Enterprise", items[1].detail)

    def test_webapp(self):
        ok = {"authDomain": "my-class-2026.firebaseapp.com", "apiKey": "k", "appId": "1:2:web:3"}
        self.assertTrue(cc.eval_webapp(200, ok, "", Cfg()).ok)
        self.assertFalse(cc.eval_webapp(200, dict(ok, authDomain="my-class-2026.web.app"), "", Cfg()).ok)
        self.assertFalse(cc.eval_webapp(200, dict(ok, apiKey="other"), "", Cfg()).ok)

    def test_auth(self):
        good = {"signIn": {"email": {"enabled": True, "passwordRequired": False}},
                "authorizedDomains": ["localhost", "my-class-2026.firebaseapp.com"]}
        self.assertTrue(cc.eval_auth(200, good, "", 200, {"enabled": True}, "", "my-class-2026").ok)
        self.assertFalse(cc.eval_auth(200, good, "", 404, None, "", "my-class-2026").ok)
        pw = {"signIn": {"email": {"enabled": True, "passwordRequired": True}}, "authorizedDomains": good["authorizedDomains"]}
        self.assertFalse(cc.eval_auth(200, pw, "", 200, {"enabled": True}, "", "my-class-2026").ok)
        nod = dict(good, authorizedDomains=["localhost"])
        self.assertFalse(cc.eval_auth(200, nod, "", 200, {"enabled": True}, "", "my-class-2026").ok)
        # 電子郵件連結是選用：整個沒開（老師決定只用 Google）不算失敗，detail 要註明
        noemail = {"signIn": {"email": {"enabled": False}}, "authorizedDomains": good["authorizedDomains"]}
        item = cc.eval_auth(200, noemail, "", 200, {"enabled": True}, "", "my-class-2026")
        self.assertTrue(item.ok)
        self.assertIn("選用", item.detail)

    def test_index_status(self):
        st = cc.index_status(LOCAL, remote("READY"), [])
        self.assertEqual((st["missing"], st["building"], st["bad"]), ([], [], []))
        self.assertTrue(cc.index_status(LOCAL, [], [])["missing"])
        self.assertTrue(cc.index_status(LOCAL, remote("CREATING"), [])["building"])
        self.assertTrue(cc.index_status(LOCAL, remote("NEEDS_REPAIR"), [])["bad"])
        extra = remote("READY") + [{"name": "projects/p/databases/(default)/collectionGroups/x/indexes/y",
                                    "queryScope": "COLLECTION", "fields": [{"fieldPath": "a", "order": "ASCENDING"},
                                                                           {"fieldPath": "b", "order": "ASCENDING"}],
                                    "state": "READY"}]
        self.assertEqual(len(cc.index_status(LOCAL, extra, [])["extra"]), 1)

    def test_field_overrides(self):
        local = {"indexes": [], "fieldOverrides": [
            {"collectionGroup": "images", "fieldPath": "data", "indexes": []},
            {"collectionGroup": "comments", "fieldPath": "createdAt",
             "indexes": [{"order": "DESCENDING", "queryScope": "COLLECTION_GROUP"}]}]}
        fields = [{"name": "projects/p/databases/(default)/collectionGroups/images/fields/data", "indexConfig": {}},
                  {"name": "projects/p/databases/(default)/collectionGroups/comments/fields/createdAt",
                   "indexConfig": {"indexes": [{"order": "DESCENDING", "queryScope": "COLLECTION_GROUP", "state": "READY"}]}}]
        st = cc.index_status(local, [], fields)
        self.assertEqual(st["missing"] + st["building"] + st["bad"], [])
        self.assertTrue(cc.index_status(local, [], fields[:1])["missing"])

    def test_rules_and_billing_and_site(self):
        self.assertTrue(cc.eval_rules("a \nb\r\n", "a\nb").ok)
        self.assertFalse(cc.eval_rules("a", "b").ok)
        self.assertIsNone(cc.eval_rules(None, "b").ok)
        self.assertIsNone(cc.eval_billing(403, None, "no").ok)
        self.assertIn("Spark", cc.eval_billing(200, {"billingEnabled": False}, "").detail)
        good_robots = (200, {"x-robots-tag": "noindex, nofollow"}, "User-agent: *")
        good_cfg = (200, {}, 'projectId: "my-class-2026"')
        self.assertTrue(cc.eval_site(Cfg.site_url, "my-class-2026", good_robots, good_cfg).ok)
        self.assertFalse(cc.eval_site(Cfg.site_url, "my-class-2026", (200, {}, ""), good_cfg).ok)
        self.assertFalse(cc.eval_site(Cfg.site_url, "my-class-2026", good_robots, (200, {}, 'projectId: "x"')).ok)


if __name__ == "__main__":
    unittest.main()
