#!/usr/bin/env python3
"""The stdlib OpenAI-compatible client and the four JSON helpers the distiller depends on."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)

from dreaming import client  # noqa: E402

OC = {"base_url": "http://127.0.0.1:8081", "api_key_file": "", "api_key_env": "DREAMING_API_KEY",
      "model": "local", "timeout": 5}


class _Resp(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8"))
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def _urlopen_factory(handler):
    def urlopen(req, timeout=None):
        return handler(req)
    return urlopen


class ChatTests(unittest.TestCase):
    def test_chat_sends_openai_shape_with_bearer_and_clamps_max_tokens(self):
        seen = {}

        def handler(req):
            seen["url"] = req.full_url
            seen["auth"] = req.get_header("Authorization")
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return _Resp({"choices": [{"message": {"content": "hello \u2014 world"}, "finish_reason": "stop"}]})

        out = client.chat(dict(OC), "sys", "usr", max_tokens=9000, urlopen=_urlopen_factory(handler),
                          env={"DREAMING_API_KEY": "k1"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["text"], "hello - world")          # to_ascii applied
        self.assertTrue(seen["url"].endswith("/v1/chat/completions"))
        self.assertEqual(seen["auth"], "Bearer k1")
        self.assertEqual(seen["body"]["max_tokens"], 4096)
        self.assertEqual([m["role"] for m in seen["body"]["messages"]], ["system", "user"])
        self.assertEqual(seen["body"]["model"], "local")

    def test_chat_reports_transport_and_http_errors_without_raising(self):
        def boom(req):
            raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, io.BytesIO(b"{}"))

        out = client.chat(dict(OC), "s", "u", urlopen=_urlopen_factory(boom), env={})
        self.assertFalse(out["ok"])
        self.assertIn("401", out["error"])
        out = client.chat(dict(OC), "s", "u", urlopen=_urlopen_factory(lambda r: _Resp({"choices": []})), env={})
        self.assertFalse(out["ok"])

    def test_api_key_from_file_wins_over_env(self):
        tmp = tempfile.mkdtemp(prefix="dreaming-key-")
        try:
            path = os.path.join(tmp, "key")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("filekey\n")
            self.assertEqual(client.read_api_key(dict(OC, api_key_file=path), env={"DREAMING_API_KEY": "envkey"}), "filekey")
            self.assertEqual(client.read_api_key(dict(OC), env={"DREAMING_API_KEY": "envkey"}), "envkey")
            self.assertEqual(client.read_api_key(dict(OC), env={}), "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_available_requires_an_authenticated_completion(self):
        # CONTROL: health up + completion ok -> True; health up + 401 -> False; health down -> False.
        def ok(req):
            if req.full_url.endswith("/health"):
                return _Resp({"status": "ok"})
            return _Resp({"choices": [{"message": {"content": "x"}}]})

        def unauthorized(req):
            if req.full_url.endswith("/health"):
                return _Resp({"status": "ok"})
            raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, io.BytesIO(b"{}"))

        def down(req):
            raise OSError("refused")

        self.assertTrue(client.available(dict(OC), urlopen=_urlopen_factory(ok), env={}))
        self.assertFalse(client.available(dict(OC), urlopen=_urlopen_factory(unauthorized), env={}))
        self.assertFalse(client.available(dict(OC), urlopen=_urlopen_factory(down), env={}))

    def test_available_falls_through_a_missing_health_endpoint(self):
        # Review finding: Ollama serves no /health (404). An HTTP answer of any kind proves the
        # server is up; only a transport failure short-circuits. The completion probe decides.
        def no_health(req):
            if req.full_url.endswith("/health"):
                raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, io.BytesIO(b""))
            return _Resp({"choices": [{"message": {"content": "OK"}}]})

        self.assertTrue(client.available(dict(OC), urlopen=_urlopen_factory(no_health), env={}))


class HelperTests(unittest.TestCase):
    GOOD = json.dumps({"state": {"a": 1}, "lessons": [{"title": "t1"}, {"title": "t2"}], "tensions": []})

    def test_extract_json_handles_clean_fenced_and_trailing_prose(self):
        self.assertEqual(client.extract_json(self.GOOD)["state"], {"a": 1})
        self.assertEqual(client.extract_json("```json\n" + self.GOOD + "\n```")["state"], {"a": 1})
        self.assertEqual(client.extract_json("Here you go:\n" + self.GOOD + "\nHope that helps")["state"], {"a": 1})
        self.assertIsNone(client.extract_json("no json here"))
        self.assertIsNone(client.extract_json(self.GOOD[:-10]))      # unbalanced -> None, never a guess
        self.assertEqual(client.extract_json("[1,2]", "array"), [1, 2])

    def test_salvage_json_list_returns_the_complete_prefix_only(self):
        cut = self.GOOD[: self.GOOD.rfind('"t2"') + 2]                 # inside the second item
        items = client.salvage_json_list(cut, "lessons")
        self.assertEqual(items, [{"title": "t1"}])
        self.assertEqual(client.salvage_json_list(cut, "missing"), [])
        self.assertEqual(client.salvage_json_list("prose", "lessons"), [])

    def test_looks_truncated_json_tells_cut_from_malformed(self):
        self.assertTrue(client.looks_truncated_json(self.GOOD[:-5]))
        self.assertFalse(client.looks_truncated_json(self.GOOD))
        self.assertFalse(client.looks_truncated_json("pure prose"))

    def test_to_ascii_folds_the_seven_prose_characters_and_never_raises(self):
        text = "a \u2014 b \u2013 c \u2018q\u2019 \u201cd\u201d \u2026 \u00e9"
        out = client.to_ascii(text)
        self.assertTrue(all(ord(c) < 128 for c in out), out)
        self.assertIn("a - b - c 'q' \"d\" ...", out)


if __name__ == "__main__":
    unittest.main()
