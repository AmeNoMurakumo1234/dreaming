#!/usr/bin/env python3
"""engines.py - the three ways a sleep can think, tried in order.

Ported from the quantum-concepts sleep step.

1. openai_compatible - the local server through client.py (base URL, key from file or env, model
              and timeout from config). Free, local, first. Any llama.cpp / vLLM / Ollama-style
              /v1/chat/completions endpoint works.
2. claude   - `claude -p` as a subprocess on the CLI's own login. Runs with --settings that
              disable every plugin (this one included - a nested run must never sleep) and empty
              the hooks: measured 2026-09-22, a bare nested call inherited a user-level Stop hook
              and answered the hook instead of the prompt, and `--bare` never reads OAuth so it
              fails "Not logged in". The smoke test asserts the reply is exactly OK for that
              reason. The USER prompt goes on stdin, never in argv: Windows caps a command line
              at 32,767 characters and a chunk is 60k.
3. mechanical - no engine at all. build_engine returns (None, "mechanical") and the caller
              writes the raw day plus a brief made from the last turns.

Every spawn carries _NO_WINDOW. A Claude Code hook is a console-less parent on Windows, so an
unguarded child console is a window that flashes on the desktop and steals focus.
"""
import json
import os
import shutil
import subprocess
from collections import namedtuple

from . import client

EngineResult = namedtuple("EngineResult", "ok text engine error")

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Disables the plugins a nested run must not carry and empties hooks. A plugin not named here is
# still enabled inside the nested run; extend the list if one starts firing (the smoke test is
# what tells you).
CLAUDE_MINIMAL_SETTINGS = json.dumps({
    "enabledPlugins": {
        "dreaming@dreaming": False,
        "topic-visualizer@topic-visualizer": False,
        "superpowers@claude-plugins-official": False,
        "ahead-of-proof@ahead-of-proof": False,
        "commit-commands@claude-plugins-official": False,
        "mind-coherence@mind-coherence-suite": False,
    },
    "hooks": {},
}, separators=(",", ":"))


def local_available(cfg):
    try:
        return bool(client.available(cfg.get("openai_compatible") or {}))
    except Exception:
        return False


def local_complete(cfg, system, user, *, max_tokens=4000):
    res = client.chat(cfg.get("openai_compatible") or {}, system, user, max_tokens=max_tokens)
    if not res["ok"]:
        return EngineResult(False, "", "openai_compatible", str(res["error"]))
    return EngineResult(True, res["text"], "openai_compatible", None)


def _claude_exe():
    return shutil.which("claude") or "claude"


def claude_complete(cfg_claude, system, user, *, timeout=None, run=subprocess.run):
    cfg_claude = cfg_claude or {}
    model = str(cfg_claude.get("model") or "haiku")
    timeout = timeout or int(cfg_claude.get("timeout") or 900)
    cmd = [_claude_exe(), "-p", "--model", model, "--output-format", "json",
           "--settings", CLAUDE_MINIMAL_SETTINGS, "--system-prompt", system]
    try:
        done = run(cmd, input=user, capture_output=True, text=True, encoding="utf-8", errors="replace",
                   timeout=timeout, creationflags=_NO_WINDOW)
    except Exception as exc:
        return EngineResult(False, "", "claude", str(exc))
    try:
        payload = json.loads(done.stdout or "")
    except ValueError:
        return EngineResult(False, "", "claude", "non-JSON stdout: %r" % (done.stdout or "")[:200])
    if payload.get("is_error"):
        return EngineResult(False, "", "claude", str(payload.get("result")))
    text = str(payload.get("result") or "").strip()
    if not text:
        return EngineResult(False, "", "claude", "empty result")
    return EngineResult(True, client.to_ascii(text), "claude", None)


def claude_smoke(cfg_claude, run=subprocess.run):
    r = claude_complete(cfg_claude, "You are a terse assistant.",
                        "Reply with exactly the word OK and nothing else.", timeout=120, run=run)
    return bool(r.ok and r.text.strip() == "OK")


def build_engine(cfg, *, local_ok=None, claude_ok=None):
    """First engine in cfg['engines'] that answers, as (callable, name). local_ok / claude_ok
    override the live probes so tests never touch a server or spawn anything."""
    for name in cfg.get("engines") or ["openai_compatible", "claude", "mechanical"]:
        if name == "openai_compatible":
            ok = local_available(cfg) if local_ok is None else local_ok
            if ok:
                return (lambda s, u, *, max_tokens=4000: local_complete(cfg, s, u, max_tokens=max_tokens)), "openai_compatible"
        elif name == "claude":
            ok = claude_smoke(cfg.get("claude") or {}) if claude_ok is None else claude_ok
            if ok:
                return (lambda s, u, *, max_tokens=4000: claude_complete(cfg.get("claude") or {}, s, u)), "claude"
        elif name == "mechanical":
            return None, "mechanical"
    return None, "mechanical"
