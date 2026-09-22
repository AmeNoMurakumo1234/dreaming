#!/usr/bin/env python3
"""Config layering: defaults < ~/.dreaming/config.json < <project>/.dreaming.json < DREAMING_* env."""
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

from dreaming import config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dreaming-cfg-")
        self.home = os.path.join(self.tmp, "home")
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(os.path.join(self.home, ".dreaming"))
        os.makedirs(self.project)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, path, obj):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)

    def test_defaults_alone(self):
        cfg = config.load(project_dir=self.project, env={}, home=self.home)
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["agent"], "auto")
        self.assertEqual(cfg["engines"], ["openai_compatible", "claude", "mechanical"])
        self.assertEqual(cfg["chunk_chars"], 60000)
        self.assertEqual(cfg["_sources"], ["defaults"])

    def test_user_then_project_then_env_each_win(self):
        self._write(os.path.join(self.home, ".dreaming", "config.json"),
                    {"chunk_chars": 1000, "agent": "UserAgent", "openai_compatible": {"model": "user-model"}})
        self._write(os.path.join(self.project, ".dreaming.json"),
                    {"chunk_chars": 2000, "openai_compatible": {"base_url": "http://x:1"}})
        cfg = config.load(project_dir=self.project, env={"DREAMING_AGENT": "EnvAgent", "DREAMING_MODEL": "env-model"},
                          home=self.home)
        self.assertEqual(cfg["chunk_chars"], 2000)
        self.assertEqual(cfg["agent"], "EnvAgent")
        self.assertEqual(cfg["openai_compatible"]["model"], "env-model")
        self.assertEqual(cfg["openai_compatible"]["base_url"], "http://x:1")
        self.assertEqual(cfg["openai_compatible"]["timeout"], 900)      # untouched default survives the merge
        self.assertEqual(cfg["_sources"], ["defaults", "user", "project", "env"])

    def test_disabled_env_and_project_flag(self):
        cfg = config.load(project_dir=self.project, env={"DREAMING_DISABLED": "1"}, home=self.home)
        self.assertFalse(cfg["enabled"])
        self._write(os.path.join(self.project, ".dreaming.json"), {"enabled": False})
        cfg = config.load(project_dir=self.project, env={}, home=self.home)
        self.assertFalse(cfg["enabled"])

    def test_paths_are_expanded_and_project_relative(self):
        self._write(os.path.join(self.project, ".dreaming.json"),
                    {"store_root": "~/.dreaming/stores", "agents": {"Joule": "team/worker/memory"}})
        cfg = config.load(project_dir=self.project, env={}, home=self.home)
        self.assertEqual(cfg["store_root"], os.path.normpath(os.path.join(self.home, ".dreaming", "stores")))
        self.assertEqual(cfg["agents"]["Joule"], os.path.normpath(os.path.join(self.project, "team", "worker", "memory")))
        self.assertTrue(os.path.isabs(cfg["agents"]["Joule"]))

    def test_bad_json_is_skipped_not_fatal(self):
        with open(os.path.join(self.project, ".dreaming.json"), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        cfg = config.load(project_dir=self.project, env={}, home=self.home)
        self.assertTrue(cfg["enabled"])
        self.assertIn("project:invalid", cfg["_sources"])

    def test_project_dir_found_from_git_toplevel(self):
        sub = os.path.join(self.project, "a", "b")
        os.makedirs(sub)
        os.makedirs(os.path.join(self.project, ".git"))
        self._write(os.path.join(self.project, ".dreaming.json"), {"chunk_chars": 4242})
        cfg = config.load(project_dir=sub, env={}, home=self.home)
        self.assertEqual(cfg["chunk_chars"], 4242)
        self.assertEqual(os.path.normcase(cfg["_project_dir"]), os.path.normcase(self.project))


if __name__ == "__main__":
    unittest.main()
