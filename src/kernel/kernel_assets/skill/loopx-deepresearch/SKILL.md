---
name: loopx-deepresearch
description: "Run a bounded LoopX deep-research loop: packet-driven expeditions, evidence ledgers, citation-auditable report."
argument-hint: <research question> [--max-sources N]
---

<!-- loopx-managed-slash-command:v1 command=/loopx-deepresearch surface=claude-skills -->

# LoopX /loopx-deepresearch

Treat this as the LoopX `/loopx-deepresearch` slash command.

Visible command arguments: `$ARGUMENTS`.
Run `loopx --format json deepresearch status --project .` first; if no research is active, treat `$ARGUMENTS` as the question and run `loopx --format json deepresearch start --project . --question $ARGUMENTS`.
Keep `research_contract`, `stop_conditions`, `next_expedition`, and `evidence_commands` from the packet visible; the packet owns what to research next and when to stop.
Record every finding through the typed subcommands (`add-source`, `add-subquestion`, `resolve-question`); never edit the state file directly, and never fabricate URLs or claims — a claim exists only if a tool you actually ran produced it.
Resolve a question only with recorded evidence claim ids; an open contradiction blocks resolution until an explicit sides-with claim and rationale are recorded.
Re-run `status` after every expedition; stop when `stop_conditions.stopped` is true, then run `deepresearch report` and present the report path.
One active run per project: to research a new question, run `deepresearch close` (or `start --new-run` once stopped) — close marks the terminal state and the next start archives it, never by editing state files.

Keep public/private boundaries intact and do not perform external writes unless the active LoopX state or owner explicitly authorizes them.
