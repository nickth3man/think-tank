"""think_tank/llm.py — Provider-agnostic chat and embedding model factories.

Every supported provider speaks the OpenAI chat-completions protocol, so a single
``ChatOpenAI``/``OpenAIEmbeddings`` client with a per-provider ``base_url`` covers
all of them. Credentials are read from the process environment (e.g. ``~/.zshenv``);
no ``.env`` file is required.

Provider policy:

* ``ollama_cloud``  — default chat provider, ``deepseek-v4.1-flash``.
* ``mistral``       — chat, ``mistral-small-latest`` (Nemo-class) or larger.
* ``opencode``      — chat, ``deepseek-v4.1-flash``.
* ``zai``           — chat, ``glm-5.3`` (only GLM models are served).
* ``openrouter``    — embeddings and judge/decision models only; never chat.

Chat selection precedence:
    per-agent config -> ``THINK_TANK_<AGENT>_PROVIDER`` -> ``THINK_TANK_PROVIDER``
    -> ``DEFAULT_CHAT_PROVIDER``
and, independently:
    per-agent config -> ``THINK_TANK_<AGENT>_MODEL`` -> ``THINK_TANK_CHAT_MODEL``
    -> provider default model

Embedding selection precedence:
    ``THINK_TANK_EMBEDDING_PROVIDER`` -> ``DEFAULT_EMBEDDING_PROVIDER``
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import SecretStr

from think_tank.telemetry import span

DEFAULT_CHAT_PROVIDER = "ollama_cloud"
DEFAULT_EMBEDDING_PROVIDER = "openrouter"
DEFAULT_CHAT_MODEL = "deepseek-v4.1-flash"

AGENT_NAMES = ("researcher", "skeptic", "visionary", "synthesizer")


@dataclass(frozen=True, slots=True)
class Provider:
    """An OpenAI-compatible inference endpoint."""

    name: str
    api_key_env: str
    base_url: str
    default_model: str
    supports_chat: bool = True
    embeddings_model: str | None = None
    structured_output_method: Literal["function_calling", "json_mode", "json_schema"] = (
        "function_calling"
    )
    #: Sent only when set. Most providers reject the parameter outright
    #: (Mistral answers 400 "reasoning_effort is not enabled for this model"),
    #: so it is opt-in per endpoint rather than a global default.
    reasoning_effort: str | None = None
    headers: tuple[tuple[str, str], ...] = ()

    @property
    def api_key(self) -> str | None:
        """The configured key, or ``None`` when the variable is unset/empty."""
        return os.getenv(self.api_key_env) or None

    @property
    def supports_embeddings(self) -> bool:
        return self.embeddings_model is not None

    def default_headers(self) -> dict[str, str] | None:
        """Headers for this provider, resolved per call so env changes take effect."""
        resolved = {key: value for key, env in self.headers if (value := os.getenv(env))}
        return resolved or None


PROVIDERS: dict[str, Provider] = {
    "ollama_cloud": Provider(
        name="ollama_cloud",
        api_key_env="OLLAMA_CLOUD_API_KEY",
        base_url="https://ollama.com/v1",
        default_model=DEFAULT_CHAT_MODEL,
        reasoning_effort="none",
    ),
    "mistral": Provider(
        name="mistral",
        api_key_env="MISTRAL_API_KEY",
        base_url="https://api.mistral.ai/v1",
        default_model="mistral-small-latest",
        embeddings_model="mistral-embed",
        structured_output_method="json_schema",
    ),
    "opencode": Provider(
        name="opencode",
        api_key_env="OPENCODE_API_KEY",
        base_url="https://opencode.ai/zen/v1",
        default_model=DEFAULT_CHAT_MODEL,
    ),
    "zai": Provider(
        name="zai",
        api_key_env="ZAI_API_KEY",
        base_url="https://api.z.ai/api/paas/v4",
        default_model="glm-5.3",
    ),
    "openrouter": Provider(
        name="openrouter",
        api_key_env="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
        default_model=DEFAULT_CHAT_MODEL,
        supports_chat=False,
        embeddings_model="openai/text-embedding-3-small",
        structured_output_method="json_schema",
        headers=(("HTTP-Referer", "OPENROUTER_APP_URL"), ("X-Title", "OPENROUTER_APP_TITLE")),
    ),
}


def resolve_provider(name: str | None = None, *, for_chat: bool = True) -> Provider:
    """Resolve a provider by name, falling back to ``THINK_TANK_PROVIDER``."""
    if name:
        resolved = name.strip().lower()
    elif for_chat:
        resolved = (os.getenv("THINK_TANK_PROVIDER") or DEFAULT_CHAT_PROVIDER).strip().lower()
    else:
        resolved = (
            (os.getenv("THINK_TANK_EMBEDDING_PROVIDER") or DEFAULT_EMBEDDING_PROVIDER)
            .strip()
            .lower()
        )
    try:
        provider = PROVIDERS[resolved]
    except KeyError:
        raise ValueError(
            f"Unknown provider {resolved!r}. Choose one of: {', '.join(sorted(PROVIDERS))}."
        ) from None
    if for_chat and not provider.supports_chat:
        raise ValueError(
            f"Provider {resolved!r} is reserved for embeddings and judge models, not chat. "
            f"Use one of: {', '.join(sorted(n for n, p in PROVIDERS.items() if p.supports_chat))}."
        )
    return provider


def _api_key(provider: Provider) -> str:
    key = provider.api_key
    if not key:
        raise RuntimeError(
            f"{provider.api_key_env} is not set. Export it before running "
            f"(e.g. in ~/.zshenv) or pick a provider whose key you do have."
        )
    return key


#: Runaway guard, not a length control. Measured on these prompts the model
#: emits 200-450 tokens regardless of a lower cap, so a tight cap buys no
#: latency and risks truncating a tool call on providers that count hidden
#: reasoning against it. The brevity prompts are the real lever.
DEFAULT_MAX_TOKENS = 4096


def _effort_for(provider: Provider) -> str | None:
    """Reasoning effort to send, or ``None`` to omit the parameter entirely.

    The env override is honoured only for providers that support it, so setting
    ``THINK_TANK_REASONING_EFFORT`` globally cannot break an endpoint that
    rejects the field.
    """
    if provider.reasoning_effort is None:
        return None
    return os.getenv("THINK_TANK_REASONING_EFFORT", provider.reasoning_effort)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_chat_model(
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> ChatOpenAI:
    """Build a chat client for the resolved provider and model.

    ``max_tokens`` matters more than any other knob here: the default model is a
    reasoning variant whose latency is dominated by generated tokens, so an
    unbounded completion is the single largest cost in a deliberation run.
    """
    p = resolve_provider(provider, for_chat=True)
    token_cap = (
        max_tokens
        if max_tokens is not None
        else _int_env("THINK_TANK_MAX_TOKENS", DEFAULT_MAX_TOKENS)
    )
    extra: dict[str, Any] = {"max_tokens": token_cap}
    effort = reasoning_effort or _effort_for(p)
    if effort is not None:
        extra["reasoning_effort"] = effort
    return ChatOpenAI(  # type: ignore[call-arg]
        model=model or os.getenv("THINK_TANK_CHAT_MODEL") or p.default_model,
        base_url=p.base_url,
        api_key=SecretStr(_api_key(p)),
        temperature=temperature,
        default_headers=p.default_headers(),
        **extra,
    )


def _agent_provider_name(agent: str, config: dict) -> str | None:
    """Provider name for one agent, or ``None`` when it uses the global default."""
    return config.get(f"{agent}_provider") or os.getenv(f"THINK_TANK_{agent.upper()}_PROVIDER")


def agent_chat_model(agent: str, config: dict, *, temperature: float = 0.0) -> ChatOpenAI:
    """Build a chat client honouring per-agent provider/model overrides.

    A global ``THINK_TANK_CHAT_MODEL`` belongs to the global provider, so it is
    not applied to an agent whose provider was overridden — that pairing would
    send a model name the other endpoint does not serve.
    """
    upper = agent.upper()
    name = _agent_provider_name(agent, config)
    model = config.get(f"{agent}_model") or os.getenv(f"THINK_TANK_{upper}_MODEL")
    if name and not model:
        model = resolve_provider(name, for_chat=True).default_model
    kwargs: dict[str, Any] = {"provider": name or "", "temperature": temperature}
    if model:
        kwargs["model"] = model
    max_tokens = config.get(f"{agent}_max_tokens") or os.getenv(f"THINK_TANK_{upper}_MAX_TOKENS")
    if max_tokens:
        kwargs["max_tokens"] = int(max_tokens)
    effort = config.get(f"{agent}_reasoning_effort") or os.getenv(
        f"THINK_TANK_{upper}_REASONING_EFFORT"
    )
    if effort:
        kwargs["reasoning_effort"] = effort
    return get_chat_model(**kwargs)


class _ProfiledEmbeddings(OpenAIEmbeddings):
    """Embeddings client that records latency for every batch it embeds."""

    provider_name: str = ""

    def embed_documents(
        self, texts: list[str], chunk_size: int | None = None, **kwargs: Any
    ) -> list[list[float]]:
        with span(
            "embeddings.documents",
            "embedding",
            provider=self.provider_name,
            model=self.model,
            n=len(texts),
        ):
            return super().embed_documents(texts, chunk_size, **kwargs)

    def embed_query(self, text: str, **kwargs: Any) -> list[float]:
        # OpenAIEmbeddings.embed_query delegates to embed_documents, which is
        # already recorded; adding a second span would double-count the call.
        return super().embed_query(text, **kwargs)

    async def aembed_documents(
        self, texts: list[str], chunk_size: int | None = None, **kwargs: Any
    ) -> list[list[float]]:
        with span(
            "embeddings.documents",
            "embedding",
            provider=self.provider_name,
            model=self.model,
            n=len(texts),
        ):
            return await super().aembed_documents(texts, chunk_size, **kwargs)

    async def aembed_query(self, text: str, **kwargs: Any) -> list[float]:
        # Delegates to aembed_documents, which records the span.
        return await super().aembed_query(text, **kwargs)


STRUCTURED_RETRIES = 3


def agent_structured_llm(
    agent: str, config: dict, schema: type, *, temperature: float = 0.0
) -> Any:
    """Chat client bound to ``schema``, resilient to weak tool-call emissions.

    Smaller models occasionally return a tool call with empty or malformed
    arguments, which LangChain parses to ``None``. Those turns are retried
    instead of surfacing as an ``AttributeError`` inside a graph node.
    """
    llm = agent_chat_model(agent, config, temperature=temperature)
    method = resolve_provider(
        _agent_provider_name(agent, config), for_chat=True
    ).structured_output_method
    bound = llm.with_structured_output(schema, method=method, include_raw=True)

    provider = resolve_provider(_agent_provider_name(agent, config), for_chat=True)
    model_name = llm.model_name

    def _invoke(messages: Any, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, STRUCTURED_RETRIES + 1):
            with span(
                f"{agent}.llm", "llm", provider=provider.name, model=model_name, attempt=attempt
            ) as sp:
                result = bound.invoke(messages, **kwargs)
                usage = getattr(result["raw"], "usage_metadata", None) or {}
                if sp is not None:
                    sp.attrs["in_tok"] = usage.get("input_tokens")
                    sp.attrs["out_tok"] = usage.get("output_tokens")
                    sp.attrs["chars"] = sum(len(str(m.content)) for m in messages)
            if result["parsed"] is not None:
                return result["parsed"]
            last_error = result["parsing_error"]
            if sp is not None:
                raw = result.get("raw")
                empty = raw is not None and not getattr(raw, "tool_calls", None)
                sp.attrs["retry_reason"] = "empty_tool_call" if empty else "parse_error"
                sp.attrs["retry_detail"] = str(last_error)[:200]
        raise RuntimeError(
            f"{agent} model did not return valid {schema.__name__} "
            f"after {STRUCTURED_RETRIES} attempts: {last_error}"
        )

    return RunnableLambda(_invoke)


def resolve_embedding_provider(name: str | None = None) -> Provider:
    """Resolve the embedding provider, rejecting providers without embeddings."""
    provider = resolve_provider(name, for_chat=False)
    if not provider.supports_embeddings:
        raise ValueError(
            f"Provider {provider.name!r} does not serve embeddings. "
            f"Set THINK_TANK_EMBEDDING_PROVIDER to one of: "
            f"{', '.join(p.name for p in PROVIDERS.values() if p.supports_embeddings)}."
        )
    return provider


def get_embeddings(*, provider: str | None = None, model: str | None = None) -> OpenAIEmbeddings:
    """Build an embedding client for the resolved provider and model."""
    p = resolve_embedding_provider(provider)
    resolved_model = model or os.getenv("THINK_TANK_EMBEDDING_MODEL") or p.embeddings_model or ""
    return _ProfiledEmbeddings(
        model=resolved_model,
        base_url=p.base_url,
        api_key=SecretStr(_api_key(p)),
        default_headers=p.default_headers(),
        check_embedding_ctx_length=False,
        provider_name=p.name,
    )


def embedding_collection_name(*, provider: str | None = None, model: str | None = None) -> str:
    """Chroma collection scoped to the embedding space, so vector dimensions never clash."""
    p = resolve_embedding_provider(provider)
    resolved_model = model or os.getenv("THINK_TANK_EMBEDDING_MODEL") or p.embeddings_model or ""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{p.name}-{resolved_model}".lower()).strip("-")
    return f"think_tank_kb__{slug}"


def missing_credentials() -> list[str]:
    """Environment variables required by the configured chat and embedding providers."""
    required = [resolve_provider(for_chat=True).api_key_env]
    embedding = resolve_embedding_provider()
    if embedding.api_key_env not in required:
        required.append(embedding.api_key_env)
    for agent in AGENT_NAMES:
        override = os.getenv(f"THINK_TANK_{agent.upper()}_PROVIDER")
        if override:
            env_name = resolve_provider(override, for_chat=True).api_key_env
            if env_name not in required:
                required.append(env_name)
    return [name for name in required if not os.getenv(name)]
