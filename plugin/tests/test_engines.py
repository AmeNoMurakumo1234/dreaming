#!/usr/bin/env python3
"""The engine ladder: claude -p adapter shape, exact-OK smoke, fall-through to mechanical."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)

from dreaming import engines as se  # noqa: E402

CFG = {"engines": ["openai_compatible", "claude", "mechanical"], "claude": {"model": "haiku"},
       "openai_compatible": {"base_url": "http://127.0.0.1:1", "model": "local", "timeout": 1}}


class _FakeCompleted:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


class EngineTests(unittest.TestCase):
    def test_claude_complete_parses_result_and_records_spawn_flags(self):
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            seen["kw"] = kw
            return _FakeCompleted(json.dumps({"is_error": False, "result": "hello"}))

        r = se.claude_complete({"model": "haiku"}, "sys", "usr", run=fake_run)
        self.assertTrue(r.ok)
        self.assertEqual(r.text, "hello")
        self.assertEqual(r.engine, "claude")
        self.assertIn("--safe-mode", seen["cmd"])
        self.assertNotIn("--bare", seen["cmd"])
        self.assertEqual(seen["kw"].get("creationflags"), se._NO_WINDOW)

    def test_claude_complete_sends_the_prompt_on_stdin_never_in_argv(self):
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            seen["kw"] = kw
            return _FakeCompleted(json.dumps({"is_error": False, "result": "ok"}))

        big = "x" * 60_000
        se.claude_complete({"model": "haiku"}, "sys", big, run=fake_run)
        self.assertEqual(seen["kw"].get("input"), big)
        self.assertNotIn(big, seen["cmd"])
        self.assertLess(max(len(a) for a in seen["cmd"]), 4096)

    def test_claude_complete_reports_is_error_and_bad_json(self):
        r = se.claude_complete({}, "s", "u", run=lambda *a, **k: _FakeCompleted(
            json.dumps({"is_error": True, "result": "Not logged in"})))
        self.assertFalse(r.ok)
        self.assertIn("Not logged in", r.error)
        r = se.claude_complete({}, "s", "u", run=lambda *a, **k: _FakeCompleted("not json at all"))
        self.assertFalse(r.ok)

    def test_claude_smoke_requires_exact_ok(self):
        # CONTROL first: a plausible-but-wrong reply must NOT pass (a nested run answering a hook).
        wrong = lambda *a, **k: _FakeCompleted(json.dumps({"is_error": False, "result": "Nothing to plant."}))
        self.assertFalse(se.claude_smoke({}, run=wrong))
        right = lambda *a, **k: _FakeCompleted(json.dumps({"is_error": False, "result": "OK"}))
        self.assertTrue(se.claude_smoke({}, run=right))

    def test_nested_claude_runs_in_safe_mode_not_a_machine_specific_plugin_list(self):
        # Measured 2026-09-22: `claude -p --safe-mode` keeps the OAuth login and answers exactly OK
        # with the prompt on stdin; it disables plugins, hooks, CLAUDE.md, MCP and skills for the
        # nested run on ANY machine, where a --settings list of plugin names only fit this one.
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return _FakeCompleted(json.dumps({"is_error": False, "result": "OK"}))

        se.claude_complete({"model": "haiku"}, "sys", "usr", run=fake_run)
        self.assertIn("--safe-mode", seen["cmd"])
        self.assertNotIn("--settings", seen["cmd"])
        self.assertNotIn("--bare", seen["cmd"])

    def test_claude_complete_survives_non_dict_json_on_stdout(self):
        r = se.claude_complete({}, "s", "u", run=lambda *a, **k: _FakeCompleted("[1, 2, 3]"))
        self.assertFalse(r.ok)
        self.assertIn("unexpected", r.error)

    def test_engine_callables_accept_a_timeout_and_cap_it_by_config(self):
        seen = {}

        def fake_run(cmd, **kw):
            seen["timeout"] = kw.get("timeout")
            return _FakeCompleted(json.dumps({"is_error": False, "result": "OK"}))

        cfg_claude = {"model": "haiku", "timeout": 900}
        se.claude_complete(cfg_claude, "s", "u", timeout=120, run=fake_run)
        self.assertEqual(seen["timeout"], 120)          # the caller's remaining budget wins when smaller
        se.claude_complete(cfg_claude, "s", "u", timeout=5000, run=fake_run)
        self.assertEqual(seen["timeout"], 900)          # the configured ceiling wins when smaller
        se.claude_complete(cfg_claude, "s", "u", run=fake_run)
        self.assertEqual(seen["timeout"], 900)          # no budget given: the configured value
        fn, name = se.build_engine(dict(CFG, engines=["claude"]), claude_ok=True)
        self.assertIn("timeout", fn.__code__.co_varnames + tuple(fn.__kwdefaults__ or {}))

    def test_build_engine_follows_config_order_and_falls_through_to_mechanical(self):
        fn, name = se.build_engine(CFG, local_ok=False, claude_ok=False)
        self.assertIsNone(fn)
        self.assertEqual(name, "mechanical")
        fn, name = se.build_engine(CFG, local_ok=False, claude_ok=True)
        self.assertEqual(name, "claude")
        self.assertTrue(callable(fn))
        fn, name = se.build_engine(CFG, local_ok=True, claude_ok=False)
        self.assertEqual(name, "openai_compatible")
        fn, name = se.build_engine(dict(CFG, engines=["claude", "openai_compatible"]), local_ok=True, claude_ok=True)
        self.assertEqual(name, "claude")
        fn, name = se.build_engine(dict(CFG, engines=["mechanical"]), local_ok=True, claude_ok=True)
        self.assertEqual(name, "mechanical")


class MultiEndpointTests(unittest.TestCase):
    """Assay, 2026-09-23: two servers running the same gguf differed 47x in speed, and
    `openai_compatible` could name exactly one of them. It may now be a list in preference order."""

    FAST = {"label": "4090", "base_url": "http://fast:1", "model": "local", "timeout": 1}
    SLOW = {"label": "mini", "base_url": "http://slow:1", "model": "local", "timeout": 1}

    def test_both_shapes_normalise_and_keep_preference_order(self):
        one = dict(CFG)
        self.assertEqual(se.endpoints(one), [CFG["openai_compatible"]])
        many = dict(CFG, openai_compatible=[self.FAST, self.SLOW])
        self.assertEqual([e["label"] for e in se.endpoints(many)], ["4090", "mini"])
        self.assertEqual(se.endpoints(dict(CFG, openai_compatible=[])), [])
        self.assertEqual(se.endpoints({}), [])

    def test_endpoint_label_is_the_label_else_the_host_and_port(self):
        self.assertEqual(se.endpoint_label(self.FAST), "4090")
        self.assertEqual(se.endpoint_label({"base_url": "http://192.168.1.111:8602/"}), "192.168.1.111:8602")
        self.assertEqual(se.endpoint_label({}), "openai_compatible")

    def test_a_raising_first_endpoint_falls_through_to_the_second_not_to_claude(self):
        calls = []

        def probe(ep):
            calls.append(ep["label"])
            if ep["label"] == "4090":
                raise OSError("connection refused")
            return True

        cfg = dict(CFG, openai_compatible=[self.FAST, self.SLOW])
        self.assertEqual(se.first_available(cfg, available=probe), self.SLOW)
        fn, name = se.build_engine(cfg, claude_ok=True, available=probe)
        self.assertEqual(name, "openai_compatible[mini]")
        self.assertEqual(calls, ["4090", "mini", "4090", "mini"])

    def test_a_single_endpoint_keeps_the_plain_engine_name(self):
        fn, name = se.build_engine(CFG, local_ok=True, claude_ok=False)
        self.assertEqual(name, "openai_compatible")
        fn, name = se.build_engine(dict(CFG, openai_compatible=[self.FAST]), local_ok=True, claude_ok=False)
        self.assertEqual(name, "openai_compatible")
        fn, name = se.build_engine(dict(CFG, openai_compatible=[self.FAST, self.SLOW]), local_ok=True, claude_ok=False)
        self.assertEqual(name, "openai_compatible[4090]")     # local_ok=True short-circuits the probe: first wins

    def test_the_chosen_endpoint_is_the_one_called(self):
        seen = {}

        def fake_chat(oc, system, user, *, max_tokens=4000, **kw):
            seen["base_url"] = oc["base_url"]
            seen["max_tokens"] = max_tokens
            return {"ok": True, "text": "{}", "error": None, "finish_reason": "stop"}

        cfg = dict(CFG, openai_compatible=[self.FAST, self.SLOW])
        fn, name = se.build_engine(cfg, claude_ok=False, available=lambda ep: ep["label"] == "mini")
        self.assertEqual(name, "openai_compatible[mini]")
        old = se.client.chat
        se.client.chat = fake_chat
        try:
            res = fn("s", "u", max_tokens=1234, timeout=5)
        finally:
            se.client.chat = old
        self.assertTrue(res.ok)
        self.assertEqual(res.engine, "openai_compatible[mini]")
        self.assertEqual(seen["base_url"], "http://slow:1")
        self.assertEqual(seen["max_tokens"], 1234)

    def test_no_endpoint_at_all_still_reaches_claude(self):
        fn, name = se.build_engine(dict(CFG, openai_compatible=[]), claude_ok=True, available=lambda ep: True)
        self.assertEqual(name, "claude")
        self.assertFalse(se.local_available(dict(CFG, openai_compatible=[])))


if __name__ == "__main__":
    unittest.main()
