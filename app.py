"""app.py — Gradio web interface for the Think Tank multi-agent deliberation system.

Run with:
    uv run python app.py

The UI lets users input a topic, then watch four specialised agents (Researcher,
Skeptic, Visionary, Synthesizer) deliberate through structured rounds, converging
on a final synthesis moderated by an Arbiter.
"""

from __future__ import annotations

import os
import textwrap

import gradio as gr
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from think_tank.graph import build_think_tank_graph
from think_tank.schemas import Challenge, Claim, LateralIdea, SynthesisAttempt
from think_tank.state import ThinkTankState

# ---------------------------------------------------------------------------
# Seed documents (same as main.py)
# ---------------------------------------------------------------------------
_SEED_DOCUMENTS = [
    "Remote work has been shown to increase productivity for knowledge workers "
    "by 13% according to a Stanford study conducted over 9 months with 16,000 "
    "employees. The increase was attributed to quieter work environments and "
    "fewer sick days.",
    "A 2023 McKinsey report found that 87% of workers offered flexible work "
    "arrangements choose to work remotely at least part of the time. Employee "
    "satisfaction scores rose by 20% when remote options were available.",
    "Communication overhead increases by approximately 30% in fully remote "
    "teams due to reliance on asynchronous channels, according to a Microsoft "
    "study of 60,000 employees. This can lead to slower decision-making in "
    "time-sensitive situations.",
    "Hybrid work models (2-3 days in-office) appear to balance productivity "
    "gains with team cohesion. A Harvard Business Review meta-analysis of 45 "
    "studies found hybrid arrangements produced optimal outcomes for both "
    "employee well-being and business metrics.",
    "Remote work exacerbates the 'always-on' culture: 62% of remote workers "
    "report difficulty disconnecting after work hours (Buffer State of Remote "
    "Work 2023). This can lead to burnout despite apparent schedule flexibility.",
    "Innovation metrics decline in fully remote settings according to a Nature "
    "Human Behaviour study analysing 20 million research papers. Face-to-face "
    "interactions were found to be significantly more likely to produce "
    "novel, breakthrough ideas compared to virtual collaboration.",
    "Cost savings from remote work are substantial: companies save an average "
    "of $11,000 per remote employee per year on real estate, utilities, and "
    "office supplies (Global Workplace Analytics 2023 estimate).",
    "Onboarding new employees remotely takes 32% longer on average compared "
    "to in-person onboarding, according to a 2022 Gartner survey of 500 HR "
    "leaders. Knowledge transfer and culture assimilation were cited as the "
    "primary challenges.",
]


def _get_vector_store() -> Chroma:
    """Return a Chroma vector store using the configured DB path."""
    db_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
    return Chroma(
        collection_name="think_tank_kb",
        embedding_function=OpenAIEmbeddings(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            model=os.getenv("OPENROUTER_EMBEDDING_MODEL", "openai/text-embedding-3-small"),
            check_embedding_ctx_length=False,
        ),
        persist_directory=db_path,
    )


def _seed_if_empty(vector_store: Chroma) -> None:
    """Populate the vector store with dummy documents when the collection is empty."""
    existing = vector_store.similarity_search("remote work productivity", k=1)
    if existing:
        return
    documents = [
        Document(page_content=text, metadata={"source": "seed", "index": i})
        for i, text in enumerate(_SEED_DOCUMENTS)
    ]
    vector_store.add_documents(documents)


# ---------------------------------------------------------------------------
# Markdown formatting helpers
# ---------------------------------------------------------------------------
def _format_claim(claim: Claim) -> str:
    evidence = f"\n\n*Evidence:* {claim.evidence_summary}" if claim.evidence_summary else ""
    return (
        f"<div style='background:#fafafa;border-left:4px solid #667eea;"
        f"border-radius:0 8px 8px 0;padding:1rem 1.25rem;margin:0.75rem 0;'>"
        f"<div style='font-size:0.8rem;color:#888;margin-bottom:0.5rem;font-weight:600;"
        f"text-transform:uppercase;letter-spacing:0.05em;'>"
        f"📄 Claim — {claim.agent_id} · Confidence: {claim.confidence.value}</div>"
        f"<div style='font-size:0.95rem;color:#333;line-height:1.6;'>"
        f"{claim.content}</div>{evidence}</div>"
    )


def _format_challenge(challenge: Challenge) -> str:
    stance_emoji = {"support": "✅", "oppose": "❌", "refine": "🔧"}.get(
        challenge.stance.value, "💬"
    )
    border_color = {
        "support": "#10b981",
        "oppose": "#ef4444",
        "refine": "#f59e0b",
    }.get(challenge.stance.value, "#667eea")
    reasoning = f"\n\n*Reasoning:* {challenge.reasoning}" if challenge.reasoning else ""
    return (
        f"<div style='background:#fafafa;border-left:4px solid {border_color};"
        f"border-radius:0 8px 8px 0;padding:1rem 1.25rem;margin:0.75rem 0;'>"
        f"<div style='font-size:0.8rem;color:#888;margin-bottom:0.5rem;font-weight:600;"
        f"text-transform:uppercase;letter-spacing:0.05em;'>"
        f"{stance_emoji} Challenge — {challenge.agent_id} → {challenge.stance.value}</div>"
        f"<div style='font-size:0.95rem;color:#333;line-height:1.6;'>"
        f"{challenge.content}</div>{reasoning}</div>"
    )


def _format_idea(idea: LateralIdea) -> str:
    novelty = f"\n\n*Novelty:* {idea.novelty_rationale}" if idea.novelty_rationale else ""
    return (
        f"<div style='background:#fafafa;border-left:4px solid #8b5cf6;"
        f"border-radius:0 8px 8px 0;padding:1rem 1.25rem;margin:0.75rem 0;'>"
        f"<div style='font-size:0.8rem;color:#888;margin-bottom:0.5rem;font-weight:600;"
        f"text-transform:uppercase;letter-spacing:0.05em;'>"
        f"💡 Lateral Idea — {idea.agent_id}</div>"
        f"<div style='font-size:0.95rem;color:#333;line-height:1.6;'>"
        f"{idea.content}</div>{novelty}</div>"
    )


def _format_synthesis_attempt(synth: SynthesisAttempt) -> str:
    return (
        f"<div style='background:#fafafa;border-left:4px solid #0ea5e9;"
        f"border-radius:0 8px 8px 0;padding:1rem 1.25rem;margin:0.75rem 0;'>"
        f"<div style='font-size:0.8rem;color:#888;margin-bottom:0.5rem;font-weight:600;"
        f"text-transform:uppercase;letter-spacing:0.05em;'>"
        f"🔄 Synthesis Attempt — Round {synth.round} · Confidence: {synth.confidence.value}</div>"
        f"<div style='font-size:0.95rem;color:#333;line-height:1.6;'>"
        f"{synth.content}</div></div>"
    )


def _format_round(state: ThinkTankState, round_num: int) -> str:
    alignment = state.get("alignment_score", 0.0)
    md = (
        f"<div style='display:inline-block;background:linear-gradient(135deg, "
        f"#667eea 0%, #764ba2 100%);color:white;padding:4px 14px;border-radius:20px;"
        f"font-weight:600;font-size:0.85rem;margin-bottom:1rem;'>"
        f"Round {round_num}</div>\n\n"
        f"<div style='font-size:0.85rem;color:#888;margin-bottom:1rem;'>"
        f"Alignment score: <strong>{alignment:.4f}</strong></div>\n\n"
    )

    claims = [c for c in state.get("claims", []) if c.round == round_num]
    challenges = [ch for ch in state.get("challenges", []) if ch.round == round_num]
    ideas = [e for e in state.get("expansions", []) if e.round == round_num]
    syntheses = [s for s in state.get("syntheses", []) if s.round == round_num]

    if claims:
        md += f"### 📄 Claims ({len(claims)})\n\n"
        for claim in claims:
            md += _format_claim(claim) + "\n\n"

    if challenges:
        md += f"### 💬 Challenges ({len(challenges)})\n\n"
        for challenge in challenges:
            md += _format_challenge(challenge) + "\n\n"

    if ideas:
        md += f"### 💡 Lateral Ideas ({len(ideas)})\n\n"
        for idea in ideas:
            md += _format_idea(idea) + "\n\n"

    if syntheses:
        md += f"### 🔄 Synthesis Attempts ({len(syntheses)})\n\n"
        for synth in syntheses:
            md += _format_synthesis_attempt(synth) + "\n\n"

    md += (
        "<div style='height:1px;background:linear-gradient(90deg, transparent, "
        "#e5e7eb, transparent);margin:2rem 0;'></div>\n\n"
    )
    return md


def _format_final_synthesis(state: ThinkTankState) -> str:
    synthesis = state.get("synthesis")
    if synthesis is None:
        return ""

    unresolved = ""
    if synthesis.unresolved_challenges:
        unresolved = (
            f"<div style='margin-top:1rem;font-size:0.9rem;color:#666;'>"
            f"<em>Unresolved challenges:</em> {len(synthesis.unresolved_challenges)}</div>"
        )

    wrapped = textwrap.fill(synthesis.content, width=100).replace("\n", "<br>")

    return (
        f"<div style='background:linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);"
        f"border:2px solid #10b981;border-radius:12px;padding:2rem;margin-top:2rem;'>"
        f"<div style='font-size:1.75rem;color:#065f46;margin-bottom:1rem;font-weight:700;'>"
        f"✨ Final Synthesis</div>"
        f"<div style='margin-bottom:1rem;'>"
        f"<span style='display:inline-block;background:white;border:1px solid #d1d5db;"
        f"border-radius:20px;padding:4px 12px;font-size:0.8rem;margin-right:8px;margin-bottom:8px;'>"
        f"📊 Alignment: {synthesis.alignment_score:.4f}</span>"
        f"<span style='display:inline-block;background:white;border:1px solid #d1d5db;"
        f"border-radius:20px;padding:4px 12px;font-size:0.8rem;margin-right:8px;margin-bottom:8px;'>"
        f"🔄 Rounds: {synthesis.rounds_taken}</span>"
        f"<span style='display:inline-block;background:white;border:1px solid #d1d5db;"
        f"border-radius:20px;padding:4px 12px;font-size:0.8rem;margin-right:8px;margin-bottom:8px;'>"
        f"📄 Claims: {len(synthesis.contributing_claim_ids)}</span></div>"
        f"<div style='font-size:1.05rem;line-height:1.8;color:#1a1a2e;'>"
        f"{wrapped}</div>{unresolved}</div>"
    )


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------
def run_deliberation(topic: str):
    """Run the Think Tank deliberation and yield Markdown updates."""
    load_dotenv()

    if not os.getenv("OPENROUTER_API_KEY"):
        yield (
            "🔑 **OPENROUTER_API_KEY is not set.**\n\n"
            "Please create a `.env` file in the project root with:\n\n"
            "```\nOPENROUTER_API_KEY=your-key-here\n```"
        )
        return

    if not topic or not topic.strip():
        yield "⚠️ Please enter a topic before starting the deliberation."
        return

    # Seed vector store
    vector_store = _get_vector_store()
    _seed_if_empty(vector_store)

    # Build graph
    graph = build_think_tank_graph()

    initial_state: ThinkTankState = {
        "topic": topic.strip(),
        "config": {
            "alignment_threshold": 0.65,
            "min_rounds": 2,
            "max_rounds": 6,
        },
        "claims": [],
        "challenges": [],
        "expansions": [],
        "syntheses": [],
        "current_round": 0,
        "alignment_score": 0.0,
        "expansion": None,
        "synthesis": None,
    }

    md = "## Deliberation Log\n\n"
    seen_rounds: set[int] = set()

    for event in graph.stream(initial_state, stream_mode="values"):
        state = event  # type: ThinkTankState
        round_num = state.get("current_round", 0)

        if round_num not in seen_rounds and round_num > 0:
            seen_rounds.add(round_num)
            md += _format_round(state, round_num)
            yield md

        synthesis = state.get("synthesis")
        if synthesis is not None:
            md += _format_final_synthesis(state)
            yield md
            break
    else:
        md += (
            "\n\n⚠️ **Deliberation ended without reaching convergence.** "
            "Try adjusting the topic or configuration."
        )
        yield md


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------
with gr.Blocks(
    title="Think Tank",
    theme=gr.themes.Soft(
        primary_hue="indigo",
        secondary_hue="violet",
        neutral_hue="slate",
    ),
) as demo:
    gr.Markdown(
        "# 🧠 Think Tank\n\n"
        "<div style='text-align:center;font-size:1.1rem;color:#666;font-style:italic;'>"
        "Multi-Agent Deliberation System</div>"
    )

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown(
                "### About\n\n"
                "The **Think Tank** orchestrates four specialised AI agents through "
                "structured rounds of debate:\n\n"
                "| Agent | Role |\n"
                "|-------|------|\n"
                "| 🔬 **Researcher** | Grounds discussion in evidence |\n"
                "| ⚔️ **Skeptic** | Stress-tests claims |\n"
                "| 💡 **Visionary** | Proposes lateral ideas |\n"
                "| 🔗 **Synthesizer** | Merges perspectives |\n"
                "| ⚖️ **Arbiter** | Decides convergence |\n\n"
                "Built with LangGraph · Gradio · OpenRouter"
            )

        with gr.Column(scale=3):
            topic_input = gr.Textbox(
                label="Topic / Task",
                placeholder="e.g. The impact of remote work on productivity",
                info="Enter a topic for the agents to deliberate on.",
                lines=1,
            )
            start_btn = gr.Button("▶️ Start Deliberation", variant="primary")
            output_md = gr.Markdown()

    start_btn.click(
        fn=run_deliberation,
        inputs=topic_input,
        outputs=output_md,
    )

if __name__ == "__main__":
    demo.launch()
