"""Build the right provider for the current settings."""

from __future__ import annotations

import os

from ..config import ConfigError, Settings
from . import PROVIDERS, ProviderSpec
from .anthropic import AnthropicProvider
from .base import BaseProvider, MissingAPIKey
from .openai_compat import OpenAICompatibleProvider


def resolve_spec(settings: Settings) -> ProviderSpec:
    provider = (settings.provider or "openai").lower().strip()
    if provider not in PROVIDERS:
        available = ", ".join(PROVIDERS)
        raise ConfigError(
            f"Unknown provider '{settings.provider}'. Available providers: {available}"
        )
    return PROVIDERS[provider]


def resolve_model(settings: Settings, spec: ProviderSpec) -> str:
    return (settings.model or os.environ.get("MIRSAD_MODEL") or spec.default_model).strip()


def provider_key(spec: ProviderSpec) -> str | None:
    """Return the API key for a provider, allowing a global override."""

    return os.environ.get("MIRSAD_API_KEY") or (
        os.environ.get(spec.env_key) if spec.env_key else None
    )


def create_provider(settings: Settings) -> BaseProvider:
    """Instantiate the provider named in *settings*."""

    spec = resolve_spec(settings)
    model = resolve_model(settings, spec)
    api_key = provider_key(spec)

    if spec.requires_key and not api_key:
        env_name = spec.env_key or "MIRSAD_API_KEY"
        raise MissingAPIKey(
            f"{spec.label} requires an API key. Set {env_name} in your "
            "environment or in ~/.mirsad/.env."
        )

    base_url = os.environ.get("MIRSAD_BASE_URL") or spec.base_url
    if spec.id == "ollama":
        base_url = os.environ.get("OLLAMA_BASE_URL") or base_url

    if spec.kind == "anthropic":
        return AnthropicProvider(
            model=model,
            api_key=api_key or "",
            base_url=base_url,
        )

    extra_headers: dict[str, str] = {}
    if spec.id == "openrouter":
        extra_headers = {
            "HTTP-Referer": "https://github.com/mirsad-agent",
            "X-Title": "Mirsad Agent",
        }
    return OpenAICompatibleProvider(
        name=spec.label,
        model=model,
        api_key=api_key,
        base_url=base_url,
        extra_headers=extra_headers,
    )


def key_status() -> list[tuple[ProviderSpec, bool]]:
    """Return each provider and whether its key is configured."""

    return [(spec, bool(provider_key(spec))) for spec in PROVIDERS.values()]
