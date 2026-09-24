#!/usr/bin/env python3
"""The pipeline and the hook-facing CLI, ported from the quantum-concepts sleep step.

The load-bearing legs are the ones that keep sleep HARMLESS rather than the ones that make it
work: it must never write outside dreams/, never touch the index, never exit non-zero from a hook,
and never mistake an engine's wrong answer for a lesson.
"""
import datetime
import io
import itertools
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

NL = chr(10)
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from dreaming import cli, config, distill as sd, extract as sx, identity, sleep as sl  # noqa: E402
from dreaming.engines import EngineResult  # noqa: E402
from test_distill import INDEX_TEXT, MAP_JSON, REDUCE_JSON  # noqa: E402
from test_extract import _read, _rec, write_fixture  # noqa: E402


def _fake_project(tmp):
    """A project with a .dreaming.json mapping Joule -> team/worker/memory, and that store present."""
    project = os.path.join(tmp, "project")
    os.makedirs(os.path.join(project, ".git"))
    with open(os.path.join(project, ".dreaming.json"), "w", encoding="utf-8") as fh:
        json.dump({"agents": {"Joule": "team/worker/memory"}}, fh)
    memory = os.path.join(project, "team", "worker", "memory")
    os.makedirs(memory)
    with open(os.path.join(memory, "MEMORY.md"), "w", encoding="utf-8") as fh:
        fh.write("# index\n  a-count-is-not-discriminating-power  -  A count is not discriminating power\n")
    with open(os.path.join(memory, "a-count-is-not-discriminating-power.md"), "w", encoding="utf-8") as fh:
        fh.write("# A count is not discriminating power\n")
    return project, memory


def _dream_dirs(root):
    """The dream FOLDERS under a dreams/ dir: the per-session watermark file lives beside them."""
    return sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)))


class SleepRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dreaming-run-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.project, self.memory = _fake_project(self.tmp)
        self.transcript = write_fixture(os.path.join(self.tmp, "t.jsonl"))
        self.index_before = _read(os.path.join(self.memory, "MEMORY.md"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _engine(self, map_text=MAP_JSON, reduce_text=REDUCE_JSON):
        def fn(system, user, *, max_tokens=4000, timeout=None):
            return EngineResult(True, reduce_text if system is sd.REDUCE_SYSTEM else map_text, "fake", None)
        return fn

    def _run(self, **kw):
        base = dict(agent="Joule", session_id="sess-0001", out_root=self.memory,
                    engine=self._engine(), engine_name="fake", index_text=INDEX_TEXT)
        base.update(kw)
        return sl.run_sleep(self.transcript, **base)

    def _main(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["--project", self.project, "--home", self.home] + list(argv))
        return rc, buf.getvalue()

    def test_full_run_writes_every_stage_and_never_the_index(self):
        out = self._run()
        folder = out["folder"]
        self.assertTrue(folder.startswith(os.path.join(self.memory, "dreams")))
        for name in ("day.md", "brief.md", "tensions.md", "sleep.log", "reduce.json"):
            self.assertTrue(os.path.isfile(os.path.join(folder, name)), name)
        self.assertTrue(os.path.isfile(os.path.join(folder, "map", "1.json")))
        self.assertEqual(len(os.listdir(os.path.join(folder, "lessons"))), 2)
        self.assertEqual((out["lessons"], out["tensions"], out["degraded"]), (2, 1, []))
        log = _read(os.path.join(folder, "sleep.log"))
        self.assertIn("watermark: as-0000-11", log)
        self.assertIn("engine: fake", log)
        self.assertEqual(_read(os.path.join(self.memory, "MEMORY.md")), self.index_before)
        self.assertEqual(sorted(os.listdir(self.memory)),
                         sorted(["MEMORY.md", "a-count-is-not-discriminating-power.md", "dreams"]))

    def test_second_sleep_uses_watermark(self):
        first = self._run(now=datetime.datetime(2026, 9, 22, 12, 0))
        with open(self.transcript, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(_rec("user", "us-0000-12", message={"role": "user", "content": "a THIRD question"})) + "\n")
        second = self._run(now=datetime.datetime(2026, 9, 22, 13, 0))
        day2 = _read(os.path.join(second["folder"], "day.md"))
        self.assertIn("a THIRD question", day2)
        self.assertNotIn("first question about GPUs", day2)
        self.assertNotEqual(first["folder"], second["folder"])

    def test_watermark_survives_the_promotion_that_deletes_the_folder(self):
        """Promotion deletes the dream folder. The watermark must not go with it, or the next
        sleep re-dreams the whole session (measured 2026-09-23: third sleep logged 'after (start)',
        hit the 400k cap and re-staged lessons already in the index)."""
        first = self._run(now=datetime.datetime(2026, 9, 22, 12, 0))
        shutil.rmtree(first["folder"])
        with open(self.transcript, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(_rec("user", "us-0000-12", message={"role": "user", "content": "a THIRD question"})) + "\n")
        second = self._run(now=datetime.datetime(2026, 9, 22, 13, 0))
        day2 = _read(os.path.join(second["folder"], "day.md"))
        self.assertIn("a THIRD question", day2)
        self.assertNotIn("first question about GPUs", day2)
        self.assertNotIn("after (start)", _read(os.path.join(second["folder"], "sleep.log")))

    def test_a_map_slice_that_returns_nothing_is_named_in_the_log(self):
        """An empty-but-valid map reply is a degraded slice, not a clean one (Haiku returned three
        of them on 2026-09-23 and the log read as a full dream)."""
        empty = json.dumps({"lessons": [], "state": {}, "tensions": []})
        out = self._run(engine=self._engine(map_text=empty))
        self.assertTrue(any("map chunk 1 returned no lessons and no state" in d for d in out["degraded"]), out["degraded"])

    def test_a_state_from_an_older_slice_never_becomes_the_brief(self):
        """The resume state may only come from the NEWEST slice. When that slice yields none, an
        articulate state from an older slice is stale by construction; the mechanical state of the
        last turns is crude but true (the 2026-09-23 brief was eight hours stale this way)."""
        with open(self.transcript, "w", encoding="utf-8") as fh:
            for i in range(20):
                fh.write(json.dumps(_rec("user", "us-0001-%02d" % i, message={"role": "user", "content": "q" * 500})) + "\n")
            fh.write(json.dumps(_rec("user", "us-0001-99", message={"role": "user", "content": "the LAST question, about the watermark"})) + "\n")
        empty = json.dumps({"lessons": [], "state": {}, "tensions": []})
        seen = []

        def fn(system, user, *, max_tokens=4000, timeout=None):
            if system is sd.REDUCE_SYSTEM:
                return EngineResult(True, REDUCE_JSON, "fake", None)
            seen.append(1)
            return EngineResult(True, MAP_JSON if len(seen) == 1 else empty, "fake", None)

        out = self._run(engine=fn, chunk_chars=2000)
        self.assertGreater(len(seen), 1, "the fixture must produce several slices")
        brief = _read(os.path.join(out["folder"], "brief.md"))
        self.assertNotIn("GPU research", brief)
        self.assertIn("the LAST question, about the watermark", brief)
        self.assertTrue(any("newest slice" in d and "mechanical" in d for d in out["degraded"]), out["degraded"])

    def test_mechanical_run_when_no_engine(self):
        out = self._run(engine=None, engine_name="mechanical")
        self.assertIn("no engine", " ".join(out["degraded"]))
        self.assertIn("second question, about the 4090", _read(os.path.join(out["folder"], "brief.md")))
        self.assertEqual(out["lessons"], 0)
        self.assertTrue(os.path.isfile(os.path.join(out["folder"], "day.md")))

    def test_engine_exception_mid_reduce_still_leaves_day_and_log(self):
        def exploding(system, user, *, max_tokens=4000, timeout=None):
            if system is sd.REDUCE_SYSTEM:
                raise RuntimeError("kaboom")
            return EngineResult(True, MAP_JSON, "fake", None)

        out = self._run(engine=exploding)
        for name in ("day.md", "sleep.log", "brief.md"):
            self.assertTrue(os.path.isfile(os.path.join(out["folder"], name)), name)
        self.assertTrue(any("kaboom" in d for d in out["degraded"]))

    def test_empty_reduce_state_falls_back_to_the_last_map_state_not_mechanical(self):
        full = json.loads(REDUCE_JSON)
        empty_state = json.dumps(dict(full, state={}))
        out = self._run(engine=self._engine(reduce_text=empty_state))
        brief = _read(os.path.join(out["folder"], "brief.md"))
        self.assertIn("GPU research", brief)
        self.assertNotIn("mechanical brief", brief)
        self.assertIn("state: copied from slice 1 of 1", _read(os.path.join(out["folder"], "sleep.log")))

    def test_the_brief_state_is_copied_from_the_newest_slice_never_the_reduce(self):
        """Field report 2026-09-23: the reduce re-emitted the SECOND-newest slice's state verbatim
        while map/7 held the right one. The state is a COPY of the newest slice, not a model
        choice, so the rule cannot be broken by a reduce that prefers an older slice."""
        with open(self.transcript, "w", encoding="utf-8") as fh:
            for i in range(20):
                fh.write(json.dumps(_rec("user", "us-0002-%02d" % i, message={"role": "user", "content": "q" * 500})) + NL)
        newest = json.dumps(dict(json.loads(MAP_JSON), state={"current_task": "the newest slice task", "exact_state": "e",
                                                             "next_step": "n", "uncommitted_decisions": [], "files_in_context": []}))
        calls = []

        def fn(system, user, *, max_tokens=4000, timeout=None):
            if system is sd.REDUCE_SYSTEM:
                return EngineResult(True, REDUCE_JSON, "fake", None)
            calls.append(1)
            head = user.split(".")[0].split()          # 'Slice', n, 'of', total
            return EngineResult(True, newest if head[1] == head[3] else MAP_JSON, "fake", None)

        out = self._run(engine=fn, chunk_chars=2000)
        n = len(calls)
        self.assertGreater(n, 1, "fixture must produce several slices")
        brief = _read(os.path.join(out["folder"], "brief.md"))
        self.assertIn("the newest slice task", brief)
        self.assertNotIn("GPU research", brief)
        self.assertIn("state: copied from slice %d of %d" % (n, n), _read(os.path.join(out["folder"], "sleep.log")))

    def test_a_tension_naming_an_entry_not_in_the_index_is_dropped_and_counted(self):
        """Field report 2026-09-23: twelve tensions, every 'existing entry' invented from the
        transcript's own sentences. A tension against an entry the mind does not hold invites it
        to resolve a contradiction it never had."""
        full = json.loads(REDUCE_JSON)
        full["tensions"].append({"claim": "c2", "existing_slug": "made-up-entry", "existing_line": "x",
                                 "side_a": "a", "side_b": "b"})
        out = self._run(engine=self._engine(reduce_text=json.dumps(full)))
        self.assertEqual(out["tensions"], 1)
        self.assertTrue(any("1 tension(s) named entries not in the index; dropped" in d for d in out["degraded"]), out["degraded"])

    def test_without_an_index_no_tension_is_filed(self):
        out = self._run(index_text="")
        self.assertEqual(out["tensions"], 0)
        self.assertTrue(any("no index; tensions not filed" in d for d in out["degraded"]), out["degraded"])

    def test_notice_carries_over_the_newest_brief_on_startup_when_asked(self):
        """A routine is a fresh session every run, so SessionStart(compact) never reaches it.
        With reseed_on_startup the notice injects the store's newest brief once, under a header
        that says whose dream it was, and only while it is younger than reseed_max_age_hours.
        SCHEDULED RUNS ONLY: an interactive session has no task, so there is no key to match a
        brief on, and two interactive sessions of one agent would hand each other their briefs."""
        from test_identity import write_scheduled_fixture
        sched = write_scheduled_fixture(os.path.join(self.tmp, "sched.jsonl"))      # task pm-agent
        first = self._run(task="pm-agent", now=datetime.datetime(2026, 9, 22, 12, 0))
        rc, out = self._main("notice", "--hook-json", json.dumps({"session_id": "run-two", "transcript_path": sched}))
        self.assertNotIn("Carry-over", out, "off by default")
        with open(os.path.join(self.project, ".dreaming.json"), "w", encoding="utf-8") as fh:
            json.dump({"agents": {"Joule": "team/worker/memory", "pm-agent": "team/worker/memory"}, "reseed_on_startup": True}, fh)
        rc, out = self._main("notice", "--hook-json", json.dumps({"session_id": "run-two", "transcript_path": sched}))
        self.assertEqual(rc, 0)
        self.assertIn("Carry-over from your previous run", out)
        self.assertIn("sess-0001", out)
        self.assertIn("GPU research", out)
        rc, out = self._main("notice", "--hook-json", json.dumps({"session_id": "interactive", "transcript_path": self.transcript}))
        self.assertNotIn("Carry-over", out, "an interactive session has no task and never receives a carry-over")
        self.assertIn("awaiting promotion", out)
        old = time.time() - 3 * 86400
        os.utime(first["folder"], (old, old))
        rc, out = self._main("notice", "--hook-json", json.dumps({"session_id": "run-two", "transcript_path": sched}))
        self.assertNotIn("Carry-over", out, "older than reseed_max_age_hours")
        self.assertIn("awaiting promotion", out)

    def test_list_all_enumerates_every_store(self):
        self._run()
        other = os.path.join(self.home, ".dreaming", "stores", "other", "dreams", "20260101-000000-abcdef12", "lessons")
        os.makedirs(other)
        with open(os.path.join(other, "x.md"), "w", encoding="utf-8") as fh:
            fh.write("# x")
        rc, out = self._main("list", "--all")
        self.assertEqual(rc, 0)
        self.assertIn("Joule", out)
        self.assertIn("other", out)
        self.assertIn("1 dream(s)", out)

    def test_carry_over_matches_the_routine_by_task_name(self):
        """Two routines can share one store (a morning and an evening run of the same mind), so
        the carry-over is keyed by the scheduled task, not by the store: a run receives only the
        newest brief written under its own task name."""
        from test_identity import write_scheduled_fixture
        sched = write_scheduled_fixture(os.path.join(self.tmp, "sched.jsonl"))      # task pm-agent
        with open(os.path.join(self.project, ".dreaming.json"), "w", encoding="utf-8") as fh:
            json.dump({"agents": {"pm-agent": "team/worker/memory", "Joule": "team/worker/memory"},
                       "reseed_on_startup": True}, fh)
        self._run(task="qa-tester", now=datetime.datetime(2026, 9, 22, 12, 0))
        rc, out = self._main("notice", "--hook-json", json.dumps({"session_id": "run-two", "transcript_path": sched}))
        self.assertNotIn("Carry-over", out, "another routine's brief must not carry over")
        self._run(task="pm-agent", now=datetime.datetime(2026, 9, 22, 13, 0))
        rc, out = self._main("notice", "--hook-json", json.dumps({"session_id": "run-two", "transcript_path": sched}))
        self.assertIn("Carry-over from your previous run", out)
        self.assertIn("task pm-agent", out)

    def test_known_rules_files_reach_the_reduce_and_restatements_are_counted(self):
        rules = os.path.join(self.tmp, "AGENTS.md")
        with open(rules, "w", encoding="utf-8") as fh:
            fh.write("RULE ONE: read the exit code of the command, not the pipe." + chr(10))
        with open(os.path.join(self.project, ".dreaming.json"), "w", encoding="utf-8") as fh:
            json.dump({"agents": {"Joule": "team/worker/memory"}, "known_rules": [rules]}, fh)
        seen = {}

        def fn(system, user, *, max_tokens=4000, timeout=None):
            if system is sd.REDUCE_SYSTEM:
                seen["user"] = user
                full = json.loads(REDUCE_JSON)
                full["lessons"].append({"title": "Read the exit code", "why": "w", "how_to_apply": "h",
                                        "provenance": [], "relation": "known", "extends": "AGENTS.md"})
                return EngineResult(True, json.dumps(full), "fake", None)
            return EngineResult(True, MAP_JSON, "fake", None)

        cfg = config.load(project_dir=self.project, env={}, home=self.home)
        out = self._run(engine=fn, known_rules=cli.known_rules_text(cfg))
        self.assertIn("RULE ONE", seen["user"])
        self.assertEqual(out["lessons"], 3, "a restatement is kept, not dropped")
        self.assertIn("1 lesson(s) restate known rules", _read(os.path.join(out["folder"], "sleep.log")))

    def test_truncated_reduce_is_named_in_the_log(self):
        full = json.loads(REDUCE_JSON)
        reordered = json.dumps({"state": full["state"], "tensions": [], "lessons": full["lessons"] * 6})
        cut = reordered[: reordered.rfind('"why"') + 8]
        out = self._run(engine=self._engine(reduce_text=cut))
        self.assertTrue(any("truncated" in d for d in out["degraded"]), out["degraded"])
        self.assertIn("GPU research", _read(os.path.join(out["folder"], "brief.md")))

    def test_budget_stops_map_and_still_reduces(self):
        ticks = itertools.chain([0, 0], itertools.repeat(10_000))
        with open(self.transcript, "w", encoding="utf-8") as fh:
            for i in range(40):
                fh.write(json.dumps(_rec("user", "us-0001-%02d" % i, message={"role": "user", "content": "q" * 500})) + "\n")
        out = self._run(budget_seconds=5, clock=lambda: next(ticks), chunk_chars=2000, min_call_seconds=1)
        self.assertTrue(any("budget" in d for d in out["degraded"]))
        self.assertTrue(os.path.isfile(os.path.join(out["folder"], "reduce.json")))
        self.assertEqual(len(os.listdir(os.path.join(out["folder"], "map"))), 1)

    def test_budget_exhausted_before_reduce_skips_it_and_unions_the_maps(self):
        ticks = itertools.chain([0, 0], itertools.repeat(10_000))
        calls = []

        def fn(system, user, *, max_tokens=4000, timeout=None):
            calls.append(system is sd.REDUCE_SYSTEM)
            return EngineResult(True, MAP_JSON, "fake", None)

        out = self._run(engine=fn, budget_seconds=5, clock=lambda: next(ticks), chunk_chars=2000, min_call_seconds=1)
        self.assertFalse(any(calls), "reduce must not run once the budget is gone")
        self.assertTrue(any("budget" in d and "reduce" in d for d in out["degraded"]), out["degraded"])
        self.assertGreaterEqual(out["lessons"], 1)

    def test_engine_calls_get_the_remaining_budget_as_their_timeout(self):
        # Review finding: the map loop checked the budget only between 900 s calls and the reduce
        # had no clock, so the hook could run past its 3600 s ceiling. Each call now gets the
        # remaining budget as its timeout, and the reduce is skipped when too little remains.
        # clock reads: started (0), the one map chunk's check (100), the reduce check (300)
        ticks = itertools.chain([0, 100, 300], itertools.repeat(300))
        seen = []

        def fn(system, user, *, max_tokens=4000, timeout=None):
            seen.append((system is sd.REDUCE_SYSTEM, timeout))
            return EngineResult(True, REDUCE_JSON if system is sd.REDUCE_SYSTEM else MAP_JSON, "fake", None)

        out = self._run(engine=fn, budget_seconds=500, clock=lambda: next(ticks))
        self.assertEqual(seen[0][1], 400)         # map call: 500 - 100 elapsed
        self.assertEqual(seen[-1], (True, 200))   # reduce call: 500 - 300 elapsed
        self.assertEqual(out["degraded"], [])

    def test_reduce_is_skipped_when_less_than_one_minimal_call_remains(self):
        ticks = itertools.chain([0, 0, 480], itertools.repeat(480))
        calls = []

        def fn(system, user, *, max_tokens=4000, timeout=None):
            calls.append(system is sd.REDUCE_SYSTEM)
            return EngineResult(True, MAP_JSON, "fake", None)

        out = self._run(engine=fn, budget_seconds=500, clock=lambda: next(ticks))
        self.assertEqual(calls, [False])
        self.assertTrue(any("reduce" in d and "budget" in d for d in out["degraded"]), out["degraded"])

    def test_dry_run_dream_creates_no_store(self):
        rc, out = self._main("dream", "--dry-run", "--engine", "mechanical", "--transcript", self.transcript)
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(os.path.join(self.memory, "dreams")))
        self.assertIn("dreaming into scratch", out)

    def test_a_brief_exists_before_the_first_engine_call(self):
        def killer(system, user, *, max_tokens=4000, timeout=None):
            raise SystemExit(1)

        with self.assertRaises(SystemExit):
            self._run(engine=killer)
        folder = os.path.join(self.memory, "dreams", _dream_dirs(os.path.join(self.memory, "dreams"))[0])
        self.assertIn("second question, about the 4090", _read(os.path.join(folder, "brief.md")))

    def test_truncated_and_errored_map_chunks_are_named_in_the_log(self):
        cut = MAP_JSON[:-40]
        seen = {"n": 0}

        def fn(system, user, *, max_tokens=4000, timeout=None):
            if system is sd.REDUCE_SYSTEM:
                return EngineResult(True, REDUCE_JSON, "fake", None)
            seen["n"] += 1
            return EngineResult(True, cut, "fake", None) if seen["n"] == 1 else EngineResult(False, "", "fake", "boom")

        out = self._run(engine=fn, chunk_chars=600)
        self.assertTrue(any("map chunk 1 truncated" in d for d in out["degraded"]), out["degraded"])
        self.assertTrue(any("map chunk 2 engine error" in d for d in out["degraded"]), out["degraded"])

    def test_two_sleeps_in_the_same_second_get_distinct_folders_and_the_newest_watermark_wins(self):
        when = datetime.datetime(2026, 9, 22, 12, 0, 0)
        first = self._run(engine=None, engine_name="mechanical", now=when)
        with open(self.transcript, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(_rec("user", "us-0000-12", message={"role": "user", "content": "later"})) + "\n")
        second = self._run(engine=None, engine_name="mechanical", now=when)
        self.assertNotEqual(first["folder"], second["folder"])
        self.assertEqual(sl.last_watermark(self.memory, "sess-0001"), "us-0000-12")

    def test_hook_sleep_writes_to_scratch_when_the_mapped_store_is_missing(self):
        shutil.rmtree(self.memory)
        scratch = os.path.join(self.tmp, "scratch")
        hook = {"session_id": "sess-0001", "transcript_path": self.transcript, "cwd": self.project,
                "scratchpad_dir": scratch, "hook_event_name": "PreCompact"}
        rc, out = self._main("sleep", "--engine", "mechanical", "--agent", "Joule", "--hook-json", json.dumps(hook))
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(self.memory))
        self.assertEqual(len(_dream_dirs(os.path.join(scratch, "dreaming", "dreams"))), 1)
        self.assertIn("missing", out)

    def test_hook_sleep_exits_zero_on_internal_exception(self):
        hook = {"session_id": "sess-0001", "transcript_path": os.path.join(self.tmp, "missing.jsonl"),
                "cwd": self.project, "scratchpad_dir": os.path.join(self.tmp, "scratch")}
        rc, out = self._main("sleep", "--engine", "mechanical", "--agent", "Joule", "--hook-json", json.dumps(hook))
        self.assertEqual(rc, 0)
        self.assertIn("sleep failed", out)

    def test_hook_sleep_is_silent_when_disabled(self):
        with open(os.path.join(self.project, ".dreaming.json"), "w", encoding="utf-8") as fh:
            json.dump({"enabled": False}, fh)
        hook = {"session_id": "sess-0001", "transcript_path": self.transcript, "cwd": self.project}
        rc, out = self._main("sleep", "--engine", "mechanical", "--agent", "Joule", "--hook-json", json.dumps(hook))
        self.assertEqual((rc, out.strip()), (0, ""))
        self.assertFalse(os.path.exists(os.path.join(self.memory, "dreams")))

    def test_index_is_not_read_when_the_store_is_missing(self):
        shutil.rmtree(self.memory)
        calls = []
        real = identity.index_text
        identity.index_text = lambda store, cfg: calls.append(store) or ""
        try:
            hook = {"session_id": "sess-0001", "transcript_path": self.transcript, "cwd": self.project,
                    "scratchpad_dir": os.path.join(self.tmp, "scratch")}
            self._main("sleep", "--engine", "mechanical", "--agent", "Joule", "--hook-json", json.dumps(hook))
        finally:
            identity.index_text = real
        self.assertEqual(calls, [])

    def test_hook_sleep_uses_the_transcript_agent_name(self):
        # No --agent, no env: the fixture's agent-name record says Joule, and Joule is mapped.
        hook = {"session_id": "sess-0001", "transcript_path": self.transcript, "cwd": self.project}
        env_before = os.environ.pop("DREAMING_AGENT", None)
        try:
            rc, out = self._main("sleep", "--engine", "mechanical", "--hook-json", json.dumps(hook))
        finally:
            if env_before is not None:
                os.environ["DREAMING_AGENT"] = env_before
        self.assertEqual(rc, 0)
        self.assertIn(os.path.join(self.memory, "dreams"), out)


class FirstPromptNoticeTests(unittest.TestCase):
    """Issue 1999 (quantum-concepts board, 2026-09-24): SessionStart(startup) fires ~250 ms BEFORE
    the transcript line that carries <scheduled-task name=...> is written. The scheduled_task source
    therefore read nothing, resolution fell through to git user.name - always Joule in a shared
    clone - and every scheduled specialist was told to promote and DELETE Joule's dreams. The
    notice now runs at the FIRST UserPromptSubmit, whose input carries the prompt, i.e. the tag
    itself; SessionStart(startup) prints nothing."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dreaming-prompt-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.project, self.memory = _fake_project(self.tmp)
        self.lemma = os.path.join(self.project, "team", "skill-maintainer", "memory")
        os.makedirs(self.lemma)
        with open(os.path.join(self.project, ".dreaming.json"), "w", encoding="utf-8") as fh:
            json.dump({"agents": {"Joule": "team/worker/memory", "worker-agent": "team/worker/memory",
                                  "skill-maintainer": "team/skill-maintainer/memory"},
                       "reseed_on_startup": True}, fh)
        self.transcript = write_fixture(os.path.join(self.tmp, "t.jsonl"))
        # Joule's store holds a dream, written under HER task, so a leak is visible and so is a
        # carry-over.
        sl.run_sleep(self.transcript, agent="Joule", session_id="sess-0001", out_root=self.memory,
                     engine=None, engine_name="mechanical", task="worker-agent",
                     now=datetime.datetime.now())
        # At startup the transcript does not yet hold the first user turn.
        self.early = os.path.join(self.tmp, "early.jsonl")
        open(self.early, "w").close()
        self._git = mock.patch.object(identity, "_git_user_name", lambda cwd, run: "Joule")
        self._git.start()

    def tearDown(self):
        self._git.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _notice(self, **hook):
        base = {"session_id": "s-1", "cwd": self.project, "transcript_path": self.early,
                "scratchpad_dir": os.path.join(self.tmp, "scratch")}
        base.update(hook)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["--project", self.project, "--home", self.home, "notice", "--hook-json", json.dumps(base)])
        self.assertEqual(rc, 0)
        out = buf.getvalue().strip()
        return json.loads(out)["hookSpecificOutput"] if out else None

    def _prompt(self, text, **hook):
        return self._notice(hook_event_name="UserPromptSubmit", prompt=text, **hook)

    def _lemma_dream(self):
        sl.run_sleep(self.transcript, agent="skill-maintainer", session_id="sess-0001", out_root=self.lemma,
                     engine=None, engine_name="mechanical", task="skill-maintainer",
                     now=datetime.datetime.now())

    def test_startup_never_names_a_store_guessed_from_git(self):
        self.assertIsNone(self._notice(hook_event_name="SessionStart", source="startup"),
                          "a startup notice can only have come from the git fallback")

    def test_a_scheduled_first_prompt_names_only_its_own_store(self):
        tag = '<scheduled-task name="skill-maintainer" file="x/SKILL.md"> run'
        self.assertIsNone(self._prompt(tag), "Lemma's store is empty; Joule's must not be offered")
        self._lemma_dream()
        out = self._prompt(tag, session_id="s-2")
        self.assertEqual(out["hookEventName"], "UserPromptSubmit")
        self.assertIn(self.lemma, out["additionalContext"])
        self.assertNotIn(self.memory, out["additionalContext"])

    def test_an_unmapped_scheduled_task_prints_nothing_rather_than_the_git_name(self):
        self.assertIsNone(self._prompt('<scheduled-task name="some-new-routine"> go'),
                          "a known scheduled run whose lane is unmapped must not fall through to git")

    def test_an_interactive_first_prompt_resolves_as_before_and_only_once(self):
        out = self._prompt("hello")
        self.assertIn(self.memory, out["additionalContext"])
        self.assertNotIn("Carry-over", out["additionalContext"], "interactive sessions never get a brief")
        self.assertIsNone(self._prompt("and a second prompt"), "the notice is once per session")

    def test_a_scheduled_run_receives_its_carry_over_at_its_first_prompt(self):
        out = self._prompt('<scheduled-task name="worker-agent" file="x"> wake')
        self.assertIn("Carry-over from your previous run", out["additionalContext"])
        self.assertIn("task worker-agent", out["additionalContext"])


class DefaultsAgreeTests(unittest.TestCase):
    def test_sleep_module_budget_default_equals_the_config_default(self):
        # Two copies of one number drift at the second one: 0.2.0 lowered config.DEFAULTS to 900
        # and sleep.py still said 2400 until a grep caught it. The config is the authority.
        from dreaming import config
        self.assertEqual(sl.DEFAULT_BUDGET_SECONDS, config.DEFAULTS["budget_seconds"])


class ReseedAndNoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dreaming-reseed-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.project, self.memory = _fake_project(self.tmp)
        self.transcript = write_fixture(os.path.join(self.tmp, "t.jsonl"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sleep(self, when):
        return sl.run_sleep(self.transcript, agent="Joule", session_id="sess-0001", out_root=self.memory,
                            engine=None, engine_name="mechanical", now=when)

    def _main(self, cmd, session="sess-0001"):
        hook = {"session_id": session, "cwd": self.project, "transcript_path": self.transcript,
                "scratchpad_dir": os.path.join(self.tmp, "scratch")}
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["--project", self.project, "--home", self.home, cmd, "--agent", "Joule",
                           "--hook-json", json.dumps(hook)])
        return rc, buf.getvalue()

    def test_reseed_picks_newest_folder_for_session(self):
        self._sleep(datetime.datetime(2026, 9, 22, 11, 0))
        new = self._sleep(datetime.datetime(2026, 9, 22, 12, 0))
        with open(os.path.join(new["folder"], "brief.md"), "a", encoding="utf-8") as fh:
            fh.write("\nNEWEST MARKER\n")
        rc, out = self._main("reseed")
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("NEWEST MARKER", ctx)
        self.assertIn("## Current Task", ctx)
        self.assertIn(os.path.basename(new["folder"]), ctx)
        self.assertIn("0 lesson(s), 0 tension(s) staged", ctx)

    def test_reseed_is_silent_without_a_dream(self):
        rc, out = self._main("reseed", session="other-session")
        self.assertEqual((rc, out.strip()), (0, ""))

    def test_notice_counts_dreams_and_is_silent_when_none(self):
        rc, out = self._main("notice")
        self.assertEqual((rc, out.strip()), (0, ""))
        self._sleep(datetime.datetime(2026, 9, 22, 11, 0))
        self._sleep(datetime.datetime(2026, 9, 22, 12, 0))
        rc, out = self._main("notice")
        self.assertEqual(rc, 0)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("2 dream(s) awaiting promotion", ctx)
        self.assertIn("dreaming-promote", ctx)
        self.assertIn(self.memory, ctx)

    def test_list_and_dreams_awaiting_agree(self):
        self._sleep(datetime.datetime(2026, 9, 22, 11, 0))
        found = sl.dreams_awaiting(self.memory)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["lessons"], found[0]["tensions"], found[0]["stale"]), (0, 0, False))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["--project", self.project, "--home", self.home, "list", "--agent", "Joule"])
        self.assertEqual(rc, 0)
        self.assertIn(found[0]["name"], buf.getvalue())


if __name__ == "__main__":
    unittest.main()
