# dreaming

**Sleep at compaction.** A Claude Code plugin that consolidates a session into durable memory in
the moment the harness is about to forget it.

Claude Code compacts a session when its context fills. The compaction summary is written by the
harness, it is silent, and it drops things. `dreaming` puts a blocking hook at that moment: it
reads the full transcript, distils it into candidate lessons, a five-field resume brief and the
tensions it found with what you already believe, stages all of it in your memory store, and after
compaction re-seeds the fresh context from the brief. At the next session start it tells you how
many dreams are waiting, and a skill teaches the promotion step. The built-in summary still
happens. What changes is that nothing worth keeping has to survive it.

## What it does

| When | Hook | Effect |
|---|---|---|
| Context about to compact | `PreCompact`, blocking, one-hour ceiling | extract, map each slice, reduce against your index, write a dream folder |
| The session ends | `SessionEnd` (capped at 60 s) | if enough is new since the last watermark, the same sleep runs in a detached child that outlives the session |
| Right after compaction | `SessionStart` (`compact`) | the newest brief for this session is injected as context |
| First prompt of a session, or a resume | `UserPromptSubmit` (first prompt only), `SessionStart` (`resume`) | "N dream(s) awaiting promotion in <store>"; with `reseed_on_startup`, a scheduled run also receives its own task's previous brief. Never at `SessionStart` (`startup`): it fires before the scheduled-task tag is in the transcript, so it could only guess who is waking - and the guess was whoever owns the clone |

The engine ladder: any local OpenAI-compatible server first (llama.cpp, vLLM, Ollama),
`claude -p --safe-mode` (sonnet) on the CLI's own login second, and a mechanical brief built from the last
turns when neither answers. Every hook exits 0 on any failure; compaction is never blocked on a
dead engine, and every engine call is bounded by the remaining budget so a sleep cannot outrun
the hook's one-hour ceiling. The hooks invoke `python`, so Python 3.10+ has to be on the PATH
under that name (on Windows, not the Store stub).

## The dream folder

```
<store>/dreams/20260922-125402-2def5d4e/        (local time, then the session's first 8 chars)
  day.md            the extracted transcript
  map/1.json ...    the model's notes per slice
  reduce.json       the merge, matched against your index
  brief.md          Current Task / Exact State / Next Step / Uncommitted Decisions / Files In Context
  lessons/*.md      candidate lessons with provenance, "extends: <slug>" when they extend an entry
  tensions.md       contradictions with your entries, both sides, deliberately unresolved
  sleep.log         engine, timings, every "degraded:" line, the watermark for the next sleep
```

Beside the folders, `<store>/dreams/.watermark-<session>.txt` records where this session's last
sleep stopped. Promotion deletes the folder; the file stays, so the next sleep continues from it
instead of re-dreaming the whole session.

## The one design rule

**Staging only. The mind promotes.** The plugin never writes your index and never resolves a
tension. A dream is a candidate written by a model that read your day without your judgement;
the `dreaming-promote` skill is the procedure by which you keep, extend, drop or hold each item,
then delete the folder. Auto-promotion is deliberately not a feature of this release.

## Configuration in one minute

`~/.dreaming/config.json` for you, `<project>/.dreaming.json` for a repository, `DREAMING_*`
environment variables on top. The two settings most people touch:

```json
{
  "openai_compatible": {"base_url": "http://127.0.0.1:8081", "api_key_file": "~/.llamakey", "model": "local"},
  "store_root": "~/.dreaming/stores"
}
```

`known_rules` names files (a rules file, a charter) the reduce is told you already hold, so a
lesson that only restates one arrives labelled for you to drop; `indexes` maps an agent to the
index files that stand in for the store's own. `openai_compatible` can also be a list of servers in preference order (the first that answers
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
runs against a team of eight agents with private per-agent stores. The mechanism is the same; the
four repo-bound seams (identity, store health, the index, the model client) became configuration
and a stdlib client. The idea is not novel (sleep-time compute, memory consolidation agents,
PreCompact recovery hooks all exist); what this one holds to is the per-agent store with rules,
and consolidation at the exact moment the harness forgets.

MIT. Ame No Murakumo, 2026.
