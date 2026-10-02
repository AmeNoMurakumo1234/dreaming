#!/usr/bin/env python3
"""engines.py - the three ways a sleep can think, tried in order.

Ported from the quantum-concepts sleep step.

1. openai_compatible - the local server through client.py (base URL, key from file or env, model
              and timeout from config). Free, local, first. Any llama.cpp / vLLM / Ollama-style
              /v1/chat/completions endpoint works.
2. claude   - `claude -p --safe-mode` as a subprocess on the CLI's own login. Measured
              2026-09-22: --safe-mode keeps the OAuth login and answers exactly OK with the prompt
              on stdin, while disabling CLAUDE.md, skills, plugins, hooks and MCP for the nested
              run on ANY machine (a --settings list of plugin names, the previous approach, only
              fit the machine it was written on, and `--bare` never reads OAuth so it fails
              "Not logged in"). Since 0.5.4 the smoke test asks for a codeword that is only on
              the SECOND line of the instructions: a nested run that inherits a hook answers the
              hook, and a run whose instructions were cut to one line answers a polite OK, and
              neither can name the codeword. EVERYTHING multi-line goes on stdin, never in argv:
              Windows caps a command line at 32,767 characters, a chunk is 60k, and cmd.exe (the
              npm `claude.CMD` shim) ends a command line at its first newline.
3. mechanical - no engine at all. build_engine returns (None, "mechanical") and the caller
              writes the raw day plus a brief made from the last turns.

Every engine callable accepts `timeout`, the seconds the caller can still afford; the engine
takes the smaller of that and its configured timeout, so a sleep never runs past its budget on
one slow call. Every spawn carries _NO_WINDOW: a Claude Code hook is a console-less parent on
Windows, so an unguarded child console is a window that flashes on the desktop.
"""
import json
import os
import shutil
import subprocess
import urllib.parse
from collections import namedtuple

from . import client

EngineResult = namedtuple("EngineResult", "ok text engine error model", defaults=(None,))

# 0.5.4: NOTHING WITH A NEWLINE GOES ON THE COMMAND LINE. On Windows `claude` usually resolves to
# the npm `claude.CMD` shim, so the call runs through cmd.exe, which ends a command line at its
# first newline. Measured 2026-09-29 on two machines: a two-line --system-prompt arrived as its
# first line only, and the model answered in shapes of its own. So the command line carries one
# fixed line, and the real instructions ride stdin ahead of the payload, fenced.
SYSTEM_ARG = "Follow the INSTRUCTIONS block at the start of the input exactly."
INSTRUCTIONS_OPEN = "<<<BEGIN INSTRUCTIONS>>>"
INSTRUCTIONS_CLOSE = "<<<END INSTRUCTIONS>>>"
SMOKE_CODEWORD = "PINEAPPLE"

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _bounded(configured, requested):
    configured = int(configured or 900)
    if requested is None:
        return configured
    return max(10, min(configured, int(requested)))


def endpoints(cfg):
    """`openai_compatible` as a list of endpoint dicts in preference order. A single dict is one
    entry, so a 0.1.x config is untouched; an empty or missing value is no endpoint at all."""
    oc = (cfg or {}).get("openai_compatible")
    if isinstance(oc, dict):
        return [oc] if oc else []
    if isinstance(oc, list):
        return [e for e in oc if isinstance(e, dict)]
    return []


def endpoint_label(ep):
    label = str((ep or {}).get("label") or "").strip()
    if label:
        return label
    netloc = urllib.parse.urlsplit(str((ep or {}).get("base_url") or "")).netloc
    return netloc or "openai_compatible"


def _engine_name(cfg, ep):
    return "openai_compatible" if len(endpoints(cfg)) <= 1 else "openai_compatible[%s]" % endpoint_label(ep)


def first_available(cfg, *, available=None):
    """The first endpoint whose probe answers. A probe that RAISES is an unavailable endpoint,
    not the end of the ladder: the next endpoint is still tried (Assay, 2026-09-23)."""
    probe = available or client.available
    for ep in endpoints(cfg):
        try:
            if probe(ep):
                return ep
        except Exception:
            continue
    return None


def local_available(cfg):
    return first_available(cfg) is not None


def local_complete(cfg, system, user, *, max_tokens=4000, timeout=None, endpoint=None):
    eps = endpoints(cfg)
    if endpoint is None:
        endpoint = eps[0] if eps else {}
    oc = dict(endpoint)
    oc["timeout"] = _bounded(oc.get("timeout"), timeout)
    name = _engine_name(cfg, endpoint)
    res = client.chat(oc, system, user, max_tokens=max_tokens)
    if not res["ok"]:
        return EngineResult(False, "", name, str(res["error"]))
    return EngineResult(True, res["text"], name, None)


def _claude_exe():
    return shutil.which("claude") or "claude"


def _answering_model(payload):
    """The model that actually answered, from the envelope's modelUsage (None when absent)."""
    usage = payload.get("modelUsage")
    if isinstance(usage, dict) and usage:
        return sorted(usage)[0] if len(usage) == 1 else ",".join(sorted(usage))
    return None


def claude_complete(cfg_claude, system, user, *, timeout=None, run=subprocess.run):
    cfg_claude = cfg_claude or {}
    model = str(cfg_claude.get("model") or "opus")
    timeout = _bounded(cfg_claude.get("timeout"), timeout)
    cmd = [_claude_exe(), "-p", "--safe-mode", "--model", model, "--output-format", "json",
           "--system-prompt", SYSTEM_ARG]
    if any("\n" in a or "\r" in a for a in cmd):
        return EngineResult(False, "", "claude", "a command-line argument carries a newline")
    stdin = "%s\n%s\n%s\n\n%s" % (INSTRUCTIONS_OPEN, system, INSTRUCTIONS_CLOSE, user)
    try:
        done = run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                   timeout=timeout, creationflags=_NO_WINDOW)
    except Exception as exc:
        return EngineResult(False, "", "claude", str(exc))
    try:
        payload = json.loads(done.stdout or "")
    except ValueError:
        return EngineResult(False, "", "claude", "non-JSON stdout: %r" % (done.stdout or "")[:200])
    if not isinstance(payload, dict):
        return EngineResult(False, "", "claude", "unexpected stdout shape: %s" % type(payload).__name__)
    if payload.get("is_error"):
        return EngineResult(False, "", "claude", str(payload.get("result")))
    text = str(payload.get("result") or "").strip()
    answered_by = _answering_model(payload)
    if not text:
        return EngineResult(False, "", "claude", "empty result", answered_by)
    return EngineResult(True, client.to_ascii(text), "claude", None, answered_by)


def claude_smoke(cfg_claude, run=subprocess.run):
    """Proves the INSTRUCTIONS arrive, not just the login: the codeword is only on the second line
    of the instructions, so a run that loses everything after the first newline cannot answer it.
    Before 0.5.4 this asserted a reply of exactly OK, which a deaf run gives too."""
    system = "You are a smoke test for a nested run.\nThe codeword is %s." % SMOKE_CODEWORD
    r = claude_complete(cfg_claude, system, "Reply with exactly the codeword and nothing else.",
                        timeout=120, run=run)
    return bool(r.ok and r.text.strip().strip(".").upper() == SMOKE_CODEWORD)


def build_engine(cfg, *, local_ok=None, claude_ok=None, available=None):
    """First engine in cfg['engines'] that answers, as (callable, name). local_ok / claude_ok
    override the live probes so tests never touch a server or spawn anything; `available` is an
    injectable per-endpoint probe used when local_ok is not given. With several endpoints the
    name is openai_compatible[<label>], with one it stays plain so existing logs read the same."""
    for name in cfg.get("engines") or ["openai_compatible", "claude", "mechanical"]:
        if name == "openai_compatible":
            eps = endpoints(cfg)
            if not eps or local_ok is False:
                continue
            ep = eps[0] if local_ok else first_available(cfg, available=available)
            if ep is not None:
                def _local(s, u, *, max_tokens=4000, timeout=None, _ep=ep):
                    return local_complete(cfg, s, u, max_tokens=max_tokens, timeout=timeout, endpoint=_ep)
                return _local, _engine_name(cfg, ep)
        elif name == "claude":
            ok = claude_smoke(cfg.get("claude") or {}) if claude_ok is None else claude_ok
            if ok:
                return (lambda s, u, *, max_tokens=4000, timeout=None:
                        claude_complete(cfg.get("claude") or {}, s, u, timeout=timeout)), "claude"
        elif name == "mechanical":
            return None, "mechanical"
    return None, "mechanical"
