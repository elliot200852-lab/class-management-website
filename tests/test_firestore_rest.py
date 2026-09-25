#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Firestore REST 客戶端（scripts/lib/firestore_rest.py）與權杖（gauth.py）：不連網，用假的傳輸與假的 gcloud。"""
import sys
import json
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import firestore_rest as fr, gauth  # noqa: E402

FAKE_TOKEN = "ya29.fake-token-for-tests-" + "x" * 20


class FakeTokens(object):
    def __init__(self):
        self.refreshed = 0
        self.notes = []

    def token(self):
        return FAKE_TOKEN + str(self.refreshed)

    def refresh(self):
        self.refreshed += 1
        return self.token()


class FakeTransport(object):
    """依序回應排好的 (狀態, 內容)；記下每個請求。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": dict(headers),
                           "body": json.loads(body.decode("utf-8")) if body else None})
        status, payload = self.responses.pop(0)
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        return status, raw


def client(responses, **kw):
    t = FakeTransport(responses)
    sleeps = []
    c = fr.Client("my-class-2026", tokens=FakeTokens(), transport=t, sleep=sleeps.append, **kw)
    return c, t, sleeps


def err(status, gstatus, message="m", reason=None):
    e = {"code": status, "status": gstatus, "message": message}
    if reason:
        e["details"] = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}]
    return {"error": e}


class TestTypedValues(unittest.TestCase):
    def test_roundtrip(self):
        data = {"s": "文字", "i": 3, "neg": -7, "f": 1.5, "t": True, "n": None, "ts": fr.Timestamp("2026-01-01T00:00:00Z"),
                "arr": [1, "a", {"m": [True]}], "empty": [], "map": {"x": {"y": 1}}, "b": b"\x00\xff"}
        fields, tr = fr.encode_fields(data)
        self.assertEqual(tr, [])
        self.assertEqual(fields["i"], {"integerValue": "3"})
        self.assertEqual(fields["t"], {"booleanValue": True})
        self.assertEqual(fields["ts"], {"timestampValue": "2026-01-01T00:00:00Z"})
        back = fr.decode_fields(json.loads(json.dumps(fields)))
        self.assertEqual(back, data)
        self.assertIsInstance(back["ts"], fr.Timestamp)

    def test_bool_is_not_int(self):
        self.assertEqual(fr.encode_value(False), {"booleanValue": False})

    def test_server_time_top_level_only(self):
        fields, tr = fr.encode_fields({"a": 1, "updatedAt": fr.SERVER_TIME})
        self.assertEqual(tr, ["updatedAt"])
        self.assertNotIn("updatedAt", fields)
        with self.assertRaises(ValueError):
            fr.encode_fields({"m": {"x": fr.SERVER_TIME}})

    def test_nested_array_rejected(self):
        with self.assertRaises(ValueError):
            fr.encode_value([[1, 2]])


class TestRequests(unittest.TestCase):
    def test_every_request_has_user_project_and_bearer(self):
        c, t, _ = client([(200, {"documents": [{"name": "projects/my-class-2026/databases/(default)/documents/allowlist/a%40b",
                                                "fields": {"kind": {"stringValue": "parent"}}}]}),
                          (404, err(404, "NOT_FOUND")),
                          (200, {}),
                          (200, [{"found": {"name": "projects/my-class-2026/databases/(default)/documents/x/y", "fields": {}}}])])
        c.list_docs("allowlist")
        self.assertIsNone(c.get("posts/2026-01-01-a"))
        c.commit([c.set_write("x/y", {"a": 1})])
        c.batch_get(["x/y"])
        self.assertEqual(len(t.calls), 4)
        for call in t.calls:
            self.assertEqual(call["headers"]["x-goog-user-project"], "my-class-2026")
            self.assertTrue(call["headers"]["Authorization"].startswith("Bearer "))
            self.assertTrue(call["url"].startswith("https://firestore.googleapis.com/v1/projects/my-class-2026/"))

    def test_doc_ids_are_encoded(self):
        c, t, _ = client([(404, err(404, "NOT_FOUND"))])
        c.get("allowlist/parent.a+x@example.com")
        self.assertIn("/allowlist/parent.a%2Bx%40example.com", t.calls[0]["url"])

    def test_bad_paths(self):
        c, _, _ = client([])
        for p in ("posts", "posts/", "/posts/a", "posts/../x", "a//b"):
            with self.assertRaises(ValueError):
                c.get(p)

    def test_401_refreshes_token_once(self):
        c, t, _ = client([(401, err(401, "UNAUTHENTICATED")), (200, {"name": "projects/my-class-2026/databases/(default)/documents/a/b"})])
        self.assertIsNotNone(c.get("a/b"))
        self.assertEqual(c.tokens.refreshed, 1)
        self.assertNotEqual(t.calls[0]["headers"]["Authorization"], t.calls[1]["headers"]["Authorization"])

    def test_401_twice_is_error_without_token(self):
        c, _, _ = client([(401, err(401, "UNAUTHENTICATED")), (401, err(401, "UNAUTHENTICATED"))])
        with self.assertRaises(fr.FirestoreError) as cm:
            c.get("a/b")
        text = cm.exception.plain()
        self.assertIn("gcloud auth login", text)
        self.assertNotIn(FAKE_TOKEN, text)

    def test_backoff_on_429_and_503(self):
        c, t, sleeps = client([(429, err(429, "RESOURCE_EXHAUSTED")), (503, err(503, "UNAVAILABLE")), (None, b"URLError"),
                               (200, {"name": "projects/my-class-2026/databases/(default)/documents/a/b"})])
        c.rng.random = lambda: 0.0
        self.assertIsNotNone(c.get("a/b"))
        self.assertEqual(sleeps, [1.0, 2.0, 4.0])

    def test_gives_up_after_five_retries(self):
        c, t, sleeps = client([(503, err(503, "UNAVAILABLE"))] * 6)
        with self.assertRaises(fr.FirestoreError):
            c.get("a/b")
        self.assertEqual(len(sleeps), 5)
        self.assertEqual(len(t.calls), 6)

    def test_plain_errors(self):
        cases = [
            (403, "PERMISSION_DENIED", "SERVICE_DISABLED", "還沒啟用"),
            (403, "PERMISSION_DENIED", "USER_PROJECT_DENIED", "不能使用這個專案"),
            (403, "PERMISSION_DENIED", None, "權限不足"),
            (404, "NOT_FOUND", None, "找不到這個專案"),
            (429, "RESOURCE_EXHAUSTED", None, "額度"),
            (400, "INVALID_ARGUMENT", None, "格式不對"),
        ]
        for status, gs, reason, words in cases:
            c, _, _ = client([(status, err(status, gs, "server says", reason))] * 6)
            c.rng.random = lambda: 0.0
            with self.assertRaises(fr.FirestoreError) as cm:
                c.list_docs("allowlist")
            self.assertIn(words, cm.exception.plain())
            self.assertIn("server says", cm.exception.plain())

    def test_emulator_mode(self):
        t = FakeTransport([(200, {})])
        c = fr.Client("demo-cmw", emulator_host="127.0.0.1:8080", transport=t)
        c.commit([c.set_write("a/b", {"x": 1})])
        self.assertTrue(t.calls[0]["url"].startswith("http://127.0.0.1:8080/v1/projects/demo-cmw/"))
        self.assertEqual(t.calls[0]["headers"]["Authorization"], "Bearer owner")
        self.assertEqual(t.calls[0]["headers"]["x-goog-user-project"], "demo-cmw")

    def test_demo_project_needs_emulator_and_emulator_must_be_local(self):
        with self.assertRaises(ValueError):
            fr.Client("demo-cmw", tokens=FakeTokens())
        with self.assertRaises(ValueError):
            fr.Client("demo-cmw", emulator_host="10.0.0.5:8080")

    def test_emulator_host_from_env(self):
        self.assertEqual(fr.emulator_host_from_env(environ={"FIRESTORE_EMULATOR_HOST": "127.0.0.1:9"}), "127.0.0.1:9")
        self.assertEqual(fr.emulator_host_from_env(environ={"CMW_EMULATOR": "1"}), fr.DEFAULT_EMULATOR_HOST)
        self.assertEqual(fr.emulator_host_from_env(flag=True, environ={}), fr.DEFAULT_EMULATOR_HOST)
        self.assertIsNone(fr.emulator_host_from_env(environ={}))

    def test_set_write_shapes(self):
        c, _, _ = client([])
        w = c.set_write("a/b", {"x": 1, "updatedAt": fr.SERVER_TIME}, must_not_exist=True)
        self.assertEqual(w["updateTransforms"], [{"fieldPath": "updatedAt", "setToServerValue": "REQUEST_TIME"}])
        self.assertEqual(w["currentDocument"], {"exists": False})
        self.assertEqual(w["update"]["name"], "projects/my-class-2026/databases/(default)/documents/a/b")
        w = c.set_write("a/b", {"t": "x", "updatedAt": fr.SERVER_TIME}, mask_fields=["t", "updatedAt"])
        self.assertEqual(w["updateMask"], {"fieldPaths": ["t"]})


class TestSplitWrites(unittest.TestCase):
    def test_images_per_commit_and_order(self):
        c, _, _ = client([])
        writes = [c.set_write("posts/2026-01-01-a/images/%016x" % i, {"data": "A" * 1000}) for i in range(25)]
        writes += [c.set_write("posts/2026-01-01-a", {"t": 1})]
        batches = fr.split_writes(writes)
        self.assertEqual([len(b) for b in batches], [10, 10, 6])
        self.assertEqual([w for b in batches for w in b], writes)

    def test_bytes_and_count_limits(self):
        c, _, _ = client([])
        writes = [c.set_write("x/%d" % i, {"d": "A" * 100}) for i in range(1200)]
        self.assertEqual([len(b) for b in fr.split_writes(writes)], [500, 500, 200])
        big = [c.set_write("x/%d" % i, {"d": "A" * 700000}) for i in range(30)]
        for b in fr.split_writes(big):
            self.assertLessEqual(sum(len(json.dumps(w)) for w in b), fr.MAX_COMMIT_BYTES)
        with self.assertRaises(ValueError):
            fr.split_writes([c.set_write("x/1", {"d": "A" * (10 * 1024 * 1024)})])


class Proc(object):
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


class TestGauth(unittest.TestCase):
    def test_emulator_token(self):
        self.assertEqual(gauth.TokenProvider(emulator=True).token(), "owner")

    def test_missing_gcloud_gives_install_link(self):
        with mock.patch.object(gauth, "find_gcloud", return_value=(None, False)):
            with self.assertRaises(gauth.AuthError) as cm:
                gauth.TokenProvider().token()
        self.assertIn(gauth.INSTALL_URL, cm.exception.plain())

    def test_not_logged_in(self):
        tp = gauth.TokenProvider(runner=lambda argv, t: Proc(1, err="ERROR: You do not currently have an active account selected."),
                                 gcloud_path="/x/gcloud")
        with self.assertRaises(gauth.AuthError) as cm:
            tp.token()
        self.assertIn("gcloud auth login", cm.exception.plain())

    def test_token_cached_and_never_in_messages(self):
        calls = []

        def run(argv, t):
            calls.append(argv)
            return Proc(0, out=FAKE_TOKEN + "\n")
        tp = gauth.TokenProvider(runner=run, gcloud_path="/x/gcloud")
        self.assertEqual(tp.token(), FAKE_TOKEN)
        tp.token()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1:], ["auth", "print-access-token"])
        tp.refresh()
        self.assertEqual(len(calls), 2)

    def test_garbage_output(self):
        tp = gauth.TokenProvider(runner=lambda argv, t: Proc(0, out="not a token"), gcloud_path="/x/gcloud")
        with self.assertRaises(gauth.AuthError):
            tp.token()

    def test_off_path_note(self):
        with mock.patch.object(gauth, "find_gcloud", return_value=("/opt/x/gcloud", False)):
            tp = gauth.TokenProvider(runner=lambda argv, t: Proc(0, out=FAKE_TOKEN))
            tp.token()
        self.assertTrue(any("PATH" in n for n in tp.notes))


if __name__ == "__main__":
    unittest.main()
