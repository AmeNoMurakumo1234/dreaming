# dreaming Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A publishable Claude Code plugin that runs the quantum-concepts sleep step for any repo, agent and user, driven by layered configuration and a stdlib model client.

**Architecture:** A `dreaming` Python package under `plugin/dreaming/` with four ported modules (extract, engines, distill, sleep) and four new seams (config, identity, client, cli); three thin hook scripts wired by `hooks/hooks.json`; two skills. Marketplace-and-plugin repo layout identical to topic-visualizer.

**Tech Stack:** Python 3.13 stdlib only (`urllib`, `json`, `subprocess`); `unittest`; Claude Code plugin manifests; `gh` for publishing.

**Spec:** `docs/superpowers/specs/2026-09-22-dreaming-plugin-design.md`

**Source being ported:** quantum-concepts at commit `901ef3e9`, files `.agents/scripts/governance/sleep_extract.py`, `sleep_engines.py`, `sleep_distill.py`, `sleep.py`, `test_sleep.py`. Read them from `F:/writing/quantum-concepts` before each porting task.

## Global Constraints

- Stdlib only. No pip dependencies anywhere in `plugin/`.
- Every `subprocess` call passes `creationflags=_NO_WINDOW` (`0x08000000` on Windows, `0` elsewhere). No model payload in argv; the user prompt to `claude -p` goes on stdin.
- Hook subcommands (`sleep`, `reseed`, `notice`) always exit 0, including on empty or garbage stdin and on internal exceptions.
- Never write the index file or any file outside `<store>/dreams/`. Never create a MAPPED store; create an UNMAPPED default store on first use.
- `enabled: false` in config or `DREAMING_DISABLED=1` in env makes every hook exit 0 silently.
- Defaults exactly as the spec's configuration block. Config layering order: defaults, `~/.dreaming/config.json`, `<project>/.dreaming.json`, `DREAMING_*` env.
- Tests run with `python -m unittest discover -s plugin/tests -v` from the repo root and must be clean under `-W error::ResourceWarning`.
- ASCII-only source and docs (the seven prose-punctuation characters never appear); written dream files pass through `to_ascii`.
- Commits by the repo's configured author; messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. A project `.dreaming.json` with an `agents` map and a session whose agent is not in it: must dream into scratch and print why, never into `store_root/<agent>`. Pinned in Task 3 (`test_unmapped_agent_goes_to_scratch_when_a_map_exists`).
2. A mapped store whose directory is missing: never created; scratch plus reason. Pinned in Task 3 (`test_mapped_store_missing_is_not_created`).
3. Garbage on a hook's stdin (not JSON, or JSON without `transcript_path`): exit 0, one printed line, nothing written under any store. Pinned in Task 6 (`test_hook_scripts_exit_zero_on_garbage_stdin`).
4. An OpenAI-compatible server that answers `/health` but rejects the key (401): the probe must report unavailable so the ladder moves on. Pinned in Task 2 (`test_available_requires_an_authenticated_completion`).
5. `~` and relative paths in config on Windows: `store_root: "~/.dreaming/stores"` and a project-relative `agents` entry must resolve to absolute paths. Pinned in Task 1 (`test_paths_are_expanded_and_project_relative`).

---

## File Structure

| File | Responsibility |
|---|---|
| Create `.claude-plugin/marketplace.json`, `plugin/.claude-plugin/plugin.json` | manifests |
| Create `LICENSE`, `.gitignore`, `README.md`, `INSTALL.md`, `CHANGELOG.md` | repo docs |
| Create `plugin/dreaming/__init__.py` | version string |
| Create `plugin/dreaming/config.py` | `DEFAULTS`, `load(project_dir, env, home)`, path expansion |
| Create `plugin/dreaming/client.py` | `chat`, `available`, `extract_json`, `salvage_json_list`, `looks_truncated_json`, `to_ascii` |
| Create `plugin/dreaming/identity.py` | `resolve(cfg, cwd, transcript, env, run)`, `Resolution`, `index_text(store, cfg)`, `scratch_root(hook)` |
| Create `plugin/dreaming/extract.py` | ported `sleep_extract.py` |
| Create `plugin/dreaming/engines.py` | ported `sleep_engines.py`, llama adapter over `client` |
| Create `plugin/dreaming/distill.py` | ported `sleep_distill.py`, helpers from `client` |
| Create `plugin/dreaming/sleep.py` | ported pipeline: `run_sleep`, `last_watermark`, `newest_dream_for`, `dreams_awaiting` |
| Create `plugin/dreaming/cli.py` | `main(argv)`: `sleep`, `reseed`, `notice`, `dream`, `list`, `config` |
| Create `plugin/hooks/hooks.json`, `plugin/hooks/precompact_sleep.py`, `sessionstart_reseed.py`, `sessionstart_notice.py` | hooks |
| Create `plugin/skills/dreaming/SKILL.md`, `plugin/skills/dreaming-promote/SKILL.md` | skills |
| Create `plugin/tests/test_config.py`, `test_client.py`, `test_identity.py`, `test_extract.py`, `test_engines.py`, `test_distill.py`, `test_sleep.py`, `test_hooks.py` | tests |
| Modify (other repo) `F:/writing/quantum-concepts/.dreaming.json` | disable file, committed there |

---

### Task 1: Scaffold, manifests, and `config.py`

**Files:**
- Create: `.claude-plugin/marketplace.json`, `plugin/.claude-plugin/plugin.json`, `LICENSE`, `.gitignore`, `plugin/dreaming/__init__.py`, `plugin/dreaming/config.py`
- Test: `plugin/tests/test_config.py`

**Interfaces:**
- Produces: `config.DEFAULTS` (dict), `config.load(project_dir=None, env=None, home=None) -> dict` returning a deep-merged dict with `_project_dir` (str or None) and `_sources` (list of str) added; `config.expand_path(value, base) -> str`.
- Env mapping: `DREAMING_DISABLED=1` -> `enabled False`; `DREAMING_AGENT` -> `agent`; `DREAMING_STORE_ROOT` -> `store_root`; `DREAMING_BASE_URL` -> `openai_compatible.base_url`; `DREAMING_API_KEY_FILE` -> `openai_compatible.api_key_file`; `DREAMING_MODEL` -> `openai_compatible.model`. (`DREAMING_API_KEY` is read by the client directly via `api_key_env`.)

- [ ] **Step 1: Write the failing tests**

`plugin/tests/test_config.py`:

```python
#!/usr/bin/env python3
"""Config layering: defaults < ~/.dreaming/config.json < <project>/.dreaming.json < DREAMING_* env."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, "..", "dreaming"))
if os.path.dirname(PKG) not in sys.path:
    sys.path.insert(0, os.path.dirname(PKG))

from dreaming import config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dreaming-cfg-")
        self.home = os.path.join(self.tmp, "home")
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(os.path.join(self.home, ".dreaming"))
        os.makedirs(self.project)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, path, obj):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)

    def test_defaults_alone(self):
        cfg = config.load(project_dir=self.project, env={}, home=self.home)
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["agent"], "auto")
        self.assertEqual(cfg["engines"], ["openai_compatible", "claude", "mechanical"])
        self.assertEqual(cfg["chunk_chars"], 60000)
        self.assertEqual(cfg["_sources"], ["defaults"])

    def test_user_then_project_then_env_each_win(self):
        self._write(os.path.join(self.home, ".dreaming", "config.json"),
                    {"chunk_chars": 1000, "agent": "UserAgent", "openai_compatible": {"model": "user-model"}})
        self._write(os.path.join(self.project, ".dreaming.json"),
                    {"chunk_chars": 2000, "openai_compatible": {"base_url": "http://x:1"}})
        cfg = config.load(project_dir=self.project, env={"DREAMING_AGENT": "EnvAgent", "DREAMING_MODEL": "env-model"},
                          home=self.home)
        self.assertEqual(cfg["chunk_chars"], 2000)
        self.assertEqual(cfg["agent"], "EnvAgent")
        self.assertEqual(cfg["openai_compatible"]["model"], "env-model")
        self.assertEqual(cfg["openai_compatible"]["base_url"], "http://x:1")
        self.assertEqual(cfg["openai_compatible"]["timeout"], 900)      # untouched default survives the merge
        self.assertEqual(cfg["_sources"], ["defaults", "user", "project", "env"])

    def test_disabled_env_and_project_flag(self):
        cfg = config.load(project_dir=self.project, env={"DREAMING_DISABLED": "1"}, home=self.home)
        self.assertFalse(cfg["enabled"])
        self._write(os.path.join(self.project, ".dreaming.json"), {"enabled": False})
        cfg = config.load(project_dir=self.project, env={}, home=self.home)
        self.assertFalse(cfg["enabled"])

    def test_paths_are_expanded_and_project_relative(self):
        self._write(os.path.join(self.project, ".dreaming.json"),
                    {"store_root": "~/.dreaming/stores", "agents": {"Joule": "team/worker/memory"}})
        cfg = config.load(project_dir=self.project, env={}, home=self.home)
        self.assertEqual(cfg["store_root"], os.path.join(self.home, ".dreaming", "stores"))
        self.assertEqual(cfg["agents"]["Joule"], os.path.join(self.project, "team", "worker", "memory"))
        self.assertTrue(os.path.isabs(cfg["agents"]["Joule"]))

    def test_bad_json_is_skipped_not_fatal(self):
        with open(os.path.join(self.project, ".dreaming.json"), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        cfg = config.load(project_dir=self.project, env={}, home=self.home)
        self.assertTrue(cfg["enabled"])
        self.assertIn("project:invalid", cfg["_sources"])

    def test_project_dir_found_from_git_toplevel(self):
        sub = os.path.join(self.project, "a", "b")
        os.makedirs(sub)
        os.makedirs(os.path.join(self.project, ".git"))
        self._write(os.path.join(self.project, ".dreaming.json"), {"chunk_chars": 4242})
        cfg = config.load(project_dir=sub, env={}, home=self.home)
        self.assertEqual(cfg["chunk_chars"], 4242)
        self.assertEqual(cfg["_project_dir"], self.project)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd F:/writing/plugins/dreaming && python -m unittest discover -s plugin/tests -v`
Expected: import error, `No module named 'dreaming'` (the package does not exist yet).

- [ ] **Step 3: Write the scaffold and config.py**

`plugin/dreaming/__init__.py`:
```python
"""dreaming - consolidate a Claude Code session into durable memory at compaction."""
__version__ = "0.1.0"
```

`plugin/dreaming/config.py`:
```python
#!/usr/bin/env python3
"""Layered configuration: defaults < ~/.dreaming/config.json < <project>/.dreaming.json < DREAMING_* env.

The project file is found from the hook's cwd by walking up to the nearest `.git` (or the cwd
itself when there is none). Relative paths in a project file are relative to the project root;
`~` is expanded everywhere. A file that does not parse is skipped and named in `_sources`, never
fatal: a hook must not die on a typo in a config file.
"""
import copy
import json
import os

DEFAULTS = {
    "enabled": True,
    "store_root": "~/.dreaming/stores",
    "agent": "auto",
    "agents": {},
    "identity_order": ["env", "transcript", "git", "default"],
    "engines": ["openai_compatible", "claude", "mechanical"],
    "openai_compatible": {"base_url": "http://127.0.0.1:8081", "api_key_file": "",
                          "api_key_env": "DREAMING_API_KEY", "model": "local", "timeout": 900},
    "claude": {"model": "haiku", "timeout": 900},
    "chunk_chars": 60000,
    "cap_chars": 400000,
    "budget_seconds": 3000,
    "result_head": 400,
    "include_thinking": False,
    "index_file": "MEMORY.md",
    "stale_days": 14,
}

_ENV_SCALARS = {
    "DREAMING_AGENT": ("agent",),
    "DREAMING_STORE_ROOT": ("store_root",),
    "DREAMING_BASE_URL": ("openai_compatible", "base_url"),
    "DREAMING_API_KEY_FILE": ("openai_compatible", "api_key_file"),
    "DREAMING_MODEL": ("openai_compatible", "model"),
}

USER_FILE = os.path.join(".dreaming", "config.json")
PROJECT_FILE = ".dreaming.json"


def _merge(base, over):
    out = copy.deepcopy(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _read(path):
    """(dict or None, status) - status is 'ok', 'absent' or 'invalid'."""
    if not os.path.isfile(path):
        return None, "absent"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        return (obj if isinstance(obj, dict) else None), ("ok" if isinstance(obj, dict) else "invalid")
    except (OSError, ValueError):
        return None, "invalid"


def project_root(start):
    """Nearest ancestor holding .git, else `start` itself. None when start is falsy."""
    if not start:
        return None
    cur = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(cur, ".git")) or os.path.isfile(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(start)
        cur = parent


def expand_path(value, base, home=None):
    value = str(value or "")
    if not value:
        return value
    if value.startswith("~"):
        value = (home or os.path.expanduser("~")) + value[1:]
    if not os.path.isabs(value) and base:
        value = os.path.join(base, value)
    return os.path.normpath(value)


def load(project_dir=None, env=None, home=None):
    env = os.environ if env is None else env
    home = home or os.path.expanduser("~")
    cfg = copy.deepcopy(DEFAULTS)
    sources = ["defaults"]

    user, status = _read(os.path.join(home, USER_FILE))
    if status == "ok":
        cfg = _merge(cfg, user)
        sources.append("user")
    elif status == "invalid":
        sources.append("user:invalid")

    root = project_root(project_dir)
    if root:
        proj, status = _read(os.path.join(root, PROJECT_FILE))
        if status == "ok":
            proj = dict(proj)
            if isinstance(proj.get("agents"), dict):
                proj["agents"] = {k: expand_path(v, root, home) for k, v in proj["agents"].items()}
            cfg = _merge(cfg, proj)
            sources.append("project")
        elif status == "invalid":
            sources.append("project:invalid")

    touched = False
    for name, path in _ENV_SCALARS.items():
        if env.get(name):
            node = cfg
            for key in path[:-1]:
                node = node.setdefault(key, {})
            node[path[-1]] = env[name]
            touched = True
    if env.get("DREAMING_DISABLED", "").strip() in ("1", "true", "yes"):
        cfg["enabled"] = False
        touched = True
    if touched:
        sources.append("env")

    cfg["store_root"] = expand_path(cfg.get("store_root"), None, home)
    cfg["agents"] = {k: expand_path(v, root, home) for k, v in (cfg.get("agents") or {}).items()}
    oc = cfg.get("openai_compatible") or {}
    if oc.get("api_key_file"):
        oc["api_key_file"] = expand_path(oc["api_key_file"], root, home)
    cfg["_project_dir"] = root
    cfg["_sources"] = sources
    return cfg
```

`plugin/.claude-plugin/plugin.json`:
```json
{
  "name": "dreaming",
  "displayName": "Dreaming",
  "description": "Sleep at compaction: a blocking PreCompact hook distils the session transcript into candidate lessons, a resume brief and held tensions, stages them in the agent's memory store, and re-seeds the fresh context after compaction. Local model first (any OpenAI-compatible server), claude -p second, a mechanical brief last. The plugin never writes an index and never resolves a tension: the mind promotes at wake, with the dreaming-promote skill.",
  "version": "0.1.0",
  "author": { "name": "Ame No Murakumo" },
  "license": "MIT",
  "keywords": ["memory", "compaction", "consolidation", "agent-memory", "hooks", "sleep", "local-llm"]
}
```

`.claude-plugin/marketplace.json`:
```json
{
  "name": "dreaming",
  "owner": { "name": "Ame No Murakumo" },
  "description": "Marketplace hosting dreaming: consolidation at compaction, so a Claude Code session sleeps into durable memory instead of losing its day to the summary.",
  "plugins": [
    {
      "name": "dreaming",
      "source": "./plugin",
      "description": "A blocking PreCompact hook distils the transcript into staged lessons, a five-field resume brief and held tensions; SessionStart(compact) re-seeds the brief; the next session start says how many dreams await promotion. Local OpenAI-compatible model first, claude -p second, mechanical last. Staging only: the mind promotes.",
      "version": "0.1.0",
      "author": { "name": "Ame No Murakumo" },
      "license": "MIT",
      "keywords": ["memory", "compaction", "consolidation", "agent-memory", "hooks", "sleep", "local-llm"]
    }
  ]
}
```

`LICENSE`: the MIT text with `Copyright (c) 2026 Ame No Murakumo`. `.gitignore`: `__pycache__/`, `*.py[cod]`, `.superpowers/`, `*.log`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s plugin/tests -v`
Expected: 6 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: scaffold, manifests, layered config

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `client.py` - OpenAI-compatible chat and the JSON helpers

**Files:**
- Create: `plugin/dreaming/client.py`
- Test: `plugin/tests/test_client.py`

**Interfaces:**
- Produces: `chat(cfg_oc, system, user, *, max_tokens=4000, temperature=0.2, urlopen=urllib.request.urlopen) -> dict {ok, text, error}`; `available(cfg_oc, *, urlopen=...) -> bool`; `read_api_key(cfg_oc, env=None) -> str`; `extract_json(text, kind="object")`; `salvage_json_list(text, key=None) -> list`; `looks_truncated_json(text, kind="object") -> bool`; `to_ascii(text) -> str`; `first_balanced_span(text, open_ch, close_ch)`.
- `chat` clamps `max_tokens` to 4096 (the provider cap the repo build hit) and always sends `temperature`.

- [ ] **Step 1: Write the failing tests**

`plugin/tests/test_client.py`:

```python
#!/usr/bin/env python3
"""The stdlib OpenAI-compatible client and the four JSON helpers the distiller depends on."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.abspath(os.path.join(HERE, "..")) not in sys.path:
    sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

from dreaming import client  # noqa: E402

OC = {"base_url": "http://127.0.0.1:8081", "api_key_file": "", "api_key_env": "DREAMING_API_KEY",
      "model": "local", "timeout": 5}


class _Resp(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode("utf-8") if not isinstance(payload, bytes) else payload)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen_factory(handler):
    def urlopen(req, timeout=None):
        return handler(req)
    return urlopen


class ChatTests(unittest.TestCase):
    def test_chat_sends_openai_shape_with_bearer_and_clamps_max_tokens(self):
        seen = {}

        def handler(req):
            seen["url"] = req.full_url
            seen["auth"] = req.get_header("Authorization")
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return _Resp({"choices": [{"message": {"content": "hello \u2014 world"}, "finish_reason": "stop"}]})

        out = client.chat(dict(OC), "sys", "usr", max_tokens=9000, urlopen=_urlopen_factory(handler),
                          env={"DREAMING_API_KEY": "k1"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["text"], "hello - world")          # to_ascii applied
        self.assertTrue(seen["url"].endswith("/v1/chat/completions"))
        self.assertEqual(seen["auth"], "Bearer k1")
        self.assertEqual(seen["body"]["max_tokens"], 4096)
        self.assertEqual([m["role"] for m in seen["body"]["messages"]], ["system", "user"])
        self.assertEqual(seen["body"]["model"], "local")

    def test_chat_reports_transport_and_http_errors_without_raising(self):
        import urllib.error

        def boom(req):
            raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, io.BytesIO(b"{}"))

        out = client.chat(dict(OC), "s", "u", urlopen=_urlopen_factory(boom), env={})
        self.assertFalse(out["ok"])
        self.assertIn("401", out["error"])
        out = client.chat(dict(OC), "s", "u", urlopen=_urlopen_factory(lambda r: _Resp({"choices": []})), env={})
        self.assertFalse(out["ok"])

    def test_api_key_from_file_wins_over_env(self):
        tmp = tempfile.mkdtemp(prefix="dreaming-key-")
        try:
            path = os.path.join(tmp, "key")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("filekey\n")
            self.assertEqual(client.read_api_key(dict(OC, api_key_file=path), env={"DREAMING_API_KEY": "envkey"}), "filekey")
            self.assertEqual(client.read_api_key(dict(OC), env={"DREAMING_API_KEY": "envkey"}), "envkey")
            self.assertEqual(client.read_api_key(dict(OC), env={}), "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_available_requires_an_authenticated_completion(self):
        # CONTROL: health up + completion ok -> True; health up + 401 -> False; health down -> False.
        import urllib.error

        def ok(req):
            if req.full_url.endswith("/health"):
                return _Resp({"status": "ok"})
            return _Resp({"choices": [{"message": {"content": "x"}}]})

        def unauthorized(req):
            if req.full_url.endswith("/health"):
                return _Resp({"status": "ok"})
            raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, io.BytesIO(b"{}"))

        def down(req):
            raise OSError("refused")

        self.assertTrue(client.available(dict(OC), urlopen=_urlopen_factory(ok), env={}))
        self.assertFalse(client.available(dict(OC), urlopen=_urlopen_factory(unauthorized), env={}))
        self.assertFalse(client.available(dict(OC), urlopen=_urlopen_factory(down), env={}))


class HelperTests(unittest.TestCase):
    GOOD = json.dumps({"state": {"a": 1}, "lessons": [{"title": "t1"}, {"title": "t2"}], "tensions": []})

    def test_extract_json_handles_clean_fenced_and_trailing_prose(self):
        self.assertEqual(client.extract_json(self.GOOD)["state"], {"a": 1})
        self.assertEqual(client.extract_json("```json\n" + self.GOOD + "\n```")["state"], {"a": 1})
        self.assertEqual(client.extract_json("Here you go:\n" + self.GOOD + "\nHope that helps")["state"], {"a": 1})
        self.assertIsNone(client.extract_json("no json here"))
        self.assertIsNone(client.extract_json(self.GOOD[:-10]))      # unbalanced -> None, never a guess
        self.assertEqual(client.extract_json("[1,2]", "array"), [1, 2])

    def test_salvage_json_list_returns_the_complete_prefix_only(self):
        cut = self.GOOD[: self.GOOD.rfind('"t2"') + 2]                 # inside the second item
        items = client.salvage_json_list(cut, "lessons")
        self.assertEqual(items, [{"title": "t1"}])
        self.assertEqual(client.salvage_json_list(cut, "missing"), [])
        self.assertEqual(client.salvage_json_list("prose", "lessons"), [])

    def test_looks_truncated_json_tells_cut_from_malformed(self):
        self.assertTrue(client.looks_truncated_json(self.GOOD[:-5]))
        self.assertFalse(client.looks_truncated_json(self.GOOD))
        self.assertFalse(client.looks_truncated_json("pure prose"))

    def test_to_ascii_folds_the_seven_prose_characters_and_never_raises(self):
        text = "a \u2014 b \u2013 c \u2018q\u2019 \u201cd\u201d \u2026 \u00e9"
        out = client.to_ascii(text)
        self.assertTrue(all(ord(c) < 128 for c in out), out)
        self.assertIn("a - b - c 'q' \"d\" ...", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m unittest discover -s plugin/tests -v`
Expected: `test_client` errors on import (`cannot import name 'client'`).

- [ ] **Step 3: Write client.py**

```python
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
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        text = text[first_nl + 1:] if first_nl >= 0 else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def extract_json(text, kind="object"):
    text = _strip_fence(text or "")
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
    text = _strip_fence(text or "")
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
        if i >= n or text[i] == "]":
            break
        if text[i] != "{":
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
    text = _strip_fence(text or "")
    if not text:
        return False
    open_ch, close_ch = ("[", "]") if kind == "array" else ("{", "}")
    if open_ch not in text:
        return False
    return first_balanced_span(text, open_ch, close_ch) is None
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m unittest discover -s plugin/tests -v`
Expected: 14 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(client): stdlib OpenAI-compatible chat, authenticated availability probe, conservative JSON helpers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `identity.py` - who is dreaming, and where

**Files:**
- Create: `plugin/dreaming/identity.py`
- Create: `plugin/dreaming/extract.py` (ported; needed here for `transcript_agent_name`)
- Test: `plugin/tests/test_identity.py`, `plugin/tests/test_extract.py`

**Interfaces:**
- Produces: `Resolution = namedtuple("Resolution", "agent source store scratch reason")` where `store` is the directory the dream goes to (already decided: the real store or the scratch root), `scratch` is a bool; `resolve(cfg, cwd, transcript=None, env=None, run=subprocess.run, hook=None) -> Resolution`; `scratch_root(hook, cfg=None) -> str`; `index_text(store, cfg) -> str`; `agent_name(cfg, cwd, transcript, env, run) -> tuple[str, str]` (name, source).
- Ported `extract.py` is byte-identical to `sleep_extract.py` at 901ef3e9 except the docstring's first line and the removal of the issue reference.

- [ ] **Step 1: Port extract.py and write its tests**

Copy `F:/writing/quantum-concepts/.agents/scripts/governance/sleep_extract.py` to `plugin/dreaming/extract.py`. Edit only the docstring: first line becomes `extract.py - a Claude Code transcript (JSONL) to the turns worth dreaming about.` and drop `Issue 1974.`

`plugin/tests/test_extract.py`: copy the `_rec`, `write_fixture`, `_read` helpers and the whole `ExtractTests` class from quantum-concepts `test_sleep.py` (at 901ef3e9), with the import changed to `from dreaming import extract as sx` and the sys.path insert pointing at `plugin/`. Keep every test, including `test_transcript_agent_name_is_read_from_the_agent_name_record`.

- [ ] **Step 2: Write the failing identity tests**

`plugin/tests/test_identity.py`:

```python
#!/usr/bin/env python3
"""Who is dreaming and where: env, transcript agent-name, git, default; mapped vs default stores."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.abspath(os.path.join(HERE, "..")) not in sys.path:
    sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

from dreaming import config, identity  # noqa: E402
from test_extract import write_fixture  # noqa: E402


class _Done:
    def __init__(self, stdout):
        self.stdout = stdout
        self.returncode = 0


def _git(name):
    return lambda *a, **k: _Done(name + "\n")


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dreaming-id-")
        self.home = os.path.join(self.tmp, "home")
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(self.home)
        os.makedirs(os.path.join(self.project, ".git"))
        self.transcript = write_fixture(os.path.join(self.tmp, "t.jsonl"))   # carries agent-name Joule

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cfg(self, project_json=None, env=None):
        if project_json is not None:
            with open(os.path.join(self.project, ".dreaming.json"), "w", encoding="utf-8") as fh:
                json.dump(project_json, fh)
        return config.load(project_dir=self.project, env=env or {}, home=self.home)

    def test_order_env_then_transcript_then_git_then_default(self):
        cfg = self._cfg()
        self.assertEqual(identity.agent_name(cfg, self.project, self.transcript, {"DREAMING_AGENT": "Env"}, _git("Git")), ("Env", "env"))
        self.assertEqual(identity.agent_name(cfg, self.project, self.transcript, {}, _git("Git")), ("Joule", "transcript"))
        self.assertEqual(identity.agent_name(cfg, self.project, None, {}, _git("Git")), ("Git", "git"))
        self.assertEqual(identity.agent_name(cfg, self.project, None, {}, _git("")), ("default", "default"))

    def test_configured_agent_beats_git_but_not_env(self):
        cfg = self._cfg({"agent": "Configured"})
        self.assertEqual(identity.agent_name(cfg, self.project, None, {}, _git("Git"))[0], "Configured")
        self.assertEqual(identity.agent_name(cfg, self.project, None, {"DREAMING_AGENT": "Env"}, _git("Git"))[0], "Env")

    def test_default_store_is_created_under_store_root(self):
        cfg = self._cfg({"store_root": "stores"})
        res = identity.resolve(cfg, self.project, transcript=self.transcript, env={}, run=_git(""))
        self.assertFalse(res.scratch)
        self.assertEqual(res.store, os.path.join(self.project, "stores", "Joule"))
        self.assertTrue(os.path.isdir(res.store))

    def test_unmapped_agent_goes_to_scratch_when_a_map_exists(self):
        os.makedirs(os.path.join(self.project, "team", "worker", "memory"))
        cfg = self._cfg({"agents": {"Joule": "team/worker/memory"}})
        res = identity.resolve(cfg, self.project, transcript=None, env={"DREAMING_AGENT": "Stranger"}, run=_git(""),
                               hook={"scratchpad_dir": os.path.join(self.tmp, "scratch")})
        self.assertTrue(res.scratch)
        self.assertTrue(res.store.startswith(os.path.join(self.tmp, "scratch")))
        self.assertIn("not in the agents map", res.reason)
        self.assertFalse(os.path.exists(os.path.join(self.project, "stores")))

    def test_mapped_store_missing_is_not_created(self):
        cfg = self._cfg({"agents": {"Joule": "team/worker/memory"}})
        res = identity.resolve(cfg, self.project, transcript=self.transcript, env={}, run=_git(""),
                               hook={"scratchpad_dir": os.path.join(self.tmp, "scratch")})
        self.assertTrue(res.scratch)
        self.assertIn("missing", res.reason)
        self.assertFalse(os.path.exists(os.path.join(self.project, "team", "worker", "memory")))

    def test_mapped_store_present_is_used(self):
        store = os.path.join(self.project, "team", "worker", "memory")
        os.makedirs(store)
        cfg = self._cfg({"agents": {"Joule": "team/worker/memory"}})
        res = identity.resolve(cfg, self.project, transcript=self.transcript, env={}, run=_git(""))
        self.assertFalse(res.scratch)
        self.assertEqual(res.store, store)

    def test_index_text_reads_bounded_lines_or_empty(self):
        store = os.path.join(self.tmp, "store")
        os.makedirs(store)
        cfg = self._cfg()
        self.assertEqual(identity.index_text(store, cfg), "")
        with open(os.path.join(store, "MEMORY.md"), "w", encoding="utf-8") as fh:
            fh.write("# index\n\n- [a-slug](a-slug.md) - " + "x" * 500 + "\n- [b-slug](b-slug.md) - short\n")
        text = identity.index_text(store, cfg)
        lines = text.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(len(l) <= 118 for l in lines))
        self.assertIn("b-slug", text)

    def test_scratch_root_prefers_hook_scratchpad(self):
        root = identity.scratch_root({"scratchpad_dir": os.path.join(self.tmp, "sp")})
        self.assertTrue(root.startswith(os.path.join(self.tmp, "sp")))
        self.assertTrue(os.path.isdir(root))
        self.assertTrue(identity.scratch_root({}).endswith("dreaming"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m unittest discover -s plugin/tests -v`
Expected: `test_extract` passes (ported), `test_identity` errors on `cannot import name 'identity'`.

- [ ] **Step 4: Write identity.py**

```python
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
    base = (hook or {}).get("scratchpad_dir") or os.path.join(tempfile.gettempdir(), SCRATCH_SUBDIR)
    root = os.path.join(base, SCRATCH_SUBDIR) if (hook or {}).get("scratchpad_dir") else base
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
    store = os.path.join(str(cfg.get("store_root") or ""), name)
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
```

- [ ] **Step 5: Run to verify they pass**

Run: `python -m unittest discover -s plugin/tests -v`
Expected: 6 config + 8 client + 10 extract + 8 identity = 32 tests, `OK`.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(identity): env, transcript agent-name, git, default; mapped stores never created; bounded index

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Port `engines.py` and `distill.py`

**Files:**
- Create: `plugin/dreaming/engines.py`, `plugin/dreaming/distill.py`
- Test: `plugin/tests/test_engines.py`, `plugin/tests/test_distill.py`

**Interfaces:**
- `engines.EngineResult`, `engines._NO_WINDOW`, `engines.CLAUDE_MINIMAL_SETTINGS`, `engines.local_available(cfg)`, `engines.local_complete(cfg, system, user, *, max_tokens)`, `engines.claude_complete(cfg_claude, system, user, *, timeout=900, run=subprocess.run)`, `engines.claude_smoke(cfg_claude, run=...)`, `engines.build_engine(cfg, *, local_ok=None, claude_ok=None) -> (callable|None, name)`; the callable is `fn(system, user, *, max_tokens) -> EngineResult`. Engine names in config: `openai_compatible`, `claude`, `mechanical`.
- `distill`: identical public surface to `sleep_distill.py` at 901ef3e9 (`MAP_SYSTEM`, `REDUCE_SYSTEM`, `STATE_FIELDS`, `DEFAULT_CHUNK_CHARS`, `PAYLOAD_OPEN`, `PAYLOAD_CLOSE`, `JSON_REMINDER`, `map_chunk`, `reduce_maps`, `mechanical_state`, `slugify`, `render_brief`, `render_lesson`, `render_tensions`, `_union`).

- [ ] **Step 1: Port engines.py**

Copy `sleep_engines.py` to `plugin/dreaming/engines.py`, then apply these edits exactly:
1. Docstring first line: `engines.py - the three ways a sleep can think, tried in order.`; replace the sentence about ai_client with "the local OpenAI-compatible server through client.py (base URL, key file or env, model from config)"; drop `Issue 1974.`
2. Remove `HERE`, `REPO`, `_TIMELINE`, `_ai_client()`, `llama_available()`, `llama_complete()`; add `from . import client`.
3. Add:
```python
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
```
4. `claude_complete(cfg_claude, system, user, *, timeout=None, run=subprocess.run)`: `model = str(cfg_claude.get("model") or "haiku")`, `timeout = timeout or int(cfg_claude.get("timeout") or 900)`; body unchanged (stdin prompt, `--settings CLAUDE_MINIMAL_SETTINGS`, `creationflags=_NO_WINDOW`). `claude_smoke(cfg_claude, run=subprocess.run)` calls it with `timeout=120`.
5. `CLAUDE_MINIMAL_SETTINGS`: keep the five plugin names and add `"dreaming@dreaming": False` (a nested run must never sleep).
6. `build_engine(cfg, *, local_ok=None, claude_ok=None)`: iterate `cfg.get("engines")`; names `openai_compatible` -> `local_available(cfg)` / `local_complete`; `claude` -> `claude_smoke(cfg["claude"])` / `claude_complete(cfg["claude"], ...)`; `mechanical` -> `(None, "mechanical")`.

`plugin/tests/test_engines.py`: port `EngineTests` from `test_sleep.py`, changing `se.claude_complete("sys", "usr", run=fake_run)` to `se.claude_complete({"model": "haiku"}, "sys", "usr", run=fake_run)` (all four call sites), `se.claude_smoke(run=...)` to `se.claude_smoke({"model": "haiku"}, run=...)`, and `build_engine` calls to pass a cfg: `se.build_engine({"engines": ["openai_compatible", "claude", "mechanical"], "claude": {}}, local_ok=False, claude_ok=False)` etc., with `order=("claude","llama")` becoming `{"engines": ["claude", "openai_compatible"]}`. Add:
```python
    def test_minimal_settings_disable_this_plugin_too(self):
        self.assertIn('"dreaming@dreaming":false', se.CLAUDE_MINIMAL_SETTINGS)
```

- [ ] **Step 2: Port distill.py**

Copy `sleep_distill.py` to `plugin/dreaming/distill.py`, then:
1. Docstring first line `distill.py - ...`; drop `Issue 1974.`
2. Remove `HERE`, `REPO`, `_TIMELINE`, `_ai_client()`; add `from . import client`.
3. `_to_ascii(text)` -> `return client.to_ascii(text)`.
4. `_parse_object(text)`: replace the `ai = _ai_client()` branch with direct calls: `client.extract_json`, `client.salvage_json_list`, `client.looks_truncated_json`; drop the no-ai fallback branch entirely.

`plugin/tests/test_distill.py`: port `DistillTests` and the `MAP_JSON`, `INDEX_TEXT`, `REDUCE_JSON`, `_engine_returning` module constants from `test_sleep.py`, importing `from dreaming import distill as sd, extract as sx` and `from dreaming.engines import EngineResult`. Keep every test.

- [ ] **Step 3: Run everything**

Run: `python -m unittest discover -s plugin/tests -v`
Expected: 32 + 6 engines + 12 distill = 50 tests, `OK`.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: port engines and distill; local engine speaks through client.py; nested claude never dreams

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Port the pipeline (`sleep.py`) and write `cli.py`

**Files:**
- Create: `plugin/dreaming/sleep.py`, `plugin/dreaming/cli.py`
- Test: `plugin/tests/test_sleep.py`

**Interfaces:**
- `sleep.run_sleep(transcript_path, *, agent, session_id, out_root, engine=None, engine_name="mechanical", include_thinking=False, budget_seconds=3000, index_text="", now=None, clock=time.monotonic, chunk_chars=60000, cap_chars=400000, result_head=400) -> dict` exactly as the repo version plus `result_head` passed to `extract_turns`; `sleep.DREAMS_DIRNAME = "dreams"`; `sleep.last_watermark(out_root, session_id)`; `sleep.newest_dream_for(out_root, session_id)`; `sleep.dreams_awaiting(out_root, *, stale_days=14, now=None) -> list[dict]` (ported from `memory_store_check.dreams_awaiting`).
- `cli.main(argv) -> int` with subcommands `sleep`, `reseed`, `notice`, `dream`, `list`, `config`; global options `--project`, `--home` (tests), `--hook-json`.

- [ ] **Step 1: Port sleep.py**

Copy quantum-concepts `sleep.py` to `plugin/dreaming/sleep.py` and keep ONLY: `_Log`, `_write`, `dream_folder_name`, `_fresh_folder`, `_session_dreams`, `last_watermark`, `run_sleep`, `_newest_dream_for` (renamed `newest_dream_for`). Replace `msc.DREAMS_DIRNAME` with a module constant `DREAMS_DIRNAME = "dreams"`; imports become `from . import distill as sd, extract as sx`. Drop everything else (identity, index, CLI). Add `dreams_awaiting` copied from `memory_store_check.dreams_awaiting` with `DREAMS_DIRNAME` and `stale_days` parameter. In `run_sleep`, pass `result_head=result_head` to `sx.extract_turns`.

- [ ] **Step 2: Write cli.py**

```python
#!/usr/bin/env python3
"""cli.py - the plugin's entry points.

    python -m dreaming.cli sleep      # PreCompact hook, hook JSON on stdin; always exit 0
    python -m dreaming.cli reseed     # SessionStart(compact) hook; prints additionalContext JSON
    python -m dreaming.cli notice     # SessionStart(startup|resume) hook; one line if dreams await
    python -m dreaming.cli dream --transcript P [--agent A] [--engine E] [--dry-run]
    python -m dreaming.cli list [--agent A]
    python -m dreaming.cli config     # the effective config and where each layer came from
"""
import argparse
import json
import os
import sys

from . import config as _config, engines as se, identity, sleep as sl


def _read_hook_json(args):
    if args.hook_json:
        return json.loads(args.hook_json)
    try:
        raw = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    except Exception:
        raw = ""
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {}


def _load(args, hook):
    cwd = args.project or hook.get("cwd") or os.getcwd()
    env = dict(os.environ)
    if args.agent:
        env["DREAMING_AGENT"] = args.agent
    cfg = _config.load(project_dir=cwd, env=env, home=args.home)
    return cfg, cwd, env


def _pick_engine(cfg, name):
    if name == "mechanical":
        return None, "mechanical"
    if name in ("openai_compatible", "claude"):
        return se.build_engine(dict(cfg, engines=[name, "mechanical"]))
    return se.build_engine(cfg)


def cmd_sleep(args):
    try:
        hook = _read_hook_json(args)
        cfg, cwd, env = _load(args, hook)
        if not cfg.get("enabled", True):
            return 0
        transcript = args.transcript or hook.get("transcript_path")
        session_id = args.session or hook.get("session_id") or ""
        res = identity.resolve(cfg, cwd, transcript=transcript, env=env, hook=hook)
        if res.scratch:
            print("dreaming: NOT writing to a store (%s)" % res.reason)
        if not transcript or not os.path.isfile(transcript):
            raise FileNotFoundError("transcript not found: %r" % transcript)
        engine, engine_name = _pick_engine(cfg, args.engine)
        index_text = "" if res.scratch else identity.index_text(res.store, cfg)
        out = sl.run_sleep(transcript, agent=res.agent, session_id=session_id, out_root=res.store,
                           engine=engine, engine_name=engine_name,
                           include_thinking=bool(args.include_thinking or cfg.get("include_thinking")),
                           budget_seconds=int(args.budget or cfg.get("budget_seconds") or 3000),
                           index_text=index_text, chunk_chars=int(cfg.get("chunk_chars") or 60000),
                           cap_chars=int(cfg.get("cap_chars") or 400000),
                           result_head=int(cfg.get("result_head") or 400))
        print("dreaming: %s | engine %s | lessons %d | tensions %d%s" % (
            out["folder"], engine_name, out["lessons"], out["tensions"],
            (" | degraded: " + "; ".join(out["degraded"])) if out["degraded"] else ""))
    except Exception as exc:
        print("dreaming: sleep failed (compaction proceeds): %s" % exc)
    return 0


def cmd_reseed(args):
    try:
        hook = _read_hook_json(args)
        cfg, cwd, env = _load(args, hook)
        if not cfg.get("enabled", True):
            return 0
        session_id = args.session or hook.get("session_id") or ""
        res = identity.resolve(cfg, cwd, transcript=hook.get("transcript_path"), env=env, hook=hook)
        roots = [res.store] if not res.scratch else []
        roots.append(identity.scratch_root(hook, cfg))
        folder = next((f for f in (sl.newest_dream_for(r, session_id) for r in roots) if f), None)
        if not folder:
            return 0
        with open(os.path.join(folder, "brief.md"), "r", encoding="utf-8", errors="replace") as fh:
            brief = fh.read()
        mine = next((d for d in sl.dreams_awaiting(os.path.dirname(os.path.dirname(folder)))
                     if os.path.normcase(d["path"]) == os.path.normcase(folder)), None)
        staged = (" - %d lesson(s), %d tension(s) staged" % (mine["lessons"], mine["tensions"])) if mine else ""
        tail = ("\n\n(dreaming re-seed: this brief was written by the sleep step before compaction. "
                "Dream folder: %s%s. Promote or delete it at your next wake - see the dreaming-promote skill.)" % (folder, staged))
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": brief + tail}}))
    except Exception as exc:
        print("dreaming: reseed skipped: %s" % exc)
    return 0


def cmd_notice(args):
    try:
        hook = _read_hook_json(args)
        cfg, cwd, env = _load(args, hook)
        if not cfg.get("enabled", True):
            return 0
        res = identity.resolve(cfg, cwd, transcript=hook.get("transcript_path"), env=env, hook=hook)
        if res.scratch:
            return 0
        dreams = sl.dreams_awaiting(res.store, stale_days=int(cfg.get("stale_days") or 14))
        if not dreams:
            return 0
        lines = ["dreaming: %d dream(s) awaiting promotion in %s (agent %s). Read them in your first coherence pass "
                 "and promote or delete each folder - the dreaming-promote skill is the procedure." % (len(dreams), res.store, res.agent)]
        for d in dreams:
            lines.append("  %s - %d lesson(s), %d tension(s)%s" % (d["name"], d["lessons"], d["tensions"], "  STALE" if d["stale"] else ""))
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(lines)}}))
    except Exception as exc:
        print("dreaming: notice skipped: %s" % exc)
    return 0


def cmd_dream(args):
    hook = {"transcript_path": args.transcript, "session_id": args.session or os.path.basename(args.transcript).split(".")[0]}
    cfg, cwd, env = _load(args, hook)
    res = identity.resolve(cfg, cwd, transcript=args.transcript, env=env, hook=hook)
    print("identity:", res.reason)
    out_root = identity.scratch_root(hook, cfg) if (args.dry_run or res.scratch) else res.store
    if args.dry_run:
        print("dreaming into scratch:", out_root)
    engine, engine_name = _pick_engine(cfg, args.engine)
    print("engine:", engine_name)
    out = sl.run_sleep(args.transcript, agent=res.agent, session_id=hook["session_id"], out_root=out_root,
                       engine=engine, engine_name=engine_name,
                       include_thinking=bool(args.include_thinking or cfg.get("include_thinking")),
                       budget_seconds=int(args.budget or cfg.get("budget_seconds") or 3000),
                       index_text="" if (args.dry_run or res.scratch) else identity.index_text(res.store, cfg),
                       chunk_chars=int(cfg.get("chunk_chars") or 60000), cap_chars=int(cfg.get("cap_chars") or 400000),
                       result_head=int(cfg.get("result_head") or 400))
    print(json.dumps({k: v for k, v in out.items() if k != "stages"}, indent=1))
    print("stages:", json.dumps(out["stages"]))
    return 0


def cmd_list(args):
    cfg, cwd, env = _load(args, {})
    res = identity.resolve(cfg, cwd, transcript=None, env=env)
    if res.scratch:
        print("no store:", res.reason)
        return 1
    dreams = sl.dreams_awaiting(res.store, stale_days=int(cfg.get("stale_days") or 14))
    if not dreams:
        print("no dreams awaiting promotion for %s in %s" % (res.agent, res.store))
        return 0
    for d in dreams:
        print("%s  -  %d lesson(s), %d tension(s), %.1f days%s" % (d["name"], d["lessons"], d["tensions"], d["age_days"], "  STALE" if d["stale"] else ""))
    return 0


def cmd_config(args):
    cfg, cwd, env = _load(args, {})
    print(json.dumps(cfg, indent=1, default=str))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="dreaming", description="Sleep at compaction.")
    parser.add_argument("--project", help="project dir (default: hook cwd, else the current dir)")
    parser.add_argument("--home", help="home dir for ~/.dreaming/config.json (tests)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--agent")
        p.add_argument("--engine", default="auto", choices=("auto", "openai_compatible", "claude", "mechanical"))
        p.add_argument("--include-thinking", action="store_true")
        p.add_argument("--budget", type=int)
        p.add_argument("--session")
        p.add_argument("--transcript")
        p.add_argument("--hook-json")

    for name in ("sleep", "reseed", "notice"):
        common(sub.add_parser(name))
    d = sub.add_parser("dream")
    common(d)
    d.add_argument("--dry-run", action="store_true")
    l = sub.add_parser("list")
    l.add_argument("--agent")
    sub.add_parser("config")
    args = parser.parse_args(argv)
    if args.cmd == "dream" and not args.transcript:
        parser.error("dream needs --transcript")
    return {"sleep": cmd_sleep, "reseed": cmd_reseed, "notice": cmd_notice, "dream": cmd_dream,
            "list": cmd_list, "config": cmd_config}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Port test_sleep.py**

`plugin/tests/test_sleep.py`: port `SleepRunTests` and `ReseedTests` from the repo's `test_sleep.py`, with these changes: imports `from dreaming import sleep as sl, distill as sd, extract as sx, cli` and `from dreaming.engines import EngineResult`; the test constants imported `from test_distill import MAP_JSON, REDUCE_JSON, INDEX_TEXT`; `_fake_store(tmp)` now creates `<tmp>/project/.git`, `<tmp>/project/.dreaming.json` = `{"agents": {"Joule": "team/worker/memory"}}`, and the store `<tmp>/project/team/worker/memory` with the same `MEMORY.md` and one lesson file; every `sl.main([...])` call becomes `cli.main(["--project", self.project, "--home", self.home, "sleep", ...])` (and `reseed`); `sl.resolve_identity` tests are replaced by the identity tests already in Task 3 (delete `test_identity_refuses_non_ok_store_and_env_override_wins` and `test_identity_prefers_the_transcript_agent_name_over_git_config`); `test_index_is_not_read_when_the_store_is_not_ok` monkeypatches `identity.index_text` instead of `sl.index_text_for` and removes the store dir so the mapped store is missing; `test_hook_sleep_exits_zero_and_writes_to_scratch_when_store_not_ok` asserts the printed line contains `missing` and that `<scratch>/dreaming/dreams` holds one folder; `sl._newest_dream_for` becomes `sl.newest_dream_for`. Keep every other test verbatim.

- [ ] **Step 4: Run everything**

Run: `python -W error::ResourceWarning -m unittest discover -s plugin/tests -v`
Expected: 50 + about 16 = 66 tests, `OK`.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: the pipeline and the cli - sleep, reseed, notice, dream, list, config

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Hooks, skills, docs

**Files:**
- Create: `plugin/hooks/hooks.json`, `plugin/hooks/precompact_sleep.py`, `plugin/hooks/sessionstart_reseed.py`, `plugin/hooks/sessionstart_notice.py`
- Create: `plugin/skills/dreaming/SKILL.md`, `plugin/skills/dreaming-promote/SKILL.md`
- Create: `README.md`, `INSTALL.md`, `CHANGELOG.md`
- Test: `plugin/tests/test_hooks.py`

- [ ] **Step 1: Write the failing hook tests**

`plugin/tests/test_hooks.py`:

```python
#!/usr/bin/env python3
"""Each hook script is a subprocess that must exit 0 on empty, garbage and valid stdin, and must
write nothing under any store when the input is garbage."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.abspath(os.path.join(HERE, "..", "hooks"))
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class HookScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dreaming-hooks-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, script, stdin):
        env = dict(os.environ, DREAMING_STORE_ROOT=os.path.join(self.tmp, "stores"), HOME=self.home,
                   USERPROFILE=self.home, CLAUDE_PLUGIN_ROOT=os.path.abspath(os.path.join(HERE, "..")))
        env.pop("DREAMING_DISABLED", None)
        return subprocess.run([sys.executable, os.path.join(HOOKS, script)], input=stdin, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120, env=env,
                              cwd=self.tmp, creationflags=_NO_WINDOW)

    def test_hook_scripts_exit_zero_on_garbage_stdin(self):
        for script in ("precompact_sleep.py", "sessionstart_reseed.py", "sessionstart_notice.py"):
            for stdin in ("", "{not json", json.dumps({"session_id": "s"})):
                done = self._run(script, stdin)
                self.assertEqual(done.returncode, 0, (script, stdin, done.stdout, done.stderr))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "stores")))

    def test_disabled_env_makes_every_hook_silent(self):
        for script in ("precompact_sleep.py", "sessionstart_reseed.py", "sessionstart_notice.py"):
            env = dict(os.environ, DREAMING_DISABLED="1")
            done = subprocess.run([sys.executable, os.path.join(HOOKS, script)], input="{}", capture_output=True,
                                  text=True, encoding="utf-8", timeout=60, env=env, creationflags=_NO_WINDOW)
            self.assertEqual(done.returncode, 0)
            self.assertEqual(done.stdout.strip(), "")

    def test_hooks_json_wires_the_three_events(self):
        with open(os.path.join(HOOKS, "hooks.json"), "r", encoding="utf-8") as fh:
            spec = json.load(fh)["hooks"]
        self.assertIn("PreCompact", spec)
        self.assertEqual(spec["PreCompact"][0]["hooks"][0]["timeout"], 3600)
        matchers = [entry.get("matcher") for entry in spec["SessionStart"]]
        self.assertIn("compact", matchers)
        self.assertTrue(any("startup" in (m or "") for m in matchers))
        for event in spec.values():
            for entry in event:
                for h in entry["hooks"]:
                    self.assertIn("${CLAUDE_PLUGIN_ROOT}", h["command"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Expected: three errors, the scripts do not exist.

- [ ] **Step 3: Write the hooks**

`plugin/hooks/hooks.json`:
```json
{
  "description": "dreaming: sleep at compaction. PreCompact runs the consolidation BLOCKING (the session is asleep) with a one-hour ceiling; SessionStart(compact) re-seeds the fresh context from the brief; SessionStart(startup|resume) says how many dreams await promotion. Every hook exits 0 on any failure; DREAMING_DISABLED=1 or enabled:false silences all three.",
  "hooks": {
    "PreCompact": [
      { "hooks": [ { "type": "command", "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/precompact_sleep.py\"", "timeout": 3600 } ] }
    ],
    "SessionStart": [
      { "matcher": "compact", "hooks": [ { "type": "command", "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/sessionstart_reseed.py\"", "timeout": 30 } ] },
      { "matcher": "startup|resume", "hooks": [ { "type": "command", "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/sessionstart_notice.py\"", "timeout": 15 } ] }
    ]
  }
}
```

Each script is the same nine lines with a different subcommand; `precompact_sleep.py`:
```python
#!/usr/bin/env python3
"""PreCompact hook: sleep. Never exits non-zero - compaction must proceed whatever happens here."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    from dreaming import cli
    code = cli.main(["sleep"])
except BaseException as exc:  # noqa: BLE001 - a hook must not die
    print("dreaming: sleep failed (compaction proceeds): %s" % exc)
    code = 0
sys.exit(0 if code is None else 0)
```
`sessionstart_reseed.py` calls `cli.main(["reseed"])`, `sessionstart_notice.py` calls `cli.main(["notice"])`, with the docstring and the failure text adjusted (`reseed skipped`, `notice skipped`).

- [ ] **Step 4: Skills and docs**

`plugin/skills/dreaming/SKILL.md` (frontmatter `name: dreaming`, description: "What the dreaming plugin does at compaction, the dream folder contract, and how to configure it (store root, agents map, engines). Load when a session mentions dreams awaiting promotion, when configuring which store an agent dreams into, or when the sleep hook's output needs reading."): sections What happens at compaction; The dream folder (the file list and the five brief fields); Configuration (the JSON block from the spec, the layering, the env names); Identity rules (the six numbered rules from the spec); Engines; Reading `sleep.log` (what `degraded:` lines mean).

`plugin/skills/dreaming-promote/SKILL.md` (frontmatter `name: dreaming-promote`, description: "The wake procedure for dreams staged by the dreaming plugin: read each dream folder, promote the lessons that hold up into real memory entries with index lines, hold genuine tensions as IN-TENSION, then delete the folder. Load at session start when the notice says dreams await promotion, or when asked to promote or clear dreams."): Procedure: 1 `python -m dreaming.cli list` (or read the notice); 2 for each folder read `brief.md`, `lessons/*.md`, `tensions.md`; 3 for each lesson decide keep / extends an existing entry / drop, and for a keep write the entry in the store's own format and add its index line by hand; 4 for each tension, if it is a reversal you can verify, fix the existing entry with provenance, else record it as IN-TENSION beside the entry it touches; 5 delete the folder; 6 never let the folder linger past `stale_days`. Rules: the tool lists, the mind writes; the plugin never touches the index; a dream is a candidate, not a fact.

`README.md`: what it is (four paragraphs from the spec's opening), the three hooks, the dream folder, quick config, the two skills, the design principle (staging only; the mind promotes), credits (built from the quantum-concepts sleep step). `INSTALL.md`: the two commands (`claude plugin marketplace add AmeNoMurakumo1234/dreaming`, `claude plugin install dreaming@dreaming`), the declarative pin block, the local-server setup (`~/.dreaming/config.json` with `base_url` and `api_key_file`), the disable file for a repo that runs its own step, and how to test with `python -m dreaming.cli dream --transcript ... --dry-run`. `CHANGELOG.md`: `0.1.0 - 2026-09-22 - first release`.

- [ ] **Step 5: Run everything**

Run: `python -W error::ResourceWarning -m unittest discover -s plugin/tests -v`
Expected: 69 tests, `OK`.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: hooks, skills, docs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Release - scanner, validate, live dream, the QC disable file, publish, install

- [ ] **Step 1: Console-flash scanner and manifest validation**

```bash
python "C:/Users/murik/.claude/skills/spawning-processes-without-flashing-windows/scan_spawns.py" F:/writing/plugins/dreaming --all
claude plugin validate F:/writing/plugins/dreaming --strict
claude plugin validate F:/writing/plugins/dreaming/plugin --strict
```
Expected: zero UNGUARDED spawns (every `subprocess.run` carries `creationflags`); both validations pass. Fix anything they name.

- [ ] **Step 2: Live dream through llama into scratch**

With `Y:/llamakey` as the key file:
```bash
cd F:/writing/plugins/dreaming/plugin && DREAMING_API_KEY_FILE=Y:/llamakey DREAMING_AGENT=Joule python -m dreaming.cli dream --dry-run --engine openai_compatible --transcript "C:/Users/murik/.claude/projects/F--writing-quantum-concepts/2def5d4e-48fc-4013-b40f-c98c51288afc.jsonl"
```
Expected: `engine: openai_compatible`, a folder under `%TEMP%/dreaming/dreams/`, lessons > 0, a brief whose Current Task is about the dreaming plugin, `degraded: none`. Read `brief.md` and two lessons; record chunks, seconds, lessons, tensions in the release commit.

- [ ] **Step 3: The quantum-concepts disable file**

In `F:/writing/quantum-concepts` create `.dreaming.json`:
```json
{
  "enabled": false,
  "note": "quantum-concepts runs its own sleep step (.agents/scripts/governance/sleep.py, issue 1974) until the cutover to the dreaming plugin. Flip to true and map agents to team/<role>/memory in the same commit that removes the repo's own PreCompact/SessionStart hooks."
}
```
Commit there as Joule: `git cas Joule -m "chore(dreaming): disable the dreaming plugin here until the cutover (1974) ..."` and push.

- [ ] **Step 4: Publish**

```bash
cd F:/writing/plugins/dreaming && git add -A && git commit -m "release: 0.1.0 ..." 
gh repo create AmeNoMurakumo1234/dreaming --public --source . --push --description "Sleep at compaction: a Claude Code plugin that consolidates a session into durable memory before the summary drops it."
```
Then on this machine:
```bash
claude plugin marketplace add AmeNoMurakumo1234/dreaming
claude plugin install dreaming@dreaming
claude plugin list
```
Expected: `dreaming@dreaming` listed and enabled. Then from `F:/writing/quantum-concepts` run `python -m dreaming.cli config --project .` via the installed copy's path (`claude plugin details dreaming` shows it) and confirm `enabled: false` with `project` among `_sources`.

- [ ] **Step 5: Final verification and commit**

Run the whole suite once more, then commit any doc corrections and push. Record in `CHANGELOG.md` the live-dream numbers.

---

## Self-review notes

- Spec coverage: layout and manifests (T1), config (T1), client (T2), identity and index and scratch (T3), ported extract (T3), engines and distill (T4), pipeline and cli and dreams_awaiting (T5), hooks and disable switch and skills and docs (T6), release checks, QC disable file, publish and install (T7).
- Review Focus 1 and 2 pinned in T3, 3 in T6, 4 in T2, 5 in T1.
- Names consistent: `Resolution(agent, source, store, scratch, reason)`, `identity.resolve/agent_name/index_text/scratch_root`, `engines.local_available/local_complete/claude_complete/claude_smoke/build_engine(cfg, ...)`, `sleep.run_sleep/last_watermark/newest_dream_for/dreams_awaiting/DREAMS_DIRNAME`, `cli.main`.
