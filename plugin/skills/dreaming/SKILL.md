---
name: dreaming
description: "What the dreaming plugin does at compaction, the dream folder contract, and how to configure it (store root, agents map, engines). Load when a session mentions dreams awaiting promotion, when configuring which store an agent dreams into, when a sleep hook's output needs reading, or when asked what dreaming is."
---

# dreaming

Claude Code compacts a session when its context fills. The compaction summary is written by the
harness, it is silent, and it drops things. This plugin puts a blocking hook at that moment: it
reads the full transcript, distils it into candidate lessons, a five-field resume brief and the
tensions it found with what you already believe, stages all of it in your memory store, and after
compaction re-seeds the fresh context from the brief. The built-in summary still happens. What
changes is that nothing worth keeping has to survive it.

## What happens, and when

| Event | Hook | What it does |
|---|---|---|
| Context about to compact (manual or automatic) | `PreCompact`, blocking, one-hour ceiling | extract the transcript, map each slice, reduce against your index, write a dream folder |
| Right after compaction | `SessionStart` with the `compact` matcher | re-inject the newest brief for this session as context |
| A new or resumed session | `SessionStart` with `startup` or `resume` | one line: how many dreams await promotion, and where |

The session is genuinely asleep during the first one. A full transcript of a long day through a
local 27B model takes two to three minutes; the ceiling is an hour and a wall-clock budget inside
it (default 50 minutes) stops the work early and writes what it has.

## The dream folder

`<store>/dreams/<YYYYMMDD-HHMMSS>-<session8>/`

| File | What it is |
|---|---|
| `day.md` | the extracted transcript: user and assistant text, tool names, trimmed tool results, one `### role @time [uuid]` marker per turn |
| `map/<n>.json` | the model's notes per slice |
| `reduce.json` | the merged notes, matched against your index |
| `brief.md` | the resume brief: Current Task, Exact State, Next Step, Uncommitted Decisions, Files Currently In Context |
| `lessons/<slug>.md` | one candidate lesson each: title, why, how to apply, provenance (session and turn uuids); `extends: <slug>` when it extends an entry you already hold |
| `tensions.md` | contradictions with your existing entries, both sides stated, deliberately NOT resolved |
| `sleep.log` | the run: engine, per-stage timings, every `degraded: <reason>` line, and the `watermark:` uuid the next sleep in this session continues from |

A dream is a CANDIDATE, not a fact. The plugin never writes your index and never resolves a
tension; the `dreaming-promote` skill is the procedure by which you do.

## Configuration

Layered, later wins: built-in defaults, then `~/.dreaming/config.json`, then `<project>/.dreaming.json`
(found from the session's working directory up to the nearest `.git`), then environment
variables `DREAMING_AGENT`, `DREAMING_DISABLED=1`, `DREAMING_STORE_ROOT`, `DREAMING_BASE_URL`,
`DREAMING_API_KEY`, `DREAMING_API_KEY_FILE`, `DREAMING_MODEL`.

```json
{
  "enabled": true,
  "store_root": "~/.dreaming/stores",
  "agent": "auto",
  "agents": {},
  "identity_order": ["env", "transcript", "git", "default"],
  "engines": ["openai_compatible", "claude", "mechanical"],
  "openai_compatible": {"base_url": "http://127.0.0.1:8081", "api_key_file": "", "api_key_env": "DREAMING_API_KEY",
                        "model": "local", "timeout": 900},
  "claude": {"model": "haiku", "timeout": 900},
  "chunk_chars": 60000, "cap_chars": 400000, "budget_seconds": 3000,
  "result_head": 400, "include_thinking": false,
  "index_file": "MEMORY.md", "stale_days": 14
}
```

`agents` maps an agent name to a store directory. At project level a relative path is relative to
the project root. When the map is non-empty, an agent not in it dreams into scratch and the hook
prints why: a map is a statement of who lives here.

## Identity and store rules

1. Agent name: `DREAMING_AGENT`, then a configured `agent` (when not `auto`), then the transcript's
   own agent-name record, then `git config user.name` in the project, then `default`.
2. Store: if `agents` is non-empty, the mapped path or scratch; else `store_root/<agent>`.
3. A mapped store whose directory is missing is NEVER created: scratch plus a printed reason. A
   lost store must not be silently rebuilt by the tool that serves it.
4. An unmapped default store is created on first use.
5. Scratch is the hook's scratchpad directory when it gives one, else `<tempdir>/dreaming/`.
6. The index is `<store>/<index_file>` when present, one bounded line per entry, and the reduce
   uses it to mark each lesson `new` or `extends: <slug>`.

## Engines

Tried in the configured order; the first that answers wins:

- `openai_compatible` - any `/v1/chat/completions` server (llama.cpp, vLLM, Ollama and the like).
  Probed with `/health` and then a one-token authenticated completion, so a server that is up but
  rejects your key is treated as down.
- `claude` - `claude -p` on the CLI's own login, with every plugin disabled and hooks emptied
  inside the nested run (this plugin included: a nested run must never sleep). The prompt goes on
  stdin.
- `mechanical` - no model: the brief is built from the last turns, no lessons. Always available.

## Reading sleep.log

Every fallback is a `degraded:` line. The ones you will see:

- `no engine - mechanical brief`: neither model answered; the brief is mechanical, promote nothing.
- `map chunk N did not parse` / `engine error`: that slice produced nothing; the others still count.
- `map chunk N truncated` / `reduce reply truncated (provider cap)`: the reply hit the token cap;
  what was salvaged is a prefix, the brief is intact (state comes first in the contract).
- `reduce input too large for the window; using the union of the map passes`: no cross-slice
  merge happened; expect near-duplicate lessons.
- `budget Ns exhausted ...`: the wall-clock budget stopped the run; the dream is complete but shorter.
- `watermark <uuid> not in transcript; extracted everything`: the session was resumed into a new
  file; the whole transcript was consolidated again.

## Turning it off

`DREAMING_DISABLED=1` in the environment, or `"enabled": false` in a config layer. A repository
that runs its own consolidation should commit a `.dreaming.json` with `enabled: false` so an
installed plugin cannot double-sleep a session there.
