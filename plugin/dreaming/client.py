#!/usr/bin/env python3
"""client.py - a stdlib OpenAI-compatible chat client and the JSON helpers the distiller needs.

No dependencies: urllib and json. The helpers are the plugin's own copies of what
quantum-concepts' ai_client provides, kept deliberately CONSERVATIVE: extract_json is
all-or-nothing on a balanced span, salvage_json_list recovers only the complete leading items
of a cut-off list and never repairs, looks_truncated_json tells "opened and never closed" from
"never JSON at all", and to_ascii folds the seven prose characters and replaces the rest.

chat() clamps max_tokens to 4096: the repo build measured that its provider clamps there, and a
reply that is cut mid-string is the failure the distiller's state-first contract exists for.
"""
import json
import os
import urllib.error
import urllib.request

MAX_TOKENS_CAP = 4096

_ASCII_MAP = {
    "\u2014": "-", "\u2013": "-", "\u2012": "-", "\u2010": "-", "\u2011": "-",
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2026": "...", "\u00a0": " ",
}


def to_ascii(text):
    text = "".join(_ASCII_MAP.get(ch, ch) for ch in str(text or ""))
    return text.encode("ascii", "replace").decode("ascii")


def read_api_key(cfg_oc, env=None):
    env = os.environ if env is None else env
    path = str(cfg_oc.get("api_key_file") or "")
    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                key = fh.read().strip()
            if key:
                return key
        except OSError:
            pass
    return str(env.get(str(cfg_oc.get("api_key_env") or "DREAMING_API_KEY")) or "").strip()


def _post(cfg_oc, path, payload, *, timeout, urlopen, env):
    base = str(cfg_oc.get("base_url") or "").rstrip("/")
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    key = read_api_key(cfg_oc, env)
    if key:
        req.add_header("Authorization", "Bearer " + key)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def chat(cfg_oc, system, user, *, max_tokens=4000, temperature=0.2, urlopen=urllib.request.urlopen, env=None):
    payload = {"model": str(cfg_oc.get("model") or "local"), "temperature": float(temperature),
               "max_tokens": int(max(64, min(MAX_TOKENS_CAP, int(max_tokens)))),
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    try:
        data = _post(cfg_oc, "/v1/chat/completions", payload, timeout=int(cfg_oc.get("timeout") or 900),
                     urlopen=urlopen, env=env)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "text": "", "error": "HTTP %s from %s" % (exc.code, cfg_oc.get("base_url"))}
    except Exception as exc:
        return {"ok": False, "text": "", "error": str(exc)}
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {"ok": False, "text": "", "error": "no choices in reply"}
    text = to_ascii(str(text or "")).strip()
    if not text:
        return {"ok": False, "text": "", "error": "empty completion"}
    return {"ok": True, "text": text, "error": None}


def available(cfg_oc, *, urlopen=urllib.request.urlopen, env=None):
    """Health first (keyless, cheap), then a one-token AUTHENTICATED completion: a server that
    answers /health but rejects the key is unavailable to us, and the ladder must move on."""
    base = str(cfg_oc.get("base_url") or "").rstrip("/")
    if not base:
        return False
    try:
        with urlopen(urllib.request.Request(base + "/health"), timeout=6) as resp:
            resp.read()
    except Exception:
        return False
    probe = dict(cfg_oc, timeout=min(30, int(cfg_oc.get("timeout") or 30)))
    return bool(chat(probe, "You are terse.", "Reply with the word OK.", max_tokens=64, urlopen=urlopen, env=env)["ok"])


# ------------------------------------------------------------------ JSON helpers ----

def first_balanced_span(text, open_ch, close_ch):
    start = text.find(open_ch)
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
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _strip_fence(text):
    text = (text or "").strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        text = text[first_nl + 1:] if first_nl >= 0 else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def extract_json(text, kind="object"):
    text = _strip_fence(text)
    if not text:
        return None
    open_ch, close_ch, want = ("[", "]", list) if kind == "array" else ("{", "}", dict)
    try:
        obj = json.loads(text)
        if isinstance(obj, want):
            return obj
    except ValueError:
        pass
    span = first_balanced_span(text, open_ch, close_ch)
    if span is None:
        return None
    try:
        obj = json.loads(span)
    except ValueError:
        return None
    return obj if isinstance(obj, want) else None


def salvage_json_list(text, key=None):
    """Complete leading OBJECT items of the list under `key` (or the first bare list). Stops at
    the first item that does not close. Never repairs."""
    text = _strip_fence(text)
    if key:
        at = text.find('"%s"' % key)
        if at < 0:
            return []
        start = text.find("[", at)
    else:
        start = text.find("[")
    if start < 0:
        return []
    items, i, n = [], start + 1, len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n,":
            i += 1
        if i >= n or text[i] == "]" or text[i] != "{":
            break
        span = first_balanced_span(text[i:], "{", "}")
        if span is None:
            break
        try:
            items.append(json.loads(span))
        except ValueError:
            break
        i += len(span)
    return items


def looks_truncated_json(text, kind="object"):
    text = _strip_fence(text)
    if not text:
        return False
    open_ch, close_ch = ("[", "]") if kind == "array" else ("{", "}")
    if open_ch not in text:
        return False
    return first_balanced_span(text, open_ch, close_ch) is None
