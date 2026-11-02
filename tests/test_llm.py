"""Tests for think_tank/llm.py — provider registry and model factories."""

from __future__ import annotations

import pytest

from think_tank import llm

CHAT_PROVIDERS = ("ollama_cloud", "mistral", "opencode", "zai")
ALL_PROVIDERS = (*CHAT_PROVIDERS, "openrouter")
TT_VARS = (
    "THINK_TANK_PROVIDER",
    "THINK_TANK_CHAT_MODEL",
    "THINK_TANK_EMBEDDING_PROVIDER",
    "THINK_TANK_EMBEDDING_MODEL",
    *(
        f"THINK_TANK_{a.upper()}_{suffix}"
        for a in llm.AGENT_NAMES
        for suffix in ("PROVIDER", "MODEL")
    ),
)
KEY_VARS = (
    "OPENROUTER_API_KEY",
    "MISTRAL_API_KEY",
    "ZAI_API_KEY",
    "OLLAMA_CLOUD_API_KEY",
    "OPENCODE_API_KEY",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch):
    """Isolate every test from THINK_TANK_* and provider keys in the real shell."""
    for name in (*TT_VARS, *KEY_VARS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "ollama-test")
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-test")
    monkeypatch.setenv("ZAI_API_KEY", "zai-test")
    monkeypatch.setenv("OPENCODE_API_KEY", "opencode-test")
    return monkeypatch


class TestRegistry:
    def test_every_provider_is_openai_compatible(self) -> None:
        for name, provider in llm.PROVIDERS.items():
            assert provider.name == name
            assert provider.base_url.startswith("https://")
            assert provider.api_key_env.endswith("_API_KEY")
            assert provider.default_model

    def test_openrouter_is_embeddings_only(self) -> None:
        openrouter = llm.PROVIDERS["openrouter"]
        assert not openrouter.supports_chat
        assert openrouter.supports_embeddings

    def test_embeddings_providers(self) -> None:
        serving = {p.name for p in llm.PROVIDERS.values() if p.supports_embeddings}
        assert serving == {"openrouter", "mistral"}

    def test_defaults(self) -> None:
        assert llm.DEFAULT_CHAT_PROVIDER == "ollama_cloud"
        assert llm.DEFAULT_EMBEDDING_PROVIDER == "openrouter"
        assert llm.PROVIDERS[llm.DEFAULT_CHAT_PROVIDER].supports_chat

    def test_chat_providers_share_the_deepseek_flash_default(self) -> None:
        for name in ("ollama_cloud", "opencode"):
            assert llm.PROVIDERS[name].default_model == "deepseek-v4.1-flash"

    def test_mistral_defaults_to_small(self) -> None:
        assert llm.PROVIDERS["mistral"].default_model == "mistral-small-latest"


class TestResolveProvider:
    def test_defaults_to_ollama_cloud(self) -> None:
        assert llm.resolve_provider().name == "ollama_cloud"

    @pytest.mark.parametrize("name", CHAT_PROVIDERS)
    def test_named_lookup(self, name: str) -> None:
        assert llm.resolve_provider(name).name == name

    def test_openrouter_is_rejected_for_chat(self) -> None:
        with pytest.raises(ValueError, match="reserved for embeddings"):
            llm.resolve_provider("openrouter")

    def test_openrouter_resolves_for_embeddings(self) -> None:
        assert llm.resolve_provider("openrouter", for_chat=False).name == "openrouter"

    def test_openrouter_is_rejected_via_env(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_PROVIDER", "openrouter")
        with pytest.raises(ValueError, match="reserved for embeddings"):
            llm.resolve_provider()

    def test_env_selects_provider(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_PROVIDER", "mistral")
        assert llm.resolve_provider().name == "mistral"

    def test_explicit_argument_beats_env(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_PROVIDER", "mistral")
        assert llm.resolve_provider("zai").name == "zai"

    def test_name_is_case_and_space_insensitive(self) -> None:
        assert llm.resolve_provider("  MISTRAL ").name == "mistral"

    def test_unknown_provider_lists_alternatives(self) -> None:
        with pytest.raises(ValueError, match="openrouter"):
            llm.resolve_provider("nope")


class TestChatModel:
    def test_builds_client_for_resolved_provider(self, clean_env) -> None:
        clean_env.setenv("MISTRAL_API_KEY", "m-key")
        model = llm.get_chat_model(provider="mistral", temperature=0.3)
        assert str(model.openai_api_base) == llm.PROVIDERS["mistral"].base_url
        assert model.model_name == llm.PROVIDERS["mistral"].default_model
        assert model.temperature == 0.3

    def test_model_env_override(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_CHAT_MODEL", "openai/gpt-5.4-mini")
        assert llm.get_chat_model().model_name == "openai/gpt-5.4-mini"

    def test_explicit_model_beats_env(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_CHAT_MODEL", "openai/gpt-5.4-mini")
        assert llm.get_chat_model(model="openai/gpt-5.5").model_name == "openai/gpt-5.5"

    def test_missing_key_raises_naming_the_variable(self, clean_env) -> None:
        clean_env.delenv("OLLAMA_CLOUD_API_KEY")
        with pytest.raises(RuntimeError, match="OLLAMA_CLOUD_API_KEY"):
            llm.get_chat_model()

    def test_default_model_is_deepseek_flash(self) -> None:
        assert llm.get_chat_model().model_name == "deepseek-v4.1-flash"

    def test_openrouter_attribution_headers(self, clean_env) -> None:
        clean_env.setenv("OPENROUTER_APP_TITLE", "Think Tank")
        clean_env.setenv("OPENROUTER_APP_URL", "https://example.test")
        headers = llm.PROVIDERS["openrouter"].default_headers()
        assert headers == {"HTTP-Referer": "https://example.test", "X-Title": "Think Tank"}


class TestAgentChatModel:
    def test_falls_back_to_global_provider(self) -> None:
        model = llm.agent_chat_model("skeptic", {})
        assert model.model_name == "deepseek-v4.1-flash"

    def test_config_keys_override_provider_and_model(self) -> None:
        model = llm.agent_chat_model(
            "visionary", {"visionary_provider": "zai", "visionary_model": "glm-5.3-flash"}
        )
        assert str(model.openai_api_base) == llm.PROVIDERS["zai"].base_url
        assert model.model_name == "glm-5.3-flash"

    def test_env_overrides_apply_per_agent(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_RESEARCHER_PROVIDER", "mistral")
        clean_env.setenv("THINK_TANK_RESEARCHER_MODEL", "mistral-large-latest")
        model = llm.agent_chat_model("researcher", {})
        assert str(model.openai_api_base) == llm.PROVIDERS["mistral"].base_url
        assert model.model_name == "mistral-large-latest"

    def test_other_agents_are_unaffected_by_an_agent_override(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_RESEARCHER_PROVIDER", "mistral")
        assert llm.agent_chat_model("skeptic", {}).model_name == "deepseek-v4.1-flash"

    def test_openrouter_chat_override_is_rejected(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_SKEPTIC_PROVIDER", "openrouter")
        with pytest.raises(ValueError, match="reserved for embeddings"):
            llm.agent_chat_model("skeptic", {})


class TestEmbeddings:
    def test_defaults_to_openrouter(self) -> None:
        assert llm.resolve_embedding_provider().name == "openrouter"

    def test_independent_of_chat_provider(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_PROVIDER", "mistral")
        assert llm.resolve_embedding_provider().name == "openrouter"

    def test_mistral_embeddings_when_selected(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_EMBEDDING_PROVIDER", "mistral")
        embeddings = llm.get_embeddings()
        assert str(embeddings.openai_api_base) == llm.PROVIDERS["mistral"].base_url
        assert embeddings.model == "mistral-embed"

    def test_rejects_provider_without_embeddings(self) -> None:
        with pytest.raises(ValueError, match="does not serve embeddings"):
            llm.get_embeddings(provider="zai")

    def test_embedding_model_env_override(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_EMBEDDING_MODEL", "mistral-embed")
        assert llm.get_embeddings().model == "mistral-embed"


class TestCollectionNaming:
    def test_scoped_to_provider_and_model(self) -> None:
        assert (
            llm.embedding_collection_name()
            == "think_tank_kb__openrouter-openai-text-embedding-3-small"
        )

    def test_changes_with_provider(self) -> None:
        assert (
            llm.embedding_collection_name(provider="mistral")
            == "think_tank_kb__mistral-mistral-embed"
        )

    def test_slugifies_model_names(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_EMBEDDING_MODEL", "Some/Weird:Model v2")
        assert llm.embedding_collection_name().endswith("__openrouter-some-weird-model-v2")


class TestMissingCredentials:
    def test_empty_when_required_keys_present(self) -> None:
        assert llm.missing_credentials() == []

    def test_reports_chat_key(self, clean_env) -> None:
        clean_env.delenv("OLLAMA_CLOUD_API_KEY")
        assert llm.missing_credentials() == ["OLLAMA_CLOUD_API_KEY"]

    def test_reports_embedding_key(self, clean_env) -> None:
        clean_env.delenv("OPENROUTER_API_KEY")
        assert llm.missing_credentials() == ["OPENROUTER_API_KEY"]

    def test_requires_both_default_keys(self, clean_env) -> None:
        clean_env.delenv("OLLAMA_CLOUD_API_KEY")
        clean_env.delenv("OPENROUTER_API_KEY")
        assert llm.missing_credentials() == ["OLLAMA_CLOUD_API_KEY", "OPENROUTER_API_KEY"]

    def test_reports_per_agent_override_key(self, clean_env) -> None:
        clean_env.delenv("ZAI_API_KEY")
        clean_env.setenv("THINK_TANK_VISIONARY_PROVIDER", "zai")
        assert llm.missing_credentials() == ["ZAI_API_KEY"]

    def test_does_not_duplicate_shared_keys(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_SKEPTIC_PROVIDER", "ollama_cloud")
        assert llm.missing_credentials() == []


class TestStructuredOutput:
    def test_uses_json_schema_for_mistral(self, clean_env) -> None:
        from langchain_core.runnables import Runnable

        from think_tank.schemas import SkepticOutput

        clean_env.setenv("THINK_TANK_PROVIDER", "mistral")
        assert isinstance(llm.agent_structured_llm("skeptic", {}, SkepticOutput), Runnable)

    def test_uses_function_calling_for_deepseek_flash(self) -> None:
        assert llm.PROVIDERS["ollama_cloud"].structured_output_method == "function_calling"
        assert llm.PROVIDERS["opencode"].structured_output_method == "function_calling"

    @pytest.mark.parametrize("agent", llm.AGENT_NAMES)
    def test_builds_for_every_agent(self, agent: str) -> None:
        from think_tank.schemas import Claim

        assert llm.agent_structured_llm(agent, {}, Claim, temperature=0.4) is not None

    def test_provider_without_chat_is_rejected(self, clean_env) -> None:
        from think_tank.schemas import Claim

        clean_env.setenv("THINK_TANK_PROVIDER", "openrouter")
        with pytest.raises(ValueError, match="reserved for embeddings"):
            llm.agent_structured_llm("researcher", {}, Claim)


class TestStructuredRetry:
    """Weak tool-call emissions must be retried, not crash a graph node."""

    def test_retries_until_a_parsed_result_appears(self, monkeypatch) -> None:
        calls = {"n": 0}

        class FakeBound:
            def invoke(self, messages, **kwargs):
                calls["n"] += 1
                return {
                    "parsed": "value" if calls["n"] == 3 else None,
                    "parsing_error": RuntimeError("empty tool call"),
                    "raw": None,
                }

        monkeypatch.setattr(
            llm.ChatOpenAI, "with_structured_output", lambda self, schema, **kw: FakeBound()
        )
        from think_tank.schemas import Claim

        assert llm.agent_structured_llm("skeptic", {}, Claim).invoke("prompt") == "value"
        assert calls["n"] == 3

    def test_gives_up_after_the_retry_budget(self, monkeypatch) -> None:
        calls = {"n": 0}

        class FakeBound:
            def invoke(self, messages, **kwargs):
                calls["n"] += 1
                return {
                    "parsed": None,
                    "parsing_error": RuntimeError("empty tool call"),
                    "raw": None,
                }

        monkeypatch.setattr(
            llm.ChatOpenAI, "with_structured_output", lambda self, schema, **kw: FakeBound()
        )
        from think_tank.schemas import Claim

        with pytest.raises(RuntimeError, match="did not return valid Claim"):
            llm.agent_structured_llm("skeptic", {}, Claim).invoke("prompt")
        assert calls["n"] == llm.STRUCTURED_RETRIES

    def test_returns_first_parsed_result_without_extra_calls(self, monkeypatch) -> None:
        calls = {"n": 0}

        class FakeBound:
            def invoke(self, messages, **kwargs):
                calls["n"] += 1
                return {"parsed": "first", "parsing_error": None, "raw": None}

        monkeypatch.setattr(
            llm.ChatOpenAI, "with_structured_output", lambda self, schema, **kw: FakeBound()
        )
        from think_tank.schemas import Claim

        assert llm.agent_structured_llm("skeptic", {}, Claim).invoke("prompt") == "first"
        assert calls["n"] == 1


class TestProviderHeaderWiring:
    """Provider headers must reach the clients, not just the Provider record."""

    def test_embeddings_carry_openrouter_headers(self, clean_env) -> None:
        clean_env.setenv("OPENROUTER_APP_TITLE", "Think Tank")
        clean_env.setenv("OPENROUTER_APP_URL", "https://example.test")
        assert llm.get_embeddings().default_headers == {
            "HTTP-Referer": "https://example.test",
            "X-Title": "Think Tank",
        }

    def test_no_headers_without_attribution_env(self) -> None:
        assert llm.get_embeddings().default_headers is None


class TestModelProviderPairing:
    """A global model name must never be sent to an overridden provider."""

    def test_global_model_does_not_leak_into_an_overridden_provider(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_CHAT_MODEL", "deepseek-v4.1-flash")
        model = llm.agent_chat_model("skeptic", {"skeptic_provider": "mistral"})
        assert model.model_name == "mistral-small-latest"
        assert str(model.openai_api_base) == llm.PROVIDERS["mistral"].base_url

    def test_global_model_still_applies_without_an_override(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_CHAT_MODEL", "glm-5.3")
        assert llm.agent_chat_model("skeptic", {}).model_name == "glm-5.3"

    def test_explicit_agent_model_wins_over_the_provider_default(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_CHAT_MODEL", "deepseek-v4.1-flash")
        model = llm.agent_chat_model(
            "skeptic", {"skeptic_provider": "mistral", "skeptic_model": "mistral-large-latest"}
        )
        assert model.model_name == "mistral-large-latest"


class TestReasoningEffort:
    """`reasoning_effort` must only be sent to providers that accept it.

    Mistral answers 400 "reasoning_effort is not enabled for this model", so a
    global default would break every non-Ollama provider.
    """

    def test_only_ollama_cloud_opts_in(self) -> None:
        assert {n for n, p in llm.PROVIDERS.items() if p.reasoning_effort} == {"ollama_cloud"}

    def test_mistral_client_omits_the_parameter(self) -> None:
        assert llm.get_chat_model(provider="mistral").reasoning_effort is None

    def test_ollama_client_sends_none_effort(self) -> None:
        assert llm.get_chat_model(provider="ollama_cloud").reasoning_effort == "none"

    def test_env_override_does_not_leak_to_unsupported_providers(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_REASONING_EFFORT", "low")
        assert llm.get_chat_model(provider="mistral").reasoning_effort is None
        assert llm.get_chat_model(provider="ollama_cloud").reasoning_effort == "low"

    def test_per_agent_override_still_applies_to_supporting_provider(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_SKEPTIC_REASONING_EFFORT", "low")
        assert llm.agent_chat_model("skeptic", {}).reasoning_effort == "low"


class TestTokenCap:
    """An unbounded completion is the dominant cost in a deliberation run."""

    def test_default_cap_is_applied(self) -> None:
        assert llm.get_chat_model().max_tokens == llm.DEFAULT_MAX_TOKENS

    def test_env_override(self, clean_env) -> None:
        clean_env.setenv("THINK_TANK_MAX_TOKENS", "250")
        assert llm.get_chat_model().max_tokens == 250

    def test_per_call_wins(self) -> None:
        assert llm.get_chat_model(max_tokens=64).max_tokens == 64


class TestTokenCapIsAGuardNotALimit:
    """A tight cap must not be introduced as a latency lever.

    Measured output on these prompts is 200-450 tokens regardless of a lower
    cap, so a small default buys nothing and can truncate a tool call on
    providers that count hidden reasoning against the max.
    """

    def test_default_cap_does_not_truncate_a_typical_structured_payload(self) -> None:
        assert llm.DEFAULT_MAX_TOKENS >= 2048
