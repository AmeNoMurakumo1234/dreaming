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
    "identity_order": ["scheduled_task", "env", "config", "transcript", "git", "default"],
    "engines": ["openai_compatible", "claude", "mechanical"],
    "openai_compatible": {"base_url": "http://127.0.0.1:8081", "api_key_file": "",
                          "api_key_env": "DREAMING_API_KEY", "model": "local", "timeout": 900},
    # sonnet, not haiku: haiku returned empty-but-valid slices on short scheduled runs five times
    # in one day (2026-09-23); the fallback runs rarely and reads better than it runs fast.
    "claude": {"model": "sonnet", "timeout": 900},
    "chunk_chars": 60000,
    "cap_chars": 400000,
    # Every engine call gets the remaining budget as its timeout, so a sleep never crosses the
    # hook's 3600 s ceiling; the brief is written mechanically before the first call, so running
    # out of budget costs lessons, not the resume. Measured full-transcript sleeps: 223 s on a
    # local 27B (Joule, 2026-09-22), 88 s on a 4090 (Assay, 2026-09-23). The default was 2400,
    # which let a compaction block an interactive session for forty minutes on a slow or
    # misconfigured server; 900 fits what the tool costs with room for a slow box. Raise it in
    # config for a server you know is slow and want to wait for.
    "budget_seconds": 900,
    "result_head": 400,
    # Sleep at session end, detached (Claude Code caps SessionEnd hooks at 60 s, so the hook only
    # decides and spawns). min_chars is rendered transcript since the last watermark: below it a
    # session (a `claude -p "Reply OK"`, a two-line resume) has nothing to dream and spawns nothing.
    "sessionend": {"enabled": True, "min_chars": 20000},
    "include_thinking": False,
    # A routine is a fresh session every run, so SessionStart(compact) never reaches it. With
    # reseed_on_startup the startup notice also injects the newest brief in the store written
    # under the SAME scheduled-task name, once, while it is younger than reseed_max_age_hours.
    "reseed_on_startup": False,
    "reseed_max_age_hours": 48,
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


def _endpoint_dicts(oc):
    """`openai_compatible` may be one endpoint dict or a LIST of them (preference order). Every
    per-endpoint fix-up (key-file expansion, an env override) walks this, never `oc.get(...)`."""
    if isinstance(oc, dict):
        return [oc]
    if isinstance(oc, list):
        return [e for e in oc if isinstance(e, dict)]
    return []


def _env_target(cfg, path):
    """(node, key) a DREAMING_* scalar writes to, or None to decline. A path into
    `openai_compatible` steers the FIRST (preferred) endpoint when it is a list; an empty list
    has nothing to steer. This used to be setdefault(key, {})[...] = value, which raised
    TypeError against a list - and a hook that cannot load its config is a hook that never
    dreams (Assay, 2026-09-23)."""
    node = cfg
    for key in path[:-1]:
        child = node.get(key)
        if child is None:
            child = node[key] = {}
        elif isinstance(child, list):
            dicts = _endpoint_dicts(child)
            if not dicts:
                return None
            child = dicts[0]
        elif not isinstance(child, dict):
            return None
        node = child
    return node, path[-1]


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
    except (OSError, ValueError):
        return None, "invalid"
    if not isinstance(obj, dict):
        return None, "invalid"
    return obj, "ok"


def project_root(start):
    """Nearest ancestor holding .git, else `start` itself. None when start is falsy."""
    if not start:
        return None
    cur = os.path.abspath(start)
    while True:
        marker = os.path.join(cur, ".git")
        if os.path.isdir(marker) or os.path.isfile(marker):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(start)
        cur = parent


def expand_path(value, base, home=None):
    value = str(value or "")
    if not value:
        return value
    if value == "~" or value.startswith(("~/", "~\\")):
        value = (home or os.path.expanduser("~")) + value[1:]
    elif value.startswith("~"):
        value = os.path.expanduser(value)      # ~user/x: the OS knows, a home override does not
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
            target = _env_target(cfg, path)
            if target is None:
                continue        # e.g. an empty endpoint list: nothing to steer, and never a raise
            node, key = target
            node[key] = env[name]
            touched = True
    if str(env.get("DREAMING_DISABLED", "")).strip().lower() in ("1", "true", "yes"):
        cfg["enabled"] = False
        touched = True
    if touched:
        sources.append("env")

    # A relative store_root is relative to the project root when there is one (a project file
    # saying "stores" means <project>/stores), else to home.
    cfg["store_root"] = expand_path(cfg.get("store_root"), root or home, home)
    cfg["agents"] = {k: expand_path(v, root, home) for k, v in (cfg.get("agents") or {}).items()}
    for oc in _endpoint_dicts(cfg.get("openai_compatible")):
        if oc.get("api_key_file"):
            oc["api_key_file"] = expand_path(oc["api_key_file"], root, home)
    cfg["_project_dir"] = root
    cfg["_sources"] = sources
    return cfg
