#!/usr/bin/env python3
"""Transcript extraction, ported from the quantum-concepts sleep step."""
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

from dreaming import extract as sx  # noqa: E402


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _rec(kind, uuid, **extra):
    base = {"type": kind, "uuid": uuid, "timestamp": "2026-09-22T16:%02d:00.000Z" % (int(uuid[-2:]) % 60),
            "sessionId": "sess-0001", "isSidechain": False}
    base.update(extra)
    return base


def write_fixture(path, *, bad_line=True):
    """Every record type observed in a real 2026-09-22 transcript, in a plausible order.
    uuids end in two digits so the timestamp is derivable and ordering is obvious."""
    recs = [
        {"type": "queue-operation", "operation": "enqueue", "timestamp": "t", "sessionId": "sess-0001"},
        _rec("attachment", "at-0000-01", attachment={"type": "x"}),
        _rec("user", "us-0000-02", message={"role": "user", "content": "first question about GPUs"}),
        {"type": "last-prompt", "lastPrompt": "x", "sessionId": "sess-0001"},
        {"type": "custom-title", "customTitle": "x", "sessionId": "sess-0001"},
        {"type": "agent-name", "agentName": "Joule", "sessionId": "sess-0001"},
        {"type": "atis-latch", "atis": {}, "sessionId": "sess-0001"},
        {"type": "file-history-snapshot", "messageId": "m", "snapshot": {}, "isSnapshotUpdate": False},
        _rec("assistant", "as-0000-03", message={"role": "assistant", "content": [
            {"type": "thinking", "thinking": "SECRET THINKING TEXT", "signature": "sig"}]}),
        _rec("assistant", "as-0000-04", message={"role": "assistant", "content": [
            {"type": "text", "text": "Joule will look that up."}]}),
        _rec("assistant", "as-0000-05", message={"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "WebSearch",
             "input": {"query": "RTX 5080 MSRP", "extra": "x" * 500}}]}),
        _rec("user", "us-0000-06", message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1",
             "content": [{"type": "text", "text": "RESULT " + "r" * 2000}]}]}),
        _rec("system", "sy-0000-07", subtype="hook", hookCount=1),
        _rec("user", "us-0000-08", isMeta=True, message={"role": "user", "content": [
            {"type": "text", "text": "Base directory for this skill: META SKILL BODY " + "s" * 3000}]}),
        _rec("user", "us-0000-09", isSidechain=True, message={"role": "user", "content": "SIDECHAIN TEXT"}),
        _rec("user", "us-0000-10", message={"role": "user", "content": [
            {"type": "text", "text": "second question, about the 4090"}]}),
        _rec("assistant", "as-0000-11", message={"role": "assistant", "content": [
            {"type": "text", "text": "The 4090 is out of production."}]}),
        {"type": "file-history-delta", "messageId": "m", "timestamp": "t"},
    ]
    with open(path, "w", encoding="utf-8") as fh:
        for i, r in enumerate(recs):
            fh.write(json.dumps(r) + "\n")
            if bad_line and i == 3:
                fh.write("{this is not json\n")
    return path


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sleep-extract-")
        self.path = write_fixture(os.path.join(self.tmp, "t.jsonl"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_keeps_user_assistant_tool_use_and_tool_result_only(self):
        turns, stats = sx.extract_turns(self.path)
        roles = [t.role for t in turns]
        self.assertEqual(roles, ["user", "assistant", "tool_use", "tool_result", "user", "assistant"])
        self.assertEqual(stats["bad_lines"], 1)
        self.assertEqual(stats["last_uuid"], "as-0000-11")
        self.assertFalse(stats["watermark_missing"])

    def test_thinking_excluded_by_default_and_included_on_flag(self):
        turns, _ = sx.extract_turns(self.path)
        self.assertNotIn("SECRET THINKING", " ".join(t.text for t in turns))
        turns, _ = sx.extract_turns(self.path, include_thinking=True)
        joined = " ".join(t.text for t in turns)
        self.assertIn("SECRET THINKING", joined)

    def test_tool_result_trimmed_to_head_and_tool_use_names_tool(self):
        turns, _ = sx.extract_turns(self.path, result_head=50)
        result = [t for t in turns if t.role == "tool_result"][0]
        self.assertLessEqual(len(result.text), 50)
        use = [t for t in turns if t.role == "tool_use"][0]
        self.assertTrue(use.text.startswith("WebSearch "))
        self.assertLess(len(use.text), 300)

    def test_meta_and_sidechain_records_dropped(self):
        turns, _ = sx.extract_turns(self.path)
        joined = " ".join(t.text for t in turns)
        self.assertNotIn("META SKILL BODY", joined)
        self.assertNotIn("SIDECHAIN TEXT", joined)

    def test_watermark_skips_everything_up_to_and_including_it(self):
        turns, stats = sx.extract_turns(self.path, after_uuid="us-0000-06")
        self.assertEqual([t.uuid for t in turns], ["us-0000-10", "as-0000-11"])
        self.assertFalse(stats["watermark_missing"])

    def test_missing_watermark_extracts_all_and_flags(self):
        turns, stats = sx.extract_turns(self.path, after_uuid="no-such-uuid")
        self.assertEqual(len(turns), 6)
        self.assertTrue(stats["watermark_missing"])

    def test_render_day_marks_turns_and_caps_keeping_newest(self):
        turns, _ = sx.extract_turns(self.path)
        text, capped = sx.render_day(turns)
        self.assertFalse(capped)
        self.assertTrue(text.startswith(sx.TURN_MARK + "user"))
        self.assertIn("[us-0000-02]", text)
        small, capped = sx.render_day(turns, cap_chars=120)
        self.assertTrue(capped)
        self.assertIn("as-0000-11", small)
        self.assertNotIn("us-0000-02", small)

    def test_a_capped_day_never_opens_on_a_tool_result(self):
        """Field report 2026-09-23: the kept window opened on an orphan tool_result whose
        tool_use fell on the far side of the cap, so the first slice began with an answer to a
        question the model never sees. Trim to a user or assistant turn."""
        T = sx.Turn
        turns = [T("u1", "t", "user", "q" * 100), T("a1", "t", "assistant", "a" * 100),
                 T("tu", "t", "tool_use", "x" * 100), T("tr", "t", "tool_result", "r" * 100),
                 T("u2", "t", "user", "the LAST question"), T("a2", "t", "assistant", "final")]
        text, capped = sx.render_day(turns, cap_chars=220)
        self.assertTrue(capped)
        self.assertTrue(text.startswith(sx.TURN_MARK + "user"), text[:60])
        self.assertNotIn("[tr]", text)
        self.assertIn("the LAST question", text)

    def test_chunk_text_splits_on_turn_boundaries(self):
        turns, _ = sx.extract_turns(self.path)
        text, _ = sx.render_day(turns)
        # 600 is larger than any single fixture turn (the 400-char tool_result is the biggest),
        # so every split here is a boundary split; hard splits are the next test's subject.
        chunks = sx.chunk_text(text, max_chars=600)
        self.assertGreater(len(chunks), 1)
        for c in chunks[1:]:
            self.assertTrue(c.startswith(sx.TURN_MARK), c[:40])
        self.assertEqual("".join(chunks).replace("\n", ""), text.replace("\n", ""))

    def test_transcript_agent_name_is_read_from_the_agent_name_record(self):
        self.assertEqual(sx.transcript_agent_name(self.path), "Joule")
        empty = os.path.join(self.tmp, "no-name.jsonl")
        with open(empty, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user", "uuid": "u", "message": {"role": "user", "content": "x"}}) + "\n")
        self.assertIsNone(sx.transcript_agent_name(empty))

    def test_chunk_text_hard_splits_one_oversized_turn(self):
        text = sx.TURN_MARK + "user @t [u1]\n" + "x" * 1000
        chunks = sx.chunk_text(text, max_chars=300)
        self.assertGreaterEqual(len(chunks), 4)




if __name__ == "__main__":
    unittest.main()
