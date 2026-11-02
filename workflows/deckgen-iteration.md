# Workflow: deckgen iteration loop

The recurring loop: improve the deckgen decks' executive quality, one generation at a
time, without a human in the loop until the end. The executable procedure lives in the
`deckgen-loop` skill (`~/.omp/agent/skills/deckgen-loop/SKILL.md`); this file is the loop's
definition and the authority when the two disagree on *what*, not *how*.

## Trigger

Event: invoked by hand (`/deckgen-loop`) whenever the decks or the renderer should improve.
Nothing fires it on a schedule; a run that changes nothing commits nothing.

## Scope

All decks under `ui/deckgen/`. The **control deck** (`think-tank.control.md` →
`think-tank.pdf`) is the acceptance surface; `lab.md` exercises new directives and
`think-tank.md` is the working deck. Both must gate PASS every generation, but only the
control deck is graded against the exit bar.

## Checkpoint policy

None during a run. Commits at every generation are the audit trail; the Jev completion
gate (`jev_gate`) is the only completion authority. The run ends with one **brief**:
score table with deltas vs run start, list of commits, what changed and why, PDF paths.

## Exit bar

Every applicable control axis ≥ 0.85 (five frozen axes; the images axis applies only when
the deck carries `IMG:`). No accepted generation may regress an axis more than 0.05 vs the
previous accepted one. Hard cap: 6 generations per run — the cap ends the run, the brief
reports where the bar was missed.

## Instruments

- Mechanical gate: `tools/deckgen/scripts/check_deck.py` (rect math over `--layout` JSON).
- Grade: `jev_noul`, five frozen propositions, frozen transcript + measured type inventory.
- Completion: `jev_gate` with claims + evidence, once, at stop.
