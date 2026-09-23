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


class EndpointListTests(ConfigTests):
    """`openai_compatible` as a LIST of endpoints (Assay, 2026-09-23). The two knock-ons that bit:
    api_key_file was expanded for a dict only, and a DREAMING_* scalar did setdefault() on a list,
    which raised - and a hook that cannot load its config is a hook that never dreams."""

    def test_api_key_file_is_expanded_for_every_endpoint(self):
        self._write(os.path.join(self.project, ".dreaming.json"),
                    {"openai_compatible": [{"base_url": "http://a:1", "api_key_file": "keys/a"},
                                           {"base_url": "http://b:1", "api_key_file": "~/b.key"}]})
        cfg = config.load(project_dir=self.project, env={}, home=self.home)
        eps = cfg["openai_compatible"]
        self.assertIsInstance(eps, list)
        self.assertEqual(eps[0]["api_key_file"], os.path.join(self.project, "keys", "a"))
        self.assertEqual(eps[1]["api_key_file"], os.path.join(self.home, "b.key"))

    def test_env_scalar_steers_the_first_endpoint_without_raising(self):
        self._write(os.path.join(self.project, ".dreaming.json"),
                    {"openai_compatible": [{"base_url": "http://a:1", "model": "a"}, {"base_url": "http://b:1", "model": "b"}]})
        cfg = config.load(project_dir=self.project, env={"DREAMING_MODEL": "env-model", "DREAMING_BASE_URL": "http://env:9"},
                          home=self.home)
        self.assertEqual(cfg["openai_compatible"][0]["model"], "env-model")
        self.assertEqual(cfg["openai_compatible"][0]["base_url"], "http://env:9")
        self.assertEqual(cfg["openai_compatible"][1]["model"], "b")
        self.assertIn("env", cfg["_sources"])

    def test_env_scalar_declines_an_empty_list_without_raising(self):
        self._write(os.path.join(self.project, ".dreaming.json"), {"openai_compatible": []})
        cfg = config.load(project_dir=self.project, env={"DREAMING_MODEL": "env-model"}, home=self.home)
        self.assertEqual(cfg["openai_compatible"], [])

    def test_a_single_dict_endpoint_is_untouched(self):
        self._write(os.path.join(self.project, ".dreaming.json"),
                    {"openai_compatible": {"base_url": "http://x:1", "api_key_file": "k"}})
        cfg = config.load(project_dir=self.project, env={"DREAMING_MODEL": "m"}, home=self.home)
        self.assertIsInstance(cfg["openai_compatible"], dict)
        self.assertEqual(cfg["openai_compatible"]["api_key_file"], os.path.join(self.project, "k"))
        self.assertEqual(cfg["openai_compatible"]["model"], "m")


if __name__ == "__main__":
    unittest.main()
