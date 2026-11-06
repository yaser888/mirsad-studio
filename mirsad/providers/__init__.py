"""LLM provider catalog and factory."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    """Static description of a supported LLM provider."""

    id: str
    label: str
    kind: str  # "openai" (chat-completions compatible) or "anthropic"
    base_url: str
    default_model: str
    env_key: str | None
    requires_key: bool = True
    note: str = ""


PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        id="openai",
        label="OpenAI",
        kind="openai",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        env_key="OPENAI_API_KEY",
        note="Official OpenAI API.",
    ),
    "anthropic": ProviderSpec(
        id="anthropic",
        label="Anthropic",
        kind="anthropic",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-sonnet-4-20250514",
        env_key="ANTHROPIC_API_KEY",
        note="Native Anthropic Messages API (not OpenAI-compatible).",
    ),
    "openrouter": ProviderSpec(
        id="openrouter",
        label="OpenRouter",
        kind="openai",
        base_url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-4o-mini",
        env_key="OPENROUTER_API_KEY",
        note="One key for hundreds of models.",
    ),
    "deepseek": ProviderSpec(
        id="deepseek",
        label="DeepSeek",
        kind="openai",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        env_key="DEEPSEEK_API_KEY",
        note="Low-cost reasoning and chat models.",
    ),
    "groq": ProviderSpec(
        id="groq",
        label="Groq",
        kind="openai",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        env_key="GROQ_API_KEY",
        note="Very fast inference.",
    ),
    "gemini": ProviderSpec(
        id="gemini",
        label="Google Gemini (AI Studio)",
        kind="openai",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-2.0-flash",
        env_key="GEMINI_API_KEY",
        note="Free-tier models through Google AI Studio (OpenAI-compatible endpoint).",
    ),
    "huggingface": ProviderSpec(
        id="huggingface",
        label="Hugging Face (serverless)",
        kind="openai",
        base_url="https://api-inference.huggingface.co/openai/v1",
        default_model="meta-llama/Llama-3.2-3B-Instruct",
        env_key="HF_TOKEN",
        note="Free serverless inference through Hugging Face.",
    ),
    "ollama": ProviderSpec(
        id="ollama",
        label="Ollama (local)",
        kind="openai",
        base_url="http://localhost:11434/v1",
        default_model="qwen2.5:7b",
        env_key=None,
        requires_key=False,
        note="Runs locally. Start Ollama before using this provider.",
    ),
}


def get_spec(provider: str) -> ProviderSpec:
    """Return the spec for *provider* or raise a helpful error."""

    try:
        return PROVIDERS[provider.lower().strip()]
    except KeyError as exc:
        available = ", ".join(PROVIDERS)
        raise KeyError(
            f"Unknown provider '{provider}'. Available providers: {available}"
        ) from exc
