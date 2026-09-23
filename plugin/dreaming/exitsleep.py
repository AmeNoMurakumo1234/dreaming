"""exitsleep.py - sleep at SESSION END, detached.

Claude Code caps SessionEnd hooks at 60 s (a 1.5 s shared budget that the timeout field can raise
to 60), and a sleep costs 70-220 s measured, so the hook cannot sleep. It decides in well under a
second - is there enough new transcript since the last watermark to be worth a dream? - and hands
the sleep to a DETACHED child: python.exe with CREATE_NO_WINDOW (so nothing flashes and its own
children inherit a windowless console), CREATE_NEW_PROCESS_GROUP and CREATE_BREAKAWAY_FROM_JOB (so
the harness tearing down its job does not take the child with it). Measured 2026-09-23: such a
child ran a full 90 s after `claude -p` had exited and spawned git windowlessly at the end.

The child is the ordinary `sleep` command, so the dream is written exactly as at compaction; the
next session's start notice reports it. The hook prints one line and always exits 0.
"""
import json
import os
import subprocess
import sys

from . import extract as sx

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

DETACHED_FLAGS = (CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB) if os.name == "nt" else 0
FALLBACK_FLAGS = (CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0

DEFAULT_MIN_CHARS = 20000

Popen = subprocess.Popen      # module attribute so tests can swap it


def settings(cfg):
    se = (cfg or {}).get("sessionend")
    se = se if isinstance(se, dict) else {}
    try:
        min_chars = int(se.get("min_chars", DEFAULT_MIN_CHARS))
    except (TypeError, ValueError):
        min_chars = DEFAULT_MIN_CHARS
    return {"enabled": bool(se.get("enabled", True)), "min_chars": max(0, min_chars)}


def new_chars(transcript, *, watermark=None, include_thinking=False, result_head=400):
    """Chars of rendered day AFTER the watermark: the same extraction the sleep will run."""
    turns, stats = sx.extract_turns(transcript, after_uuid=watermark, include_thinking=include_thinking,
                                    result_head=result_head)
    day, _capped = sx.render_day(turns)
    return len(day), stats


def decide(cfg, transcript, *, watermark=None):
    """('spawn', chars) or ('skip', reason). Fast: one pass over the transcript, no engine."""
    if not (cfg or {}).get("enabled", True):
        return "skip", "disabled"
    se = settings(cfg)
    if not se["enabled"]:
        return "skip", "sessionend disabled"
    if not transcript or not os.path.isfile(str(transcript)):
        return "skip", "transcript not found: %r" % (transcript,)
    chars, stats = new_chars(transcript, watermark=watermark, include_thinking=bool((cfg or {}).get("include_thinking")),
                             result_head=int((cfg or {}).get("result_head") or 400))
    if chars < se["min_chars"]:
        return "skip", "%d chars since watermark, below sessionend.min_chars %d" % (chars, se["min_chars"])
    return "spawn", chars


def child_argv(hook, project, engine="auto"):
    """The detached child is the plain `sleep` command with the hook JSON on argv (it is a few
    hundred bytes; the prompt-sized payloads that need stdin never travel this way)."""
    payload = {k: hook.get(k) for k in ("session_id", "transcript_path", "cwd", "scratchpad_dir", "reason")
               if hook.get(k) is not None}
    argv = [sys.executable, "-m", "dreaming.cli", "--project", str(project), "sleep", "--hook-json", json.dumps(payload)]
    if engine and engine != "auto":
        argv += ["--engine", engine]
    return argv


def spawn_detached(argv, log_path, *, cwd, popen=None):
    """(pid, label) or (None, error). Tries the breakaway flags first; a job that forbids
    breakaway refuses the spawn with an OSError, and the plain windowless flags are the fallback.
    stdin is DEVNULL and stdout/stderr go to log_path, so the child holds no handle on the
    session's console and the session can exit."""
    popen = popen or Popen
    os.makedirs(os.path.dirname(os.path.abspath(log_path)) or ".", exist_ok=True)
    errors = []
    for flags, label in ((DETACHED_FLAGS, "breakaway"), (FALLBACK_FLAGS, "no-breakaway")):
        try:
            with open(log_path, "a", encoding="utf-8") as log:
                proc = popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                             close_fds=True, creationflags=flags, cwd=cwd)
            return proc.pid, label
        except OSError as exc:
            errors.append("%s: %s" % (label, exc))
    return None, "; ".join(errors)
