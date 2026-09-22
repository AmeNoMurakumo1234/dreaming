# Changelog

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
- 73 tests, stdlib only, every subprocess windowless.
