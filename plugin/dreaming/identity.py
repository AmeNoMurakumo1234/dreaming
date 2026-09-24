#!/usr/bin/env python3
"""identity.py - who is dreaming, and where the dream goes.

Agent name, in the configured order: DREAMING_AGENT (env), a configured `agent` that is not
"auto" (config), the transcript's own agent-name record, git config user.name in the project,
then `default`. The name becomes a path component, so it is validated: separators, `..`,
reserved characters, blanks and absurd lengths fall back to `default` with the source marked
`invalid`.

Store: if the effective config carries an `agents` map, the map decides - a mapped name goes to
its path, an unmapped name goes to scratch with a reason, because a map is a statement of who
lives here. Without a map the store is store_root/<agent> and is created on first use.

A MAPPED store whose directory is missing is never created. A lost store must not be silently
rebuilt by the tool that serves it; the dream goes to scratch and the hook prints why.
"""
import os
import subprocess
import tempfile
from collections import namedtuple

from . import extract

Resolution = namedtuple("Resolution", "agent source store scratch reason")

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
SCRATCH_SUBDIR = "dreaming"
INDEX_LINE_CAP = 118


def _git_user_name(cwd, run):
    try:
        done = run(["git", "config", "user.name"], cwd=cwd or None, capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=20, creationflags=_NO_WINDOW)
        return (done.stdout or "").strip()
    except Exception:
        return ""


_RESERVED = set('<>:"|?*/\\') | {chr(i) for i in range(32)}
MAX_NAME = 64


def safe_name(name):
    """The name as a single path component, or None when it cannot be one."""
    name = str(name or "").strip()
    if not name or name in (".", "..") or len(name) > MAX_NAME or any(ch in _RESERVED for ch in name):
        return None
    return name


def _candidate(name, source):
    """(name, source) with the validation applied: an unusable name becomes default, marked."""
    ok = safe_name(name)
    if ok is None:
        return "default", "%s:invalid-name" % source
    return ok, source


def agent_candidates(cfg, cwd, transcript, env, run=subprocess.run, task_hint=None):
    """Every source's name, in the configured order, as (name, source). `default` closes the list.
    `task_hint` is a scheduled-task name the caller already holds (the first prompt carries it);
    it stands in for the transcript read, which at SessionStart(startup) finds nothing (1999)."""
    env = os.environ if env is None else env
    configured = str(cfg.get("agent") or "auto").strip()
    out = []
    for source in cfg.get("identity_order") or ["scheduled_task", "env", "config", "transcript", "git", "default"]:
        if source == "scheduled_task" and task_hint:
            out.append(_candidate(task_hint, "scheduled_task"))
        elif source == "scheduled_task" and transcript and os.path.isfile(transcript):
            try:
                name = extract.scheduled_task_name(transcript) or ""
            except Exception:
                name = ""
            if name:
                out.append(_candidate(name, "scheduled_task"))
        elif source == "env":
            name = str(env.get("DREAMING_AGENT") or "").strip()
            if name:
                out.append(_candidate(name, "env"))
        elif source == "config":
            if configured and configured.lower() != "auto":
                out.append(_candidate(configured, "config"))
        elif source == "transcript" and transcript and os.path.isfile(transcript):
            try:
                name = extract.transcript_agent_name(transcript) or ""
            except Exception:
                name = ""
            if name:
                out.append(_candidate(name, "transcript"))
        elif source == "git":
            name = _git_user_name(cwd, run)
            if name:
                out.append(_candidate(name, "git"))
        elif source == "default":
            out.append(("default", "default"))
    if not out or out[-1][0] != "default":
        out.append(("default", "default"))
    return out


def agent_name(cfg, cwd, transcript, env, run=subprocess.run):
    return agent_candidates(cfg, cwd, transcript, env, run)[0]


def scratch_root(hook, cfg=None):
    hook = hook or {}
    if hook.get("scratchpad_dir"):
        root = os.path.join(str(hook["scratchpad_dir"]), SCRATCH_SUBDIR)
    else:
        root = os.path.join(tempfile.gettempdir(), SCRATCH_SUBDIR)
    os.makedirs(root, exist_ok=True)
    return root


def resolve(cfg, cwd, transcript=None, env=None, run=subprocess.run, hook=None, task_hint=None):
    candidates = agent_candidates(cfg, cwd, transcript, env, run, task_hint=task_hint)
    name, source = candidates[0]
    agents = cfg.get("agents") or {}
    if agents:
        # With a map, the FIRST source whose name is mapped wins. Measured 2026-09-22: the desktop
        # app's transcript agent-name record carries the session TITLE, so trusting the first
        # source alone sent a real session to scratch while git config named the agent correctly.
        for cand, src in candidates:
            path = agents.get(cand)
            if not path:
                continue
            if not os.path.isdir(path):
                return Resolution(cand, src, scratch_root(hook, cfg), True,
                                  "mapped store for %s is missing at %s; not creating it; dreaming into scratch" % (cand, path))
            return Resolution(cand, src, path, False, "%s (%s) -> %s" % (cand, src, path))
        tried = ", ".join("%s (%s)" % (c, s) for c, s in candidates if s != "default")
        if str(cfg.get("agents_fallback") or "scratch") == "store_root":
            store = os.path.normpath(os.path.join(str(cfg.get("store_root") or ""), name))
            return Resolution(name, source, store, False,
                              "none of [%s] is in the agents map; agents_fallback store_root -> %s" % (tried or "no name found", store))
        return Resolution(name, source, scratch_root(hook, cfg), True,
                          "none of [%s] is in the agents map; dreaming into scratch" % (tried or "no name found"))
    store = os.path.normpath(os.path.join(str(cfg.get("store_root") or ""), name))
    return Resolution(name, source, store, False, "%s (%s) -> %s" % (name, source, store))


def ensure_store(res):
    """Create the resolved DEFAULT store. Called by the one command that is about to write a
    dream (sleep, or a non-dry dream), never by notice, reseed, list or a dry run - review
    finding: every hook call used to create the directory before anything was validated. A
    mapped store is never created here either: resolve() already sent a missing one to scratch."""
    if not res.scratch:
        os.makedirs(res.store, exist_ok=True)
    return res.store


def _index_lines(path):
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip(chr(10))
            if not line.strip():
                continue
            out.append(line if len(line) <= INDEX_LINE_CAP else line[:INDEX_LINE_CAP - 3].rstrip() + "...")
    return out


def index_paths(store, cfg, agent=None):
    """The index file(s) for this agent: the `indexes` map's list when it names the agent (absolute
    or ~-relative, several allowed - a lane whose real index lives outside its store), else the
    one <store>/<index_file>."""
    listed = (cfg.get("indexes") or {}).get(agent or "")
    if isinstance(listed, str):
        listed = [listed]
    if listed:
        return [os.path.expanduser(str(p)) for p in listed]
    return [os.path.join(store, str(cfg.get("index_file") or "MEMORY.md"))]


def index_text(store, cfg, agent=None):
    """One bounded line per non-blank line of every index file, in order; '' if none exist."""
    out = []
    for path in index_paths(store, cfg, agent):
        out.extend(_index_lines(path))
    return chr(10).join(out) + (chr(10) if out else "")
