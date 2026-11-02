// Think Tank dashboard. Renders one deliberation report (rust/src/uireport.rs).
// Every value shown comes from the report; nothing here is invented.

const STEPS = [
  { id: "researcher", name: "Researcher", role: "looks up facts", out: "Claim", tip: "An AI agent. Looks up facts in the document library, then states a position (a claim)." },
  { id: "skeptic", name: "Skeptic", role: "argues back", out: "Challenge", tip: "An AI agent. Argues against, agrees with, or refines the claim." },
  { id: "visionary", name: "Visionary", role: "adds an angle", out: "Idea", tip: "An AI agent. Proposes an unconventional angle nobody has tried." },
  { id: "synthesizer", name: "Synthesizer", role: "merges it", out: "Merge", tip: "An AI agent. Merges the round into one answer and lists open disagreements." },
  { id: "arbiter", name: "Arbiter", role: "scores & decides", out: "Score", tip: "Not an AI model but a plain program: scores how settled the debate is and decides whether to go again." },
];
const STEP_BY_ID = Object.fromEntries(STEPS.map((s) => [s.id, s]));

const TIPS = {
  claim: "A position stated by the Researcher, with the evidence behind it.",
  challenge: "The Skeptic's reply to one claim.",
  stance: "oppose = argues against · support = agrees · refine = agrees in part",
  confidence: "How sure the agent says it is (its own statement, not measured).",
  dimension: "An aspect of the question the claim is rated on, such as risk.",
  embedding: "The meaning of the text as a list of numbers. Similar meaning, similar numbers.",
  cosine: "Similarity of two embeddings: 1 = same meaning, 0 = unrelated, negative = opposite.",
  semantic: "Average similarity between this round's claims and the claims before it. High = the position stopped moving.",
  opposition: "Share of this round's challenges whose stance is oppose.",
  score: "0.80 × semantic alignment + 0.20 × (1 − opposition ratio).",
  target: "The score needed before the debate may stop on agreement.",
  min: "The debate cannot stop on agreement before this many rounds.",
  max: "The debate always stops after this many rounds.",
  tension: "A disagreement between viewpoints.",
  directive: "The Arbiter's instruction for the next round.",
  span: "One timed step of the run.",
  replay: "Recorded AI answers played through the real agent code. Not a live model, and the embeddings are placeholders, so scores are a demonstration.",
  resolved: "The system never marks a challenge resolved, so all stay open.",
  llm: "Waiting for an AI model",
  node: "An agent's own step",
  vector_store: "Searching the document library",
  startup: "Preparing the run",
};

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const n4 = (v) => Number(v).toFixed(4);
const n2 = (v) => Number(v).toFixed(2);
const short = (id) => String(id).slice(0, 8);
const when = (iso) => new Date(iso).toLocaleTimeString(undefined, { hour12: false });
const tip = (key, text) => `<span class="tip" tabindex="0" data-tip="${esc(TIPS[key] || key)}">${esc(text ?? key)}</span>`;

const app = document.getElementById("app");
let R = null; // report
let IX = null; // lookups
let sel = { round: 1, step: "final" };
let timer = null;
let tab = "timing";

// ---------- derived data ----------

function build(report) {
  const claims = new Map();
  const challenges = new Map();
  for (const r of report.rounds) {
    for (const c of r.artifacts.claims) claims.set(c.id, { ...c, n: r.number });
    for (const c of r.artifacts.challenges) challenges.set(c.id, { ...c, n: r.number });
  }
  // Spans are recorded as they finish; a round ends at its arbiter span.
  const spansByRound = new Map();
  let round = 1;
  for (const s of report.telemetry.spans) {
    const agent = s.name.split(".")[0] === "kb" ? "researcher" : s.name.split(".")[0];
    if (!spansByRound.has(round)) spansByRound.set(round, []);
    spansByRound.get(round).push({ ...s, agent });
    if (s.name.startsWith("arbiter")) round += 1;
  }
  return { claims, challenges, spansByRound };
}

const roundOf = (n) => R.rounds.find((r) => r.number === n);
const order = () => [...R.rounds.flatMap((r) => STEPS.map((s) => ({ round: r.number, step: s.id }))), { round: R.rounds.length, step: "final" }];

// ---------- small parts ----------

function chipAgent(id) {
  const s = STEP_BY_ID[id];
  return `<span class="chip agent a-${esc(id)}">${esc(s ? s.name : id)}</span>`;
}
const idc = (id) => `<span class="chip id" title="${esc(id)}">${esc(short(id))}</span>`;
const kv = (k, v) => `<div class="kv"><span class="k">${k}</span><span class="v">${v}</span></div>`;

function spark(values) {
  const max = Math.max(...values.map(Math.abs), 1e-9);
  return `<span class="spark" title="${values.length} numbers">${values.map((v) => `<i class="${v < 0 ? "neg" : ""}" style="height:${Math.max(2, Math.round((Math.abs(v) / max) * 22))}px"></i>`).join("")}</span>`;
}

function meter(value, max = 1, cls = "") {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return `<span class="meter ${cls}"><i style="width:${pct}%"></i></span>`;
}

function link(kind, id, label) {
  return `<button class="ref" data-ref="${kind}:${esc(id)}">${esc(label)}</button>`;
}

function claimRef(id) {
  const c = IX.claims.get(id);
  return c
    ? `<div class="ref-card">${link("claim", id, `R${c.n} claim ${short(id)}`)}<span class="clip">${esc(c.content)}</span></div>`
    : idc(id);
}

// ---------- header ----------

function renderHeader(scenarios, current) {
  const f = R.final;
  const s = f.synthesis;
  const ok = R.outcome === "converged";
  const tokens = R.telemetry.spans.reduce((a, sp) => a + sp.attrs.reduce((b, [k, v]) => b + (k === "in_tok" || k === "out_tok" ? Number(v) || 0 : 0), 0), 0);
  const tile = (label, value, cls = "", kind = "") => `<div class="tile ${cls}"><b>${value}</b><span>${label}</span>${kind ? `<em>${kind}</em>` : ""}</div>`;
  return `<header class="top">
    <div class="brand">Think Tank</div>
    <div class="topic" title="${esc(R.topic)}">${esc(R.topic)}</div>
    <span class="meta">4 agents → arbiter → verdict</span>
    <span class="chip warn">${tip("replay", "REPLAY")}</span>
    <select id="scenario" aria-label="Recorded run">${scenarios.map((n) => `<option ${n === current ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
  </header>
  <section class="tiles" aria-label="Run summary">
    ${tile("outcome", ok ? "Agreed" : "Forced stop", ok ? "good" : "bad", ok ? "stopped on agreement" : "stopped at the limit")}
    ${tile("rounds", `${s.rounds_taken}<small>/${R.config.max_rounds}</small>`, "", "used / allowed")}
    ${tile(tip("score", "final score"), n2(s.alignment_score), "", "0 to 1, higher = settled")}
    ${tile(tip("target", "target"), n2(R.config.alignment_threshold), "", "score needed to stop")}
    ${tile("claims", f.claims_total, "", "positions the researcher stated")}
    ${tile("challenges", f.challenges_total, "", "rebuttals the skeptic raised")}
    ${tile("ideas", f.lateral_ideas_total, "", "new angles the visionary added")}
    ${tile("merges", f.synthesis_attempts_total, "", "merged answers, one per round")}
    ${tile("time", `${n2(R.telemetry.wall_clock_s * 1000)}<small> ms</small>`, "", "whole run")}
    ${tile("tokens", tokens, "", "AI words in + out")}
  </section>`;
}

// ---------- rail ----------

function preview(round, stepId) {
  const a = round.artifacts;
  switch (stepId) {
    case "researcher": return a.claims[0]?.content ?? "";
    case "skeptic": return a.challenges[0] ? `${a.challenges[0].stance}: ${a.challenges[0].content}` : "";
    case "visionary": return a.lateral_ideas[0]?.content ?? "";
    case "synthesizer": return a.synthesis_attempts[0]?.content ?? "";
    default: return `score ${n4(round.score)} · ${verdictLabel(round)}`;
  }
}

const verdictLabel = (r) => ({ continue: "go again", converged: "stop: agreed", forced: "stop: limit" }[r.verdict.kind] || r.verdict.kind);

function renderRail() {
  const rounds = R.rounds.map((r) => `<div class="rail-round">
      <div class="rail-head">Round ${r.number}<span class="chip ${r.verdict.kind === "continue" ? "warn" : r.verdict.kind === "converged" ? "good" : "bad"}">${esc(verdictLabel(r))}</span><b>${n2(r.score)} <small>score</small></b></div>
      ${STEPS.map((s) => `<button class="rail-step ${sel.round === r.number && sel.step === s.id ? "on" : ""} a-${s.id}" data-go="${r.number}:${s.id}">
        <i class="dot"></i><span class="who">${esc(s.name)}</span><span class="clip">${esc(preview(r, s.id))}</span></button>`).join("")}
    </div>`).join("");
  return `<nav class="rail" aria-label="Conversation"><div class="rail-title">What each agent said, round by round</div>${rounds}
    <button class="rail-step final ${sel.step === "final" ? "on" : ""}" data-go="${R.rounds.length}:final"><i class="dot"></i><span class="who">Final answer</span><span class="clip">${esc(R.final.synthesis.content)}</span></button></nav>`;
}

// ---------- pipeline graph ----------

function renderGraph() {
  const pos = { researcher: 74, skeptic: 230, visionary: 386, synthesizer: 542, arbiter: 698 };
  const y = 74, w = 128, h = 66;
  const r = roundOf(sel.round);
  const counts = {
    researcher: r.artifacts.claims.length, skeptic: r.artifacts.challenges.length,
    visionary: r.artifacts.lateral_ideas.length, synthesizer: r.artifacts.synthesis_attempts.length,
    arbiter: n2(r.score),
  };
  const idx = STEPS.findIndex((s) => s.id === sel.step);
  const status = (i) => (sel.step === "final" ? "done" : i < idx ? "done" : i === idx ? "active" : "idle");
  const nodes = STEPS.map((s, i) => `<g class="node a-${s.id} ${status(i)}" data-go="${sel.round}:${s.id}" tabindex="0" role="button" aria-label="${esc(s.name)}: ${esc(counts[s.id])} ${esc(s.out)}">
      <rect x="${pos[s.id] - w / 2}" y="${y - h / 2}" width="${w}" height="${h}" rx="10"/>
      <text x="${pos[s.id]}" y="${y - 10}" class="nm">${esc(s.name)}</text>
      <text x="${pos[s.id]}" y="${y + 6}" class="rl">${esc(s.role)}</text>
      <text x="${pos[s.id]}" y="${y + 21}" class="ct">${esc(s.out)} · ${esc(counts[s.id])}</text></g>`).join("");
  const arrows = STEPS.slice(0, -1).map((s, i) => {
    const x1 = pos[s.id] + w / 2, x2 = pos[STEPS[i + 1].id] - w / 2;
    return `<path class="edge ${i < idx || sel.step === "final" ? "lit" : ""}" d="M${x1} ${y} H${x2 - 6}" marker-end="url(#ah)"/>`;
  }).join("");
  const again = r.verdict.kind === "continue";
  const t = R.config.alignment_threshold;
  const why = again ? `score ${n2(r.score)} < ${n2(t)}` : r.verdict.kind === "converged" ? "settled" : "round limit";
  const loop = `<path class="edge loop ${again ? "lit" : ""}" d="M${pos.arbiter} ${y + h / 2} V${y + 82} H${pos.researcher} V${y + h / 2 + 6}" marker-end="url(#ah)"/>
    <text x="${(pos.arbiter + pos.researcher) / 2}" y="${y + 78}" class="lp">${again ? `AGAIN — ${esc(why)}` : "AGAIN"}</text>`;
  const exit = `<path class="edge exit ${!again ? "lit" : ""}" d="M${pos.arbiter + w / 2} ${y} H878" marker-end="url(#ah)"/>
    <text x="${pos.arbiter + w / 2 + 6}" y="${y - 10}" class="ex ${!again ? "lit" : ""}">${again ? "STOP" : `STOP — ${esc(why)}`}</text>`;
  return `<svg class="graph" viewBox="0 0 1050 200" role="img" aria-label="Round ${sel.round} pipeline">
    <defs><marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10z" fill="currentColor"/></marker></defs>
    ${arrows}${loop}${exit}${nodes}</svg>`;
}

function renderControls() {
  const pills = R.rounds.map((r) => `<button class="pill ${sel.round === r.number ? "on" : ""}" data-go="${r.number}:${sel.step === "final" ? "researcher" : sel.step}">R${r.number}</button>`).join("");
  return `<div class="controls"><button class="btn" data-act="prev" aria-label="Previous step">◀</button>
    <button class="btn play" data-act="play" aria-label="${timer ? "Pause" : "Play the process"}">${timer ? "❚❚" : "▶"}</button>
    <button class="btn" data-act="next" aria-label="Next step">▶|</button>${pills}</div>`;
}

// ---------- score ----------

function renderChart() {
  const t = R.config.alignment_threshold;
  const bars = R.rounds.map((r, i) => {
    const bw = 66, gap = 44, x = 40 + i * (bw + gap), hgt = r.score * 100;
    return `<g class="bar ${sel.round === r.number ? "on" : ""}" data-go="${r.number}:arbiter" tabindex="0" role="button" aria-label="Round ${r.number} score ${n2(r.score)}">
      <rect x="${x}" y="${120 - hgt}" width="${bw}" height="${Math.max(hgt, 1)}" rx="3"/>
      <text x="${x + bw / 2}" y="${112 - hgt}" class="bv">${n2(r.score)}</text>
      <text x="${x + bw / 2}" y="138" class="bl">R${r.number}</text></g>`;
  }).join("");
  const width = 70 + R.rounds.length * 110;
  const chart = `<svg class="chart" viewBox="0 0 ${width} 150" role="img" aria-label="Score by round against target ${n2(t)}">
    <line x1="30" x2="${width - 6}" y1="${120 - t * 100}" y2="${120 - t * 100}" class="tl"/>
    <text x="${width - 8}" y="${114 - t * 100}" class="tt" text-anchor="end">target ${n2(t)}</text>
    <line x1="30" x2="30" y1="14" y2="120" class="ax"/><line x1="30" x2="${width - 6}" y1="120" y2="120" class="ax"/>
    <text x="26" y="24" class="ay" text-anchor="end">1</text><text x="26" y="123" class="ay" text-anchor="end">0</text>${bars}</svg>`;
  return `<div class="panel"><h2>Score by round<span class="muted"> — settled-ness, 0 to 1, after each round</span></h2>${chart}</div>`;
}

function renderScorePanel() {
  const t = R.config.alignment_threshold;
  const r = roundOf(sel.round === undefined ? 1 : sel.round);
  const p = r.score_parts;
  const opposed = r.artifacts.challenges.filter((c) => c.stance === "oppose").length;
  const fin = r.number;
  const checks = [
    [r.score >= t, `score ${n2(r.score)} vs ${tip("target", "needed")} ${n2(t)}`],
    [fin >= R.config.min_rounds, `${fin} rounds run, ${tip("min", "at least")} ${R.config.min_rounds} needed`],
    [fin >= R.config.max_rounds, `${fin} rounds run, ${tip("max", "limit")} ${R.config.max_rounds}`, true],
  ].map(([yes, label, stop]) => `<span class="check ${yes ? (stop ? "stop" : "yes") : "no"}"><b>${yes ? "✓" : "✗"}</b>${label}</span>`).join("");
  const stopped = r.verdict.kind !== "continue";
  const sem = p.semantic_term, opp = p.opposition_term;
  return `<div class="panel"><h2>Round ${r.number} score<span class="muted"> — 0.80 × semantic + 0.20 × (1 − opposition)</span></h2>
      <div class="stack" title="semantic part + opposition part"><i class="s" style="width:${sem * 100}%"></i><i class="o" style="width:${opp * 100}%"></i></div>
      <table class="calc"><tbody>
        <tr><td><i class="sw s"></i>${tip("semantic", "semantic")} <small>similarity to earlier rounds, 0–1</small></td><td class="n">${n4(p.semantic_alignment)}</td><td class="n">× 0.80</td><td class="n">= ${n4(sem)}</td></tr>
        <tr><td><i class="sw o"></i>1 − ${tip("opposition", "opposition")} <small>share of rebuttals that disagreed, 0 to 1 (${opposed} of ${p.challenge_count} here)</small></td><td class="n">${n4(1 - p.opposition_ratio)}</td><td class="n">× 0.20</td><td class="n">= ${n4(opp)}</td></tr>
        <tr class="sum"><td colspan="3">score</td><td class="n">${n4(r.score)}</td></tr></tbody></table>
      <div class="checks-head">${r.verdict.kind === "converged" ? "why it stopped: score reached the target after enough rounds" : r.verdict.kind === "forced" ? "why it stopped: the round limit was reached" : "why it kept going: the score was still below the target"}</div>
      <div class="checks">${checks}</div>
      <div class="verdict ${r.verdict.kind}">${esc(verdictLabel(r))}</div></div>`;
}

// ---------- detail ----------

function spanFooter(agent) {
  const spans = (IX.spansByRound.get(sel.round) || []).filter((s) => s.agent === agent);
  if (!spans.length) return "";
  return `<div class="spans">${spans.map((s) => {
    const at = Object.fromEntries(s.attrs);
    const extra = [at.model, at.in_tok != null ? `${at.in_tok}→${at.out_tok} tok` : null].filter(Boolean).join(" · ");
    const label = { llm: "model call", node: "agent step", vector_store: "doc search", startup: "setup", arbiter: "score step" }[s.kind] || s.kind;
    return `<span class="chip kind-${esc(s.kind)}" title="${esc(s.name)} — ${esc(TIPS[s.kind] || s.kind)}">${esc(label)} · measured ${n2(s.duration_ms)} ms${extra ? ` · ${esc(extra)}` : ""}</span>`;
  }).join("")}</div>`;
}

function confChip(level) {
  return `<span class="chip ${{ high: "good", medium: "warn", low: "bad" }[level] || ""}">${tip("confidence", "confidence")} ${esc(level)}</span>`;
}

function detailClaim(c) {
  return `<article class="card a-researcher" id="claim-${esc(c.id)}">
    <div class="row">${chipAgent(c.agent_id)}${tip("claim", "Claim")}${idc(c.id)}${confChip(c.confidence)}<span class="time">${when(c.created_at)}</span></div>
    <p class="text">${esc(c.content)}</p>
    ${kv("Evidence", esc(c.evidence_summary))}
    ${kv(tip("dimension", "Rated on"), Object.entries(c.dimensions).map(([k, v]) => `<span class="chip">${esc(k)} <b>${esc(v)}</b></span>`).join("") || "—")}
    ${kv(tip("embedding", "Meaning"), `${spark(c.embedding)} <span class="muted">${c.embedding.length} numbers</span>`)}
  </article>`;
}

function detailChallenge(c) {
  const cls = { oppose: "bad", support: "good", refine: "warn" }[c.stance] || "";
  return `<article class="card a-skeptic" id="challenge-${esc(c.id)}">
    <div class="row">${chipAgent(c.agent_id)}${tip("challenge", "Challenge")}${idc(c.id)}<span class="chip ${cls} big">${tip("stance", c.stance)}</span>
      <span class="chip warn">${tip("resolved", "open")}</span><span class="time">${when(c.created_at)}</span></div>
    <p class="text">${esc(c.content)}</p>
    ${kv("Reasoning", esc(c.reasoning))}
    ${kv("Targets", claimRef(c.target_claim_id))}
  </article>`;
}

function detailIdea(e) {
  return `<article class="card a-visionary"><div class="row">${chipAgent(e.agent_id)}Idea${idc(e.id)}<span class="time">${when(e.created_at)}</span></div>
    <p class="text">${esc(e.content)}</p>
    ${kv("Why new", esc(e.novelty_rationale))}
    ${kv("Builds on", e.related_claim_ids.map(claimRef).join("") || "—")}</article>`;
}

function listItems(items, cls) {
  return items.length ? `<ul class="tl ${cls}">${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : "—";
}

function detailMerge(s) {
  return `<article class="card a-synthesizer"><div class="row">${chipAgent(s.agent_id)}Merge${idc(s.id)}${confChip(s.confidence)}<span class="time">${when(s.created_at)}</span></div>
    <p class="text">${esc(s.content)}</p>
    ${kv(`${tip("tension", "Settled")}`, listItems(s.resolved_tensions, "ok"))}
    ${kv(`${tip("tension", "Still open")}`, listItems(s.remaining_tensions, "open"))}
    ${kv("Built from", s.incorporated_claim_ids.map(claimRef).join("") || "—")}</article>`;
}

function detailArbiter(r) {
  const p = r.score_parts;
  const comps = p.comparisons.length
    ? `<table class="mini"><thead><tr><th>claim</th><th>vs</th><th>${tip("cosine", "similarity")}</th></tr></thead><tbody>${p.comparisons.map((c) => `<tr><td>${link("claim", c.a, `R${IX.claims.get(c.a)?.n} ${short(c.a)}`)}</td><td>${link("claim", c.b, `R${IX.claims.get(c.b)?.n} ${short(c.b)}`)} <small>${c.scope === "same_round" ? "same round" : "earlier round"}</small></td><td class="n">${n4(c.cosine)}</td></tr>`).join("")}</tbody></table>`
    : `<span class="muted">no earlier claims to compare with → 0</span>`;
  const d = r.directive;
  return `<article class="card a-arbiter"><div class="row">${chipAgent("arbiter")}Score ${n4(r.score)}<span class="chip ${r.verdict.kind === "continue" ? "warn" : r.verdict.kind === "converged" ? "good" : "bad"}">${esc(verdictLabel(r))}</span></div>
    ${kv(`${tip("semantic", "Comparisons")} <small>claim pairs and how alike their meaning is</small>`, comps)}
    ${kv(`${tip("resolved", "Resolved share")}`, `${n4(p.challenge_resolution_rate)} <span class="muted">— share of challenges marked resolved; never scored</span>`)}
    ${d ? `${kv(tip("directive", "Next-round instruction"), `<span class="quote">${esc(d.prompt)}</span>`)}
      ${kv(`Focus <small>the topic the next round should work on</small>`, d.focus_dimensions.map((f) => `<span class="chip">${esc(f)}</span>`).join("") || "—")}
      ${kv(`Disagreements <small>what the next round must address</small>`, `<span class="quote pre">${esc(d.disagreement_summary)}</span>`)}
` : ""}
  </article>`;
}

function detailFinal() {
  const s = R.final.synthesis;
  const ok = R.outcome === "converged";
  return `<article class="card final ${ok ? "" : "forced"}"><div class="row"><span class="chip ${ok ? "good" : "bad"} big">${ok ? "Agreed" : "Forced stop"}</span>Final answer${idc(s.id)}<span class="time">${when(s.created_at)}</span></div>
    <p class="text">${esc(s.content)}</p>
    ${kv("Rounds", s.rounds_taken)}${kv("Score", n4(s.alignment_score))}
    ${kv("Rests on", s.contributing_claim_ids.map(claimRef).join("") || "—")}
    ${kv(`Never settled (${s.unresolved_challenges.length})`, s.unresolved_challenges.map((id) => { const c = IX.challenges.get(id); return c ? `<div class="ref-card">${link("challenge", id, `R${c.n} ${c.stance} ${short(id)}`)}<span class="clip">${esc(c.content)}</span></div>` : idc(id); }).join("") || "—")}
  </article>`;
}

function renderDetail() {
  const r = roundOf(sel.round);
  const a = r.artifacts;
  let body;
  switch (sel.step) {
    case "researcher": body = a.claims.map(detailClaim).join("") + spanFooter("researcher"); break;
    case "skeptic": body = a.challenges.map(detailChallenge).join("") + spanFooter("skeptic"); break;
    case "visionary": body = a.lateral_ideas.map(detailIdea).join("") + spanFooter("visionary"); break;
    case "synthesizer": body = a.synthesis_attempts.map(detailMerge).join("") + spanFooter("synthesizer"); break;
    case "arbiter": body = detailArbiter(r) + spanFooter("arbiter"); break;
    default: body = detailFinal();
  }
  const s = STEP_BY_ID[sel.step];
  // Escape the interpolated values only; the kicker is markup and stays markup.
  const title = s
    ? `Round ${esc(sel.round)} · ${esc(s.name)}`
    : "Final answer";
  const kicker = s ? "what this step produced" : "what the debate settled on";
  return `<div class="panel detail"><h2>${title} <small class="kicker">${esc(kicker)}</small>${s ? `<span class="muted"> — ${esc(s.tip)}</span>` : ""}</h2>${body}</div>`;
}

// ---------- bottom tabs ----------

const SPAN_LABEL = {
  "kb.retrieve": "search the document library",
  "researcher.llm": "researcher asks the model for a claim",
  "skeptic.llm": "skeptic asks the model for a rebuttal",
  "visionary.llm": "visionary asks the model for an angle",
  "synthesizer.llm": "synthesizer asks the model for a merge",
  "arbiter.score": "arbiter scores the round",
  "researcher": "researcher step, whole", "skeptic": "skeptic step, whole",
  "visionary": "visionary step, whole", "synthesizer": "synthesizer step, whole",
};
const spanLabel = (n) => SPAN_LABEL[n] || n;

function renderTiming() {
  const t = R.telemetry;
  const wall = Math.max(t.wall_clock_s * 1000, 0.001);
  const KIND_LABEL = { llm: "waiting on the model", node: "agent's own step", vector_store: "document search", startup: "setup", arbiter: "scoring" };
  const kinds = t.by_kind.map((k) => `<span class="chip kind-${esc(k.kind)}" title="${esc(TIPS[k.kind] || "")}">${esc(KIND_LABEL[k.kind] || k.kind)} · ${k.count}× · ${n2(k.seconds * 1000)} ms · ${n2(k.share)}% of run</span>`).join("");
  const head = `<div class="wf-head"><span>what ran</span><span>when, across the whole run</span><span>how long</span></div>`;
  const rows = t.spans.map((s, i) => {
    const agent = s.name.split(".")[0] === "kb" ? "researcher" : s.name.split(".")[0];
    const attrs = s.attrs.map(([k, v]) => `${k}=${v}`).join(" ");
    return `<div class="wf-row a-${agent} ${sel.step === agent ? "hl" : ""}" title="${esc(attrs)}">
      <span class="wf-name" style="padding-left:${s.depth * 12}px" title="${esc(s.name)}">${esc(spanLabel(s.name))}</span>
      <span class="wf-track"><i class="kind-${esc(s.kind)}" style="left:${((s.offset_ms / wall) * 100).toFixed(2)}%;width:${Math.max((s.duration_ms / wall) * 100, 0.4).toFixed(2)}%"></i></span>
      <span class="n">${n2(s.duration_ms)} ms</span></div>`;
  }).join("");
  return `<div class="kinds">${kinds}</div>${head}<div class="wf">${rows}</div>`;
}

function renderEvidence() {
  const e = R.evidence;
  return `<div class="ev">${e.documents.map((d, i) => `<div class="ev-row"><span class="n">#${i + 1}</span><span class="clip2">${esc(d.text)}</span>
    <span class="sim" title="${esc(TIPS.cosine)}">${meter(Math.max(d.similarity, 0))}<b>${n2(d.similarity)}</b></span></div>`).join("")}</div>`;
}

function renderSettings() {
  const c = R.config;
  const chips = [
    ["target", n2(c.alignment_threshold)], ["min rounds", c.min_rounds], ["max rounds", c.max_rounds],
    ["chat", `${R.providers.chat?.name} · ${R.providers.chat?.default_model}`],
    ["embeddings", `${R.providers.embedding?.name} · ${R.providers.embedding?.model}`],
    ["run", R.run_id], ["built", new Date(R.generated_at).toLocaleTimeString(undefined, { hour12: false })],
    ["source", `${R.source.kind} · ${R.source.scenario}`],
    ...Object.entries(c.values).map(([k, v]) => [`set ${k}`, v]),
  ];
  return `<div class="chips">${chips.map(([k, v]) => `<span class="chip"><span class="muted">${esc(k)}</span> <b>${esc(v)}</b></span>`).join("")}</div>`;
}

function renderFields() {
  const groups = {};
  for (const f of R.state_fields) (groups[f.group] ||= []).push(f);
  return `<div class="fields">${Object.entries(groups).map(([g, fs]) => `<div class="fgroup"><b>${esc(g)}</b>${fs.map((f) => `<span class="chip" title="${esc(f.where)}">${esc(f.field.split(".").pop())}</span>`).join("")}</div>`).join("")}</div>`;
}

function renderTerms() {
  const keys = ["claim", "challenge", "stance", "confidence", "dimension", "embedding", "cosine", "semantic", "opposition", "score", "target", "min", "max", "tension", "directive", "span", "replay", "resolved"];
  return `<dl class="terms">${keys.map((k) => `<dt>${esc(k)}</dt><dd>${esc(TIPS[k])}</dd>`).join("")}</dl>`;
}

const TABS = { timing: ["Timing", renderTiming], evidence: ["Evidence", renderEvidence], settings: ["Settings", renderSettings], fields: ["Fields", renderFields], terms: ["Terms", renderTerms] };

function renderBottom() {
  return `<section class="panel bottom"><div class="tabs" role="tablist">${Object.entries(TABS).map(([id, [label]]) => `<button role="tab" aria-selected="${tab === id}" class="${tab === id ? "on" : ""}" data-tab="${id}">${label}</button>`).join("")}</div>
    <div class="tabbody">${TABS[tab][1]()}</div></section>`;
}

// ---------- frame ----------

let chrome = { scenarios: [], current: "" };

function render() {
  const scrollRail = document.querySelector(".rail")?.scrollTop ?? 0;
  app.innerHTML = `${renderHeader(chrome.scenarios, chrome.current)}
    <main class="grid">
      ${renderRail()}
      <div class="center"><div class="panel flow"><h2>Process<span class="muted"> — five steps; the Arbiter either loops or exits</span></h2>${renderControls()}${renderGraph()}</div>${renderChart()}</div>
      <div class="center">${renderDetail()}${renderScorePanel()}</div>
    </main>${renderBottom()}`;
  const rail = document.querySelector(".rail");
  if (rail) {
    rail.scrollTop = scrollRail;
    rail.querySelector(".on")?.scrollIntoView({ block: "nearest" });
  }
  history.replaceState(null, "", `#r=${sel.round}&s=${sel.step}`);
}

function go(round, step) {
  sel = { round: Number(round), step };
  render();
}

function stepBy(delta) {
  const seq = order();
  const i = seq.findIndex((s) => s.round === sel.round && s.step === sel.step);
  const next = seq[Math.min(Math.max(i + delta, 0), seq.length - 1)];
  go(next.round, next.step);
  return next;
}

function play() {
  if (timer) { clearInterval(timer); timer = null; render(); return; }
  go(1, "researcher");
  timer = setInterval(() => {
    const seq = order();
    const i = seq.findIndex((s) => s.round === sel.round && s.step === sel.step);
    if (i >= seq.length - 1) { clearInterval(timer); timer = null; render(); return; }
    stepBy(1);
  }, 1100);
  render();
}

app.addEventListener("click", (event) => {
  const t = event.target.closest("[data-go],[data-act],[data-tab],[data-ref]");
  if (!t) return;
  if (t.dataset.go) { const [r, s] = t.dataset.go.split(":"); go(r, s); }
  else if (t.dataset.tab) { tab = t.dataset.tab; render(); }
  else if (t.dataset.act === "play") play();
  else if (t.dataset.act === "next") stepBy(1);
  else if (t.dataset.act === "prev") stepBy(-1);
  else if (t.dataset.ref) {
    const [kind, id] = t.dataset.ref.split(":");
    const item = (kind === "claim" ? IX.claims : IX.challenges).get(id);
    if (item) { go(item.n, kind === "claim" ? "researcher" : "skeptic"); document.getElementById(`${kind}-${id}`)?.classList.add("flash"); }
  }
});
app.addEventListener("keydown", (event) => {
  if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-go]")) { event.preventDefault(); event.target.click(); }
});
app.addEventListener("change", (event) => {
  if (event.target.id === "scenario") { const u = new URL(location.href); u.hash = ""; u.searchParams.set("scenario", event.target.value); location.href = u; }
});

async function getJson(url) {
  const response = await fetch(url);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `${url}: ${response.status}`);
  return body;
}

async function load() {
  const { scenarios } = await getJson("/api/scenarios");
  const asked = new URL(location.href).searchParams.get("scenario");
  const current = scenarios.includes(asked) ? asked : scenarios[0];
  R = await getJson(`/api/report?scenario=${encodeURIComponent(current)}`);
  IX = build(R);
  chrome = { scenarios, current };
  const m = location.hash.match(/r=(\d+)&s=(\w+)/);
  sel = m && roundOf(Number(m[1])) ? { round: Number(m[1]), step: m[2] } : { round: R.rounds.length, step: "final" };
  document.title = `Think Tank · ${R.topic}`;
  render();
}

load().catch((error) => {
  app.innerHTML = `<div class="error" role="alert"><b>Could not load</b> ${esc(error.message)}</div>`;
});

// Deep links: a hash change selects another round/step without a reload.
window.addEventListener("hashchange", () => {
  const m = location.hash.match(/r=(\d+)&s=(\w+)/);
  if (m && roundOf(Number(m[1]))) go(m[1], m[2]);
});

// Dev live-reload: reload when any file under ui/web changes.
let seenVersion = null;
setInterval(async () => {
  try {
    const version = await (await fetch("/__version")).text();
    if (seenVersion !== null && version !== seenVersion) location.reload();
    seenVersion = version;
  } catch { /* server restarting */ }
}, 700);
