"""app.py — Streamlit web interface for the Think Tank multi-agent deliberation system.

Run with:
    uv run streamlit run app.py

The UI lets users input a topic, then watch four specialised agents (Researcher,
Skeptic, Visionary, Synthesizer) deliberate through structured rounds, converging
on a final synthesis moderated by an Arbiter.
"""

from __future__ import annotations

import os
import textwrap
import typing as t

import streamlit as st
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from think_tank.graph import build_think_tank_graph
from think_tank.schemas import Challenge, Claim, LateralIdea, SynthesisAttempt
from think_tank.state import ThinkTankState

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Think Tank",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Custom CSS for a polished look
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&display=swap');

    html, body, [class*="stApp"] {
        font-family: 'Source Serif 4', Georgia, serif;
    }

    h1, h2, h3 {
        font-family: 'Playfair Display', serif !important;
        letter-spacing: -0.02em;
    }

    .think-tank-title {
        font-family: 'Playfair Display', serif;
        font-size: 3rem;
        font-weight: 700;
        color: #1a1a2e;
        text-align: center;
        margin-bottom: 0.25rem;
        letter-spacing: -0.03em;
    }

    .think-tank-subtitle {
        font-family: 'Source Serif 4', serif;
        font-size: 1.1rem;
        color: #666;
        text-align: center;
        margin-bottom: 2rem;
        font-style: italic;
    }

    .round-badge {
        display: inline-block;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 4px 14px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.85rem;
        margin-bottom: 1rem;
    }

    .artifact-card {
        background: #fafafa;
        border-left: 4px solid #667eea;
        border-radius: 0 8px 8px 0;
        padding: 1rem 1.25rem;
        margin: 0.75rem 0;
    }

    .artifact-meta {
        font-size: 0.8rem;
        color: #888;
        margin-bottom: 0.5rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .claim-card   { border-left-color: #667eea; }
    .challenge-card.support   { border-left-color: #10b981; }
    .challenge-card.oppose    { border-left-color: #ef4444; }
    .challenge-card.refine    { border-left-color: #f59e0b; }
    .idea-card    { border-left-color: #8b5cf6; }
    .synthesis-card { border-left-color: #0ea5e9; }

    .final-synthesis-box {
        background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
        border: 2px solid #10b981;
        border-radius: 12px;
        padding: 2rem;
        margin-top: 2rem;
    }

    .final-synthesis-title {
        font-family: 'Playfair Display', serif;
        font-size: 1.75rem;
        color: #065f46;
        margin-bottom: 1rem;
    }

    .stat-pill {
        display: inline-block;
        background: white;
        border: 1px solid #d1d5db;
        border-radius: 20px;
        padding: 4px 12px;
        font-size: 0.8rem;
        margin-right: 8px;
        margin-bottom: 8px;
    }

    .divider-line {
        height: 1px;
        background: linear-gradient(90deg, transparent, #e5e7eb, transparent);
        margin: 2rem 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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
# Render helpers
# ---------------------------------------------------------------------------
def _render_claim(claim: Claim) -> None:
    """Render a single claim card."""
    st.markdown(
        f"""
        <div class="artifact-card claim-card">
            <div class="artifact-meta">📄 Claim &mdash; {claim.agent_id} &middot; Confidence: {claim.confidence.value}</div>
            <div style="font-size: 0.95rem; color: #333; line-height: 1.6;">
                {claim.content}
            </div>
            {"<div style='margin-top:0.5rem;font-size:0.85rem;color:#666;'><em>Evidence:</em> " + claim.evidence_summary + "</div>" if claim.evidence_summary else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_challenge(challenge: Challenge) -> None:
    """Render a single challenge card."""
    stance_class = challenge.stance.value
    stance_emoji = {"support": "✅", "oppose": "❌", "refine": "🔧"}.get(stance_class, "💬")
    st.markdown(
        f"""
        <div class="artifact-card challenge-card {stance_class}">
            <div class="artifact-meta">{stance_emoji} Challenge &mdash; {challenge.agent_id} &rarr; {challenge.stance.value}</div>
            <div style="font-size: 0.95rem; color: #333; line-height: 1.6;">
                {challenge.content}
            </div>
            {"<div style='margin-top:0.5rem;font-size:0.85rem;color:#666;'><em>Reasoning:</em> " + challenge.reasoning + "</div>" if challenge.reasoning else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_idea(idea: LateralIdea) -> None:
    """Render a single lateral idea card."""
    st.markdown(
        f"""
        <div class="artifact-card idea-card">
            <div class="artifact-meta">💡 Lateral Idea &mdash; {idea.agent_id}</div>
            <div style="font-size: 0.95rem; color: #333; line-height: 1.6;">
                {idea.content}
            </div>
            {"<div style='margin-top:0.5rem;font-size:0.85rem;color:#666;'><em>Novelty:</em> " + idea.novelty_rationale + "</div>" if idea.novelty_rationale else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_synthesis_attempt(synth: SynthesisAttempt) -> None:
    """Render a synthesis attempt card."""
    st.markdown(
        f"""
        <div class="artifact-card synthesis-card">
            <div class="artifact-meta">🔄 Synthesis Attempt &mdash; Round {synth.round} &middot; Confidence: {synth.confidence.value}</div>
            <div style="font-size: 0.95rem; color: #333; line-height: 1.6;">
                {synth.content}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_round(state: ThinkTankState, round_num: int) -> None:
    """Render all artifacts for a single deliberation round."""
    alignment = state.get("alignment_score", 0.0)

    st.markdown(f'<div class="round-badge">Round {round_num}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-size:0.85rem;color:#888;margin-bottom:1rem;">Alignment score: <strong>{alignment:.4f}</strong></div>',
        unsafe_allow_html=True,
    )

    claims = [c for c in state.get("claims", []) if c.round == round_num]
    challenges = [ch for ch in state.get("challenges", []) if ch.round == round_num]
    ideas = [e for e in state.get("expansions", []) if e.round == round_num]
    syntheses = [s for s in state.get("syntheses", []) if s.round == round_num]

    if claims:
        with st.expander(f"📄 Claims ({len(claims)})", expanded=True):
            for claim in claims:
                _render_claim(claim)

    if challenges:
        with st.expander(f"💬 Challenges ({len(challenges)})", expanded=True):
            for challenge in challenges:
                _render_challenge(challenge)

    if ideas:
        with st.expander(f"💡 Lateral Ideas ({len(ideas)})", expanded=True):
            for idea in ideas:
                _render_idea(idea)

    if syntheses:
        with st.expander(f"🔄 Synthesis Attempts ({len(syntheses)})", expanded=True):
            for synth in syntheses:
                _render_synthesis_attempt(synth)

    st.markdown('<div class="divider-line"></div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------
def main() -> None:
    """Run the Think Tank Streamlit app."""
    # --- Load environment ---
    load_dotenv()

    if not os.getenv("OPENROUTER_API_KEY"):
        st.error(
            "🔑 **OPENROUTER_API_KEY is not set.**\n\n"
            "Please create a `.env` file in the project root with:\n\n"
            "```\nOPENROUTER_API_KEY=your-key-here\n```"
        )
        st.stop()

    # --- Header ---
    st.markdown('<div class="think-tank-title">🧠 Think Tank</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="think-tank-subtitle">Multi-Agent Deliberation System</div>',
        unsafe_allow_html=True,
    )

    # --- Sidebar info ---
    with st.sidebar:
        st.header("About")
        st.markdown(
            """
            The **Think Tank** orchestrates four specialised AI agents through
            structured rounds of debate:

            | Agent | Role |
            |-------|------|
            | 🔬 **Researcher** | Grounds discussion in evidence |
            | ⚔️ **Skeptic** | Stress-tests claims |
            | 💡 **Visionary** | Proposes lateral ideas |
            | 🔗 **Synthesizer** | Merges perspectives |
            | ⚖️ **Arbiter** | Decides convergence |
            """
        )
        st.divider()
        st.caption("Built with LangGraph · Streamlit · OpenRouter")

    # --- Input ---
    topic = st.text_input(
        "Topic / Task",
        placeholder="e.g. The impact of remote work on productivity",
        help="Enter a topic for the agents to deliberate on.",
    )

    col1, col2 = st.columns([1, 4])
    with col1:
        start_button = st.button("▶️ Start Deliberation", type="primary", use_container_width=True)

    # --- Deliberation ---
    if start_button:
        if not topic or not topic.strip():
            st.warning("⚠️ Please enter a topic before starting the deliberation.")
            st.stop()

        # Seed vector store
        with st.spinner("🔧 Initialising knowledge base..."):
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

        st.markdown("---")
        st.subheader("Deliberation Log")

        # Stream the graph
        seen_rounds: set[int] = set()
        progress_bar = st.progress(0.0)
        status_text = st.empty()

        for event in graph.stream(initial_state, stream_mode="values"):
            state = t.cast(ThinkTankState, event)
            round_num = state.get("current_round", 0)

            # Update progress
            max_rounds = state.get("config", {}).get("max_rounds", 6)
            progress = min(round_num / max_rounds, 1.0)
            progress_bar.progress(progress)

            # Render new round if we haven't seen it
            if round_num not in seen_rounds and round_num > 0:
                seen_rounds.add(round_num)
                status_text.markdown(
                    f"🔄 **Round {round_num}** in progress... Alignment: `{state.get('alignment_score', 0.0):.4f}`"
                )
                _render_round(state, round_num)

            # Check for final synthesis
            synthesis = state.get("synthesis")
            if synthesis is not None:
                progress_bar.empty()
                status_text.empty()
                st.balloons()

                st.markdown(
                    f"""
                    <div class="final-synthesis-box">
                        <div class="final-synthesis-title">✨ Final Synthesis</div>
                        <div style="margin-bottom:1rem;">
                            <span class="stat-pill">📊 Alignment: {synthesis.alignment_score:.4f}</span>
                            <span class="stat-pill">🔄 Rounds: {synthesis.rounds_taken}</span>
                            <span class="stat-pill">📄 Claims: {len(synthesis.contributing_claim_ids)}</span>
                        </div>
                        <div style="font-size: 1.05rem; line-height: 1.8; color: #1a1a2e;">
                            {textwrap.fill(synthesis.content, width=100).replace(chr(10), '<br>')}
                        </div>
                        {f"<div style='margin-top:1rem;font-size:0.9rem;color:#666;'><em>Unresolved challenges:</em> {len(synthesis.unresolved_challenges)}</div>" if synthesis.unresolved_challenges else ""}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                break

        else:
            # Stream ended without convergence
            progress_bar.empty()
            status_text.empty()
            st.warning("⚠️ Deliberation ended without reaching convergence. Try adjusting the topic or configuration.")


if __name__ == "__main__":
    main()
