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
| The session ends (exit, `/clear`, a `claude -p` run finishing) | `SessionEnd`, capped at 60 s by Claude Code | decide in under a second whether enough transcript is new since the last watermark (`sessionend.min_chars`), then hand the same sleep to a DETACHED windowless child that outlives the session; its dream is reported by the next start notice |
| Right after compaction | `SessionStart` with the `compact` matcher | re-inject the newest brief for this session as context |
| A new or resumed session | `SessionStart` with `startup` or `resume` | one line: how many dreams await promotion, and where; with `reseed_on_startup`, the CARRY-OVER first (below) |

The session is genuinely asleep during the first one. A full transcript of a long day through a
local 27B model takes two to three minutes; the ceiling is an hour and a wall-clock budget inside
it (default 50 minutes) stops the work early and writes what it has.

## The dream folder

`<store>/dreams/<YYYYMMDD-HHMMSS>-<session8>/` - the stamp is LOCAL time, as are the stamps in `sleep.log`

| File | What it is |
|---|---|
| `day.md` | the extracted transcript: user and assistant text, tool names, trimmed tool results, one `### role @time [uuid]` marker per turn |
| `map/<n>.json` | the model's notes per slice |
| `reduce.json` | the merged notes, matched against your index |
| `brief.md` | the resume brief: Current Task, Exact State, Next Step, Uncommitted Decisions, Files Currently In Context - a COPY of the newest slice's state (since 0.3.2 the reduce never chooses it) |
| `lessons/<slug>.md` | one candidate lesson each: title, why, how to apply, provenance (session and turn uuids); `extends: <slug>` when it extends an entry you already hold; `restates a known rule: <file>` when it only restates a `known_rules` file (kept for you to drop, never dropped by the tool); `scope: generalised` when it reaches past what the session showed (test it hardest) |
| `tensions.md` | contradictions with your existing entries, both sides stated, deliberately NOT resolved |
| `sleep.log` | the run: engine, per-stage timings, every `degraded: <reason>` line, and the `watermark:` uuid the next sleep in this session continues from |

Beside the folders, `<store>/dreams/.watermark-<session>.txt` holds where this session's last
sleep stopped. It is a file, not a folder, so nothing counts it as a dream, and promotion (which
deletes the folder) leaves it alone: the next sleep in the session continues from it. Before
0.3.1 the watermark lived only in sleep.log and died with the promoted folder, so the third sleep
of a session re-dreamed the whole transcript.

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
  "agents_fallback": "scratch",
  "indexes": {},
  "known_rules": [],
  "identity_order": ["scheduled_task", "env", "config", "transcript", "git", "default"],
  "engines": ["openai_compatible", "claude", "mechanical"],
  "openai_compatible": {"base_url": "http://127.0.0.1:8081", "api_key_file": "", "api_key_env": "DREAMING_API_KEY",
                        "model": "local", "timeout": 900, "max_tokens": 0, "label": ""},
  "claude": {"model": "sonnet", "timeout": 900},
  "chunk_chars": 60000, "cap_chars": 400000, "budget_seconds": 900,
  "sessionend": {"enabled": true, "min_chars": 20000},
  "reseed_on_startup": false, "reseed_max_age_hours": 48,
  "result_head": 400, "include_thinking": false,
  "index_file": "MEMORY.md", "stale_days": 14
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
exit sleep; compaction still sleeps.

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
6. The index is `<store>/<index_file>` when present, one bounded line per entry, and the reduce
   uses it to mark each lesson `new` or `extends: <slug>`. `index_file` may be an ABSOLUTE path
   for a lane whose real index lives outside its store, and `indexes` maps an agent to a LIST of
   index files (absolute or ~-relative) that replaces it for that agent. Without an index no
   tension is filed, and with one a tension must name an entry in it (0.3.2).

## Known rules: what the reduce is told you already hold

`known_rules` lists files (absolute, ~-relative, or relative to the project) whose content goes
to the reduce as ALREADY HELD - a rules file, a lane charter - bounded to a quarter of the
reduce window with the head kept, so put the rules first in the file. Field measurement: of
twenty lessons in one promotion pass, eleven restated rules written in such files, which the
index does not carry. A lesson that only restates one comes back labelled `known`, is counted in
`sleep.log`, and is KEPT: the tool lists, the mind drops.

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
- Promotion is still the mind's job, not the routine's. `python -m dreaming.cli list --all`
  lists every mapped store and every child of `store_root` that holds dreams, with counts, so
  an interactive checkup can see every lane's dreams without walking directories.

## Engines

Tried in the configured order; the first that answers wins:

- `openai_compatible` - any `/v1/chat/completions` server (llama.cpp, vLLM, Ollama and the like),
  or a list of them in preference order. Each is probed with `/health` (a 404 is fine, Ollama
  has none) and then a one-token authenticated completion, so a server that is up but rejects
  your key is treated as down. With several endpoints the engine is logged as
  `openai_compatible[<label>]`; with one it stays `openai_compatible`.
- `claude` - `claude -p --safe-mode --model sonnet` on the CLI's own login (`claude.model`; sonnet
  since 0.4.0, because haiku returned empty slices on short scheduled runs). Safe mode disables CLAUDE.md, skills,
  plugins, hooks and MCP inside the nested run on any machine (this plugin included: a nested run
  must never sleep) and keeps the OAuth login (measured 2026-09-22). The prompt goes on stdin.
- `mechanical` - no model: the brief is built from the last turns, no lessons. Always available.

Every engine call gets the remaining budget as its timeout, capped by the engine's configured
timeout, and a stage is skipped when less than thirty seconds remain, so a sleep cannot cross the
hook's 3600 s ceiling whatever the budget. The default budget is 900 s (it was 2400 until 0.2.0):
measured full-transcript sleeps cost 223 s on a local 27B and 88 s on a 4090, and a budget that
let a slow or misconfigured server block an interactive session for forty minutes was the wrong
default. The brief is written before the first engine call, so running out costs lessons, never
the resume. Raise `budget_seconds` for a server you know is slow and want to wait for.

## Reading sleep.log

Every fallback is a `degraded:` line. The ones you will see:

- `no engine - mechanical brief`: neither model answered; the brief is mechanical, promote nothing.
- `map chunk N did not parse` / `engine error`: that slice produced nothing; the others still count.
- `map chunk N returned no lessons and no state`: the reply parsed and was empty. One is a quiet
  slice; several, or the newest one, means the model was not really reading. Measured twice on
  the `claude` engine at its default `haiku` on short, structured scheduled runs; if that is your
  shape, set `"claude": {"model": "sonnet"}` - the fallback runs rarely and reads better than
  it runs fast.
- `newest slice yielded no state (unmapped or empty); brief is mechanical`: the resume state may
  only come from the newest slice of the day, and that slice gave none, so the brief is built from
  the last turns rather than from an older slice's articulate but stale state. The plain line
  `state: copied from slice N of N` is the healthy case: the brief is that slice's state, verbatim.
- `no index; tensions not filed (N dropped)` / `N tension(s) named entries not in the index; dropped`:
  a tension must name an entry you hold; the model had invented the entry from the day itself.
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
