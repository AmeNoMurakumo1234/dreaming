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

    def _mechanical_config(self):
        os.makedirs(os.path.join(self.home, ".dreaming"), exist_ok=True)
        with open(os.path.join(self.home, ".dreaming", "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"engines": ["mechanical"]}, fh)

    def test_hook_scripts_exit_zero_on_garbage_stdin_and_create_no_store(self):
        self._mechanical_config()
        for script in SCRIPTS:
            for stdin in ("", "{not json", json.dumps({"session_id": "s"}), "[1,2,3]"):
                done = self._run(script, stdin)
                self.assertEqual(done.returncode, 0, (script, stdin, done.stdout, done.stderr))
        # Review finding: the old assertion looked for stores/default/dreams, which no code path
        # creates on garbage; the store DIRECTORY was being created by every hook call.
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "stores")), os.listdir(self.tmp))

    def test_hook_reads_utf8_stdin_whatever_the_locale_codec_is(self):
        # Review finding (Critical): on Windows a piped stdin decodes as cp1252, so a non-ASCII
        # path in the hook JSON was mangled or dropped - and with it the cwd that finds the
        # project's enabled:false. The child runs with the UTF-8 env overrides removed.
        self._mechanical_config()
        project = os.path.join(self.tmp, "Müller-中文")
        os.makedirs(os.path.join(project, ".git"))
        transcript = os.path.join(project, "s.jsonl")
        with open(transcript, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user", "uuid": "u-01", "timestamp": "t",
                                 "message": {"role": "user", "content": "hello from a non-ascii path"}}) + "\n")
        hook = json.dumps({"session_id": "sess-utf8", "transcript_path": transcript, "cwd": project,
                           "scratchpad_dir": os.path.join(self.tmp, "scratch")}, ensure_ascii=False)
        env = dict(os.environ, DREAMING_STORE_ROOT=os.path.join(self.tmp, "stores"), HOME=self.home,
                   USERPROFILE=self.home, DREAMING_AGENT="Joule")
        for name in ("PYTHONIOENCODING", "PYTHONUTF8", "DREAMING_DISABLED"):
            env.pop(name, None)
        done = subprocess.run([sys.executable, os.path.join(HOOKS, "precompact_sleep.py")], input=hook.encode("utf-8"),
                              capture_output=True, timeout=120, env=env, cwd=self.tmp, creationflags=_NO_WINDOW)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = done.stdout.decode("utf-8", "replace")
        self.assertNotIn("sleep failed", out)
        store = os.path.join(self.tmp, "stores", "Joule", "dreams")
        self.assertTrue(os.path.isdir(store), out)
        self.assertEqual(len(os.listdir(store)), 1)
        # and enabled:false in that same non-ASCII project is honoured
        with open(os.path.join(project, ".dreaming.json"), "w", encoding="utf-8") as fh:
            json.dump({"enabled": False}, fh)
        done = subprocess.run([sys.executable, os.path.join(HOOKS, "precompact_sleep.py")], input=hook.encode("utf-8"),
                              capture_output=True, timeout=120, env=env, cwd=self.tmp, creationflags=_NO_WINDOW)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout.decode("utf-8", "replace").strip(), "")
        self.assertEqual(len(os.listdir(store)), 1)

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
