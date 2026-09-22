#!/usr/bin/env python3
"""identity.py - who is dreaming, and where the dream goes.

Agent name, in the configured order: DREAMING_AGENT, the transcript's own agent-name record, git
config user.name in the project, then `default`. A configured `agent` (not "auto") sits between
env and transcript: it is the user saying who lives here.

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


def agent_name(cfg, cwd, transcript, env, run=subprocess.run):
    env = os.environ if env is None else env
    configured = str(cfg.get("agent") or "auto").strip()
    for source in cfg.get("identity_order") or ["env", "transcript", "git", "default"]:
        if source == "env":
            name = str(env.get("DREAMING_AGENT") or "").strip()
            if name:
                return name, "env"
            if configured and configured.lower() != "auto":
                return configured, "config"
        elif source == "transcript" and transcript and os.path.isfile(transcript):
            try:
                name = extract.transcript_agent_name(transcript) or ""
            except Exception:
                name = ""
            if name:
                return name, "transcript"
        elif source == "git":
            name = _git_user_name(cwd, run)
            if name:
                return name, "git"
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
    os.makedirs(store, exist_ok=True)
    return Resolution(name, source, store, False, "%s (%s) -> %s" % (name, source, store))


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
