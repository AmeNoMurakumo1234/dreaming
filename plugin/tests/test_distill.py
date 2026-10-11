#!/usr/bin/env python3
"""The state call, the parser behind it, the mechanical fallback and the brief renderer.

Since 0.5.8 a sleep is brief-only: one call, on the newest slice, for the resume state (owner ruling
2026-09-25 - a dream is compaction continuity and is never promoted). The map/reduce/lesson/tension
machinery and its tests were removed in 0.6.0.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)

from dreaming import distill as sd, extract as sx  # noqa: E402
from dreaming.engines import EngineResult  # noqa: E402


def _engine_returning(text):
    return lambda system, user, *, max_tokens=4000, timeout=None: EngineResult(True, text, "fake", None)


MAP_JSON = json.dumps({
    "state": {"current_task": "GPU research", "exact_state": "answering the 4090 question",
              "next_step": "reply", "uncommitted_decisions": ["buy the 5070 Ti"],
              "files_in_context": ["docs/x.md"]},
})


class StateCallTests(unittest.TestCase):
    def test_a_well_formed_reply_parses(self):
        out = sd.state_of_slice(_engine_returning(MAP_JSON), "chunk text", 1, 1)
        self.assertFalse(out["parse_failed"])
        self.assertEqual(out["state"]["current_task"], "GPU research")
        self.assertEqual(out["state"]["uncommitted_decisions"], ["buy the 5070 Ti"])

    def test_a_wrong_reply_is_flagged_not_fatal(self):
        # CONTROL: the well-formed case above passes, so a failure here is the shape, not the parser.
        prose = sd.state_of_slice(_engine_returning("Sure! Here is what I noticed: nothing."), "c", 1, 1)
        self.assertTrue(prose["parse_failed"])
        wrong_keys = sd.state_of_slice(_engine_returning(json.dumps({"summary": "x"})), "c", 1, 1)
        self.assertTrue(wrong_keys["parse_failed"])
        listed = sd.state_of_slice(_engine_returning(json.dumps({"state": ["a", "b"]})), "c", 1, 1)
        self.assertFalse(listed["parse_failed"])
        self.assertTrue(listed["state_dropped"])
        self.assertEqual(listed["state_shape"], "list")
        failed = lambda s, u, *, max_tokens=4000, timeout=None: EngineResult(False, "", "fake", "boom")
        out = sd.state_of_slice(failed, "c", 1, 1)
        self.assertTrue(out["parse_failed"])
        self.assertIn("boom", out["raw"])

    def test_a_reply_truncated_after_the_state_keeps_the_state_and_says_so(self):
        whole = json.dumps({"state": json.loads(MAP_JSON)["state"], "padding": "x" * 400})
        out = sd.state_of_slice(_engine_returning(whole[:-60]), "c", 1, 1)
        self.assertFalse(out["parse_failed"])
        self.assertTrue(out["truncated"])
        self.assertEqual(out["state"]["current_task"], "GPU research")

    def test_the_contract_is_restated_after_the_fenced_payload(self):
        # Measured 2026-09-22 on the first live dream: with the instructions only in the system
        # prompt and a 40k-token slice after them, Qwen CONTINUED the transcript instead of
        # returning JSON. The contract comes again after the payload, and the payload is fenced.
        seen = {}

        def capture(system, user, *, max_tokens=4000, timeout=None):
            seen["system"], seen["user"] = system, user
            return EngineResult(True, MAP_JSON, "fake", None)

        sd.state_of_slice(capture, "SLICE BODY", 3, 3)
        user = seen["user"]
        self.assertIs(seen["system"], sd.STATE_SYSTEM)
        self.assertLess(user.find(sd.PAYLOAD_OPEN), user.find("SLICE BODY"))
        self.assertLess(user.find("SLICE BODY"), user.find(sd.PAYLOAD_CLOSE))
        self.assertTrue(user.rstrip().endswith(sd.STATE_REMINDER.rstrip()), user[-200:])

    def test_nothing_in_the_call_asks_for_lessons_or_tensions(self):
        for text in (sd.STATE_SYSTEM, sd.STATE_REMINDER):
            for word in ("lesson", "tension"):
                self.assertNotIn(word, text.lower())

    def test_the_call_carries_the_timeout_it_is_given(self):
        seen = []

        def engine(system, user, *, max_tokens=4000, timeout=None):
            seen.append(timeout)
            return EngineResult(True, MAP_JSON, "fake", None)

        sd.state_of_slice(engine, "c", 1, 1, timeout=123)
        self.assertEqual(seen, [123])

    def test_default_chunk_is_small_enough_for_a_local_27b_to_follow(self):
        self.assertLessEqual(sd.DEFAULT_CHUNK_CHARS, 60_000)


class MechanicalAndPayloadTests(unittest.TestCase):
    def test_mechanical_state_uses_last_turns(self):
        turns = [sx.Turn("u1", "t1", "user", "please fix the gate"),
                 sx.Turn("a1", "t2", "assistant", "on it"),
                 sx.Turn("t1", "t3", "tool_use", "Bash {\"command\": \"pytest\"}"),
                 sx.Turn("a2", "t4", "assistant", "the gate is fixed; next I commit")]
        state = sd.mechanical_state(turns)
        self.assertIn("please fix the gate", state["current_task"])
        self.assertIn("the gate is fixed", state["exact_state"])
        self.assertIn("Bash", state["files_in_context"][0])

    def test_a_harness_payload_is_never_the_task(self):
        """Field report 2026-09-25 (Assay's note on 1974): a brief's Current Task was a raw
        background-task notification. The harness speaks in the user role - task notifications,
        system reminders - and none of it is a request anyone made."""
        turns = [sx.Turn("u1", "t1", "user", "please fix the gate"),
                 sx.Turn("t1", "t2", "tool_use", "Bash {\"command\": \"pytest\"}"),
                 sx.Turn("a1", "t3", "assistant", "suite running"),
                 sx.Turn("u2", "t4", "user", "<task-notification>\n<task-id>bwex0qful</task-id>"),
                 sx.Turn("u3", "t5", "user", "[SYSTEM NOTIFICATION - NOT USER INPUT] done"),
                 sx.Turn("a2", "t6", "assistant", "the gate is fixed")]
        state = sd.mechanical_state(turns)
        self.assertIn("please fix the gate", state["current_task"])
        self.assertNotIn("task-notification", state["current_task"])
        self.assertIn("Bash", " ".join(state["files_in_context"]))

    def test_a_request_that_merely_mentions_a_notification_is_still_a_request(self):
        """The control: the guard reads what a turn IS, not words it contains."""
        for text in ("why did the task-notification arrive twice?",
                     "fix the system reminder wording in the hook"):
            self.assertFalse(sd.is_system_payload(text), text)
        for text in ("<task-notification><task-id>x</task-id>", "  <system-reminder>\nhi",
                     "[SYSTEM NOTIFICATION - NOT USER INPUT]", "<local-command-stdout>ok"):
            self.assertTrue(sd.is_system_payload(text), text)

    def test_the_brief_is_ascii_and_carries_every_heading(self):
        meta = {"agent": "Joule", "session_id": "sess-0001", "engine": "fake", "when": "2026-09-22 12:00"}
        brief = sd.render_brief({"current_task": "a task — with a dash", "exact_state": "e",
                                 "next_step": "n", "uncommitted_decisions": ["d1"],
                                 "files_in_context": ["f1"]}, meta)
        self.assertTrue(all(ord(c) < 128 for c in brief), brief)
        self.assertIn("sess-0001", brief)
        for heading in ("## Current Task", "## Exact State", "## Next Step",
                        "## Uncommitted Decisions", "## Files Currently In Context"):
            self.assertIn(heading, brief)


if __name__ == "__main__":
    unittest.main()
