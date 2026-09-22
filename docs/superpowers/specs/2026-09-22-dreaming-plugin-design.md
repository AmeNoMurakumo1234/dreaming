# dreaming: a Claude Code plugin that consolidates a session into durable memory at compaction

Date: 2026-09-22. Author: Joule. Owner: Ame No Murakumo (design approved in conversation, same day).

## What this is

Claude Code compacts a session when its context fills. The compaction summary is written by the
harness, it is silent, and it drops things. This plugin puts a blocking hook at that moment: it
reads the full transcript, distils it into candidate lessons, a five-field resume brief and the
tensions it found with what the agent already believes, stages all of it in the agent's memory
store, and after compaction re-seeds the fresh context from the brief. At the next session start
it says how many dreams are waiting, and a skill teaches the promotion step. The built-in summary
still happens; what changes is that nothing worth keeping has to survive it.

It is the generalisation of the sleep step built and reviewed the same day inside quantum-concepts
(`docs/superpowers/specs/2026-09-22-sleep-step-design.md` there, issue 1974). That spec carries the
rationale in full; this one records only what changes when the same mechanism has to serve any
repo, any agent, and any user.

## Decisions already made by the owner

- **Public GitHub marketplace** `AmeNoMurakumo1234/dreaming`, MIT, repo-is-the-marketplace layout
  like `topic-visualizer`. Installs with two commands.
- **quantum-concepts cuts over later.** This build adds one file to that repo, a `.dreaming.json`
  with `enabled: false`, so an install on this machine cannot double-sleep a session that already
  runs its own step. The cutover is a separate, small commit.
- **Blocking sleep**, **staging only** (the plugin never writes an index and never resolves a
  tension), **local engine first**. Unchanged from the repo build.

## What is ported unchanged

From quantum-concepts at commit 901ef3e9, `.agents/scripts/governance/`: the transcript extractor
(`sleep_extract.py`), the prompts and map/reduce/renderers (`sleep_distill.py`), the engine ladder
(`sleep_engines.py`), the pipeline and re-seed (`sleep.py`), and their tests. Every fix from that
day's review comes with them: fenced state-first prompts, index bounded to a third of the window,
halving that gives up when it stops shrinking, the wall-clock budget on the reduce, a brief on disk
before the first engine call, folder names with seconds plus a collision suffix, the newest
watermark line winning, truncated replies and engine errors named in the log, the user prompt on
stdin for the nested `claude -p`, every subprocess spawned without a console window.

## What changes: four seams become configuration

| In quantum-concepts | In the plugin |
|---|---|
| Identity via the team roster into `team/<role>/memory` | `identity.py`: env, transcript agent-name, git config, `default`; a project-level `agents` map names the store, else `store_root/<agent>` |
| Store health via `memory_store_check` | `identity.py`: a mapped store that is missing is never created (scratch plus a printed reason); an unmapped default store is created on first use |
| The live index via `cli-memory-search.py index` | `identity.py`: `<store>/<index_file>` read directly if present, one bounded line per entry, else no index |
| `ai_client` for the llama call and the JSON helpers | `client.py`: a stdlib OpenAI-compatible client (base URL, key from file or env, model, timeout; `/health` then a one-token completion as the probe) and the four helpers: `extract_json`, `salvage_json_list`, `looks_truncated_json`, `to_ascii` |

## Repository layout

```
dreaming/                              the marketplace repo
  .claude-plugin/marketplace.json      one plugin, source ./plugin
  README.md  INSTALL.md  LICENSE  CHANGELOG.md  .gitignore
  docs/superpowers/{specs,plans}/
  plugin/
    .claude-plugin/plugin.json
    hooks/hooks.json                   PreCompact -> sleep; SessionStart(compact) -> reseed;
                                       SessionStart(startup|resume) -> notice
    hooks/precompact_sleep.py          thin: exec cli sleep, exit 0
    hooks/sessionstart_reseed.py       thin: exec cli reseed, exit 0
    hooks/sessionstart_notice.py       thin: exec cli notice, exit 0
    dreaming/__init__.py
    dreaming/config.py                 defaults < ~/.dreaming/config.json < <project>/.dreaming.json < DREAMING_* env
    dreaming/identity.py               agent, store path, scratch decision, index text
    dreaming/client.py                 OpenAI-compatible chat + JSON helpers, stdlib only
    dreaming/extract.py                ported
    dreaming/engines.py                ported; llama adapter now calls client.py
    dreaming/distill.py                ported; helpers now from client.py
    dreaming/sleep.py                  ported pipeline: run_sleep, last_watermark, newest dream
    dreaming/cli.py                    sleep | reseed | notice | dream | list | config
    skills/dreaming/SKILL.md           what it is, the folder contract, configuration
    skills/dreaming-promote/SKILL.md   the wake procedure: read, promote, hold tensions, delete
    tests/test_extract.py test_client.py test_config.py test_identity.py test_engines.py
          test_distill.py test_sleep.py test_hooks.py
```

## Configuration

Layered, later wins: built-in defaults, then `~/.dreaming/config.json`, then `<project>/.dreaming.json`
where `<project>` is the hook's `cwd` (or the git toplevel above it), then environment variables
`DREAMING_<KEY>` for scalar keys (`DREAMING_AGENT`, `DREAMING_DISABLED=1`, `DREAMING_STORE_ROOT`,
`DREAMING_BASE_URL`, `DREAMING_API_KEY`, `DREAMING_API_KEY_FILE`, `DREAMING_MODEL`).

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

1. Agent name: first of `DREAMING_AGENT`, the transcript's last `agent-name` record, `git config
   user.name` in the project, `default`, in the configured order.
2. Store: if `agents` is non-empty, the mapped path or scratch; else `store_root/<agent>`.
3. A mapped store whose directory is missing is NEVER created: scratch plus a printed reason. A
   lost store must not be silently rebuilt by the tool that serves it.
4. An unmapped default store is created on first use.
5. Scratch is the hook's `scratchpad_dir` if given, else `<tempdir>/dreaming/`, always under a
   `dreams/` subfolder so `reseed` and `list` can find it.
6. The index is `<store>/<index_file>` when present: each non-blank line trimmed to 118 chars, in
   file order, then bounded by the reduce to a third of the window.

## Hooks and their contracts

- `PreCompact` (no matcher, timeout 3600): `cli sleep` with the hook JSON on stdin. Prints one
  summary line. Exit 0 always.
- `SessionStart` matcher `compact` (timeout 30): `cli reseed`. Prints the documented
  `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ...}}` carrying
  the newest brief for this session plus one line naming the dream folder and the staged counts.
  Prints nothing when there is no dream. Exit 0 always.
- `SessionStart` matcher `startup|resume` (timeout 15): `cli notice`. When the agent's store holds
  dreams, prints one line of additional context: how many, the store path, and that the
  `dreaming-promote` skill is the procedure. Silent otherwise. Exit 0 always.
- Every hook honours `enabled: false` and `DREAMING_DISABLED=1` by exiting 0 silently.

## The dream folder (unchanged contract)

`<store>/dreams/<YYYYMMDD-HHMMSS>-<session8>[-n]/` with `day.md`, `map/<n>.json`, `reduce.json`,
`brief.md`, `lessons/<slug>.md`, `tensions.md`, `sleep.log`. The brief uses the five fields Current
Task, Exact State, Next Step, Uncommitted Decisions, Files Currently In Context. Lessons carry the
title, why, how to apply, and a provenance line with the session and turn uuids. Tensions are held
with both sides. `sleep.log` names every fallback as `degraded: <reason>` and records the
watermark uuid the next sleep in the same session continues from.

## Invariants (each is a test)

- Never writes into a mapped store that is missing; never creates one.
- Never edits the index file or any file outside `dreams/`.
- Hook subcommands always exit 0, including on garbage stdin and internal exceptions.
- Every stage's output is on disk before the next engine call; a brief exists before the first one.
- Every fallback is named in `sleep.log`.
- The second sleep in a session consumes only records after the first's watermark.
- No subprocess is spawned with a console window; no model payload rides in argv.

## Testing

The ported suite adapted to the new seams, plus: config layering and env override; identity with
and without an `agents` map, mapped-but-missing store, default store created; the client's JSON
helpers on well-formed, prose, wrong-key and truncated inputs, with the well-formed case as the
control; the OpenAI-compatible request shape against a fake `urlopen`; each hook script exits 0 on
empty, garbage and valid stdin. Release checks: the console-flash scanner over the plugin,
`claude plugin validate --strict`, one live dream of a real transcript through llama into a temp
store, then a real install on this machine with `claude plugin list` showing it and a
quantum-concepts session confirming the `.dreaming.json` disable takes effect.

## Out of scope for v1

Auto-promotion (a later opt-in), async sleep, PostCompact, writing any index, an MCP server, a web
view, Anthropic API keys (the `claude -p` engine uses the CLI's own login), and the quantum-concepts
cutover.
