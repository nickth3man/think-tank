# Workflow: deckgen iteration loop

The recurring loop: improve the deckgen decks' executive quality one **generation** at a
time, with no human checkpoint. This file is the loop's definition and wins when the
procedure disagrees on *what*; the procedure is `~/.omp/agent/skills/deckgen-loop/SKILL.md`
and the frozen grading instrument is `tools/deckgen/GRADE.md`.

## Trigger

Invoked by hand (`/deckgen-loop`), optionally with the generation count
(`/deckgen-loop 8`). No schedule, no file watcher: a run that changes nothing commits
nothing.

## Scope

Every deck under `ui/deckgen/`. The **control deck** (`think-tank.control.md` →
`think-tank.pdf`) is the acceptance surface and the only deck graded against the exit bar.
`lab.md` exercises directives; `think-tank.md` is the working deck. Every deck a change
touches gates `PASS` before the generation is graded — shared renderer code reaches decks
nobody opened.

## Checkpoint policy

None during a run. Commits are the audit trail; `jev_gate` is the only completion
authority. A run ends with one **brief**: the score table with deltas against the run's
start, the budget and how it was set, the commits, what changed and why, the PDF paths.

## Exit bar, budget and stops

**Exit bar**: every applicable control axis ≥ 0.85 (the images axis applies only to a deck
carrying `IMG:`), and no accepted generation regressing an axis more than 0.05 against the
previous accepted one.

**Budget**: the most generations a run may take, fixed per invocation. A number in the
invocation sets it; without one the agent sets it from the evidence — axes below the bar,
their distance, whether an aimed fix exists for the weakest — and names it in the brief.
No axis below the bar means budget 0. The budget is a ceiling, never a quota.

The run ends at whichever comes first:

1. **The exit bar** — every applicable axis at or above it.
2. **The budget** — generations spent, with the shortfall reported.
3. **Saturation** — two consecutive generations aimed at the same weakest axis move it by
   less than the ±0.02 noise floor in total. The axis is at the design's ceiling: record
   the evidence in `docs/deckgen-iterations.md` and report the gap instead of churning.
4. **No aimed fix left** — the remaining axes have no change with a stated mechanism.

## Document check

The loop's own documents are checked mechanically:

```bash
.venv/bin/python tools/deckgen/scripts/check_docs.py   # exit 1 on drift
```

It proves the frozen instrument is single-sourced in `tools/deckgen/GRADE.md`, every path
the documents name exists, the numbers two documents share agree, and the skill's
frontmatter names its directory. A documentation edit is not done until it passes.

## Invariants

Two failures cost this loop real generations; both are structural, not stylistic.

- **A score describes one artifact.** A grade is valid only for the exact render that
  passed its gate. Any renderer or deck edit after grading voids the score — re-render,
  re-gate, re-grade; never carry a number across a change.
- **Gate what the change touches.** Renderer edits propagate to every deck; gating only the
  deck you edited ships an unverified layout to the others.
