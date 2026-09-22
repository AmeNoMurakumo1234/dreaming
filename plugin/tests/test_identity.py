#!/usr/bin/env python3
"""Who is dreaming and where: env, transcript agent-name, git, default; mapped vs default stores."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from dreaming import config, identity  # noqa: E402
from test_extract import write_fixture  # noqa: E402


class _Done:
    def __init__(self, stdout):
        self.stdout = stdout
        self.returncode = 0


def _git(name):
    return lambda *a, **k: _Done(name + "\n")


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dreaming-id-")
        self.home = os.path.join(self.tmp, "home")
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(self.home)
        os.makedirs(os.path.join(self.project, ".git"))
        self.transcript = write_fixture(os.path.join(self.tmp, "t.jsonl"))   # carries agent-name Joule

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cfg(self, project_json=None, env=None):
        if project_json is not None:
            with open(os.path.join(self.project, ".dreaming.json"), "w", encoding="utf-8") as fh:
                json.dump(project_json, fh)
        return config.load(project_dir=self.project, env=env or {}, home=self.home)

    def test_order_env_then_transcript_then_git_then_default(self):
        cfg = self._cfg()
        self.assertEqual(identity.agent_name(cfg, self.project, self.transcript, {"DREAMING_AGENT": "Env"}, _git("Git")), ("Env", "env"))
        self.assertEqual(identity.agent_name(cfg, self.project, self.transcript, {}, _git("Git")), ("Joule", "transcript"))
        self.assertEqual(identity.agent_name(cfg, self.project, None, {}, _git("Git")), ("Git", "git"))
        self.assertEqual(identity.agent_name(cfg, self.project, None, {}, _git("")), ("default", "default"))

    def test_configured_agent_is_its_own_step_after_env(self):
        cfg = self._cfg({"agent": "Configured"})
        self.assertEqual(identity.agent_name(cfg, self.project, None, {}, _git("Git")), ("Configured", "config"))
        self.assertEqual(identity.agent_name(cfg, self.project, None, {"DREAMING_AGENT": "Env"}, _git("Git"))[0], "Env")
        # Review finding: a reordered identity_order without "env" used to discard the configured
        # agent silently. It is now the explicit "config" step, present in the default order.
        self.assertEqual(config.DEFAULTS["identity_order"], ["env", "config", "transcript", "git", "default"])
        cfg = self._cfg({"agent": "Configured", "identity_order": ["config", "git", "default"]})
        self.assertEqual(identity.agent_name(cfg, self.project, None, {"DREAMING_AGENT": "Env"}, _git("Git"))[0], "Configured")

    def test_unsafe_agent_names_fall_back_to_default_with_a_reason(self):
        # Review finding: the name is a path component taken from data (transcript, git config).
        cfg = self._cfg()
        for bad in ("..", "a/b", "a\\b", "con:trol", "star*", "x" * 200):
            name, source = identity.agent_name(cfg, self.project, None, {"DREAMING_AGENT": bad}, _git(""))
            self.assertEqual(name, "default", bad)
            self.assertIn("invalid", source, bad)
        for blank in ("", "  "):   # absent, not invalid: the next source is consulted
            self.assertEqual(identity.agent_name(cfg, self.project, None, {"DREAMING_AGENT": blank}, _git("Git")), ("Git", "git"))
        name, source = identity.agent_name(cfg, self.project, None, {"DREAMING_AGENT": "Ame No Murakumo"}, _git(""))
        self.assertEqual((name, source), ("Ame No Murakumo", "env"))

    def test_resolve_never_creates_a_store_and_ensure_store_does(self):
        cfg = self._cfg({"store_root": "stores"})
        res = identity.resolve(cfg, self.project, transcript=self.transcript, env={}, run=_git(""))
        self.assertFalse(res.scratch)
        self.assertFalse(os.path.exists(res.store))
        identity.ensure_store(res)
        self.assertTrue(os.path.isdir(res.store))

    def test_default_store_is_created_under_store_root(self):
        cfg = self._cfg({"store_root": "stores"})
        res = identity.resolve(cfg, self.project, transcript=self.transcript, env={}, run=_git(""))
        self.assertFalse(res.scratch)
        self.assertEqual(res.store, os.path.normpath(os.path.join(self.project, "stores", "Joule")))

    def test_unmapped_agent_goes_to_scratch_when_a_map_exists(self):
        os.makedirs(os.path.join(self.project, "team", "worker", "memory"))
        cfg = self._cfg({"agents": {"Joule": "team/worker/memory"}})
        res = identity.resolve(cfg, self.project, transcript=None, env={"DREAMING_AGENT": "Stranger"}, run=_git(""),
                               hook={"scratchpad_dir": os.path.join(self.tmp, "scratch")})
        self.assertTrue(res.scratch)
        self.assertTrue(res.store.startswith(os.path.join(self.tmp, "scratch")))
        self.assertIn("not in the agents map", res.reason)
        self.assertFalse(os.path.exists(os.path.join(self.project, "stores")))

    def test_mapped_store_missing_is_not_created(self):
        cfg = self._cfg({"agents": {"Joule": "team/worker/memory"}})
        res = identity.resolve(cfg, self.project, transcript=self.transcript, env={}, run=_git(""),
                               hook={"scratchpad_dir": os.path.join(self.tmp, "scratch")})
        self.assertTrue(res.scratch)
        self.assertIn("missing", res.reason)
        self.assertFalse(os.path.exists(os.path.join(self.project, "team", "worker", "memory")))

    def test_mapped_store_present_is_used(self):
        store = os.path.join(self.project, "team", "worker", "memory")
        os.makedirs(store)
        cfg = self._cfg({"agents": {"Joule": "team/worker/memory"}})
        res = identity.resolve(cfg, self.project, transcript=self.transcript, env={}, run=_git(""))
        self.assertFalse(res.scratch)
        self.assertEqual(os.path.normcase(res.store), os.path.normcase(store))

    def test_index_text_reads_bounded_lines_or_empty(self):
        store = os.path.join(self.tmp, "store")
        os.makedirs(store)
        cfg = self._cfg()
        self.assertEqual(identity.index_text(store, cfg), "")
        with open(os.path.join(store, "MEMORY.md"), "w", encoding="utf-8") as fh:
            fh.write("# index\n\n- [a-slug](a-slug.md) - " + "x" * 500 + "\n- [b-slug](b-slug.md) - short\n")
        text = identity.index_text(store, cfg)
        lines = text.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(len(l) <= 118 for l in lines))
        self.assertIn("b-slug", text)

    def test_scratch_root_prefers_hook_scratchpad(self):
        root = identity.scratch_root({"scratchpad_dir": os.path.join(self.tmp, "sp")})
        self.assertTrue(root.startswith(os.path.join(self.tmp, "sp")))
        self.assertTrue(os.path.isdir(root))
        self.assertTrue(identity.scratch_root({}).endswith("dreaming"))


if __name__ == "__main__":
    unittest.main()
