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


def agent_name(cfg, cwd, transcript, env, run=subprocess.run):
    env = os.environ if env is None else env
    configured = str(cfg.get("agent") or "auto").strip()
    for source in cfg.get("identity_order") or ["env", "config", "transcript", "git", "default"]:
        if source == "env":
            name = str(env.get("DREAMING_AGENT") or "").strip()
            if name:
                return _candidate(name, "env")
        elif source == "config":
            if configured and configured.lower() != "auto":
                return _candidate(configured, "config")
        elif source == "transcript" and transcript and os.path.isfile(transcript):
            try:
                name = extract.transcript_agent_name(transcript) or ""
            except Exception:
                name = ""
            if name:
                return _candidate(name, "transcript")
        elif source == "git":
            name = _git_user_name(cwd, run)
            if name:
                return _candidate(name, "git")
        elif source == "default":
            return "default", "default"
    return "default", "default"


def scratch_root(hook, cfg=None):
    hook = hook or {}
    if hook.get("scratchpad_dir"):
        root = os.path.join(str(hook["scratchpad_dir"]), SCRATCH_SUBDIR)
    else:
        root = os.path.join(tempfile.gettempdir(), SCRATCH_SUBDIR)
    os.makedirs(root, exist_ok=True)
    return root


def resolve(cfg, cwd, transcript=None, env=None, run=subprocess.run, hook=None):
    name, source = agent_name(cfg, cwd, transcript, env, run)
    agents = cfg.get("agents") or {}
    if agents:
        path = agents.get(name)
        if not path:
            return Resolution(name, source, scratch_root(hook, cfg), True,
                              "%s (%s) is not in the agents map; dreaming into scratch" % (name, source))
        if not os.path.isdir(path):
            return Resolution(name, source, scratch_root(hook, cfg), True,
                              "mapped store for %s is missing at %s; not creating it; dreaming into scratch" % (name, path))
        return Resolution(name, source, path, False, "%s (%s) -> %s" % (name, source, path))
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


def index_text(store, cfg):
    """One bounded line per non-blank line of <store>/<index_file>, in file order; '' if absent."""
    path = os.path.join(store, str(cfg.get("index_file") or "MEMORY.md"))
    if not os.path.isfile(path):
        return ""
    out = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            out.append(line if len(line) <= INDEX_LINE_CAP else line[:INDEX_LINE_CAP - 3].rstrip() + "...")
    return "\n".join(out) + ("\n" if out else "")
