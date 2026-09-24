# Changelog

## 0.3.2 - 2026-09-23

Three defects from a field report on the first PreCompact sleep of a long interactive session
(4090-class local server, 220 s, seven slices), plus one documented behaviour. 5 tests added,
126 pass.

- The brief's state is a COPY of the newest slice's state, never the reduce's choice. The reduce
  had re-emitted the second-newest slice's state verbatim - six hours stale - while the newest
  slice held the right one, so the 0.3.1 rule (which only fired when the newest slice was EMPTY)
  did not catch it. Now `sleep.log` says `state: copied from slice N of N`; an unmapped or empty
  newest slice still means the mechanical state, as before.
- A tension must name an entry the index actually holds. With no index the reduce had filed
  twelve tensions against "existing entries" built from the transcript's own sentences. Now:
  no index, no tensions (`no index; tensions not filed (N dropped)`); with an index, a tension
  whose `existing_slug` is not in it is dropped and counted
  (`N tension(s) named entries not in the index; dropped`).
- A capped day opens on a user or assistant turn, never on an orphan `tool_result` whose
  `tool_use` fell on the far side of the cap.
- Documented: `index_file` may be an absolute path, for a lane whose real index lives outside
  its store (it already worked; now it is pinned by a test and said in the skill). Dream folder
  names and `sleep.log` stamps are LOCAL time, said in the skill. A private LAN address in the
  docs' endpoint example is now a documentation address.

## 0.3.1 - 2026-09-23

Two defects exposed by the first live sleep on the `claude` engine (llama down, Haiku dreamed;
7 slices, 23 lessons, 3 tensions, 319 s), both fixed test-first (3 tests added, 121 pass).

- The watermark no longer dies with the promoted folder. It lived only in the dream folder's
  sleep.log, and promotion deletes the folder, so a session whose earlier dreams had been promoted
  slept from `(start)` again: the whole transcript re-extracted, the 400k cap hit, lessons already
  in the index re-staged. Every sleep now also writes `<store>/dreams/.watermark-<session>.txt`
  (a file, so the dream listings never count it), and `last_watermark` reads it first, falling
  back to surviving folders for stores written before this release.
- A map slice that parses but returns no lessons and no state is now a degraded line
  (`map chunk N returned no lessons and no state`). Haiku returned three such slices, the newest
  three, and the log read as a full dream.
- The resume state may only come from the NEWEST slice. When that slice was never mapped (budget)
  or came back without a state, the reduce's state was built from an older slice and was stale by
  construction: the live brief told a waking agent it was on work finished eight hours earlier,
  naming files that had been deleted. The sleep now writes the mechanical state of the last turns
  instead and says so (`newest slice yielded no state (unmapped or empty); brief is mechanical`).
  Crude and true beats articulate and stale.

## 0.3.0 - 2026-09-23

Sleep at session end, so a short session that never compacts still dreams.

- Claude Code caps SessionEnd hooks at 60 s (docs: a 1.5 s shared budget, raised by `timeout` to at
  most 60), and a sleep costs 70-220 s measured, so the hook cannot sleep. `sessionend_spawn.py`
  decides in under a second - enough rendered transcript since the last watermark? - and hands the
  ordinary `sleep` command to a DETACHED child: `python.exe` with CREATE_NO_WINDOW,
  CREATE_NEW_PROCESS_GROUP and CREATE_BREAKAWAY_FROM_JOB, stdin DEVNULL, stdout to a log in the
  scratch dir. Measured: such a child ran 90 s past its session's exit and spawned git windowlessly.
  The next session's start notice reports the dream as usual.
- New config `sessionend: {"enabled": true, "min_chars": 20000}`; below `min_chars` (a
  `claude -p "Reply OK"`, a two-line resume) nothing is spawned. The nested `claude -p` engine runs
  in safe mode, so its own exit never fires this hook.
- Measured on `claude -p`: SessionEnd fires with `reason: other` and a payload carrying
  `session_id`, `transcript_path`, `cwd`, `prompt_id`, and the transcript holds the final
  assistant turn at fire time.
- 11 tests added (118 pass), including an end-to-end guard in which the hook script returns and a
  dream folder then appears, written by the detached child.

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
