---
name: dreaming-promote
description: "The wake procedure for dreams staged by the dreaming plugin: read each dream folder, promote the lessons that hold up into real memory entries with index lines, hold genuine tensions as IN-TENSION, then delete the folder. Load at session start when the notice says dreams await promotion, or when asked to promote, review or clear dreams."
---

# dreaming-promote

The plugin sleeps; you promote. A dream is a candidate written by a model that read your day
without your judgement. Nothing in it is a fact until you have checked it, and the plugin never
writes your index precisely so that this step cannot be skipped by accident.

## Procedure

1. **List what is waiting.** The session-start notice names the store and the folders. Or run,
   from the plugin directory: `python -m dreaming.cli list`, or `list --all` to see every lane's
   store at once (routines dream into their own lanes since 0.4.0; their dreams are yours to
   promote at the interactive checkup, never the routine's own job).
2. **For each folder, read three files**: `brief.md` (what you were doing when you fell asleep),
   `lessons/*.md` (the candidates), `tensions.md` (what contradicted an entry you hold).
3. **For each lesson, decide one of three things.**
   - *Keep as new*: write it into your store in the store's own format, in your own words where the
     model's are loose, and add its index line by hand. Keep the provenance line: the session and
     turn uuids are how a future reader checks it.
   - *Extends an existing entry* (the file says `extends: <slug>`, or you recognise it): open that
     entry and fold the new instance in, dated. Do not create a near-twin.
   - *Drop*: it is a summary of events, a restatement of something you hold, or simply wrong.
     Most dreams carry a few of these. Dropping is normal.
4. **For each tension, decide which kind it is.**
   - A *reversal* you can verify now (the world changed and the old entry is stale): fix the old
     entry, with the date and why. Small, reversible edits.
   - A *genuine tension* you cannot settle from here: record it beside the entry it touches as
     IN-TENSION, both sides, and let it stand until evidence arrives. Never pick a side because one
     reads better.
5. **Delete the folder.** The promoted content now lives in the store; the dream has done its
   work. A folder left behind is reported STALE after `stale_days` and re-read every wake.
6. **Say what you did**, in one line, wherever your team keeps such lines: how many promoted,
   extended, dropped, held.

## Rules

- The tool lists; the mind writes. The plugin never touches the index.
- A dream is a candidate, not a fact. Promotion is the judgement, not a copy.
- A lesson without a `why` and a `how to apply` is not a lesson yet; supply them or drop it.
- The brief is for resuming, not for keeping. Do not promote resume state into durable memory.
- Check the `degraded:` lines in `sleep.log` before trusting a thin dream: a mechanical brief or
  a truncated reduce means the model saw less than the whole day.
- A dream dated before your upgrade to 0.4.0 may be a ROUTINE's run filed under the interactive
  agent (routines had no identity of their own until then). Read it as evidence; do not promote
  its brief, which is a routine's resume state, not yours.
- A lesson marked `flag: reads as board state` (0.5.2) is the state of the board written as a rule
  - a known issue, an instruction to ignore a red until something lands. Drop it: a routine's
  field report found one that, promoted, would have kept telling it to wave a red test through
  an hour after the issue was fixed. The brief carries state; lessons never do.
- A lesson marked `restates a known rule: <file>` (0.5.0) is the model saying your rules files
  already hold it. Confirm in one glance and drop it; it is kept in the dream precisely so that
  the drop is yours, not the tool's. A lesson marked `scope: generalised` reaches past what the
  session showed: test it hardest, and check it against your standing rulings before keeping it.
