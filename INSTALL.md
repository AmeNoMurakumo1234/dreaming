# Installing dreaming

This repo is both a Claude Code marketplace and the `dreaming` plugin it hosts. Source of truth:
`https://github.com/AmeNoMurakumo1234/dreaming`. Python 3.10+ on your PATH as `python` is the
only requirement; the plugin is stdlib only. On Windows make sure `python` resolves to a real
interpreter and not the Microsoft Store stub (`python --version` should print a version).

## Quick start

From any terminal:

```
claude plugin marketplace add AmeNoMurakumo1234/dreaming
claude plugin install dreaming@dreaming
```

Inside a running `claude` session:

```
/plugin marketplace add AmeNoMurakumo1234/dreaming
/plugin install dreaming@dreaming
```

**Pin it in a repo (declarative).** Commit a `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "dreaming": { "source": { "source": "github", "repo": "AmeNoMurakumo1234/dreaming" } }
  },
  "enabledPlugins": { "dreaming@dreaming": true }
}
```

## Point it at your local model

Create `~/.dreaming/config.json`:

```json
{
  "openai_compatible": {
    "base_url": "http://127.0.0.1:8081",
    "api_key_file": "~/.llamakey",
    "model": "local"
  }
}
```

Any `/v1/chat/completions` server works. The key file is optional; `DREAMING_API_KEY` in the
environment is the alternative. Without a reachable server the plugin falls back to `claude -p`
(which uses the CLI's own login, so run `claude login` once if you want that engine) and then to a
mechanical brief.

**A reasoning server needs a bigger reply budget.** Some servers split the model's thinking into
`reasoning_content` and count it against `max_tokens`; at the default 4096 they can spend the whole
budget thinking and return no content, and sleep.log says so:
`hit max_tokens (4096) before any content; the server spent the budget on 15084 chars of
reasoning_content - raise openai_compatible.max_tokens`. Set it per server:

```json
{ "openai_compatible": {"base_url": "http://127.0.0.1:8081", "api_key_file": "~/.llamakey", "model": "local",
                        "max_tokens": 12000} }
```

**Several servers.** Give `openai_compatible` a list in preference order; the first that answers
its probe is used for the whole sleep, and one that raises is skipped rather than ending the
ladder. `label` names it in the logs.

```json
{ "openai_compatible": [
    {"label": "4090", "base_url": "https://fast.example", "api_key_file": "~/.llamakey", "model": "local"},
    {"label": "mini", "base_url": "http://192.168.1.111:8602", "api_key_file": "~/.llamakey", "model": "local",
     "max_tokens": 12000, "timeout": 1200}
  ] }
```

## Try it on a transcript without touching a store

```
cd <plugin dir>/plugin
python -m dreaming.cli dream --dry-run --transcript "~/.claude/projects/<project>/<session>.jsonl"
```

The dream lands under your temp directory (`dreaming/dreams/...`), and the output prints the
folder, the engine, and the lesson and tension counts. `python -m dreaming.cli config` prints the
effective configuration and which layers contributed. The installed plugin's directory is shown by
`claude plugin details dreaming`.

## A repository that already consolidates its own sessions

Commit a `.dreaming.json` at its root:

```json
{ "enabled": false, "note": "this repo runs its own sleep step" }
```

Every hook then exits silently there, so an installed plugin cannot double-sleep a session.

## Several agents sharing one clone

Commit a `.dreaming.json` mapping each agent to its store:

```json
{ "agents": { "Joule": "team/worker/memory", "Codex": "team/book-content/memory" } }
```

The agent is the first source, in this order, whose name is IN THE MAP: `DREAMING_AGENT`, a
configured `agent`, the transcript's own agent-name record, `git config user.name`. The map
filters each candidate rather than the first one only, because a source can return a name that
is not an identity: the Claude Code desktop app writes the SESSION TITLE into the transcript's
agent-name record, so a session titled "RTX 5080 market research" still dreams as the `Joule`
that git names. An agent no source can name dreams into scratch, and the hook prints every
candidate it tried; a mapped store that is missing is never created.

## Updating

```
claude plugin update dreaming@dreaming
```

The installer then prints "Restart to apply changes". Measured 2026-09-22 in the desktop app: a
session that had the plugin installed at 0.1.0, updated to 0.1.1 mid-session, and was then
compacted ran the 0.1.1 hook without a restart (the dream landed in the mapped store, which the
0.1.0 identity rule could not have produced from that transcript). That is one measurement of
one hook, so treat it as "you probably do not have to restart", not as a promise; the hook
command resolves `${CLAUDE_PLUGIN_ROOT}` at fire time, and the versioned cache directories sit
side by side, so an old session that keeps the old root is at worst one sleep behind.

## Uninstall

```
claude plugin uninstall dreaming@dreaming
```

Dream folders already staged under your stores are left where they are.
