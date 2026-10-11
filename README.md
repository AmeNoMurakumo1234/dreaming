# dreaming

**Sleep at compaction.** A Claude Code plugin that carries a session across the moment the harness
is about to forget it.

Claude Code compacts a session when its context fills. The compaction summary is written by the
harness, it is silent, and it drops things. `dreaming` puts a blocking hook at that moment: it reads
the newest slice of the transcript, writes a five-field resume brief into your memory store, and
after compaction re-seeds the fresh context from that brief. The built-in summary still happens.
What changes is that the exact task, the exact stopping point and the next step survive it.

**A dream is continuity, not memory.** It carries ONE session across a compaction and is never
promoted into lessons (since 0.6.0). A dream folder found at the start of a new session has nothing
left to carry, so the notice says to delete it, and the reaper clears old ones on its own.

## What it does

| When | Hook | Effect |
|---|---|---|
| Context about to compact | `PreCompact`, blocking, one-hour ceiling | extract the transcript, read its newest slice for the resume state (one engine call), write a dream folder, reap other sessions' old ones |
| The session ends (OFF by default; `sessionend.enabled` opts in) | `SessionEnd` (capped at 60 s) | if enough is new since the last watermark, the same sleep runs in a detached child that outlives the session |
| Right after compaction | `SessionStart` (`compact`) | the newest brief for this session is injected as context |
| First prompt of a session, or a resume | `UserPromptSubmit` (first prompt only), `SessionStart` (`resume`) | "N dream folder(s) left in <store> ... delete each folder"; with `reseed_on_startup`, a scheduled run also receives its own task's previous brief. Never at `SessionStart` (`startup`): it fires before the scheduled-task tag is in the transcript, so it could only guess who is waking - and the guess was whoever owns the clone |

The engine ladder: any local OpenAI-compatible server first (llama.cpp, vLLM, Ollama),
`claude -p --safe-mode` (opus) on the CLI's own login second, and a mechanical brief built from the last
turns when neither answers. Every hook exits 0 on any failure; compaction is never blocked on a
dead engine, and every engine call is bounded by the remaining budget so a sleep cannot outrun
the hook's one-hour ceiling. The hooks invoke `python`, so Python 3.10+ has to be on the PATH
under that name (on Windows, not the Store stub).

## The dream folder

```
<store>/dreams/20260922-125402-2def5d4e/        (local time, then the session's first 8 chars)
  day.md            the extracted transcript since this session's last sleep
  map/<n>.json      the model's reply for the newest slice (n of n) - the only slice it reads
  brief.md          Current Task / Exact State / Next Step / Uncommitted Decisions / Files In Context
  sleep.log         engine, timings, every "degraded:" line, the watermark for the next sleep
```

Beside the folders, `<store>/dreams/.watermark-<session>.txt` records where this session's last
sleep stopped, so the next sleep in the same session continues from it instead of re-reading the
whole session - even if you deleted the folder in between.

## The one design rule

**A sleep writes only inside `<store>/dreams/`.** It never reads or writes your index, never edits a
memory file, and never decides anything for you. If the engine cannot answer - no budget left, an
error, a reply it cannot parse, an empty state - the brief falls back to a mechanical one built from
the last turns, and `sleep.log` names why. Compaction is never blocked on a dream.

## Configuration in one minute

`~/.dreaming/config.json` for you, `<project>/.dreaming.json` for a repository, `DREAMING_*`
environment variables on top. The two settings most people touch:

```json
{
  "openai_compatible": {"base_url": "http://127.0.0.1:8081", "api_key_file": "~/.llamakey", "model": "local"},
  "store_root": "~/.dreaming/stores"
}
```

`openai_compatible` can also be a list of servers in preference order (the first that answers
is used, a dead one is skipped), and each server takes a `max_tokens` for reasoning models that
spend the reply budget thinking. A repository with several agents sharing one clone maps each to
its own store:

```json
{ "agents": { "Joule": "team/worker/memory", "Codex": "team/book-content/memory" } }
```

With a map in place the agent is the first identity source whose name is in the map (the
sources, in order: the `<scheduled-task name=...>` tag of a scheduled run, `DREAMING_AGENT`, a
configured `agent`, the transcript's agent-name record, `git config user.name`). A scheduled run
therefore dreams into its task's own lane, and can pick the dream up on its next run. An agent no source can name dreams into scratch, and a mapped store that
is missing is never created (a lost store must not be silently rebuilt by the tool that serves
it). The full contract is in the `dreaming` skill.

## Install

```
claude plugin marketplace add AmeNoMurakumo1234/dreaming
claude plugin install dreaming@dreaming
```

See `INSTALL.md` for the declarative pin, the local-server setup, and how to try it on a
transcript without touching a store.

## Where it came from

Built from the sleep step shipped inside the quantum-concepts repository on 2026-09-22, where it
runs against a team of eight agents with private per-agent stores. The repo-bound seams (identity,
store health, the model client) became configuration and a stdlib client. The idea is not novel (sleep-time compute, memory consolidation agents,
PreCompact recovery hooks all exist); what this one holds to is the per-agent store with rules,
and consolidation at the exact moment the harness forgets.

MIT. Ame No Murakumo, 2026.
