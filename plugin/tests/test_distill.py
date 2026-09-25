#!/usr/bin/env python3
"""Map, reduce and renderers, ported from the quantum-concepts sleep step."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from dreaming import distill as sd, extract as sx  # noqa: E402
from dreaming.engines import EngineResult  # noqa: E402


def _engine_returning(text):
    return lambda system, user, *, max_tokens=4000: EngineResult(True, text, "fake", None)


MAP_JSON = json.dumps({
    "lessons": [{"title": "A control can certify a copy of the rule nobody runs",
                 "why": "the guard read a copy", "how_to_apply": "run the real one",
                 "provenance": ["as-0000-11"]}],
    "state": {"current_task": "GPU research", "exact_state": "answering the 4090 question",
              "next_step": "reply", "uncommitted_decisions": ["buy the 5070 Ti"],
              "files_in_context": ["docs/x.md"]},
    "tensions": [{"claim": "eBay used prices are a market", "existing_slug": "",
                  "existing_line": "", "side_a": "trackers cite them", "side_b": "owner says scams"}],
})

INDEX_TEXT = ("  a-control-can-certify-a-copy-of-the-rule-nobody-runs  -  A control can certify a copy\n"
              "  a-count-is-not-discriminating-power  -  A count is not discriminating power\n")

REDUCE_JSON = json.dumps({
    "lessons": [{"title": "A control can certify a copy of the rule nobody runs",
                 "why": "w", "how_to_apply": "h", "provenance": ["as-0000-11"],
                 "relation": "extends", "extends": "a-control-can-certify-a-copy-of-the-rule-nobody-runs"},
                {"title": "eBay used prices are not a market", "why": "w2", "how_to_apply": "h2",
                 "provenance": ["us-0000-10"], "relation": "new", "extends": None}],
    "state": {"current_task": "GPU research", "exact_state": "s", "next_step": "n",
              "uncommitted_decisions": ["d"], "files_in_context": ["f"]},
    "tensions": [{"claim": "c", "existing_slug": "a-count-is-not-discriminating-power",
                  "existing_line": "A count is not discriminating power", "side_a": "a", "side_b": "b"}],
})


class DistillTests(unittest.TestCase):
    def test_map_parses_well_formed_json(self):
        out = sd.map_chunk(_engine_returning(MAP_JSON), "chunk text", 1, 1)
        self.assertFalse(out["parse_failed"])
        self.assertEqual(len(out["lessons"]), 1)
        self.assertEqual(out["state"]["current_task"], "GPU research")
        self.assertEqual(len(out["tensions"]), 1)

    def test_map_wrong_shape_is_flagged_not_fatal(self):
        # CONTROL: the well-formed case above passes, so a failure here is the shape, not the parser.
        prose = sd.map_chunk(_engine_returning("Sure! Here is what I noticed: nothing."), "c", 1, 1)
        self.assertTrue(prose["parse_failed"])
        self.assertEqual(prose["lessons"], [])
        wrong_keys = sd.map_chunk(_engine_returning(json.dumps({"summary": "x"})), "c", 1, 1)
        self.assertEqual(wrong_keys["lessons"], [])
        self.assertTrue(wrong_keys["parse_failed"])
        truncated = sd.map_chunk(_engine_returning(MAP_JSON[:-40]), "c", 1, 1)
        self.assertTrue(truncated["truncated"])
        self.assertFalse(truncated["parse_failed"])
        self.assertEqual(len(truncated["lessons"]), 1)
        failed = lambda s, u, *, max_tokens=4000: EngineResult(False, "", "fake", "boom")
        out = sd.map_chunk(failed, "c", 1, 1)
        self.assertTrue(out["parse_failed"])
        self.assertIn("boom", out["raw"])

    def test_reduce_marks_extends_and_files_tensions_apart_from_lessons(self):
        maps = [sd.map_chunk(_engine_returning(MAP_JSON), "c", 1, 1)]
        out = sd.reduce_maps(_engine_returning(REDUCE_JSON), maps, INDEX_TEXT)
        self.assertFalse(out["parse_failed"])
        rel = {l["title"]: l["relation"] for l in out["lessons"]}
        self.assertEqual(rel["A control can certify a copy of the rule nobody runs"], "extends")
        self.assertEqual(rel["eBay used prices are not a market"], "new")
        self.assertEqual(out["tensions"][0]["existing_slug"], "a-count-is-not-discriminating-power")
        self.assertEqual(out["halved"], 0)
        for field in sd.STATE_FIELDS:
            self.assertIn(field, out["state"])

    def test_reduce_halves_when_input_exceeds_window(self):
        calls = []

        def counting(system, user, *, max_tokens=4000, timeout=None):
            calls.append(len(user))
            return EngineResult(True, REDUCE_JSON, "fake", None)

        big = {"lessons": [], "state": {}, "tensions": [], "parse_failed": False,
               "raw": "x" * 5000}
        maps = [dict(big, lessons=[{"title": "t%d" % i, "why": "y" * 900, "how_to_apply": "h",
                                    "provenance": []}]) for i in range(8)]
        out = sd.reduce_maps(counting, maps, INDEX_TEXT, max_chars=3000)
        self.assertGreater(out["halved"], 0)
        self.assertTrue(all(n <= 3000 + len(sd.REDUCE_SYSTEM) + 4000 for n in calls))

    def test_map_and_reduce_prompts_restate_the_contract_after_the_payload(self):
        # Measured 2026-09-22 on the first live dream: with the instructions only in the system
        # prompt and a 40k-token slice after them, Qwen CONTINUED the transcript ("Let me run
        # the completion smoke test.") instead of returning JSON. The contract has to come
        # again after the payload, and the payload has to be fenced so the model can tell
        # where the transcript stops and the instruction resumes.
        seen = {}

        def capture(system, user, *, max_tokens=4000, timeout=None):
            seen["user"] = user
            return EngineResult(True, MAP_JSON, "fake", None)

        sd.map_chunk(capture, "SLICE BODY", 1, 1)
        user = seen["user"]
        self.assertLess(user.find(sd.PAYLOAD_OPEN), user.find("SLICE BODY"))
        self.assertLess(user.find("SLICE BODY"), user.find(sd.PAYLOAD_CLOSE))
        self.assertTrue(user.rstrip().endswith(sd.JSON_REMINDER.rstrip()), user[-200:])
        maps = [sd.map_chunk(_engine_returning(MAP_JSON), "c", 1, 1)]
        sd.reduce_maps(capture, maps, INDEX_TEXT)
        user = seen["user"]
        self.assertIn(sd.PAYLOAD_OPEN, user)
        self.assertTrue(user.rstrip().endswith(sd.JSON_REMINDER.rstrip()), user[-200:])

    def test_state_survives_a_reduce_reply_truncated_inside_the_lessons(self):
        # Measured 2026-09-22, full-transcript dream: the reduce reply was cut off at ~14k chars
        # inside the lessons list; salvage recovered the lessons prefix and the STATE, which came
        # after them, was lost - the brief silently fell back to the mechanical form. So the
        # contract puts state first, and a truncated reply is salvaged for state and flagged.
        full = json.loads(REDUCE_JSON)
        reordered = json.dumps({"state": full["state"], "tensions": full["tensions"],
                                "lessons": full["lessons"] * 6}, indent=1)
        cut = reordered[: reordered.rfind('"why"') + 8]   # ends inside a string, unbalanced
        self.assertFalse(cut.rstrip().endswith("}"))
        maps = [sd.map_chunk(_engine_returning(MAP_JSON), "c", 1, 1)]
        out = sd.reduce_maps(_engine_returning(cut), maps, INDEX_TEXT)
        self.assertEqual(out["state"]["current_task"], "GPU research")
        self.assertTrue(out["truncated"])
        self.assertGreaterEqual(len(out["lessons"]), 1)
        self.assertLess(len(out["lessons"]), 12)
        self.assertFalse(out["parse_failed"])

    def test_prompts_put_state_before_lessons(self):
        for prompt in (sd.MAP_SYSTEM, sd.REDUCE_SYSTEM):
            self.assertLess(prompt.find('"state"'), prompt.find('"lessons"'), prompt[:200])

    def test_default_chunk_is_small_enough_for_a_local_27b_to_follow(self):
        self.assertLessEqual(sd.DEFAULT_CHUNK_CHARS, 60_000)

    def test_reduce_stops_halving_when_the_merge_does_not_shrink(self):
        # Review finding (Critical): two max-size reduce replies plus a big index can exceed the
        # window forever - halve, merge, still too big, halve again - 300 engine calls measured,
        # each up to 900 s live. The recursion has to notice it is not shrinking and give up to
        # the union of the map passes.
        full = json.loads(REDUCE_JSON)
        fat = dict(full, lessons=[dict(full["lessons"][0], why="w" * 290, how_to_apply="h" * 290,
                                       title="lesson %d" % i) for i in range(12)])
        fat_reply = json.dumps(fat)
        calls = []

        def engine(system, user, *, max_tokens=4000, timeout=None):
            calls.append(len(user))
            return EngineResult(True, fat_reply, "fake", None)

        maps = [sd.map_chunk(_engine_returning(MAP_JSON), "c", i, 4) for i in range(1, 5)]
        out = sd.reduce_maps(engine, maps, "i" * 40_000, max_chars=60_000)
        self.assertLessEqual(len(calls), 12, len(calls))
        self.assertFalse(out["parse_failed"])
        self.assertGreaterEqual(len(out["lessons"]), 1)
        self.assertFalse(out["gave_up"])   # the bounded index made it fit: one call, no halving

    def test_reduce_gives_up_to_the_union_when_halving_cannot_shrink(self):
        full = json.loads(REDUCE_JSON)
        fat = dict(full, lessons=[dict(full["lessons"][0], why="w" * 290, how_to_apply="h" * 290,
                                       title="lesson %d" % i) for i in range(12)])
        fat_reply = json.dumps(fat)
        calls = []

        def engine(system, user, *, max_tokens=4000, timeout=None):
            calls.append(len(user))
            return EngineResult(True, fat_reply, "fake", None)

        maps = [dict(sd.map_chunk(_engine_returning(MAP_JSON), "c", i, 8),
                     lessons=[{"title": "t%d-%d" % (i, j), "why": "y" * 900, "how_to_apply": "h", "provenance": [],
                               "relation": "new", "extends": None} for j in range(6)]) for i in range(1, 9)]
        out = sd.reduce_maps(engine, maps, "", max_chars=9000)
        self.assertTrue(out["gave_up"])
        self.assertLessEqual(len(calls), 12, len(calls))
        self.assertGreaterEqual(len(out["lessons"]), 1)

    def test_engine_calls_carry_the_timeout_they_are_given(self):
        seen = []

        def engine(system, user, *, max_tokens=4000, timeout=None):
            seen.append(timeout)
            return EngineResult(True, MAP_JSON if system is sd.MAP_SYSTEM else REDUCE_JSON, "fake", None)

        m = sd.map_chunk(engine, "c", 1, 1, timeout=123)
        sd.reduce_maps(engine, [m], INDEX_TEXT, timeout=45)
        self.assertEqual(seen, [123, 45])

    def test_reduce_bounds_the_index_it_sends(self):
        seen = {}

        def capture(system, user, *, max_tokens=4000, timeout=None):
            seen["user"] = user
            return EngineResult(True, REDUCE_JSON, "fake", None)

        maps = [sd.map_chunk(_engine_returning(MAP_JSON), "c", 1, 1)]
        sd.reduce_maps(capture, maps, "  slug-%d  -  headline\n" * 20_000, max_chars=60_000)
        self.assertLess(len(seen["user"]), 60_000 + len(sd.REDUCE_SYSTEM))
        self.assertIn("index truncated", seen["user"])

    def test_mechanical_state_uses_last_turns(self):
        turns = [sx.Turn("u1", "t1", "user", "please fix the gate"),
                 sx.Turn("a1", "t2", "assistant", "on it"),
                 sx.Turn("t1", "t3", "tool_use", "Bash {\"command\": \"pytest\"}"),
                 sx.Turn("a2", "t4", "assistant", "the gate is fixed; next I commit")]
        state = sd.mechanical_state(turns)
        self.assertIn("please fix the gate", state["current_task"])
        self.assertIn("the gate is fixed", state["exact_state"])
        self.assertIn("Bash", state["files_in_context"][0])

    def test_renderers_are_ascii_and_carry_provenance(self):
        meta = {"agent": "Joule", "session_id": "sess-0001", "engine": "fake", "when": "2026-09-22 12:00"}
        lesson = {"title": "A lesson \u2014 with a dash", "why": "w", "how_to_apply": "h",
                  "provenance": ["as-0000-11"], "relation": "extends", "extends": "some-slug"}
        text = sd.render_lesson(lesson, meta)
        self.assertTrue(all(ord(c) < 128 for c in text), text)
        self.assertIn("sess-0001", text)
        self.assertIn("as-0000-11", text)
        self.assertIn("extends: some-slug", text)
        self.assertEqual(sd.slugify("A lesson \u2014 with a dash"), "a-lesson-with-a-dash")
        brief = sd.render_brief({"current_task": "t", "exact_state": "e", "next_step": "n",
                                 "uncommitted_decisions": ["d1"], "files_in_context": ["f1"]}, meta)
        for heading in ("## Current Task", "## Exact State", "## Next Step",
                        "## Uncommitted Decisions", "## Files Currently In Context"):
            self.assertIn(heading, brief)
        tens = sd.render_tensions([{"claim": "c", "existing_slug": "s", "existing_line": "l",
                                    "side_a": "a", "side_b": "b"}], meta)
        self.assertIn("IN-TENSION", tens)




if __name__ == "__main__":
    unittest.main()


class KnownRulesAndScopeTests(unittest.TestCase):
    """Field report on 0.4.0: 11 of 20 lessons restated rules already written in the house's rules
    files, which the index does not carry; and one 'sensible generic prior' contradicted a standing
    ruling. The reduce is told the rules; the plugin never discards on the model's verdict - a
    restatement stays in the dream, labelled, for the promoter to drop in one glance."""

    def test_reduce_prompt_carries_known_rules_bounded_and_a_restatement_keeps_its_label(self):
        seen = {}

        def capture(system, user, *, max_tokens=4000, timeout=None):
            seen["user"] = user
            full = json.loads(REDUCE_JSON)
            full["lessons"].append({"title": "Read the exit code of the command, not the pipe", "why": "w",
                                    "how_to_apply": "h", "provenance": [], "relation": "known",
                                    "extends": "AGENTS.md"})
            return EngineResult(True, json.dumps(full), "fake", None)

        maps = [sd.map_chunk(_engine_returning(MAP_JSON), "c", 1, 1)]
        rules = "RULE ONE: read the exit code of the command, not the pipe." + chr(10) + ("filler line" + chr(10)) * 400
        out = sd.reduce_maps(capture, maps, INDEX_TEXT, known_rules=rules, max_chars=8000)
        self.assertIn("KNOWN RULES", seen["user"])
        self.assertIn("RULE ONE", seen["user"])
        self.assertLess(seen["user"].count("filler line"), 400, "the rules are bounded like the index")
        rel = {l["title"]: (l["relation"], l["extends"]) for l in out["lessons"]}
        self.assertEqual(rel["Read the exit code of the command, not the pipe"], ("known", "AGENTS.md"))

    def test_lesson_scope_is_asked_for_kept_and_rendered(self):
        self.assertIn('"scope"', sd.MAP_SYSTEM)
        self.assertIn('"scope"', sd.REDUCE_SYSTEM)
        cleaned = sd._clean_lessons([{"title": "t", "scope": "generalised"}, {"title": "u", "scope": "observed"}, {"title": "v"}])
        self.assertEqual([l["scope"] for l in cleaned], ["generalised", "observed", ""])
        meta = {"when": "w", "agent": "a", "session_id": "s", "engine": "e"}
        self.assertIn("scope: generalised", sd.render_lesson(cleaned[0], meta))
        self.assertNotIn("scope:", sd.render_lesson(cleaned[2], meta))
        known = dict(cleaned[1], relation="known", extends="AGENTS.md")
        self.assertIn("restates a known rule: AGENTS.md", sd.render_lesson(known, meta))


class LessonHygieneTests(unittest.TestCase):
    """Field report from a routine's three wakes (2026-09-24): 2 of 12 lessons kept. One would have
    done harm - 'the pairsheet failure is known issue 1984, so ignore it when it is the only red' is
    board STATE, and promoted it becomes a standing permission to wave a red through that goes stale
    within the hour. Others restated held entries the reduce had been shown, or were tool trivia. The
    prompts now say so; the write stage LABELS what a rule can recognise, and never drops it."""

    def test_prompts_forbid_board_state_tool_trivia_and_before_after_tensions(self):
        for prompt in (sd.MAP_SYSTEM, sd.REDUCE_SYSTEM):
            self.assertIn("never board state", prompt)
            self.assertIn("known issue", prompt)
            self.assertIn("failed call", prompt)
        self.assertIn("before-fix", sd.MAP_SYSTEM)

    def test_board_state_phrasing_is_flagged_not_dropped(self):
        lessons = sd._clean_lessons([
            {"title": "The pairsheet failure is known issue 1984, so ignore it when it is the only red",
             "why": "w", "how_to_apply": "h"},
            {"title": "Ignore the flaky lint until 2002 lands", "why": "w", "how_to_apply": "h"},
            {"title": "A guard that ignores its own exit code is not a guard", "why": "w", "how_to_apply": "h"},
        ])
        out, counts = sd.flag_lessons(lessons, "")
        self.assertEqual(len(out), 3, "labelled, never dropped")
        self.assertIn("board_state", out[0]["flags"])
        self.assertIn("board_state", out[1]["flags"])
        self.assertEqual(out[2]["flags"], [], "a lesson ABOUT ignoring is not an instruction to ignore")
        self.assertEqual(counts["board_state"], 2)
        meta = {"when": "w", "agent": "a", "session_id": "s", "engine": "e"}
        self.assertIn("flag: reads as board state", sd.render_lesson(out[0], meta))

    def test_a_title_that_overlaps_an_index_headline_is_labelled_extends(self):
        index = ("- a-piped-exit-code-is-not-a-verification - A piped exit code is not a verification" + chr(10) +
                 "- a-count-with-no-denominator-lies-loudest-at-zero - A count with no denominator lies loudest at zero" + chr(10))
        lessons = sd._clean_lessons([
            {"title": "A piped exit code is never a verification of the command", "why": "w", "how_to_apply": "h"},
            {"title": "Read the mtime of verify-last.log before trusting it", "why": "w", "how_to_apply": "h"},
        ])
        out, counts = sd.flag_lessons(lessons, index)
        self.assertEqual((out[0]["relation"], out[0]["extends"]), ("extends", "a-piped-exit-code-is-not-a-verification"))
        self.assertIn("restates_index", out[0]["flags"])
        self.assertEqual((out[1]["relation"], out[1]["flags"]), ("new", []))
        self.assertEqual(counts["restates_index"], 1)
