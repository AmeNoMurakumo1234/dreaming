#!/usr/bin/env python3
"""extract.py - a Claude Code transcript (JSONL) to the turns worth dreaming about.

Ported from the quantum-concepts sleep step (its spec: docs/superpowers/specs/2026-09-22-sleep-step-design.md there).

Pure: reads one file, returns turns and stats, writes nothing. The transcript can be hundreds
of megabytes (one on this machine is 364 MB), so it is streamed line by line and never held
whole. Tool results are the bulk of that size and the least of the meaning, so they are cut to
a short head; thinking blocks are dropped unless asked for; harness records (attachments,
queue operations, snapshots, titles, latches, system hook records) are skipped outright.

Two records that LOOK like the user's words are not: `isMeta` user records are skill bodies
the harness injected (thousands of lines each), and `isSidechain` records belong to subagent
threads. Both are dropped, or every dream is dominated by text nobody said.
"""
import json
import re
from collections import namedtuple

Turn = namedtuple("Turn", "uuid timestamp role text")

TURN_MARK = "### "
KEPT_TYPES = ("user", "assistant")


def _texts_from_content(record_type, content, *, include_thinking, result_head):
    """Yield (role, text) for the blocks of one message record."""
    if isinstance(content, str):
        yield (record_type, content)
        return
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            yield (record_type, str(block.get("text") or ""))
        elif kind == "thinking" and include_thinking:
            yield ("assistant", "[thinking] " + str(block.get("thinking") or "")[:result_head * 2])
        elif kind == "tool_use":
            name = str(block.get("name") or "?")
            try:
                first = json.dumps(block.get("input"), ensure_ascii=True)[:200]
            except (TypeError, ValueError):
                first = ""
            yield ("tool_use", "%s %s" % (name, first))
        elif kind == "tool_result":
            inner = block.get("content")
            if isinstance(inner, list):
                inner = " ".join(str(b.get("text") or "") for b in inner
                                 if isinstance(b, dict) and b.get("type") == "text")
            yield ("tool_result", str(inner or "")[:result_head])


def _uuid_present(path, wanted):
    """Is this uuid anywhere in the file? A cheap substring scan, so a rotated or foreign
    transcript is detected before the main pass silently skips everything."""
    needle = '"uuid": "%s"' % wanted
    needle2 = '"uuid":"%s"' % wanted
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if needle in line or needle2 in line:
                return True
    return False


def extract_turns(path, *, after_uuid=None, include_thinking=False, result_head=400):
    """Return (turns, stats). With after_uuid, only records AFTER that uuid are returned; if
    the uuid is not in the file at all, everything is returned and stats['watermark_missing']
    is True - extracting nothing on a bad watermark would be the silent failure this repo
    keeps naming."""
    stats = {"records": 0, "kept": 0, "bad_lines": 0, "last_uuid": None,
             "watermark_missing": False}
    skipping = after_uuid is not None
    if skipping and not _uuid_present(path, after_uuid):
        skipping = False
        stats["watermark_missing"] = True
    turns = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stats["records"] += 1
            try:
                rec = json.loads(line)
            except ValueError:
                stats["bad_lines"] += 1
                continue
            if not isinstance(rec, dict) or rec.get("type") not in KEPT_TYPES:
                continue
            uuid = str(rec.get("uuid") or "")
            if skipping:
                if uuid == after_uuid:
                    skipping = False
                continue
            if rec.get("isMeta") or rec.get("isSidechain"):
                continue
            message = rec.get("message") or {}
            content = message.get("content") if isinstance(message, dict) else None
            for role, text in _texts_from_content(rec["type"], content,
                                                  include_thinking=include_thinking,
                                                  result_head=result_head):
                text = text.strip()
                if not text:
                    continue
                turns.append(Turn(uuid, str(rec.get("timestamp") or ""), role, text))
                stats["kept"] += 1
            stats["last_uuid"] = uuid or stats["last_uuid"]
    return turns, stats


def transcript_agent_name(path):
    """The session's own identity: the LAST `agent-name` record's agentName, or None. Cheap
    substring pre-filter so a 364 MB transcript is not JSON-parsed line by line for this."""
    found = None
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"agent-name"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("type") == "agent-name":
                name = str(rec.get("agentName") or "").strip()
                if name:
                    found = name
    return found


_TASK_TAG = re.compile(r'<scheduled-task[^>]*name="([^"]+)"')


def scheduled_task_name(path):
    """The `name` of a <scheduled-task ...> tag in the transcript's FIRST user turn, or None.
    A scheduled run's first turn carries the task's name on every run - the lane, where git
    user.name and a configured agent are per box and the agent-name record is the session title
    (field report 2026-09-23; measured in this house on pm-agent, book-content-agent and
    web-gui-product). Only the first user turn counts: a tag quoted later is not an identity."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"user"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict) or rec.get("type") != "user":
                continue
            content = (rec.get("message") or {}).get("content")
            if isinstance(content, list):
                content = " ".join(str(b.get("text") or "") for b in content if isinstance(b, dict))
            m = _TASK_TAG.search(str(content or ""))
            return m.group(1).strip() if m else None
    return None


def _render_turn(turn):
    return "%s%s @%s [%s]\n%s\n\n" % (TURN_MARK, turn.role, turn.timestamp, turn.uuid, turn.text)


def render_day(turns, *, cap_chars=400_000):
    """One text, newest turns kept when the cap bites. Returns (text, capped)."""
    pairs = [(t.role, _render_turn(t)) for t in turns]
    total = sum(len(r) for _, r in pairs)
    capped = False
    while pairs and total > cap_chars:
        total -= len(pairs.pop(0)[1])
        capped = True
    if capped:
        # Open on a user or assistant turn, never on an orphan tool_result whose tool_use fell
        # on the far side of the cap (field report 2026-09-23) - unless that would empty the day.
        i = 0
        while i < len(pairs) and pairs[i][0] not in ("user", "assistant"):
            i += 1
        if i < len(pairs):
            pairs = pairs[i:]
    return "".join(r for _, r in pairs), capped


def chunk_text(text, *, max_chars=160_000):
    """Split on turn boundaries, never inside a turn unless one turn alone exceeds the cap."""
    pieces = []
    for i, part in enumerate(text.split("\n" + TURN_MARK)):
        pieces.append(part if i == 0 else "\n" + TURN_MARK + part)
    chunks, current = [], ""
    for piece in pieces:
        while len(piece) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(piece[:max_chars])
            piece = piece[max_chars:]
        if len(current) + len(piece) > max_chars and current:
            chunks.append(current)
            current = ""
        current += piece
    if current:
        chunks.append(current)
    return [c.lstrip("\n") if i else c for i, c in enumerate(chunks)]
