"""think_tank/kb.py — Chroma knowledge base wired to the configured embedding provider."""

from __future__ import annotations

import os

from langchain_chroma import Chroma

from think_tank.llm import embedding_collection_name, get_embeddings
from think_tank.telemetry import span

SEED_DOCUMENTS = [
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


def get_vector_store() -> Chroma:
    """Open the persistent Chroma collection for the active embedding space."""
    return Chroma(
        collection_name=embedding_collection_name(),
        embedding_function=get_embeddings(),
        persist_directory=os.getenv("CHROMA_DB_PATH", "./chroma_db"),
    )


def _seed_documents() -> list:
    from langchain_core.documents import Document

    return [
        Document(page_content=text, metadata={"source": "seed", "index": i})
        for i, text in enumerate(SEED_DOCUMENTS)
    ]


def _is_empty(vector_store: Chroma) -> bool:
    """Cheap emptiness probe.

    A similarity search would embed the query first — a full network round trip
    just to learn whether the collection has any documents.
    """
    return not vector_store.get(limit=1)["ids"]


def seed_if_empty(vector_store: Chroma) -> bool:
    """Populate the collection with the seed documents when it is empty.

    Returns ``True`` when documents were added.
    """
    with span("kb.seed.check", "vector_store"):
        if not _is_empty(vector_store):
            return False
    with span("kb.seed.load", "vector_store", n=len(SEED_DOCUMENTS)):
        vector_store.add_documents(_seed_documents())
    return True


async def aseed_if_empty(vector_store: Chroma) -> bool:
    """Async variant of :func:`seed_if_empty`."""
    with span("kb.seed.check", "vector_store"):
        if not _is_empty(vector_store):
            return False
    with span("kb.seed.load", "vector_store", n=len(SEED_DOCUMENTS)):
        await vector_store.aadd_documents(_seed_documents())
    return True


def retrieve(topic: str, k: int = 5) -> str:
    """Similarity-search the knowledge base and join the matched passages.

    Callers cache the result in run state rather than here: a process-global
    cache would go stale when the collection is reseeded or ``CHROMA_DB_PATH``
    changes, and would leak between test runs.
    """
    with span("kb.retrieve", "vector_store", k=k):
        results = get_vector_store().similarity_search(topic, k=k)
    if not results:
        return f"No pre-indexed documents found for: {topic!r}."
    return "\n".join(doc.page_content for doc in results)
