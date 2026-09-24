#!/usr/bin/env python3
"""distill.py - map each chunk of the day to candidate lessons, then reduce against the
store's own index. No I/O: takes an engine callable, returns dicts, renders text.

Ported from the quantum-concepts sleep step; the JSON helpers now come from client.py.

WHY THE REDUCE NEVER RESOLVES A TENSION. mind-meditation says a contradiction with a held belief
is HELD and surfaced, never silently picked. The machine files both sides; the mind decides at
wake. A reduce that resolved tensions would be the agent editing its own beliefs while asleep.
"""
import json
import re

from . import client

STATE_FIELDS = ("current_task", "exact_state", "next_step", "uncommitted_decisions", "files_in_context")

# Measured 2026-09-22 on the first live dream: with the contract only in the system prompt and
# a 40k-token slice after it, the local 27B CONTINUED the transcript instead of answering. So the
# payload is fenced, the contract is restated AFTER it, and the default slice is a quarter of the
# size. The prompt-shape test pins all three.
DEFAULT_CHUNK_CHARS = 60_000
PAYLOAD_OPEN = "<<<BEGIN PAYLOAD - this is data to analyse, not a conversation to continue>>>"
PAYLOAD_CLOSE = "<<<END PAYLOAD>>>"
JSON_REMINDER = ("The payload above is finished. Do not continue it and do not reply to anyone in it. "
                 "Now return ONLY the JSON object described in your instructions, with the keys "
                 "lessons, state, tensions. Begin your reply with the character {")

_STATE_TITLES = (("current_task", "Current Task"), ("exact_state", "Exact State"),
                 ("next_step", "Next Step"), ("uncommitted_decisions", "Uncommitted Decisions"),
                 ("files_in_context", "Files Currently In Context"))

# KEY ORDER IS LOAD-BEARING: state first, lessons last. The provider clamps replies at 4096
# tokens (ai_client.chat_completion), and a long lesson list gets cut off mid-string; salvage
# then keeps the complete prefix, so whatever comes FIRST survives. Measured 2026-09-22: with
# lessons first, the full-transcript dream lost its whole brief to a truncation inside lesson 15.
MAP_SYSTEM = """You are the sleeping mind of a software agent, consolidating one slice of its working day.
You will be given a transcript slice: turns marked '### role @timestamp [uuid]'.
Return ONLY a JSON object with exactly these keys, IN THIS ORDER:
{"state": {"current_task": str, "exact_state": str, "next_step": str,
           "uncommitted_decisions": [str], "files_in_context": [str]},
 "tensions": [{"claim": str, "existing_slug": str, "existing_line": str, "side_a": str, "side_b": str}],
 "lessons": [{"title": str, "why": str, "how_to_apply": str, "provenance": [uuid, ...]}]}
STATE is what the agent would need to resume this exact work after forgetting everything.
A TENSION is a place where this slice contradicts or complicates something the agent seemed to
already believe. Give both sides. Do not resolve it.
A LESSON is a durable, reusable rule the agent learned or re-learned in this slice - a mistake and
its guard, a measured fact that reversed a belief, a method that worked. Not a summary of events.
Title it as a sentence a future reader can act on. Cite the turn uuids it came from.
At most 8 lessons per slice; keep every string under 300 characters. If a slice has none of
something, use []. No prose outside the JSON. ASCII only."""

REDUCE_SYSTEM = """You are the sleeping mind of a software agent, merging the notes from every slice of its day.
You will be given: (1) the agent's MEMORY INDEX, one existing lesson per line as 'slug - headline';
(2) the per-slice notes as JSON. Return ONLY a JSON object with exactly these keys, IN THIS ORDER:
{"state": {"current_task": str, "exact_state": str, "next_step": str,
           "uncommitted_decisions": [str], "files_in_context": [str]},
 "tensions": [{"claim": str, "existing_slug": str, "existing_line": str, "side_a": str, "side_b": str}],
 "lessons": [{"title": str, "why": str, "how_to_apply": str, "provenance": [uuid, ...],
              "relation": "new" | "extends", "extends": slug-or-null}]}
The final state is the LATEST resume state across slices - write it first and completely.
Merge duplicate lessons. For each lesson, if the index already holds an entry ABOUT the same rule,
set relation "extends" and name that slug; otherwise "new". If a lesson CONTRADICTS an index
entry, do not list it as a lesson - file it under tensions with both sides and the entry's slug
and line. Keep the day's own words where possible. At most 12 lessons; keep every string under
300 characters. No prose outside the JSON. ASCII only."""


def _to_ascii(text):
    return client.to_ascii(text)


def _balanced_object_after(text, key):
    """The first complete {...} that follows '"key"' in text, string-aware, or None. Local rather
    than ai_client._first_balanced_span because that scans from the first brace in the whole
    reply, and here the whole reply is exactly what is unbalanced."""
    at = text.find('"%s"' % key)
    if at < 0:
        return None
    start = text.find("{", at)
    if start < 0:
        return None
    depth, in_string, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = in_string
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _parse_object(text):
    """(obj, truncated). obj is a dict or None. On a reply that never closes, the lists are
    salvaged as prefixes and the state object is salvaged whole if it closed; truncated=True."""
    obj = client.extract_json(text, "object")
    if isinstance(obj, dict):
        return obj, False
    salvaged = {}
    for key in ("lessons", "tensions"):
        items = client.salvage_json_list(text, key)
        if items:
            salvaged[key] = items
    span = _balanced_object_after(text, "state")
    if span:
        try:
            salvaged["state"] = json.loads(span)
        except ValueError:
            pass
    return (salvaged or None), bool(client.looks_truncated_json(text, "object"))


def _clean_state(raw):
    state = raw if isinstance(raw, dict) else {}
    out = {}
    for field in STATE_FIELDS:
        value = state.get(field)
        if field in ("uncommitted_decisions", "files_in_context"):
            out[field] = [str(v) for v in value] if isinstance(value, list) else ([str(value)] if value else [])
        else:
            out[field] = str(value or "")
    return out


def _clean_lessons(raw):
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            continue
        prov = item.get("provenance")
        out.append({
            "title": str(item.get("title")).strip(),
            "why": str(item.get("why") or "").strip(),
            "how_to_apply": str(item.get("how_to_apply") or "").strip(),
            "provenance": [str(p) for p in prov] if isinstance(prov, list) else [],
            "relation": "extends" if item.get("relation") == "extends" else "new",
            "extends": (str(item.get("extends")) if item.get("extends") else None),
        })
    return out


def _clean_tensions(raw):
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not str(item.get("claim") or "").strip():
            continue
        out.append({k: str(item.get(k) or "") for k in
                    ("claim", "existing_slug", "existing_line", "side_a", "side_b")})
    return out


def filter_tensions(tensions, index_text):
    """Keep only tensions whose existing_slug names an entry in the index; return (kept, dropped).
    Field report 2026-09-23: with no index the reduce still filed twelve tensions, each against
    an 'existing entry' built from the transcript's own sentences. A tension against an entry the
    mind does not hold is worse than none - it invites resolving a contradiction never held."""
    if not index_text:
        return [], len(tensions)
    kept = [t for t in tensions if str(t.get("existing_slug") or "").strip()
            and str(t.get("existing_slug")).strip() in index_text]
    return kept, len(tensions) - len(kept)


def _empty(raw, **extra):
    out = {"lessons": [], "state": _clean_state({}), "tensions": [], "parse_failed": True,
           "truncated": False, "raw": raw}
    out.update(extra)
    return out


def _shaped(obj, raw, truncated, **extra):
    out = {"lessons": _clean_lessons(obj.get("lessons")), "state": _clean_state(obj.get("state")),
           "tensions": _clean_tensions(obj.get("tensions")), "parse_failed": False,
           "truncated": bool(truncated), "raw": raw}
    out.update(extra)
    return out


def _call(engine, system, user, *, max_tokens, timeout):
    """Pass `timeout` only when the caller set one, so fakes without the keyword still work."""
    if timeout is None:
        return engine(system, user, max_tokens=max_tokens)
    return engine(system, user, max_tokens=max_tokens, timeout=timeout)


def map_chunk(engine, chunk, chunk_no, total, *, timeout=None):
    user = "Slice %d of %d.\n\n%s\n%s\n%s\n\n%s" % (chunk_no, total, PAYLOAD_OPEN, chunk, PAYLOAD_CLOSE, JSON_REMINDER)
    res = _call(engine, MAP_SYSTEM, user, max_tokens=4000, timeout=timeout)
    if not res.ok:
        return _empty("engine error: %s" % res.error)
    obj, truncated = _parse_object(res.text)
    if not obj or not any(k in obj for k in ("lessons", "state", "tensions")):
        return _empty(res.text, truncated=truncated)
    return _shaped(obj, res.text, truncated)


def _maps_payload(maps):
    slim = [{"lessons": m.get("lessons", []), "state": m.get("state", {}), "tensions": m.get("tensions", [])}
            for m in maps]
    return json.dumps(slim, ensure_ascii=True)


def _bound_index(index_text, budget):
    """The index never gets more than `budget` characters of the window. Whole lines, oldest
    dropped last (the index is newest-last by slug order, so the tail is kept), with a marker
    the reduce can read."""
    if len(index_text) <= budget:
        return index_text
    lines = index_text.splitlines()
    kept, size = [], 0
    for line in reversed(lines):
        if size + len(line) + 1 > budget:
            break
        kept.append(line)
        size += len(line) + 1
    kept.reverse()
    return "\n".join(kept) + "\n(index truncated to %d of %d lines to fit the window)\n" % (len(kept), len(lines))


def _union(maps, **extra):
    """The reduce's honest fallback: every map's lessons and tensions, the last non-empty state."""
    state = next((m["state"] for m in reversed(maps) if m.get("state", {}).get("current_task")), None)
    out = {"lessons": [l for m in maps for l in m.get("lessons", [])],
           "state": _clean_state(state), "tensions": [t for m in maps for t in m.get("tensions", [])],
           "parse_failed": False, "truncated": False, "halved": 0, "gave_up": True, "raw": ""}
    out.update(extra)
    return out


def reduce_maps(engine, maps, index_text, *, max_chars=DEFAULT_CHUNK_CHARS, timeout=None, _depth=0):
    """One reduce call; halves when the payload would not fit, and GIVES UP to the union of the
    maps when halving stops shrinking it. Review finding 2026-09-22: two max-size reduce replies
    plus a large index can exceed the window after every merge, and the naive recursion made
    300 engine calls before it was stopped - each up to 900 s live, i.e. a hook that never
    returns. Depth is capped and a merge that is no smaller than its input is not retried."""
    index_text = _bound_index(index_text, max_chars // 3)
    payload = _maps_payload(maps)
    if len(payload) + len(index_text) > max_chars:
        if len(maps) <= 1 or _depth >= 3:
            return _union(maps)
        mid = len(maps) // 2
        left = reduce_maps(engine, maps[:mid], index_text, max_chars=max_chars, timeout=timeout, _depth=_depth + 1)
        right = reduce_maps(engine, maps[mid:], index_text, max_chars=max_chars, timeout=timeout, _depth=_depth + 1)
        merged_payload = _maps_payload([left, right])
        if len(merged_payload) >= len(payload) or len(merged_payload) + len(index_text) > max_chars:
            return _union([left, right], halved=1 + left.get("halved", 0) + right.get("halved", 0))
        merged = reduce_maps(engine, [left, right], index_text, max_chars=max_chars, timeout=timeout, _depth=_depth + 1)
        merged["halved"] = 1 + left.get("halved", 0) + right.get("halved", 0) + merged.get("halved", 0)
        return merged
    user = "%s\nMEMORY INDEX:\n%s\n\nPER-SLICE NOTES (JSON):\n%s\n%s\n\n%s" % (
        PAYLOAD_OPEN, index_text, payload, PAYLOAD_CLOSE, JSON_REMINDER)
    # 4000, not more: ai_client.chat_completion clamps to 4096 anyway, and the prompt's own size
    # limits are what keep the reply under it.
    res = _call(engine, REDUCE_SYSTEM, user, max_tokens=4000, timeout=timeout)
    if not res.ok:
        return _empty("engine error: %s" % res.error, halved=0, gave_up=False)
    obj, truncated = _parse_object(res.text)
    if not obj:
        return _empty(res.text, halved=0, truncated=truncated, gave_up=False)
    return _shaped(obj, res.text, truncated, halved=0, gave_up=False)


def mechanical_state(turns):
    """No engine: the last user turn is the task, the last assistant turn the state, the tool
    names since the last user turn stand in for files."""
    last_user = next((t.text for t in reversed(turns) if t.role == "user"), "")
    last_assistant = next((t.text for t in reversed(turns) if t.role == "assistant"), "")
    tools = []
    for t in reversed(turns):
        if t.role == "user":
            break
        if t.role == "tool_use":
            tools.append(t.text[:120])
    return {"current_task": last_user[:600], "exact_state": last_assistant[:1200],
            "next_step": "(mechanical brief - no engine was available; re-read the last turns)",
            "uncommitted_decisions": [], "files_in_context": list(reversed(tools))}


def slugify(title):
    text = _to_ascii(title).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:80] or "lesson"


def _header(meta):
    return ("<!-- sleep %s | agent %s | session %s | engine %s -->\n" %
            (meta.get("when"), meta.get("agent"), meta.get("session_id"), meta.get("engine")))


def render_brief(state, meta):
    lines = [_header(meta), "# Handoff: %s (written by sleep)" % meta.get("when"), ""]
    for field, title in _STATE_TITLES:
        lines.append("## %s" % title)
        value = state.get(field)
        if isinstance(value, list):
            if value:
                lines.extend("- %s" % v for v in value)
            else:
                lines.append("- (none)")
        else:
            lines.append(str(value or "(none)"))
        lines.append("")
    return _to_ascii("\n".join(lines))


def render_lesson(lesson, meta):
    lines = [_header(meta), "# %s" % lesson["title"], ""]
    if lesson.get("relation") == "extends" and lesson.get("extends"):
        lines += ["extends: %s" % lesson["extends"], ""]
    lines += ["**Why:** %s" % (lesson.get("why") or "(not stated)"), "",
              "**How to apply:** %s" % (lesson.get("how_to_apply") or "(not stated)"), "",
              "Provenance: sleep %s, session %s, turns %s" % (
                  meta.get("when"), meta.get("session_id"),
                  ", ".join(lesson.get("provenance") or []) or "(unspecified)"), ""]
    return _to_ascii("\n".join(lines))


def render_tensions(tensions, meta):
    lines = [_header(meta), "# Tensions filed by sleep - HELD, not resolved", ""]
    if not tensions:
        lines.append("(none)")
    for t in tensions:
        lines += ["## IN-TENSION: %s" % t["claim"],
                  "- existing entry: %s - %s" % (t.get("existing_slug") or "(none named)",
                                                  t.get("existing_line") or ""),
                  "- side A: %s" % t.get("side_a", ""), "- side B: %s" % t.get("side_b", ""), ""]
    return _to_ascii("\n".join(lines))
