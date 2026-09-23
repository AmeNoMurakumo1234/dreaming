# Changelog

## 0.2.0 - 2026-09-23

Three defects found by Assay wiring 0.1.2 to two llama servers running the same gguf (report of
2026-09-23; re-implemented here test-first from the report, 22 tests added, 107 pass).

- `chat()` reads `finish_reason`. An empty reply at `length` now says which budget was hit and how
  many chars of `reasoning_content` consumed it; any other empty reply names its reason;
  `finish_reason` rides every result. The old bare `empty completion` covered "said nothing" and
  "ran out of room", which want opposite fixes.
- `openai_compatible.max_tokens` (per endpoint) overrides both the caller's request and the 4096
  clamp; unset keeps 0.1.2 behaviour exactly. Against a reasoning server no configuration of
  0.1.2 could produce an answer.
- `openai_compatible` may be a LIST of endpoint dicts in preference order; a single dict is one
  entry. The first whose probe answers is used for the sleep, a probe that raises falls through to
  the next endpoint (not to `claude`), and with several endpoints the engine is logged as
  `openai_compatible[<label>]`. Two config knock-ons fixed with it: `api_key_file` is expanded for
  every endpoint, and a `DREAMING_*` scalar steers the first endpoint instead of raising
  `TypeError` on a list (a hook that cannot load its config never dreams).
- `budget_seconds` default 2400 -> 900. Measured sleeps: 223 s (local 27B), 88 s (4090). The hook
  ceiling stays 3600 so a configured larger budget still fits.

Ruled and not changed: the map and reduce still ask for 4000 tokens (the configured `max_tokens`
wins, which is the knob an operator actually has); `EngineResult` does not carry `finish_reason`
(a truncated non-empty reply is already caught by the distiller's salvage and flagged in the log).

## 0.1.2 - 2026-09-22

Documentation only; no code change.

- The 0.1.1 identity rule (first MAPPED source wins) reached the code and the changelog but not
  the skill, the README or INSTALL.md, which still described the 0.1.0 order. All three now state
  the rule and the desktop-app fact behind it (the transcript's agent-name record is the session
  title).
- INSTALL.md gains an Updating section: `claude plugin update` says "Restart to apply changes",
  and the one measurement so far says the updated hook fires without one.
- First live fire, for the record: the installed plugin's PreCompact hook ran on a real `/compact`
  in the desktop app. 2,162 transcript records, 910 after the watermark, 7 map chunks of 60k
  chars on a local Qwen3.8-27B, reduce halved 0, no degraded stage, 223 s asleep, 5 lessons and
  2 tensions staged in the mapped store, and the five-field brief re-seeded at the top of the
  fresh context. Where the brief and the harness summary disagreed (one dream waiting versus
  two) the brief was right.

## 0.1.1 - 2026-09-22

- With an `agents` map, the FIRST identity source whose name is mapped wins. Measured in the Claude
  desktop app: the transcript's agent-name record carries the session TITLE, not the agent, so a
  real session was sent to scratch while git config named the agent correctly. The scratch reason
  now lists every candidate tried.

## 0.1.0 - 2026-09-22

First release. Ported from the quantum-concepts sleep step (issue 1974 there), with the four
repo-bound seams turned into configuration:

- `PreCompact` blocking sleep (one-hour ceiling, 50-minute internal budget), `SessionStart(compact)`
  re-seed, `SessionStart(startup|resume)` notice.
- Layered config: defaults, `~/.dreaming/config.json`, `<project>/.dreaming.json`, `DREAMING_*`.
- Identity: env, transcript agent-name, git config, default; `agents` map with scratch for the
  unmapped; a mapped store that is missing is never created.
- Engines: any OpenAI-compatible server (stdlib client, authenticated probe), `claude -p` over
  stdin with plugins disabled inside the nested run, mechanical fallback.
- Fenced state-first prompts, bounded index, bounded halving, budget on the reduce, brief before the
  first engine call, seconds-plus-suffix folder names, newest watermark, truncation and engine
  errors named in `sleep.log`.
- Two skills: `dreaming` (the contract and configuration) and `dreaming-promote` (the wake step).
- After a fresh whole-branch review: hook JSON read as UTF-8 regardless of the locale codec (a
  non-ASCII path used to break the hook and defeat `enabled: false` on Windows); stores created
  only by the sleep that writes them; agent names validated as path components; `claude -p
  --safe-mode` instead of a machine-specific plugin list; every engine call bounded by the
  remaining budget (default 2400 s) so a sleep cannot cross the hook ceiling; `config` is its own
  identity step; a missing `/health` no longer hides an Ollama-style server.
- 84 tests, stdlib only, every subprocess windowless.
- Measured on a 1,782-record transcript through a local Qwen3.8-27B (llama.cpp): 6 slices of 60k chars,
  194 s, 9 lessons, 1 tension, no degraded stage, resume brief correct.
