# Changelog

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
