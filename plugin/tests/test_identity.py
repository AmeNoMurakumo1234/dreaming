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
        self.assertEqual(config.DEFAULTS["identity_order"], ["scheduled_task", "env", "config", "transcript", "git", "default"])
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
        self.assertIn("in the agents map", res.reason)
        self.assertIn("Stranger (env)", res.reason)
        self.assertFalse(os.path.exists(os.path.join(self.project, "stores")))

    def test_with_a_map_the_first_source_whose_name_is_mapped_wins(self):
        # Measured 2026-09-22 in the desktop app: the transcript's last agent-name record carried the
        # SESSION TITLE ("RTX 5080 market research"), so a map keyed by agent sent a real Joule
        # session to scratch. With a map present, an unmapped name is not a verdict - the next
        # source is consulted, and only when no source maps does the dream go to scratch.
        store = os.path.join(self.project, "team", "worker", "memory")
        os.makedirs(store)
        cfg = self._cfg({"agents": {"Joule": "team/worker/memory"}})
        titled = os.path.join(self.tmp, "titled.jsonl")
        with open(titled, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "agent-name", "agentName": "RTX 5080 market research", "sessionId": "s"}) + "\n")
        res = identity.resolve(cfg, self.project, transcript=titled, env={}, run=_git("Joule"))
        self.assertFalse(res.scratch)
        self.assertEqual((res.agent, res.source), ("Joule", "git"))
        res = identity.resolve(cfg, self.project, transcript=titled, env={}, run=_git("Nobody"),
                               hook={"scratchpad_dir": os.path.join(self.tmp, "scratch")})
        self.assertTrue(res.scratch)
        self.assertIn("RTX 5080 market research", res.reason)
        self.assertIn("Nobody", res.reason)

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


class IndexPathTests(unittest.TestCase):
    def test_index_file_may_be_an_absolute_path_outside_the_store(self):
        """Field report 2026-09-23: a lane's real index lived outside its store and a
        store-relative name could not reach it, so no lesson was ever marked extends."""
        import tempfile, shutil
        tmp = tempfile.mkdtemp(prefix="dreaming-idx-")
        try:
            idx = os.path.join(tmp, "elsewhere", "INDEX.md")
            os.makedirs(os.path.dirname(idx))
            with open(idx, "w", encoding="utf-8") as fh:
                fh.write("- a-real-entry - A real entry" + chr(10))
            store = os.path.join(tmp, "store")
            os.makedirs(store)
            text = identity.index_text(store, {"index_file": idx})
            self.assertIn("a-real-entry", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


TAG = '<scheduled-task name="pm-agent" file="tasks/pm-agent/SKILL.md">'


def write_scheduled_fixture(path, *, tag_in_first=True):
    """A scheduled run's transcript: the task tag opens the FIRST user turn (or a later one, for
    the control), and the agent-name record carries the session TITLE, as the desktop app writes."""
    from test_extract import _rec
    first = (TAG + " run the routine") if tag_in_first else "an ordinary question"
    recs = [_rec("user", "us-0000-02", message={"role": "user", "content": first}),
            {"type": "agent-name", "agentName": "Pm agent", "sessionId": "sess-0001"},
            _rec("assistant", "as-0000-03", message={"role": "assistant", "content": [{"type": "text", "text": "ok"}]}),
            _rec("user", "us-0000-04", message={"role": "user", "content": TAG + " again" if not tag_in_first else "more"})]
    with open(path, "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r) + chr(10))
    return path


class ScheduledTaskIdentityTests(unittest.TestCase):
    """Field report 2026-09-23: a scheduled run's first user turn carries <scheduled-task name=...>,
    which names the LANE on every run - where git user.name and config.agent are per BOX and the
    agent-name record is the session title. Measured in this house too: pm-agent,
    book-content-agent, web-gui-product."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dreaming-st-")
        self.home = os.path.join(self.tmp, "home"); os.makedirs(self.home)
        self.project = os.path.join(self.tmp, "project"); os.makedirs(os.path.join(self.project, ".git"))
        self.transcript = write_scheduled_fixture(os.path.join(self.tmp, "t.jsonl"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cfg(self, project_json=None):
        if project_json is not None:
            with open(os.path.join(self.project, ".dreaming.json"), "w", encoding="utf-8") as fh:
                json.dump(project_json, fh)
        return config.load(project_dir=self.project, env={}, home=self.home)

    def test_the_task_tag_is_the_first_identity_source_even_over_env(self):
        cfg = self._cfg()
        self.assertEqual(identity.agent_name(cfg, self.project, self.transcript, {"DREAMING_AGENT": "Env"}, _git("Git")),
                         ("pm-agent", "scheduled_task"))

    def test_a_tag_in_a_later_turn_is_not_an_identity(self):
        later = write_scheduled_fixture(os.path.join(self.tmp, "later.jsonl"), tag_in_first=False)
        cfg = self._cfg()
        self.assertEqual(identity.agent_name(cfg, self.project, later, {}, _git("Git")), ("Pm agent", "transcript"))

    def test_the_task_name_goes_through_the_agents_map_like_any_other(self):
        lane = os.path.join(self.project, "team", "pm", "memory"); os.makedirs(lane)
        worker = os.path.join(self.project, "team", "worker", "memory"); os.makedirs(worker)
        cfg = self._cfg({"agents": {"pm-agent": "team/pm/memory", "Joule": "team/worker/memory"}})
        res = identity.resolve(cfg, self.project, transcript=self.transcript, env={}, run=_git("Joule"))
        self.assertEqual((res.agent, res.source, os.path.normcase(res.store)), ("pm-agent", "scheduled_task", os.path.normcase(lane)))
        # unmapped task, mapped git name: the map still decides, one step down the chain
        cfg = self._cfg({"agents": {"Joule": "team/worker/memory"}})
        res = identity.resolve(cfg, self.project, transcript=self.transcript, env={}, run=_git("Joule"))
        self.assertEqual((res.agent, res.source), ("Joule", "git"))

    def test_without_a_map_the_task_gets_a_store_under_its_own_name(self):
        cfg = self._cfg()
        res = identity.resolve(cfg, self.project, transcript=self.transcript, env={}, run=_git("Box"))
        self.assertFalse(res.scratch)
        self.assertEqual(os.path.basename(res.store), "pm-agent")


class PerAgentIndexAndFallbackTests(unittest.TestCase):
    """Field report on 0.4.0: a lane's index lives outside its store and is SEVERAL files; and a
    map that names only the interactive agent sent every routine's dream to scratch, undoing the
    lane split. Both are config, both opt-in, neither changes a store that does not ask."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dreaming-idx-")
        self.home = os.path.join(self.tmp, "home"); os.makedirs(self.home)
        self.project = os.path.join(self.tmp, "project"); os.makedirs(os.path.join(self.project, ".git"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cfg(self, project_json):
        with open(os.path.join(self.project, ".dreaming.json"), "w", encoding="utf-8") as fh:
            json.dump(project_json, fh)
        return config.load(project_dir=self.project, env={}, home=self.home)

    def test_indexes_map_reads_several_files_for_one_agent_and_skips_a_missing_one(self):
        a = os.path.join(self.tmp, "a", "INDEX.md"); os.makedirs(os.path.dirname(a))
        b = os.path.join(self.tmp, "b", "INDEX.md"); os.makedirs(os.path.dirname(b))
        with open(a, "w", encoding="utf-8") as fh:
            fh.write("- from-a - A" + chr(10))
        with open(b, "w", encoding="utf-8") as fh:
            fh.write("- from-b - B" + chr(10))
        store = os.path.join(self.tmp, "store"); os.makedirs(store)
        with open(os.path.join(store, "MEMORY.md"), "w", encoding="utf-8") as fh:
            fh.write("- from-store - S" + chr(10))
        cfg = self._cfg({"indexes": {"Joule": [a, b, os.path.join(self.tmp, "missing.md")]}})
        text = identity.index_text(store, cfg, agent="Joule")
        self.assertIn("from-a", text); self.assertIn("from-b", text)
        self.assertNotIn("from-store", text, "a per-agent list replaces the store index, it does not add to it")
        self.assertIn("from-store", identity.index_text(store, cfg, agent="Other"))

    def test_agents_fallback_store_root_gives_an_unmapped_name_its_own_store(self):
        os.makedirs(os.path.join(self.project, "team", "worker", "memory"))
        cfg = self._cfg({"agents": {"Joule": "team/worker/memory"}, "agents_fallback": "store_root",
                         "store_root": os.path.join(self.tmp, "stores")})
        res = identity.resolve(cfg, self.project, transcript=None, env={"DREAMING_AGENT": "pm-agent"}, run=_git(""),
                               hook={"scratchpad_dir": os.path.join(self.tmp, "scratch")})
        self.assertFalse(res.scratch)
        self.assertEqual(os.path.normcase(res.store), os.path.normcase(os.path.join(self.tmp, "stores", "pm-agent")))
        self.assertIn("agents_fallback", res.reason)
        self.assertFalse(os.path.exists(res.store), "resolve never creates it; the sleep does")
        # the default is still scratch: a map is a statement of who lives here
        cfg = self._cfg({"agents": {"Joule": "team/worker/memory"}})
        res = identity.resolve(cfg, self.project, transcript=None, env={"DREAMING_AGENT": "pm-agent"}, run=_git(""),
                               hook={"scratchpad_dir": os.path.join(self.tmp, "scratch")})
        self.assertTrue(res.scratch)
