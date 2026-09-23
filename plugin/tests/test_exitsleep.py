#!/usr/bin/env python3
"""Sleep at session end (0.3). SessionEnd hooks are capped at 60 s by Claude Code, so the hook
decides fast and hands the sleep to a DETACHED child that outlives the session."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)

from dreaming import cli, exitsleep  # noqa: E402


def _record(uuid, role, text):
    return json.dumps({"type": role, "uuid": uuid, "timestamp": "2026-09-23T01:00:00Z",
                       "message": {"role": role, "content": text}}) + "\n"


class ExitSleepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dreaming-exit-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, ".dreaming"))
        with open(os.path.join(self.home, ".dreaming", "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"engines": ["mechanical"], "store_root": os.path.join(self.tmp, "stores")}, fh)
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(os.path.join(self.project, ".git"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _transcript(self, name, *records):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(records)
        return path

    def _cfg(self, **over):
        cfg = {"enabled": True, "sessionend": {"enabled": True, "min_chars": 20000}}
        cfg.update(over)
        return cfg

    # decide -------------------------------------------------------------------------------

    def test_decide_skips_when_disabled_or_transcript_missing(self):
        big = self._transcript("big.jsonl", _record("u1", "user", "x" * 30000))
        self.assertEqual(exitsleep.decide(self._cfg(sessionend={"enabled": False}), big, watermark=None)[0], "skip")
        self.assertEqual(exitsleep.decide(self._cfg(enabled=False), big, watermark=None)[0], "skip")
        verdict, why = exitsleep.decide(self._cfg(), os.path.join(self.tmp, "nope.jsonl"), watermark=None)
        self.assertEqual(verdict, "skip")
        self.assertIn("transcript", why)

    def test_decide_skips_a_short_session_and_spawns_a_long_one(self):
        # a `claude -p "Reply OK"` session must not spawn a sleep: nothing to dream
        short = self._transcript("short.jsonl", _record("u1", "user", "Reply OK"), _record("a1", "assistant", "OK"))
        verdict, why = exitsleep.decide(self._cfg(), short, watermark=None)
        self.assertEqual(verdict, "skip")
        self.assertIn("20000", why)
        big = self._transcript("big.jsonl", _record("u1", "user", "x" * 30000))
        verdict, chars = exitsleep.decide(self._cfg(), big, watermark=None)
        self.assertEqual(verdict, "spawn")
        self.assertGreaterEqual(chars, 30000)

    def test_decide_counts_only_what_is_after_the_watermark(self):
        # a session that compacted (and so already dreamed) and then said two more words
        path = self._transcript("wm.jsonl", _record("u1", "user", "x" * 30000), _record("a1", "assistant", "done"),
                                _record("u2", "user", "thanks"))
        self.assertEqual(exitsleep.decide(self._cfg(), path, watermark="a1")[0], "skip")
        self.assertEqual(exitsleep.decide(self._cfg(), path, watermark=None)[0], "spawn")
        self.assertEqual(exitsleep.decide(self._cfg(sessionend={"enabled": True, "min_chars": 3}), path,
                                          watermark="a1")[0], "spawn")

    # child argv and detached spawn ---------------------------------------------------------

    def test_child_argv_is_the_sleep_command_with_the_hook_json_and_no_shell(self):
        hook = {"session_id": "sess-1", "transcript_path": "T.jsonl", "cwd": self.project, "reason": "other"}
        argv = exitsleep.child_argv(hook, self.project)
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1:3], ["-m", "dreaming.cli"])
        self.assertIn("sleep", argv)
        self.assertEqual(argv[argv.index("--project") + 1], self.project)
        passed = json.loads(argv[argv.index("--hook-json") + 1])
        self.assertEqual(passed["transcript_path"], "T.jsonl")
        self.assertEqual(passed["session_id"], "sess-1")

    def test_spawn_detached_uses_breakaway_flags_and_falls_back_when_the_job_refuses(self):
        calls = []

        def fake_popen(argv, **kw):
            calls.append(kw)
            if len(calls) == 1:
                raise OSError(5, "breakaway refused")

            class P:
                pid = 4242
            return P()

        log = os.path.join(self.tmp, "exit.log")
        pid, label = exitsleep.spawn_detached(["x"], log, cwd=self.tmp, popen=fake_popen)
        self.assertEqual((pid, label), (4242, "no-breakaway"))
        self.assertEqual(len(calls), 2)
        if os.name == "nt":
            self.assertTrue(calls[0]["creationflags"] & exitsleep.CREATE_BREAKAWAY_FROM_JOB)
            self.assertFalse(calls[1]["creationflags"] & exitsleep.CREATE_BREAKAWAY_FROM_JOB)
            for kw in calls:
                self.assertTrue(kw["creationflags"] & exitsleep.CREATE_NO_WINDOW)
        for kw in calls:
            self.assertIs(kw["stdin"], subprocess.DEVNULL)
            self.assertTrue(kw["close_fds"])
            self.assertEqual(kw["cwd"], self.tmp)
        self.assertTrue(os.path.isfile(log))          # the child's stdout/stderr land in the log

    def test_spawn_detached_reports_a_total_failure_instead_of_raising(self):
        def always_fails(argv, **kw):
            raise OSError(2, "no python")
        pid, label = exitsleep.spawn_detached(["x"], os.path.join(self.tmp, "l"), cwd=self.tmp, popen=always_fails)
        self.assertIsNone(pid)
        self.assertIn("no python", label)

    # cli ----------------------------------------------------------------------------------

    def _sessionend(self, transcript, capture):
        hook = {"session_id": "sess-cli", "transcript_path": transcript, "cwd": self.project, "reason": "other",
                "scratchpad_dir": os.path.join(self.tmp, "scratch")}
        old = exitsleep.Popen
        exitsleep.Popen = capture
        try:
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli.main(["--home", self.home, "sessionend", "--hook-json", json.dumps(hook)])
        finally:
            exitsleep.Popen = old
        return rc, buf.getvalue()

    def test_cli_sessionend_spawns_for_a_long_session_and_says_so(self):
        seen = {}

        def capture(argv, **kw):
            seen["argv"] = argv

            class P:
                pid = 77
            return P()

        big = self._transcript("big.jsonl", _record("u1", "user", "x" * 30000))
        rc, out = self._sessionend(big, capture)
        self.assertEqual(rc, 0)
        self.assertIn("exit sleep spawned", out)
        self.assertIn("pid 77", out)
        self.assertIn("sleep", seen["argv"])

    def test_cli_sessionend_skips_a_short_session_and_never_spawns(self):
        def never(argv, **kw):
            raise AssertionError("must not spawn")
        short = self._transcript("short.jsonl", _record("u1", "user", "OK"))
        rc, out = self._sessionend(short, never)
        self.assertEqual(rc, 0)
        self.assertIn("exit sleep skipped", out)

    def test_cli_sessionend_is_silent_when_disabled(self):
        with open(os.path.join(self.project, ".dreaming.json"), "w", encoding="utf-8") as fh:
            json.dump({"sessionend": {"enabled": False}}, fh)
        big = self._transcript("big.jsonl", _record("u1", "user", "x" * 30000))
        rc, out = self._sessionend(big, lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not spawn")))
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "")


if __name__ == "__main__":
    unittest.main()
