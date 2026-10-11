---
name: dreaming
description: "What the dreaming plugin does at compaction, the dream folder contract, and how to configure it (store root, agents map, engines). Load when a session mentions leftover dream folders, when configuring which store an agent dreams into, when a sleep hook's output needs reading, or when asked what dreaming is."
---

# dreaming

Claude Code compacts a session when its context fills. The compaction summary is written by the
harness, it is silent, and it drops things. This plugin puts a blocking hook at that moment: it
reads the NEWEST slice of the transcript, writes a five-field resume brief into your memory store,
and after compaction re-seeds the fresh context from that brief. The built-in summary still
happens. What changes is that the exact task, stopping point and next step survive it.

**A dream is continuity across ONE compaction, never memory** (owner ruling 2026-09-25). Since 0.6.0
a sleep is brief-only: no lessons, no tensions, no reduce, and the index is never read. A dream
folder found at the start of a NEW session has nothing left to carry - delete it; the reaper
clears other sessions' old ones on its own. If an old doc, prompt or notice tells you to promote a
dream into lessons, it predates 0.5.3 and is stale.

## What happens, and when

| Event | Hook | What it does |
|---|---|---|
| Context about to compact (manual or automatic) | `PreCompact`, blocking, one-hour ceiling | extract the transcript, read its newest slice for the resume state (ONE engine call), write a dream folder, reap other sessions' folders older than `reap_days` |
| The session ends (exit, `/clear`, a `claude -p` run finishing) - OFF by default since 0.5.3 | `SessionEnd`, capped at 60 s by Claude Code | when opted in, decide in under a second whether enough transcript is new since the last watermark (`sessionend.min_chars`), then hand the same sleep to a DETACHED windowless child that outlives the session; its dream is reported by the next start notice |
| Right after compaction | `SessionStart` with the `compact` matcher | re-inject the newest brief for this session as context |
| A new or resumed session | `SessionStart` with `startup` or `resume` | one line: how many dream folders are left, and where - delete them; with `reseed_on_startup`, the CARRY-OVER first (below) |

The session is genuinely asleep during the first one, but briefly: one call on one slice of at
most `chunk_chars`. The ceiling is an hour and a wall-clock budget inside it (default 900 s) bounds
the call; when too little budget remains the call is skipped and the brief is mechanical.

## The dream folder

`<store>/dreams/<YYYYMMDD-HHMMSS>-<session8>/` - the stamp is LOCAL time, as are the stamps in `sleep.log`

| File | What it is |
|---|---|
| `day.md` | the extracted transcript: user and assistant text, tool names, trimmed tool results, one `### role @time [uuid]` marker per turn |
| `map/<n>.json` | the model's reply for the newest slice (n of n) - the only slice a sleep reads |
| `brief.md` | the resume brief: Current Task, Exact State, Next Step, Uncommitted Decisions, Files Currently In Context - the newest slice's state, verbatim, or the mechanical state of the last turns |
| `sleep.log` | the run: engine, per-stage timings, every `degraded: <reason>` line, and the `watermark:` uuid the next sleep in this session continues from |

Beside the folders, `<store>/dreams/.watermark-<session>.txt` holds where this session's last
sleep stopped. It is a file, not a folder, so nothing counts it as a dream, and deleting a folder
leaves it alone: the next sleep in the session continues from it rather than re-reading the whole
transcript.

A sleep writes ONLY inside `<store>/dreams/`. It never reads or writes your index or any memory file.

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
  "agents_fallback": "scratch",
  "identity_order": ["scheduled_task", "env", "config", "transcript", "git", "default"],
  "engines": ["openai_compatible", "claude", "mechanical"],
  "openai_compatible": {"base_url": "http://127.0.0.1:8081", "api_key_file": "", "api_key_env": "DREAMING_API_KEY",
                        "model": "local", "timeout": 900, "max_tokens": 0, "label": ""},
  "claude": {"model": "opus", "timeout": 900},
  "chunk_chars": 60000, "cap_chars": 400000, "budget_seconds": 900,
  "sessionend": {"enabled": false, "min_chars": 20000},
  "reseed_on_startup": false, "reseed_max_age_hours": 48,
  "result_head": 400, "include_thinking": false,
  "stale_days": 14, "reap_days": 14
}
```

`agents` maps an agent name to a store directory. At project level a relative path is relative to
the project root. When the map is non-empty, an agent not in it dreams into scratch and the hook
prints why: a map is a statement of who lives here.

`sessionend` governs the sleep at session end. Claude Code caps SessionEnd hooks at 60 s and a
sleep costs minutes, so the hook only decides and spawns: it renders the transcript since the last
watermark and, at `min_chars` or more, starts the ordinary `sleep` as a detached child
(`python.exe` with CREATE_NO_WINDOW, CREATE_NEW_PROCESS_GROUP and CREATE_BREAKAWAY_FROM_JOB,
stdin closed, output to `<scratch>/exit-<session>.log`). Below `min_chars` nothing is spawned, which
is what keeps a `claude -p "Reply OK"` from dreaming. `enabled: false` here turns off only the
exit sleep; compaction still sleeps. It defaults to `false` since 0.5.3: dreams are compaction
continuity, and a sleep at session end carries nothing anywhere. `reap_days` (default 14, 0 = off)
is how old another session's dream folder or watermark must be before a sleep removes it.

`openai_compatible` may also be a LIST of endpoint dicts in preference order, each with its own
`base_url`, key, model, timeout and `max_tokens`, and an optional `label` for the logs:

```json
{ "openai_compatible": [
    {"label": "4090", "base_url": "https://fast.example:443", "api_key_file": "~/.llamakey", "model": "local"},
    {"label": "mini", "base_url": "http://192.0.2.11:8602", "api_key_file": "~/.llamakey", "model": "local",
     "max_tokens": 12000, "timeout": 1200}
  ] }
```

The first endpoint whose probe answers is used for the whole sleep; a probe that raises moves to
the next endpoint, not to `claude`. A single dict is one endpoint and reads exactly as before.
`DREAMING_BASE_URL`, `DREAMING_MODEL` and `DREAMING_API_KEY_FILE` steer the FIRST endpoint of a
list. `max_tokens` (per endpoint) overrides the 4096 reply clamp: a REASONING server that splits
its thinking into `reasoning_content` spends the budget there first and writes no content at
4000, which sleep.log reports as `hit max_tokens (4000) before any content; the server spent the
budget on N chars of reasoning_content` - raise `max_tokens` for that endpoint (8000-12000 has
worked) or point at a server that does not split.

## Identity and store rules

1. Agent name, in `identity_order`: `scheduled_task` (the `name` of the `<scheduled-task ...>` tag
   in the transcript's FIRST user turn - a scheduled run's lane, on every run; a tag quoted in a
   later turn is not an identity), `env` (`DREAMING_AGENT`), `config` (a configured `agent`
   that is not `auto`), `transcript` (the session's own agent-name record), `git` (`git config
   user.name` in the project), `default`. The name becomes a path component, so separators,
   `..`, reserved characters and absurd lengths fall back to `default` with the source marked
   `invalid`.
   With a non-empty `agents` map the rule is stricter: the winner is the FIRST source in that
   order whose name is IN THE MAP, not the first source that returns any name. A source can
   return a name that is not an identity at all - in the Claude Code desktop app the transcript's
   agent-name record carries the SESSION TITLE - and taking it would send a real agent to scratch
   while `git` one step down names them correctly. If no source is mapped, scratch, and the
   printed reason lists every candidate tried.
2. Store: if `agents` is non-empty, the mapped path, else scratch - or `store_root/<agent>` when
   `agents_fallback` is `"store_root"` (opt-in: routine lanes appear by name at run time, and a
   map naming only the interactive agent would otherwise send every routine's dream to scratch);
   without a map, `store_root/<agent>`.
3. A mapped store whose directory is missing is NEVER created: scratch plus a printed reason. A
   lost store must not be silently rebuilt by the tool that serves it.
4. An unmapped default store is created by the sleep that first writes into it, and by nothing
   else: `notice`, `reseed`, `list` and a `--dry-run` dream create no directories.
5. Scratch is the hook's scratchpad directory when it gives one, else `<tempdir>/dreaming/`.

## Routines: a lane's dream, picked up by the lane

A scheduled run is a fresh session every time, so the compaction re-seed (which matches the
session id) never reaches it. Three pieces make a routine's dream its own:

- Its identity is the task name from the `<scheduled-task ...>` tag (rule 1 above), so the dream
  lands in that task's store: map the task names in `agents` (`"pm-agent": "team/pm/memory"`),
  or without a map it is `store_root/<task>`. The brief's header stamps the task
  (`| task pm-agent`) and so does `sleep.log`.
- `reseed_on_startup: true` makes the startup notice inject the store's newest brief written
  under the SAME task name - once, under `# Carry-over from your previous run (dream <name>,
  task <task>)`, with a trailer saying it is what the last run LEFT and must be verified before
  acting on it. Keyed by TASK, not store: two routines of one mind may share a store (a morning
  and an evening run) and never receive each other's brief. Only while the dream is younger than
  `reseed_max_age_hours`. SCHEDULED RUNS ONLY: an interactive session has no task, so there is
  no key to match a brief on, and two interactive sessions of one agent would hand each other
  their briefs; it never receives a carry-over, whatever the option says. Its compaction re-seed
  matches on the SESSION ID and is untouched.
- `python -m dreaming.cli list --all` lists every mapped store and every child of `store_root`
  that holds dreams, with their ages, so a checkup can see (and clear) every lane's leftover
  dreams without walking directories.

## Engines

Tried in the configured order; the first that answers wins:

- `openai_compatible` - any `/v1/chat/completions` server (llama.cpp, vLLM, Ollama and the like),
  or a list of them in preference order. Each is probed with `/health` (a 404 is fine, Ollama
  has none) and then a one-token authenticated completion, so a server that is up but rejects
  your key is treated as down. With several endpoints the engine is logged as
  `openai_compatible[<label>]`; with one it stays `openai_compatible`.
- `claude` - `claude -p --safe-mode --model opus` on the CLI's own login (`claude.model`; opus since 0.5.6, sonnet
  since 0.4.0, because haiku returned empty slices on short scheduled runs). Safe mode disables CLAUDE.md, skills,
  plugins, hooks and MCP inside the nested run on any machine (this plugin included: a nested run
  must never sleep) and keeps the OAuth login (measured 2026-09-22). The prompt goes on stdin.
- `mechanical` - no model: the brief is built from the last turns. Always available.

The one engine call gets the remaining budget as its timeout, capped by the engine's configured
timeout, and is skipped when less than thirty seconds remain, so a sleep cannot cross the hook's
3600 s ceiling whatever the budget. The brief is written before the call, so a run that dies or
runs out still re-seeds something.

## Reading sleep.log

Every fallback is a `degraded:` line. The ones you will see:

- `no engine - mechanical brief`: neither model answered; the brief is mechanical.
- `slice N of N engine error: ...` / `slice N of N did not parse`: the call produced nothing usable;
  the brief is mechanical.
- `slice N of N returned no state`: the reply parsed, was in the right shape, and was empty.
- `slice N of N: state in an unexpected shape (list), dropped`: the model answered in a shape the
  parser cannot use. On the `claude` engine before 0.5.4 this was the signature of the Windows
  truncation of the instructions to their first line; on 0.5.4 or later the model genuinely ignored
  the schema - check which model answered (the `read` line names it) before blaming the prompt.
- `slice N of N truncated (provider cap)`: the reply hit the token cap; the state comes first in the
  contract, so it is usually salvaged whole.
- `newest slice yielded no state (unread or empty); brief is mechanical`: the newest slice gave no
  state, so the brief is built from the last turns. The plain line `state: from slice N of N (only
  the newest slice is read)` is the healthy case: the brief is that slice's state, verbatim.
- `the state named a system payload as the task; replaced with the last real request`: the model
  took a task notification or a system reminder for the task; the rest of its state is kept.
- `budget Ns exhausted before the newest slice; brief is mechanical`: no call was made.
- `watermark <uuid> not in transcript; extracted everything`: the session was resumed into a new
  file; the whole transcript was extracted again.

## Turning it off

`DREAMING_DISABLED=1` in the environment, or `"enabled": false` in a config layer. A repository
that runs its own consolidation should commit a `.dreaming.json` with `enabled: false` so an
installed plugin cannot double-sleep a session there.
