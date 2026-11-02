# The deckgen grade instrument

The frozen instrument behind every `deckgen-loop` generation. Byte-stable: change it and
every prior score becomes incomparable (the log in `docs/deckgen-iterations.md` records
which template era each number came from). The loop procedure is
`~/.omp/agent/skills/deckgen-loop/SKILL.md`; the loop definition is
`workflows/deckgen-iteration.md`.

## The five propositions

Pass these to `jev_noul` verbatim, in this order, one batch. Never paraphrase — a reworded
proposition is a different instrument and its score cannot be compared to the log.

1. `The slides use space well - empty areas look distributed and intentional`
2. `Body text is consistent and appropriately sized for a presentation`
3. `The layouts vary enough across slides to keep an executive engaged`
4. `Images and charts are integrated cleanly and sized to fill their space`
5. `The title slide is well composed.`

The propositions name the axes in order: **space, body, variety, images, title**.

## The context every grade is given

The grade is only as honest as its context. Build it the same way every generation:

1. **One paragraph per page**, in page order, describing what that page actually shows:
   the layout family, the content's role, and where each element sits (band, column, row).
2. **The measured type inventory**, last, as its own block. Read it from the render, never
   from memory: the display sizes, the deck-wide body size (`DECKGEN_VERBOSE=1` prints it),
   the stat value size, the label size. State the number of distinct body sizes and that
   the deck uses one.

Describing type by impression is the failure this rule exists for: a prose transcript once
scored body 0.80 while the inventory of the same render scored 0.48, exposing five type
sizes a paragraph had hidden.

## Reading a grade

- Noise floor: **±0.02** per axis on an unchanged render and identical transcript. A move
  inside the floor is not a signal.
- Axis scope: the **images** axis applies only to a deck carrying `IMG:`. A deck with no
  image scores it meaninglessly — record it, never chase it.
- The grade is advisory. The mechanical gate (`check_deck.py`) is the correctness
  authority; a `PASS` there is not a quality claim and a grade never overrides a failure.
