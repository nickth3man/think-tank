# Think Tank
KICKER: MULTI-AGENT DELIBERATION
TAG: RUST · CARGO
BADGE: CONVERGED | accent
SUBTITLE: Four agents debate. An Arbiter decides when they have converged — measured, not guessed.
META: ENGINEERING REPORT · RENDERED FROM REPOSITORY DATA
---

KICKER: HOW IT WORKS
# A strictly sequential debate loop
- Researcher claims, Skeptic challenges, Visionary lateral-ideas, Synthesizer merges — then the Arbiter scores the round.
- The Arbiter weighs semantic stabilisation at 0.80 and the opposition ratio at 0.20.
- Rounds repeat until the alignment score clears the target, or the round budget runs out.
- Unconverged rounds carry the arbiter's expansion directive into the next round's agents.
STAT: 4 | AGENTS PER ROUND
STAT: 0.80 | SEMANTIC WEIGHT
STAT: 6 | ROUND CEILING
---

KICKER: PROVEN ON ITS OWN OUTPUT
# This deck is the measurement
- This PDF was rendered by deckgen: a headless egui harness painting ArtCraft's design tokens onto A4 pages, assembled with pdf-writer.
- One binary, no browser, no network: a coding agent can regenerate a deck like this from any repository's data.
STAT: 0 | BROWSERS IN THE LOOP
DIVIDER: RENDERED OFFLINE
IMG: ../deck/shots/chart.jpg
---

KICKER: ENGINEERING
# Boring on purpose
- One Rust crate, no reducers: every node clones state and appends, so history is never lost.
- All providers speak the OpenAI protocol; adding one is a row in a table.
- Tests drive a local stub server — the suite makes zero network calls.
STAT: 5 | NODES PER ROUND
STAT: 3 | STRUCTURED-OUTPUT RETRIES
STAT: 0 | NETWORK CALLS IN TESTS
---

KICKER: THE HONEST NUMBERS
# What the arbiter actually saw
HERO: 1.00 | CONVERGED SCORE - AGAINST A 0.65 TARGET, IN 2 OF 6 ROUNDS
THE FORCED RUN: The same loop scored 0.1536 against an impossible 1.01 target, spending 392 tokens.
- A benchmark that only shows wins is marketing — this one shows both.
---

KICKER: PART TWO
# Where this goes
---

KICKER: THE TAKEAWAY
# Decks as a build artifact
CALLOUT: Any repo that emits JSON can emit a deck | Reports, benchmarks and architecture reviews render from the same file. A coding agent regenerates this PDF from repository data — no browser, no network, no layout code.
STAT: 1 | DESIGN SYSTEM
STAT: 3 | OFL TYPEFACES
STAT: 7 | PAGES FROM ONE FILE
