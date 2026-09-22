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
    if str(env.get("DREAMING_DISABLED", "")).strip().lower() in ("1", "true", "yes"):
        cfg["enabled"] = False
        touched = True
    if touched:
        sources.append("env")

    # A relative store_root is relative to the project root when there is one (a project file
    # saying "stores" means <project>/stores), else to home.
    cfg["store_root"] = expand_path(cfg.get("store_root"), root or home, home)
    cfg["agents"] = {k: expand_path(v, root, home) for k, v in (cfg.get("agents") or {}).items()}
    oc = cfg.get("openai_compatible") or {}
    if oc.get("api_key_file"):
        oc["api_key_file"] = expand_path(oc["api_key_file"], root, home)
    cfg["_project_dir"] = root
    cfg["_sources"] = sources
    return cfg
