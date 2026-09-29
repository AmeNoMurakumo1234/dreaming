#!/usr/bin/env python3
"""0.5.4: the claude engine's instructions must reach the model, and a reply in the wrong shape
must be named in the log, never blamed on the model as "returned no lessons".

Field report 2026-09-29 (a routine on Windows, plugin 0.5.2): `claude` resolves to the npm
`claude.CMD` shim, so the call runs through cmd.exe, which ENDS the command line at its first
newline. The multi-line --system-prompt arrived as its first line only. Measured on the reporter's
machine and again on the maintainer's: a two-line system prompt whose instruction is on line 2 is
ignored; the same instruction on one line is obeyed. The model then answered in shapes of its own,
the parser dropped every lesson, and the log said the chunk "returned no lessons and no state".
45 lessons written, 0 kept.

The replies below COPY THE SHAPES of that report's seven map replies (lessons as strings, lessons
keyed lesson/evidence, state as a list). Their text is synthetic: this plugin is public, and the
real replies carry a user's paths and work.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
for p in (PLUGIN, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from dreaming import distill as sd, engines as se, sleep as sl  # noqa: E402
from dreaming.engines import EngineResult  # noqa: E402
from test_distill import INDEX_TEXT, REDUCE_JSON  # noqa: E402
from test_extract import write_fixture  # noqa: E402
from test_sleep import _fake_project  # noqa: E402


class _Done:
    def __init__(self, stdout):
        self.stdout, self.stderr, self.returncode = stdout, "", 0


def _cmd_exe_model(cmd, **kw):
    """A stand-in for `claude.CMD` + a model that obeys what it RECEIVES: cmd.exe cuts every
    argument at its first newline, then the 'model' answers the codeword if the codeword reached
    it, else a polite OK. That is exactly the behaviour measured on 2026-09-29."""
    received = " ".join(a.split("\n")[0] for a in cmd) + " " + (kw.get("input") or "")
    words = [w.strip(".") for w in received.split()]
    reply = "PINEAPPLE" if "PINEAPPLE" in words and "codeword" in received else "OK."
    return _Done(json.dumps({"is_error": False, "result": reply,
                             "modelUsage": {"claude-test-model-1": {"inputTokens": 1}}}))


WRONG_SHAPES = {
    "lessons as strings, state as a list": {
        "state": ["was fixing the parser", "tests green"],
        "tensions": [],
        "lessons": ["A count is not a measurement", "Read the envelope before the text", "Name the drop"]},
    "lessons keyed lesson/evidence": {
        "state": {"current_task": "shipping a fix", "exact_state": "tests written", "next_step": "run them",
                  "uncommitted_decisions": [], "files_in_context": []},
        "tensions": [],
        "lessons": [{"lesson": "Cut at the first newline", "evidence": "two probes"},
                    {"lesson": "Stdin carries what argv cannot", "evidence": "one probe", "why": "shim"}]},
}


class InstructionsArriveTests(unittest.TestCase):
    def test_no_command_line_argument_ever_carries_a_newline(self):
        seen = {}

        def run(cmd, **kw):
            seen["cmd"] = cmd
            return _Done(json.dumps({"is_error": False, "result": "ok"}))

        se.claude_complete({"model": "haiku"}, "line one\nline two\r\nline three", "user text", run=run)
        bad = [a for a in seen["cmd"] if "\n" in a or "\r" in a]
        self.assertEqual(bad, [], "cmd.exe ends a command line at its first newline")

    def test_every_line_of_the_instructions_reaches_stdin_ahead_of_the_payload(self):
        seen = {}

        def run(cmd, **kw):
            seen["input"] = kw.get("input") or ""
            return _Done(json.dumps({"is_error": False, "result": "ok"}))

        system = "FIRST instruction line\nSECOND instruction line\nTHIRD instruction line"
        se.claude_complete({"model": "haiku"}, system, "THE PAYLOAD", run=run)
        stdin = seen["input"]
        for line in system.split("\n"):
            self.assertIn(line, stdin)
        self.assertLess(stdin.index("THIRD instruction line"), stdin.index("THE PAYLOAD"))

    def test_a_real_map_prompt_survives_the_cmd_exe_cut(self):
        """The schema line of MAP_SYSTEM is not on its first line, so it only arrives if the
        instructions travel off the command line."""
        seen = {}

        def run(cmd, **kw):
            received = " ".join(a.split("\n")[0] for a in cmd) + (kw.get("input") or "")
            seen["received"] = received
            return _Done(json.dumps({"is_error": False, "result": "{}"}))

        se.claude_complete({"model": "haiku"}, sd.MAP_SYSTEM, "slice", run=run)
        self.assertIn("Return ONLY a JSON object with exactly these keys", seen["received"])

    def test_the_smoke_test_fails_when_the_instructions_do_not_arrive(self):
        """CONTROL: a model that never sees the system text answers a polite OK. Before 0.5.4 the
        smoke asserted exactly OK, so it passed on a login alone and proved nothing else."""
        deaf = lambda cmd, **kw: _Done(json.dumps({"is_error": False, "result": "OK"}))
        self.assertFalse(se.claude_smoke({}, run=deaf))

    def test_the_smoke_test_passes_through_the_cmd_exe_cut_once_instructions_ride_stdin(self):
        self.assertTrue(se.claude_smoke({}, run=_cmd_exe_model))

    def test_the_answering_model_is_read_from_the_envelope(self):
        r = se.claude_complete({"model": "opus"}, "s", "u", run=_cmd_exe_model)
        self.assertEqual(r.model, "claude-test-model-1")
        r = se.claude_complete({"model": "opus"}, "s", "u",
                               run=lambda cmd, **kw: _Done(json.dumps({"is_error": False, "result": "x"})))
        self.assertIsNone(r.model)


class DroppedShapesTests(unittest.TestCase):
    def _map(self, reply):
        engine = lambda s, u, *, max_tokens=4000: EngineResult(True, json.dumps(reply), "fake", None)
        return sd.map_chunk(engine, "slice", 1, 1)

    def test_lessons_in_an_unexpected_shape_are_counted_not_silently_lost(self):
        m = self._map(WRONG_SHAPES["lessons as strings, state as a list"])
        self.assertEqual((len(m["lessons"]), m["dropped_lessons"]), (0, 3))
        self.assertTrue(m["state_dropped"])
        m = self._map(WRONG_SHAPES["lessons keyed lesson/evidence"])
        self.assertEqual((len(m["lessons"]), m["dropped_lessons"]), (0, 2))
        self.assertFalse(m["state_dropped"])

    def test_a_well_shaped_reply_drops_nothing(self):
        good = {"state": {"current_task": "t"}, "tensions": [],
                "lessons": [{"title": "A real lesson", "why": "w", "how_to_apply": "h", "provenance": []}]}
        m = self._map(good)
        self.assertEqual((len(m["lessons"]), m["dropped_lessons"], m["state_dropped"]), (1, 0, False))


class SleepLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dreaming-shape-")
        self.project, self.memory = _fake_project(self.tmp)
        self.transcript = write_fixture(os.path.join(self.tmp, "t.jsonl"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sleep(self, map_reply, model=None):
        def engine(system, user, *, max_tokens=4000, timeout=None):
            text = REDUCE_JSON if system is sd.REDUCE_SYSTEM else json.dumps(map_reply)
            return EngineResult(True, text, "fake", None, model)
        return sl.run_sleep(self.transcript, agent="Joule", session_id="sess-0001", out_root=self.memory,
                            engine=engine, engine_name="fake", index_text=INDEX_TEXT)

    def test_a_chunk_whose_every_lesson_is_misshapen_says_so(self):
        out = self._sleep(WRONG_SHAPES["lessons as strings, state as a list"])
        joined = " | ".join(out["degraded"])
        self.assertIn("map chunk 1: 3 lessons in an unexpected shape, all dropped", joined)
        self.assertIn("map chunk 1: state in an unexpected shape (list), dropped", joined)
        self.assertNotIn("returned no lessons", joined)

    def test_the_answering_model_is_written_to_the_sleep_log(self):
        out = self._sleep({"state": {"current_task": "t"}, "tensions": [],
                           "lessons": [{"title": "T", "why": "w", "how_to_apply": "h"}]},
                          model="claude-test-model-1")
        with open(os.path.join(out["folder"], "sleep.log"), encoding="utf-8") as fh:
            self.assertIn("model claude-test-model-1", fh.read())


if __name__ == "__main__":
    unittest.main()
