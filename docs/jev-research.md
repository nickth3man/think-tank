# Integrating TypeSafe Jev 1.14 — research and candidate features

Research date: 2026-11-01.

**What the numbers in this document are.** Every Jev answer reported below came from
a live request against `typesafe/jev-1.14-20261014`. That verifies request shape,
cost, and that the questions move in the direction they should. It does **not**
establish accuracy: the states were hand-written and unlabeled, so a value like
`challenge_addressed = 0.47` tells you what Jev said, not whether it was right. See
"How to validate before trusting any of this".

**Which access path.** The proven path is OpenRouter's `/api/v1/systemone` with
model `typesafe/jev-1.14`, authenticated by `OPENROUTER_API_KEY` — the only key this
environment has. TypeSafe's native API (`api.typesafe.ai`, model `jev-1.14.0`,
`TYPESAFE_API_KEY`, `typesafe-sdk`) is documented but was not exercised here. Both
paths are named below where it matters.

## Sources

Primary:

| Claim | Source |
|---|---|
| Question types, request/response shapes, limits, pricing | <https://docs.typesafe.ai/api/system-one.md>, <https://docs.typesafe.ai/primitives.md>, <https://docs.typesafe.ai/models.md> |
| Model IDs and aliases (`jev-latest` / `jev-preview` → `jev-1.14.0`) | <https://docs.typesafe.ai/models.md> |
| `confidence` semantics and the 0.7/0.3 Noul starting points | <https://docs.typesafe.ai/confidence.md> |
| Known weak spots — **1.13 only** | <https://docs.typesafe.ai/model-jaggedness/jev-1.13.md> (a `jev-1.14.md` page returns 404, so 1.14's jaggedness is undocumented) |
| Batching economy | <https://docs.typesafe.ai/cookbooks/parallel_questions.md> |
| LangChain integration (`langchain-typesafe`) | <https://docs.langchain.com/oss/python/integrations/providers/typesafe> |

Secondary, used only for pattern ideas — see the next section.

### How far to trust the weak-spots list

The jaggedness page is written for `jev-1.13`. TypeSafe publishes nothing equivalent
for 1.14, so every 1.13 failure mode in this document is **inferred, not confirmed
for 1.14**: option-order sensitivity, context rot, numeric precision, date handling.
The mitigations are cheap, so apply them anyway — but do not cite 1.14 behaviour on
the strength of that page. Which question types are validated for 1.14: none
publicly, beyond what the primitives page asserts.

## There is no official `awesome-jev`

`github.com/typesafe-ai/awesome-jev` and `github.com/TypeSafeAI/awesome-jev` both
return **404** from the GitHub API. The TypeSafe org publishes no awesome list, and
`docs.typesafe.ai/llms.txt` lists no such page. It is entirely a community artifact.

Both lists below are **secondary, community-run sources**. I opened each README
directly; the counts are from counting entries in the fetched files, not from a
scout's summary.

| Repo | Stars | Entries | Sections | License |
|---|---|---|---|---|
| [`yibie/awesome-jev`](https://github.com/yibie/awesome-jev) | 2,522 | 711 | 26 | none declared |
| [`cobanov/awesome-jev`](https://github.com/cobanov/awesome-jev) | 587 | 326 | 19 | CC0-1.0 |

Note `cobanov/awesome-jev` carries 326 entries, not the 155 an earlier summary
claimed, and `yibie` has 26 sections, not 20.

**Closest published analogue to this repo** — and the strongest single piece of
evidence for the design in this document:
[`sanketmuchhala/jevgate`](https://github.com/sanketmuchhala/jevgate) (Python,
`jev-1.14.0`, no license declared). Its README states the split this document
recommends, in almost the same words:

> System-1 is Jev 1.14 (`jev-1.14.0`) … called from a Python FastAPI service.
> System-2 is a reasoning LLM … For triage, it sees only the specific propositions
> System-1 was unsure about.
>
> **Python owns** the policy, the thresholds, the three-valued rule logic, which
> uncertainty matters, which reviewer verdicts count, and the final route.

Two details worth copying rather than inventing (`src/policy.py`, `src/router.py`):
a Score condition is read as `P(level ≥ 3)` from the **distribution**, not the
expected `score`; and a Choice condition **sums the probabilities** of the options
it names instead of taking the argmax. Both bands need `p ≥ 0.7` for TRUE, `p ≤ 0.1`
(high stakes) or `p ≤ 0.3` (standard) for FALSE, and the gap is UNCERTAIN. It also
refuses an ungrounded "yes" from its System-2 reviewer without a verbatim quote.

These thresholds are a real, working convention — but they come from a third-party
project, not from TypeSafe. Treat them as a sensible default to calibrate, not as
ground truth.

The only LangGraph-flavoured entry in either list is
[`GiesN/typesafe-jev-workflow`](https://github.com/GiesN/typesafe-jev-workflow)
(11 stars, no description) — thin evidence, so nothing below rests on it.

## Verified API facts

- **Pin the versioned ID.** `jev-latest` and `jev-preview` both currently resolve to
  `jev-1.14.0` (stated in `models.md`), but aliases move and can change answers
  without a code change. Send `jev-1.14.0` when thresholds are tuned. Through
  OpenRouter the alias is `typesafe/jev-1.14` and responses echo the concrete
  `typesafe/jev-1.14-20261014` — assert on that echoed string.
- **Request shape.** `{model, state, questions}`. `questions` is a **map**, not an
  array, and each question's text field is `instructions` (not `question`). Both are
  easy to get wrong; I hit both errors.
- **Answers.** `{model, answers, usage}`. Noul returns `{type, noul}` with **no
  `confidence`** — the probability is the whole answer. Choice/Score return
  `probabilities` and `confidence`. If you want one gate for both, use
  `|2p − 1|` for Noul (`confidence.md` gives exactly that conversion).
- **`confidence` is not correctness.** Per `confidence.md` it is a statistic from
  the returned distribution — `(3p_max − 1)/2` for a 3-option Choice. It measures
  how *concentrated* the answer is, not whether it is right. Gate on the
  probability, and let low confidence mean "needs another look", never "probably
  fine" or "probably wrong".
- **Limits.** 64k per-request / 32k per-question context; 32 MiB body; 64 nesting
  levels.
- **Price.** $42/Btok, **input tokens only, output free**. A representative
  8-question deliberation round measured **$0.00005**.
- **Batching.** One request with N questions reads the state once. Docs measure
  12.2× cheaper and 10.0× faster than N separate calls
  (<https://docs.typesafe.ai/cookbooks/parallel_questions.md>).
- **Context rot cuts both ways.** Batching is cheap, but pushing *irrelevant*
  material into `state` costs accuracy (`jev-1.13.md`). Batch questions that share
  a narrow state; do not batch by dumping the whole transcript.

## Ground rules for using Jev here

1. Jev judges; code decides. Every question below feeds a threshold or a branch
   that stays in Python.
2. One judgment per question. No "or", no compound conditions.
3. Give the evidence. A question about support must include the evidence being
   checked against — see "Restating the claim inflates its own grounding score"
   below.
4. A failed call is an error, never a "no".
5. Never treat `confidence` as correctness. Use probability thresholds (0.7/0.3)
   and let the 0.3–0.7 band take its own path.

## Restating the claim inflates its own grounding score (controlled)

I originally reported this as "the same sentence scored 0.75 rich, 0.42 minimal", and
attributed it to state shape. **That attribution was wrong**, and the controlled runs
below replace it. The original 0.75 came from a state that restated the claim in
`current_round_claim` as well as `claim` — a factor I had not isolated.

Holding claim text, passages, question text and criteria byte-identical, and varying
only the wrapper:

| State | `claim_grounded` (3 runs) | Mean |
|---|---|---|
| `claim{content}` + 3 passages | 0.40 / 0.40 / 0.41 | **0.40** |
| `+ confidence:"medium"` | 0.48 / 0.40 / 0.51 | 0.46 |
| `+ evidence_summary` (agent's own claim that evidence exists) | 0.49 / 0.50 / 0.50 | 0.50 |
| `+ id, agent` (inert metadata) | 0.53 / 0.52 / 0.50 | 0.52 |
| `+ everything, incl. a restated copy of the claim` | 0.70 / 0.65 / 0.68 | **~0.68** |

Each addition nudges the score up by ~0.04, and the restated copy is the largest
single contributor. Isolated directly:

| Extra fields under the claim | Truthful claim | Fabricated claim ("raises productivity 23%") |
|---|---|---|
| 0 restatements | 0.40 | 0.03 |
| 1 restatement | 0.57 | 0.03 |
| 2 restatements | 0.58 | 0.03 |
| 3 restatements | 0.61 | 0.03 |

Two conclusions, and they matter more than the original table:

1. **Repetition inflates.** Repeating a claim inside `state` raises its own grounding
   score from 0.40 to ~0.61. The `current_round_claim` field exists precisely to
   restate the claim, so this inflation is the *default* shape if you build state
   naively — and it is worth ~0.2 of probability.
2. **It does not rescue a fabrication.** The fabricated claim stays at 0.03 under
   restatement. So the signal survives, but the *threshold* does not: a state that
   restates the claim needs a higher accept bar than one that does not. Tune the
   threshold against the exact state shape you ship, and never carry a threshold
   between two shapes.

A separate, cleaner demonstration of the same family of problem: stance collapsed
without evidence in state. Asking "is this claim well supported?" while supplying no
support made Jev answer `oppose` for *both* a supported and a fabricated claim
(0.80 / 0.79), then shift to `refine`/`refine` on a rerun. **A question about support
needs the support in the state** — and an ambiguous state can also be unstable
across calls. Once `passages` were included, the same Choice discriminated correctly
(`support` 0.68 / `refine` 0.47) and `claim_grounded` dropped fabricated content to
0.03.

Implication for this repo: keep the judged claim in **one** field, or accept the
inflation knowingly. If `current_round_claim` and `claim` both exist in a round, they
will duplicate.

## The ten candidates

Ranked by (defect fixed × verifiability) ÷ integration cost. Each was probed live —
which establishes shape and direction, not accuracy. Each carries a **Primitive**
line: Noul answers have no `confidence` (gate on the probability, or on
`|2p − 1|`), while Choice/Score return one (gate on it where the point is
confidence-gating).

### 1. Grounding gate on researcher claims — highest value
**Fixes:** the Researcher is told *"rely only on the provided evidence excerpts"*
(`researcher.py:36`) and nothing verifies it. `evidence_summary` is generated prose
that no code compares to the excerpts.
**Question:** Noul — "Does `claim.content` assert only what `passages` support?"
**Primitive:** Noul. No `confidence`; gate on the probability or `|2p − 1|`.
**Validate:** relabel ~50 claims from real runs (supported / overstated / invented);
require ≥0.9 precision at the 0.7 accept bar before auto-accepting, and confirm the
0.3 reject bar never drops a genuinely grounded claim.
**Measured:** real quote **0.97**, faithful paraphrase **0.93**, inflated sample size
**0.02**, invented authority **0.02**, off-topic **0.03**.
**Labeled check (10 items, 5 grounded / 5 fabricated, naive state that restates the
claim):** grounded scored **0.70–0.97** (mean 0.89); fabricated scored **0.02–0.03**
(mean 0.02). At a 0.7 threshold, **5/5 grounded accepted and 5/5 fabricated
rejected**; a 0.5 threshold gives the same split. The gap between the fabricated
ceiling (0.03) and the grounded floor (0.70) is the useful number — it means the
question discriminates with room to spare, not that 0.7 is the right bar for your
data. Note the grounded floor was a paraphrase that *inferred* a conclusion ("driven
mainly by outcomes and trust") rather than quoting one; that is where a real run will
lose grounded claims first.
**Code decides:** `<0.3` → re-prompt once with the offending assertion named;
`>0.7` → accept; band → mark `confidence=low` and surface a warning event.
**Cost:** ~$0.00003.

### 2. Set `Challenge.resolved` — a field nothing writes
**Fixes:** `Challenge.resolved` has no producer anywhere (`skeptic.py:127` omits it;
`SkepticOutput` has no field for it). Every consumer of `resolved` reads a constant
`False`, which is why `_challenge_resolution_rate` was dead weight and the
alignment score was structurally capped.
**Question:** Noul — "Does `current_round_claim` respond to the objection in
`challenge`?"
**Primitive:** Noul.
**Validate:** label real challenge→claim pairs resolved / not resolved; a `resolved`
flag is only worth setting if it predicts the next round's content. Check that the
0.3–0.7 band is common rather than a sign the question is malformed.
**Measured:** **0.47** on the real pair (a genuine "partially" — the claim narrowed
but did not refute).
**Code decides:** `>0.7` → `resolved=True`; `<0.3` → carry the challenge forward;
band → carry forward *and* list it as a remaining tension.
**Why Jev and not an LLM:** resolution is a single bounded judgment over two short
texts, needed every round for every challenge. A generated answer would need its own
parsing and could not be thresholded.

### 3. Replace cosine "alignment" with a stability judgment
**Fixes:** `_pairwise_alignment` (`arbiter.py:35-57`) compares claim embeddings. Only
the researcher emits claims, so the intra-round term is always empty and the metric
is effectively "did the researcher repeat itself". It also silently returns `0.0` on
embedding-length mismatch, conflating a model change with total disagreement.
**Question:** Noul — "Have the agents reached a shared position such that another
round is unlikely to change the answer?"
**Primitive:** Noul.
**Validate:** replay 10–20 completed runs; correlate the verdict with whether the
next round actually changed the conclusion. Only swap out the cosine term once the
label beats it on that replay.
**Measured:** aligned positions **0.91**, genuinely diverged positions **0.08**, and
on a real round-over-round pair where the conclusion flipped, `position_stable`
**0.04**.
**Code decides:** keep the composite but substitute this for the cosine term, or
require both. Do not silently swap it — it changes when runs stop.

### 4. Per-passage retrieval gating
**Fixes:** `kb.retrieve` takes a fixed `k=5` with no score threshold and joins
passages with `"\n"`, discarding metadata, so the researcher cannot tell a strong
excerpt from a weak one. The only quality check is "zero rows".
**Questions:** one batched Noul per passage — "Does `passages[i]` bear directly on
`topic`?"
**Primitive:** Noul, one per passage, batched in a single request.
**Validate:** take retrievals from real queries, label each passage relevant /
not, and compare ranking against the current fixed `k=5` dump. Watch for a false
reject rate — dropping good evidence is worse than keeping a weak excerpt.
**Measured:** 0.78 / 0.97 / 0.70 across three passages, ranking the on-topic HBR
study highest.
**Code decides:** drop `<0.3`, keep `>0.7`, order by probability, and label each
excerpt with its score so the researcher can weight them.

### 5. Target-claim selection as a Choice (validates the ID)
**Fixes:** `skeptic.py:129` copies `output.target_claim_id` verbatim from the model.
Nothing checks it against real IDs; a hallucinated ID silently drops out of every
downstream filter. Also degenerate today: only one researcher claim exists, so
"pick the weakest claim" has one candidate.
**Question:** Choice over claim IDs, with each claim's text as its criterion.
**Primitive:** Choice — returns `confidence`; the IDs are validated by construction.
**Validate:** shuffle the option order across calls (see Order sensitivity) and
check the same claim wins; confirm the chosen ID exists in `latest_claims` before
using it.
**Measured:** picked the fabricated `c_71bd` at **0.78** (correct — it is the
unsupported one).
**Order sensitivity:** one probe reversed the option order and returned the same
answer (0.78 → 0.79). That is **a single swap on a single question whose answer sat
near 0.78 — it does not establish that 1.14 has no first-option bias.** The 1.13
guidance is to reorder options and check consistency; no 1.14 page exists either
way. The mitigation stays in the design: shuffle option order per call, or log the
order alongside the answer, and confirm consistency on several near-tied questions
before relying on the label.
**Code decides:** because the options *are* real IDs, the answer is valid by
construction — the hallucinated-ID class of bug disappears.

### 6. Stance as a Choice with criteria, evidence in state
**Fixes:** `SkepticOutput.stance` is a free enum pick from prose definitions.
`_opposition_ratio` then weights 20% of the convergence score on that single
unverified judgment.
**Question:** Choice — support / refine / oppose, judging against `passages`.
**Primitive:** Choice — returns `confidence`; use the probability mass per option.
**Validate:** label stances by hand on ~30 grounded claims; a fabricated claim
should not land on `support`. If it does at a meaningful rate, tighten the criteria
text before wiring it into `_opposition_ratio`.
**Measured:** with evidence, supported claim → `support` **0.68**; fabricated claim →
`refine` **0.47** (Jev hedges rather than opposing — a real limitation).
**Code decides:** map probabilities, not just the top label; `oppose` needs
probability mass, not a plurality.
**Caution:** without `passages` this question is unstable. Do not ship it before
candidate 1.

### 7. Score: how material is the remaining disagreement
**Fixes:** the arbiter's expansion prompt asserts the group "has not yet aligned"
using a cosine number, with no notion of whether the disagreement matters.
**Question:** Score over three levels — verbal only / material but resolvable /
material and unresolvable without new evidence.
**Primitive:** Score — returns `confidence` and the level distribution; read
`P(level ≥ 2)` rather than the expected `score`, as jevgate does.
**Validate:** label real rounds by whether the disagreement was worth another
round. Level 0 triggering early stop is the risky direction: measure how often it
would have cut a run that was still converging.
**Measured:** **1.88**, with 0.90 mass on the "unresolvable" level.
**Code decides:** level 0 → stop looping early (a real round-count win); level 2 →
synthesis must state the gap rather than manufacture consensus.

### 8. Expansion focus as a Choice over named dimensions
**Fixes:** `_find_weak_dimensions` counts distinct values per dimension
(`arbiter.py:81-87`). Two agents saying "moderate risk" and "moderately risky" count
as maximal disagreement. It needs ≥2 claims to return anything, and the graph
produces one, so it falls through to the hardcoded `"overall reasoning"` — meaning
the arbiter's directive is usually a constant.
**Question:** Choice over 4 named dimensions.
**Primitive:** Choice — and the only candidate where the confidence gate is the
whole design.
**Validate:** label which dimension a human would call weak; check the top choice
and its confidence together. Given 0.53 / 0.37 here, expect a large uncertain band —
count how often that fallback fires before removing the hardcoded default.
**Measured:** picked `evidence_quality` at **0.53**, but `confidence` only **0.37**
— an honest "unsettled". Treat the low confidence as signal: this is the one
candidate where a fallback path matters.
**Code decides:** use the top choice only above a confidence floor, else fall back.

### 9. Synthesis fidelity check
**Fixes:** the synthesizer's prose becomes the final answer (`arbiter.py:166-180`)
with nothing checking it against its inputs. Separately, its
`incorporated_claim_ids` and `resolved_tensions` are generated and then discarded —
`Synthesis.contributing_claim_ids` is rebuilt from `latest_claims` instead, and
`resolved_tensions` has no reader at all.
**Question:** Noul — "Does `synthesis` state anything that `claim` and `challenge` do
not support?" with criteria `true` = "the synthesis adds claims not supported by the
inputs", `false` = "the synthesis only reflects the inputs".
**Polarity — read this before setting a threshold:** **high means UNFAITHFUL.** The
answer is a probability that the synthesis overreaches, so `>0.7` should *block*, and
`<0.3` should accept. This is the opposite sign from candidates 1 and 2 (where high
is good), and the earlier probe key `synthesis_faithful` named it backwards — the
instruction text always had this polarity.
**Measured:** **0.84** — i.e. Jev judges this synthesis **likely to add unsupported
content**, not "mostly faithful". In my own defense of that synthesis the
qualification ("observational and selection-confounded") is added by the synthesizer,
not present in any passage, so the value is plausible on inspection.
**Primitive:** Noul. No `confidence`; gate on the probability, remembering higher =
worse here.
**Validate:** label real syntheses faithful / overreaching, and confirm the direction
on the labeled set before wiring it to anything destructive. A sign error here would
block every good synthesis and pass every bad one.
Better use: validate the synthesizer's `incorporated_claim_ids` against the real
claim set the same way candidate 5 validates `target_claim_id`.

### 10. A real convergence verdict instead of a label derived from presence
**Fixes:** `app.py:2697` renders `CONVERGE` whenever a synthesis object exists, so a
`forced_end` run displays as converged. The `verdict = "forced" if forced_end and not
converged` distinction at `arbiter.py:164` never reaches the dashboard. In the other
direction, the dashboard's `vector_store.result` / `top_score: 0.847` events are
**demo fixtures only** — the live adapter never emits them.
**Question:** Noul — "Do the positions agree on the substance, or only on framing?"
**Primitive:** Noul.
**Validate:** label real runs converged / not, and check agreement with the
`forced_end` flag. The label is only an improvement if it disagrees with the flag
where the flag is wrong.
**Measured:** 0.91 aligned / 0.08 diverged (same probe as candidate 3).
**Code decides:** drive the UI label and the `Synthesis` verdict from
`converged`/`forced_end` explicitly, and emit real retrieval scores once candidate 4
exists.

## How to validate before trusting any of this

Nothing in this document is evidence that Jev is *right*. Every number is one
answer to one hand-written state, and the state-shape experiment above showed a
single Noul moving ~0.2 from restating the claim inside `state`. Before any verdict
is allowed to gate a run, do this:

1. **Build a labeled set from real runs.** The pipeline already produces the
   material: `claims`, `challenges`, and `syntheses` per round. Persist a few
   deliberations, then hand-label the judgments each candidate needs (grounded /
   not, resolved / not, converged / not). Start with ~50 items per candidate —
   enough to see a rate, not enough to over-fit a threshold.
2. **Split it.** Label on one set of runs, tune the threshold, then check on runs
   you did not tune against. With this few labels, treat any threshold as a
   placeholder and re-derive it as the labeled set grows.
3. **Set an accuracy bar before looking.** For candidate 1 that means ≥0.9 precision
   at the accept bar and a false-reject rate you can live with. Without a number
   chosen in advance, every result reads as "good enough".
4. **Gate on the margin, not the point.** For Noul, use the 0.7 / 0.3 bands and route
   the 0.3–0.7 middle somewhere deliberate. For Choice/Score, use `confidence` or,
   better, the summed probability of the options the rule names — that is how
   jevgate reads a Score, as `P(level ≥ 3)` rather than the expected score.
5. **Keep a no-Jev path.** If the call fails or lands in the uncertain band, run the
   existing heuristic and record which path ran. A silent `0.0` — the current
   `_pairwise_alignment` behaviour on a length mismatch — is the failure mode to
   avoid.
6. **Log the state with the answer.** Record the exact `state` and the echoed
   `model` string next to every probability. Without the state, a later threshold
   change cannot be explained.

Cost is not the constraint here: a 50-item labeled sweep is roughly $0.01.

## Rejected

- **Box / images** — the input boundary is text; no image in this pipeline.
- **Jev for generation** — explicitly not what it does; the four agents stay on
  chat models.
- **Using Jev to pick the next agent or "decide what to do next"** — that is
  decision logic, and it belongs in the graph.
- **`confidence` as the accept gate** — it measures distribution concentration, not
  correctness. Thresholds on the probability instead.
- **Whole-transcript state** — context rot (`jev-1.13.md`); send a narrow slice
  (one claim plus one challenge), not the full deliberation.

## Recommended build order

1. A single `think_tank/judge.py` holding all question text, thresholds, and the
   client — one place to audit wording, and one place to record the state it sent.
2. Land candidate 1 alone behind a labeled check from "How to validate". It is the
   highest-value and the easiest to evaluate; nothing else should ship before it
   because candidates 6 and 9 assume evidence is in the state and candidate 2's
   threshold needs to be tuned against real answers.
3. Then batch only the questions that share a state. Candidates **3, 4 and 9** each
   need a *different* slice, so they do not go in one call:
   - candidate 4 needs `passages` + `topic` (retrieval);
   - candidate 3 needs two rounds' claims;
   - candidate 9 needs `synthesis` + the claims and challenges it drew on.
   Batch within a slice (e.g. all per-passage Nouls for candidate 4 are one call);
   do not merge slices to save a request. Batching is 12× cheaper because the state
   is read once — that only helps when the questions genuinely share it, and
   irrelevant material in `state` costs accuracy (context rot).
4. Add **2** and **5** once `resolved` has a producer and `SkepticOutput` can carry
   it.
5. **7** and **8** next, since they change round count and need re-profiling with
   `THINK_TANK_PROFILE=1`. Candidate 8 needs its fallback path designed, not just
   its question.
6. **10** last — it touches the UI and the `Synthesis` verdict, and benefits from
   real retrieval scores once 4 exists.
7. Keep a `JevUnavailable` path: if the call fails, log it and run the existing
   heuristic rather than silently treating it as "no".

## Which access path to build against

Two paths exist and they are not interchangeable in the request. Keep them apart.

| | Native TypeSafe | OpenRouter (proven here) |
|---|---|---|
| Endpoint | `https://api.typesafe.ai/v1/systemone` | `https://openrouter.ai/api/v1/systemone` |
| Base URL you configure | `https://api.typesafe.ai` | `https://openrouter.ai/api` (both SDKs append `/v1/systemone`) |
| Model ID | `jev-1.14.0` | `typesafe/jev-1.14` (echoes `…-20261014`) |
| Auth | `TYPESAFE_API_KEY` | `OPENROUTER_API_KEY` |
| Client | `typesafe-sdk` 0.7.5, or `langchain-typesafe` 0.0.1a3 | same clients, or plain HTTP |
| Extra response fields | schema-defined | adds `cost`, `id`, `provider` |
| Key in this environment | **absent** | **present** |

Because `OPENROUTER_API_KEY` is the only key available here, the OpenRouter route is
the one that works today, and it is the one every measurement above came from.
Three ways to call it, in order of preference:

1. **`typesafe-sdk` 0.7.5** — verified end-to-end on this route (see below). Typed
   questions, typed answers, typed errors. Recommended.
2. **An `httpx` wrapper** in the style of `think_tank/llm.py` — the request is
   `{model, state, questions}` and the response `{model, answers, usage}`. Nothing
   to keep in sync, but you re-implement retries and error classes.
3. **`langchain-typesafe`** — only if you actually want it as a LangChain `Runnable`
   in a chain. It is a third alpha.

Note on the SDK's method name: it is `client.system_one(state=…, questions=…,
model=…)`, not `client.system_one.create(…)`. That mistake cost me a call, so it is
worth writing down.

`langchain-typesafe` also works, with two caveats. It is **`0.0.1a3`, an alpha,
marked beta** — PyPI lists only `0.0.1a1`, `0.0.1a2`, `0.0.1a3`, and importing it
emits `LangChainBetaWarning`; its own docs say the API may change. And it needs
`TYPESAFE_BASE_URL=https://openrouter.ai/api` — without the `/v1/systemone` suffix,
because the client appends it itself.

**`typesafe-sdk` also works on the OpenRouter path — now verified.** PyPI has it at
**0.7.5**, and I ran it end-to-end against `https://openrouter.ai/api` with
`TYPESAFE_BASE_URL` and `OPENROUTER_API_KEY`: it returned `model:
typesafe/jev-1.14-20261014` and `grounded = 0.02` for a fabricated claim. The call
shape is `client.system_one(state=..., questions={...}, model="typesafe/jev-1.14")`
— note the method is `system_one`, not `system_one.create`. It reads `TYPESAFE_BASE_URL`
and appends `/v1/systemone` the same way, and it has typed error classes
(`TypeSafeAuthenticationError`, `TypeSafeRateLimitError`, …) which is a real
advantage over a hand-rolled wrapper. Prefer it over `langchain-typesafe`: 0.7.5 is a
versioned release, not a third alpha.

Pin the `model` string explicitly either way, and assert on the `model` echoed in
every response rather than trusting the alias.

If a `TYPESAFE_API_KEY` is added later, the native path gives `jev-1.14.0` and a
schema-defined response. Nothing in this document depends on which path is used,
beyond the model IDs.
