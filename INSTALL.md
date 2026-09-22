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

The agent is taken from `DREAMING_AGENT`, else the transcript's own agent-name record, else
`git config user.name`. An agent not in the map dreams into scratch; a mapped store that is
missing is never created.

## Uninstall

```
claude plugin uninstall dreaming@dreaming
```

Dream folders already staged under your stores are left where they are.
