---
name: deckgen-loop
description: Iterate the deckgen decks to executive quality — render, gate, grade, fix the weakest axis, commit each generation, Jev-gate completion. No human checkpoint. Optional count sets the generation budget (`/deckgen-loop 8`); without one the agent picks it.
disable-model-invocation: true
---

Improve the `ui/deckgen/` decks one **generation** at a time — diagnose, fix, verify,
accept, commit — until the exit bar is met or the run's budget is spent. The loop's
definition (scope, exit bar, budget, stop rules) is `workflows/deckgen-iteration.md`; when
the two disagree on *what*, that file wins. The frozen grading instrument is
`tools/deckgen/GRADE.md`. This file is the procedure. Its source lives at
`workflows/deckgen-loop/SKILL.md`; this installed copy is generated from it by
`tools/deckgen/scripts/install_skill.sh` — edit the repo copy, then reinstall.

## 1. Baseline

Gate the decks you are about to change:

```bash
for d in think-tank.control think-tank lab; do
  cargo run --release --manifest-path tools/deckgen/Cargo.toml \
    -- ui/deckgen/$d.md -o /tmp/$d.pdf --layout /tmp/$d.json
  .venv/bin/python tools/deckgen/scripts/check_deck.py /tmp/$d.pdf --layout /tmp/$d.json
done
```

Every source must print `PASS` before you grade anything. A `FAIL` is a defect: fix it,
re-gate, and only then proceed. Grade nothing against a render that has not passed.

Then grade once to establish the run's start scores.

## 2. Grade

Grade the **control deck** only, with `jev_noul`, using the propositions and context rules
from `tools/deckgen/GRADE.md` verbatim. Record the other decks' scores for the regression
check; the bar applies to the control deck alone.

## 3. Diagnose

The **weakest applicable axis** below the exit bar wins the generation. Name the fix
before making it: one change, aimed at that axis, with the page and mechanism you expect
to move it. Quote the measurement that motivates it — a gap, an overlap, a size or a count
read from the `--layout` JSON — in the commit message; a change with no number behind it
is a hypothesis, so record the number either way.

New design rule needed → `jev_find` or `jev_rerank` candidate sources, read the top one,
apply its rule, and log the citation in `docs/deckgen-iterations.md`.

## 4. Verify

1. `cargo build --release` — no errors; `cargo clippy --release` — no warnings you added.
2. `cargo test --release --manifest-path tools/deckgen/Cargo.toml` — every test passes. New
   behaviour gets a behavioural regression test; wiring, forwarding and source text do not.
3. Re-render and gate **every deck the change touches**, not only the one you edited —
   shared renderer code reaches decks you did not open. `PASS` on each.
4. Render every touched page to PNG at 100 dpi and open each one. Record what you saw and
   whether it matches the mechanism from step 3.
5. Editing any loop document → `.venv/bin/python tools/deckgen/scripts/check_docs.py`
   prints `PASS`; changing the checker itself → its tests pass
   (`.venv/bin/python -m unittest tools.deckgen.scripts.test_check_docs`).

## 5. Accept or reject

Grade the render that passed step 4 — grading any other artifact is void. Accept when the
weakest applicable axis clears the 0.85 exit bar and no axis regressed more than 0.05
against the last accepted generation (noise floor ±0.02, so a smaller move is not a move). Otherwise revert the
files (`git checkout`), log the attempt with its scores, and take the next-weakest axis.

## 6. Commit

One commit per generation, accepted or rejected. Conventional commits in the repo's style
(`feat(tools): …`, `fix: …`, `docs: …`). The same commit carries the generation's entry in
`docs/deckgen-iterations.md` — axis scores, the fix and its mechanism, the decision. A new
directive, layout family, dependency or script updates `tools/deckgen/README.md` and, when
it changes how a deck is authored, `tools/deckgen/SKILL.md` in that same commit.

## 7. Budget

Read the count from the invocation. `/deckgen-loop 8` → budget 8. No count → set it from
the evidence (axes below the bar, their distance, whether an aimed fix exists) and state
it plus its reason in the brief; every axis at or above the bar → budget 0, grade and
report without changing a file. Ceiling and early-stop rules: see the workflow file.

## 8. Finish

Apply the stop conditions from `workflows/deckgen-iteration.md`. Then call `jev_gate`
**once** with the run's claims — the measured axis
scores, every deck gating `PASS`, the tests passing, the commits made — against the
evidence that proves each (grade output, gate output, test output, `git log`, the diff).

Report one **brief**: the score table with deltas against the run's start, the budget and
how it was set, the commits, what changed and why, and the PDF paths. When the bar was
missed, say so with the numbers and the saturation evidence; the last accepted generation
stands. Never re-word evidence or re-run an instrument to turn a shortfall into a pass.
