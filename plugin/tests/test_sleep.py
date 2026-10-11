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
from test_distill import MAP_JSON  # noqa: E402
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

    def _engine(self, map_text=MAP_JSON):
        def fn(system, user, *, max_tokens=4000, timeout=None):
            return EngineResult(True, map_text, "fake", None)
        return fn

    def _run(self, **kw):
        base = dict(agent="Joule", session_id="sess-0001", out_root=self.memory,
                    engine=self._engine(), engine_name="fake")
        base.update(kw)
        return sl.run_sleep(self.transcript, **base)

    def _main(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["--project", self.project, "--home", self.home] + list(argv))
        return rc, buf.getvalue()

    def test_full_run_writes_the_brief_and_nothing_to_promote(self):
        """0.6.0 (owner 2026-09-25): a dream is compaction continuity, never mined for lessons. So
        a sleep writes the day, the newest slice's map, the brief and the log - and NO lessons/,
        tensions.md or reduce.json, which existed only to be promoted."""
        out = self._run()
        folder = out["folder"]
        self.assertTrue(folder.startswith(os.path.join(self.memory, "dreams")))
        for name in ("day.md", "brief.md", "sleep.log"):
            self.assertTrue(os.path.isfile(os.path.join(folder, name)), name)
        self.assertTrue(os.path.isfile(os.path.join(folder, "map", "1.json")))
        for name in ("lessons", "tensions.md", "reduce.json"):
            self.assertFalse(os.path.exists(os.path.join(folder, name)), name)
        self.assertEqual(out["degraded"], [])
        self.assertIn("GPU research", _read(os.path.join(folder, "brief.md")))
        log = _read(os.path.join(folder, "sleep.log"))
        self.assertIn("watermark: as-0000-11", log)
        self.assertIn("engine: fake", log)
        self.assertEqual(_read(os.path.join(self.memory, "MEMORY.md")), self.index_before)
        self.assertEqual(sorted(os.listdir(self.memory)),
                         sorted(["MEMORY.md", "a-count-is-not-discriminating-power.md", "dreams"]))

    def test_a_sleep_makes_one_state_only_call_on_the_newest_slice(self):
        """0.6.0: the brief's state was always a COPY of the newest slice (0.3.2), so mapping the
        older slices and reducing them bought only lessons. The sleep reads the newest slice and
        nothing else: one engine call, the state-only prompt, the newest slice's text."""
        with open(self.transcript, "w", encoding="utf-8") as fh:
            for i in range(20):
                fh.write(json.dumps(_rec("user", "us-0003-%02d" % i, message={"role": "user", "content": "old %02d " % i + "q" * 500})) + NL)
            fh.write(json.dumps(_rec("user", "us-0003-99", message={"role": "user", "content": "the NEWEST words"})) + NL)
        calls = []

        def fn(system, user, *, max_tokens=4000, timeout=None):
            calls.append((system, user))
            return EngineResult(True, MAP_JSON, "fake", None)

        out = self._run(engine=fn, chunk_chars=2000)
        self.assertEqual(len(calls), 1, "exactly one engine call")
        system, user = calls[0]
        self.assertIs(system, sd.STATE_SYSTEM)
        self.assertIn("the NEWEST words", user)
        self.assertNotIn("old 00 ", user, "an older slice must not reach the model")
        self.assertNotIn("lessons", user, "the call must not ask for what nothing promotes")
        n = len(sx.chunk_text(_read(os.path.join(out["folder"], "day.md")), max_chars=2000))
        self.assertGreater(n, 1, "the fixture must produce several slices")
        self.assertEqual(os.listdir(os.path.join(out["folder"], "map")), ["%d.json" % n])
        self.assertIn("state: from slice %d of %d" % (n, n), _read(os.path.join(out["folder"], "sleep.log")))

    def test_the_state_prompt_asks_for_no_lessons_or_tensions(self):
        self.assertIn('"state"', sd.STATE_SYSTEM)
        for word in ("lesson", "tension"):
            self.assertNotIn(word, sd.STATE_SYSTEM.lower())

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

    def test_a_slice_that_returns_no_state_gives_a_mechanical_brief_and_says_so(self):
        """An empty-but-valid reply is a degraded sleep, not a clean one (Haiku returned three of
        them on 2026-09-23 and the log read as a full dream). The mechanical state of the last
        turns is crude but true."""
        out = self._run(engine=self._engine(map_text=json.dumps({"state": {}})))
        self.assertTrue(any("slice 1 of 1 returned no state" in d for d in out["degraded"]), out["degraded"])
        self.assertTrue(any("newest slice" in d and "mechanical" in d for d in out["degraded"]), out["degraded"])
        self.assertIn("second question, about the 4090", _read(os.path.join(out["folder"], "brief.md")))

    def test_a_model_that_names_a_notification_as_the_task_is_overruled(self):
        """The Sonnet fallback once wrote a brief whose Current Task was a raw task notification
        (1974). The model's state is otherwise kept; only the task is replaced by the last real
        request, and the sleep says so."""
        payload = "<task-notification>\n<task-id>bwex0qful</task-id>\n<status>failed</status>"
        bad = json.dumps(dict(json.loads(MAP_JSON), state={
            "current_task": payload, "exact_state": "the suite finished red",
            "next_step": "n", "uncommitted_decisions": [], "files_in_context": []}))
        out = self._run(engine=self._engine(map_text=bad))
        brief = _read(os.path.join(out["folder"], "brief.md"))
        self.assertNotIn("task-notification", brief)
        self.assertIn("second question, about the 4090", brief)
        self.assertIn("the suite finished red", brief)
        self.assertTrue(any("system payload" in d for d in out["degraded"]), out["degraded"])

    def test_mechanical_run_when_no_engine(self):
        out = self._run(engine=None, engine_name="mechanical")
        self.assertIn("no engine", " ".join(out["degraded"]))
        self.assertIn("second question, about the 4090", _read(os.path.join(out["folder"], "brief.md")))
        self.assertTrue(os.path.isfile(os.path.join(out["folder"], "day.md")))

    def test_engine_exception_in_the_state_call_still_leaves_day_log_and_brief(self):
        def exploding(system, user, *, max_tokens=4000, timeout=None):
            raise RuntimeError("kaboom")

        out = self._run(engine=exploding)
        for name in ("day.md", "sleep.log", "brief.md"):
            self.assertTrue(os.path.isfile(os.path.join(out["folder"], name)), name)
        self.assertTrue(any("kaboom" in d for d in out["degraded"]))
        self.assertIn("second question, about the 4090", _read(os.path.join(out["folder"], "brief.md")))

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
        self.assertIn("dream folder(s) left", out)
        old = time.time() - 3 * 86400
        os.utime(first["folder"], (old, old))
        rc, out = self._main("notice", "--hook-json", json.dumps({"session_id": "run-two", "transcript_path": sched}))
        self.assertNotIn("Carry-over", out, "older than reseed_max_age_hours")
        self.assertIn("dream folder(s) left", out)

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

    def test_a_truncated_state_reply_is_named_and_its_state_kept(self):
        whole = json.dumps({"state": json.loads(MAP_JSON)["state"], "padding": "x" * 400})
        out = self._run(engine=self._engine(map_text=whole[:-60]))
        self.assertTrue(any("slice 1 of 1 truncated" in d for d in out["degraded"]), out["degraded"])
        self.assertIn("GPU research", _read(os.path.join(out["folder"], "brief.md")))

    def test_an_engine_error_is_named_and_the_brief_is_mechanical(self):
        def fn(system, user, *, max_tokens=4000, timeout=None):
            return EngineResult(False, "", "fake", "boom")

        out = self._run(engine=fn)
        self.assertTrue(any("slice 1 of 1 engine error: boom" in d for d in out["degraded"]), out["degraded"])
        self.assertIn("second question, about the 4090", _read(os.path.join(out["folder"], "brief.md")))

    def test_no_budget_for_the_state_call_gives_a_mechanical_brief_and_no_call(self):
        ticks = itertools.chain([0], itertools.repeat(10_000))
        calls = []

        def fn(system, user, *, max_tokens=4000, timeout=None):
            calls.append(1)
            return EngineResult(True, MAP_JSON, "fake", None)

        out = self._run(engine=fn, budget_seconds=5, clock=lambda: next(ticks), min_call_seconds=1)
        self.assertEqual(calls, [])
        self.assertTrue(any("budget" in d and "mechanical" in d for d in out["degraded"]), out["degraded"])
        self.assertFalse(os.path.exists(os.path.join(out["folder"], "map")))
        self.assertIn("second question, about the 4090", _read(os.path.join(out["folder"], "brief.md")))

    def test_the_state_call_gets_the_remaining_budget_as_its_timeout(self):
        # The hook has a 3600 s ceiling, so the one call is bounded by what is left of the budget.
        ticks = itertools.chain([0, 100], itertools.repeat(100))
        seen = []

        def fn(system, user, *, max_tokens=4000, timeout=None):
            seen.append(timeout)
            return EngineResult(True, MAP_JSON, "fake", None)

        out = self._run(engine=fn, budget_seconds=500, clock=lambda: next(ticks))
        self.assertEqual(seen, [400])
        self.assertEqual(out["degraded"], [])

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

    def test_hook_sleep_reaps_another_sessions_old_dream_and_keeps_its_own(self):
        """0.6.0 reaper, wired: the PreCompact sleep clears an old dream of ANOTHER session and
        says so on its line; the dream it just wrote, of this session, stays."""
        old = os.path.join(self.memory, "dreams", "20260101-000000-otherses")
        os.makedirs(old)
        past = time.time() - 30 * 86400
        os.utime(old, (past, past))
        hook = {"session_id": "sess-0001", "transcript_path": self.transcript, "cwd": self.project}
        rc, out = self._main("sleep", "--engine", "mechanical", "--agent", "Joule", "--hook-json", json.dumps(hook))
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(old))
        self.assertIn("reaped 1", out)
        self.assertEqual(len(_dream_dirs(os.path.join(self.memory, "dreams"))), 1)

    def test_hook_sleep_is_silent_when_disabled(self):
        with open(os.path.join(self.project, ".dreaming.json"), "w", encoding="utf-8") as fh:
            json.dump({"enabled": False}, fh)
        hook = {"session_id": "sess-0001", "transcript_path": self.transcript, "cwd": self.project}
        rc, out = self._main("sleep", "--engine", "mechanical", "--agent", "Joule", "--hook-json", json.dumps(hook))
        self.assertEqual((rc, out.strip()), (0, ""))
        self.assertFalse(os.path.exists(os.path.join(self.memory, "dreams")))


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
        self.assertNotIn("lesson", ctx.lower(), "a dream carries no lessons since 0.5.8, so the re-seed counts none")
        self.assertNotIn("promot", ctx.lower().split("(dreaming re-seed")[1], "the re-seed tail must not ask for promotion")

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
        self.assertIn("2 dream folder(s) left", ctx)
        self.assertIn(self.memory, ctx)
        # 0.6.0, owner ruling 2026-09-25: dreams are compaction continuity only. The notice tells a
        # waking mind to DELETE, never to promote - it once cost a wrong act in a lane that did not
        # load the QC anti-fact (1974, Vera 09-26).
        self.assertIn("delete", ctx)
        self.assertNotIn("promot", ctx.lower())

    def test_list_and_dreams_awaiting_agree(self):
        self._sleep(datetime.datetime(2026, 9, 22, 11, 0))
        found = sl.dreams_awaiting(self.memory)
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0]["stale"])
        self.assertNotIn("lessons", found[0])
        self.assertNotIn("tensions", found[0])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["--project", self.project, "--home", self.home, "list", "--agent", "Joule"])
        self.assertEqual(rc, 0)
        self.assertIn(found[0]["name"], buf.getvalue())


if __name__ == "__main__":
    unittest.main()
