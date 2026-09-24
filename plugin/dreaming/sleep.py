#!/usr/bin/env python3
"""sleep.py - the pipeline: extract, map, reduce, write; the dream folder; the watermark.

Ported from the quantum-concepts sleep step. Everything about WHO is dreaming and WHERE lives in
identity.py; this module takes an out_root and an engine and does the four stages, each leaving a
file before the next engine call, and never touches anything outside <out_root>/dreams/.

INVARIANTS (each one is a test in tests/test_sleep.py):
  - never edits an index file or an existing lesson file
  - every stage is on disk before the next stage's engine call; a brief before the first
  - every fallback is named in sleep.log as 'degraded: <reason>'
  - the second sleep in a session consumes only records after the first's watermark
"""
import datetime as _dt
import json
import os
import time
import traceback

from . import distill as sd, extract as sx

DREAMS_DIRNAME = "dreams"
DEFAULT_BUDGET_SECONDS = 900    # config.DEFAULTS is the authority; keep this equal to it
DEFAULT_CHUNK_CHARS = sd.DEFAULT_CHUNK_CHARS
DEFAULT_CAP_CHARS = 400_000
DREAM_STALE_DAYS = 14
# The smallest engine call worth starting; below this remaining budget a stage is skipped.
MIN_CALL_SECONDS = 30


def dream_folder_name(session_id, now):
    return "%s-%s" % (now.strftime("%Y%m%d-%H%M%S"), (session_id or "nosession")[:8])


def _fresh_folder(out_root, session_id, now):
    """Never share a folder: two sleeps in one second get -2, -3, ... (review finding: a shared
    folder overwrote the brief, accumulated lessons, and left two watermark lines)."""
    base = os.path.join(out_root, DREAMS_DIRNAME, dream_folder_name(session_id, now))
    folder, n = base, 1
    while os.path.exists(folder):
        n += 1
        folder = "%s-%d" % (base, n)
    os.makedirs(folder)
    return folder


def _session_dreams(root, session_id):
    """Dream folders of THIS session, newest first: by name, then by mtime as the tiebreak."""
    sid8 = (session_id or "nosession")[:8]
    if not os.path.isdir(root):
        return []
    mine = []
    for name in os.listdir(root):
        stem = name.rsplit("-", 1)[0] if name.count("-") >= 3 and name.rsplit("-", 1)[1].isdigit() else name
        if stem.endswith("-" + sid8) or name.endswith("-" + sid8):
            mine.append(name)
    return sorted(mine, key=lambda n: (n, os.path.getmtime(os.path.join(root, n))), reverse=True)


def watermark_file(memory_path, session_id):
    """<store>/dreams/.watermark-<session>.txt - the per-session watermark, kept OUTSIDE the dream
    folder because promotion deletes the folder (measured 2026-09-23: the third sleep of a session
    whose two earlier dreams had been promoted logged 'after (start)', re-extracted everything,
    hit the cap and re-staged lessons already in the index). A file, not a directory, so the
    dream listings - which count every subdirectory of dreams/ as a dream - never see it."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (session_id or "nosession"))
    return os.path.join(memory_path, DREAMS_DIRNAME, ".watermark-%s.txt" % safe)


def last_watermark(memory_path, session_id):
    """The uuid the newest sleep of THIS session stopped at: the watermark file first, else the
    LAST watermark line of the newest surviving folder's sleep.log (stores written before 0.3.1)."""
    wf = watermark_file(memory_path, session_id)
    if os.path.isfile(wf):
        with open(wf, "r", encoding="utf-8", errors="replace") as fh:
            value = fh.read().strip()
        if value:
            return value
    root = os.path.join(memory_path, DREAMS_DIRNAME)
    for name in _session_dreams(root, session_id):
        log = os.path.join(root, name, "sleep.log")
        if not os.path.isfile(log):
            continue
        value = None
        with open(log, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                marker = "watermark: "
                if marker in line:
                    value = line.split(marker, 1)[1].strip() or value
        if value:
            return value
    return None


class _Log:
    def __init__(self, path):
        self.path = path
        self.degraded = []

    def write(self, line):
        stamp = _dt.datetime.now().strftime("%H:%M:%S")
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (stamp, line))

    def degrade(self, reason):
        self.degraded.append(reason)
        self.write("degraded: %s" % reason)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def run_sleep(transcript_path, *, agent, session_id, out_root, engine=None, engine_name="mechanical",
              include_thinking=False, budget_seconds=DEFAULT_BUDGET_SECONDS, index_text="",
              now=None, clock=time.monotonic, chunk_chars=DEFAULT_CHUNK_CHARS, cap_chars=DEFAULT_CAP_CHARS,
              result_head=400, min_call_seconds=MIN_CALL_SECONDS, task=None, known_rules=""):
    now = now or _dt.datetime.now()
    folder = _fresh_folder(out_root, session_id, now)
    log = _Log(os.path.join(folder, "sleep.log"))
    meta = {"agent": agent, "session_id": session_id, "engine": engine_name,
            "when": now.strftime("%Y-%m-%d %H:%M"), "task": task or ""}
    log.write("sleep start | agent: %s | session: %s | engine: %s%s" % (
        agent, session_id, engine_name, (" | task: %s" % task) if task else ""))
    started = clock()
    result = {"folder": folder, "lessons": 0, "tensions": 0, "degraded": log.degraded, "stages": {}}

    # 1. extract - on disk before any engine call
    watermark = last_watermark(out_root, session_id)
    turns, stats = sx.extract_turns(transcript_path, after_uuid=watermark, include_thinking=include_thinking,
                                     result_head=result_head)
    if stats["watermark_missing"]:
        log.degrade("watermark %s not in transcript; extracted everything" % watermark)
    day, capped = sx.render_day(turns, cap_chars=cap_chars)
    if capped:
        log.degrade("day capped at %d chars, newest kept" % cap_chars)
    _write(os.path.join(folder, "day.md"), day)
    log.write("extract | records %d | kept %d | bad lines %d | after %s" % (
        stats["records"], stats["kept"], stats["bad_lines"], watermark or "(start)"))
    committed = stats["last_uuid"] or watermark or ""
    log.write("watermark: %s" % committed)
    if committed:
        _write(watermark_file(out_root, session_id), committed)
    result["stages"]["extract"] = stats
    # A brief exists before the first engine call, so a sleep killed mid-map still re-seeds
    # something and the watermark it committed does not orphan its span (review finding).
    _write(os.path.join(folder, "brief.md"), sd.render_brief(sd.mechanical_state(turns), meta))

    state = None
    lessons, tensions = [], []
    try:
        if engine is None:
            log.degrade("no engine - mechanical brief")
            state = sd.mechanical_state(turns)
        else:
            # 2. map
            chunks = sx.chunk_text(day, max_chars=chunk_chars)
            maps = []
            for i, chunk in enumerate(chunks, 1):
                remaining = budget_seconds - (clock() - started)
                if remaining < min_call_seconds:
                    log.degrade("budget %ds exhausted after %d of %d chunks" % (budget_seconds, len(maps), len(chunks)))
                    break
                m = sd.map_chunk(engine, chunk, i, len(chunks), timeout=int(remaining))
                _write(os.path.join(folder, "map", "%d.json" % i), json.dumps(m, ensure_ascii=True, indent=1))
                if m["parse_failed"]:
                    if str(m.get("raw", "")).startswith("engine error:"):
                        log.degrade("map chunk %d engine error: %s" % (i, str(m["raw"])[14:200]))
                    else:
                        log.degrade("map chunk %d did not parse" % i)
                elif m.get("truncated"):
                    log.degrade("map chunk %d truncated (provider cap); salvaged %d lesson(s)" % (i, len(m["lessons"])))
                elif not m["lessons"] and not m["tensions"] and not m["state"].get("current_task"):
                    log.degrade("map chunk %d returned no lessons and no state" % i)
                maps.append(m)
                log.write("map | chunk %d/%d | %d chars | lessons %d" % (i, len(chunks), len(chunk), len(m["lessons"])))
            # 3. reduce
            remaining = budget_seconds - (clock() - started)
            if maps and remaining < min_call_seconds:
                log.degrade("budget %ds exhausted before reduce; using the union of the map passes" % budget_seconds)
                r = sd._union(maps)
                _write(os.path.join(folder, "reduce.json"), json.dumps(r, ensure_ascii=True, indent=1))
                lessons, tensions, state = r["lessons"], r["tensions"], r["state"]
            elif maps:
                r = sd.reduce_maps(engine, maps, index_text, max_chars=chunk_chars, timeout=int(remaining),
                                   known_rules=known_rules)
                _write(os.path.join(folder, "reduce.json"), json.dumps(r, ensure_ascii=True, indent=1))
                if r.get("gave_up"):
                    log.degrade("reduce input too large for the window; using the union of the map passes")
                if r["parse_failed"]:
                    log.degrade("reduce did not parse; falling back to the union of the map passes")
                    lessons = [l for m in maps for l in m["lessons"]]
                    tensions = [t for m in maps for t in m["tensions"]]
                else:
                    lessons, tensions = r["lessons"], r["tensions"]
                    if r.get("truncated"):
                        log.degrade("reduce reply truncated (provider cap); salvaged %d lesson(s)" % len(lessons))
                    log.write("reduce | lessons %d | tensions %d | halved %d" % (len(lessons), len(tensions), r["halved"]))
                    known = sum(1 for l in lessons if l.get("relation") == "known")
                    if known:
                        log.write("%d lesson(s) restate known rules (kept, labelled; the promoter drops them)" % known)
            # The resume state is a COPY of the newest slice's, never the reduce's choice. Two
            # field measurements on 2026-09-23: the reduce re-emitted the second-newest slice's
            # state verbatim while the newest slice held the right one; and on another run the
            # newest three slices came back empty and the reduce built a brief from six the
            # previous evening. If the newest slice was never mapped (budget) or has no state,
            # the mechanical state of the last turns is crude but true.
            if maps and len(maps) == len(chunks) and maps[-1]["state"].get("current_task"):
                state = maps[-1]["state"]
                log.write("state: copied from slice %d of %d" % (len(maps), len(chunks)))
            else:
                log.degrade("newest slice yielded no state (unmapped or empty); brief is mechanical")
                state = sd.mechanical_state(turns)
    except Exception as exc:  # the hook must never die on an engine or a bug
        log.degrade("exception: %s" % exc)
        log.write(traceback.format_exc())
        state = state or sd.mechanical_state(turns)

    # 4. write - a tension must name an entry the mind actually holds
    tensions, dropped = sd.filter_tensions(tensions, index_text)
    if dropped and not index_text:
        log.degrade("no index; tensions not filed (%d dropped)" % dropped)
    elif dropped:
        log.degrade("%d tension(s) named entries not in the index; dropped" % dropped)
    _write(os.path.join(folder, "brief.md"), sd.render_brief(state, meta))
    os.makedirs(os.path.join(folder, "lessons"), exist_ok=True)
    used = set()
    for lesson in lessons:
        slug = sd.slugify(lesson["title"])
        while slug in used:
            slug += "-2"
        used.add(slug)
        _write(os.path.join(folder, "lessons", slug + ".md"), sd.render_lesson(lesson, meta))
    _write(os.path.join(folder, "tensions.md"), sd.render_tensions(tensions, meta))
    result["lessons"], result["tensions"] = len(lessons), len(tensions)
    log.write("write | lessons %d | tensions %d | %.1fs" % (len(lessons), len(tensions), clock() - started))
    log.write("engine: %s" % engine_name)
    return result


def brief_task(text):
    """The `task <name>` stamped in a brief's header, or '' when the brief was not a routine's."""
    head = text.split(chr(10), 1)[0]
    marker = "| task "
    if marker not in head:
        return ""
    return head.split(marker, 1)[1].split("|", 1)[0].replace("-->", "").strip()


def newest_brief(memory_path, *, task="", max_age_hours=48, now=None):
    """The store's newest brief written under the SAME scheduled-task name (a routine's), or with
    no task at all for an interactive session, younger than max_age_hours. Keyed by task, not by
    store: two routines of one mind may share a store and must not receive each other's brief."""
    now = time.time() if now is None else now
    for d in dreams_awaiting(memory_path, now=now):
        path = os.path.join(d["path"], "brief.md")
        if not os.path.isfile(path):
            continue
        if d["age_days"] * 24.0 > max_age_hours:
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if brief_task(text) != (task or ""):
            continue
        return {"folder": d["path"], "name": d["name"], "text": text, "task": task or ""}
    return None


def newest_dream_for(memory_path, session_id):
    root = os.path.join(memory_path, DREAMS_DIRNAME)
    for name in _session_dreams(root, session_id):
        if os.path.isfile(os.path.join(root, name, "brief.md")):
            return os.path.join(root, name)
    return None


def dreams_awaiting(out_root, *, stale_days=DREAM_STALE_DAYS, now=None):
    """Dream folders under <out_root>/dreams/, newest first. Read-only."""
    root = os.path.join(out_root, DREAMS_DIRNAME)
    if not os.path.isdir(root):
        return []
    now = time.time() if now is None else now
    out = []
    for name in sorted(os.listdir(root), reverse=True):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        lessons_dir = os.path.join(path, "lessons")
        lessons = (len([f for f in os.listdir(lessons_dir) if f.endswith(".md")])
                   if os.path.isdir(lessons_dir) else 0)
        tensions = 0
        tpath = os.path.join(path, "tensions.md")
        if os.path.isfile(tpath):
            with open(tpath, "r", encoding="utf-8", errors="replace") as fh:
                tensions = sum(1 for line in fh if line.startswith("## IN-TENSION"))
        age_days = max(0.0, (now - os.path.getmtime(path)) / 86400.0)
        out.append({"name": name, "path": path, "lessons": lessons, "tensions": tensions,
                    "age_days": age_days, "stale": age_days > stale_days})
    return out
