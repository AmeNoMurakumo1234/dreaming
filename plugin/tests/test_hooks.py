#!/usr/bin/env python3
"""Each hook script is a subprocess that must exit 0 on empty, garbage and valid-but-useless stdin,
must write nothing under any store when the input is garbage, and must be silent when disabled."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.abspath(os.path.join(HERE, "..", "hooks"))
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
SCRIPTS = ("precompact_sleep.py", "sessionstart_reseed.py", "sessionstart_notice.py")


class HookScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dreaming-hooks-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, script, stdin, extra_env=None):
        env = dict(os.environ, DREAMING_STORE_ROOT=os.path.join(self.tmp, "stores"), HOME=self.home,
                   USERPROFILE=self.home, CLAUDE_PLUGIN_ROOT=os.path.abspath(os.path.join(HERE, "..")))
        env.pop("DREAMING_DISABLED", None)
        env.pop("DREAMING_AGENT", None)
        env.update(extra_env or {})
        return subprocess.run([sys.executable, os.path.join(HOOKS, script)], input=stdin, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120, env=env,
                              cwd=self.tmp, creationflags=_NO_WINDOW)

    def test_hook_scripts_exit_zero_on_garbage_stdin(self):
        for script in SCRIPTS:
            for stdin in ("", "{not json", json.dumps({"session_id": "s"}), "[1,2,3]"):
                done = self._run(script, stdin)
                self.assertEqual(done.returncode, 0, (script, stdin, done.stdout, done.stderr))
                self.assertEqual(done.stderr.strip(), "", (script, stdin, done.stderr))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "stores", "default", "dreams")))

    def test_disabled_env_makes_every_hook_silent(self):
        for script in SCRIPTS:
            done = self._run(script, "{}", {"DREAMING_DISABLED": "1"})
            self.assertEqual(done.returncode, 0)
            self.assertEqual(done.stdout.strip(), "", (script, done.stdout))

    def test_hooks_json_wires_the_three_events(self):
        with open(os.path.join(HOOKS, "hooks.json"), "r", encoding="utf-8") as fh:
            spec = json.load(fh)["hooks"]
        self.assertIn("PreCompact", spec)
        self.assertEqual(spec["PreCompact"][0]["hooks"][0]["timeout"], 3600)
        matchers = [entry.get("matcher") for entry in spec["SessionStart"]]
        self.assertIn("compact", matchers)
        self.assertTrue(any("startup" in (m or "") for m in matchers))
        for event in spec.values():
            for entry in event:
                for h in entry["hooks"]:
                    self.assertIn("${CLAUDE_PLUGIN_ROOT}", h["command"])
                    self.assertTrue(os.path.isfile(os.path.join(HOOKS, os.path.basename(h["command"].split("/")[-1].strip('"')))),
                                    h["command"])


if __name__ == "__main__":
    unittest.main()
