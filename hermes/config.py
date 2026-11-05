"""Configuration, environment loading, and app paths."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    """Raised for invalid configuration."""


APP_DIR = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
CONFIG_FILE = APP_DIR / "config.json"
ENV_FILE = APP_DIR / ".env"
SESSIONS_DIR = APP_DIR / "sessions"

DEFAULT_CONFIG: dict[str, Any] = {
    "provider": "openai",
    "model": None,
    "temperature": 0.2,
    "max_steps": 12,
    "max_history": 80,
    "auto_approve": False,
}

_ENV_TEMPLATE = """\
# Hermes Agent environment - keep this file private.
# Fill in the API key(s) for the provider(s) you use.

OPENAI_API_KEY=
ANTHROPIC_API_KEY=
OPENROUTER_API_KEY=
DEEPSEEK_API_KEY=
GROQ_API_KEY=

# Local Ollama (no key required)
# OLLAMA_BASE_URL=http://localhost:11434/v1

# Defaults
# HERMES_PROVIDER=openai
# HERMES_MODEL=gpt-4o-mini
# HERMES_TEMPERATURE=0.2
# HERMES_MAX_STEPS=12
# HERMES_MAX_HISTORY=80
# HERMES_AUTO_APPROVE=false

# Optional web search provider (DuckDuckGo is used when empty)
# TAVILY_API_KEY=
"""


@dataclass
class Settings:
    provider: str = "openai"
    model: str | None = None
    temperature: float = 0.2
    max_steps: int = 12
    max_history: int = 80
    auto_approve: bool = False
    workdir: Path = field(default_factory=Path.cwd)

    def effective_model(self, default: str) -> str:
        return (self.model or os.environ.get("HERMES_MODEL") or default).strip()


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines without overwriting existing environment vars."""

    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def bootstrap_env(cwd: Path | None = None) -> None:
    """Load project .env first, then the user-level ~/.hermes/.env."""

    candidates = [Path(cwd or Path.cwd()) / ".env", ENV_FILE]
    for path in candidates:
        load_dotenv(path)


def read_config_file() -> dict[str, Any]:
    if not CONFIG_FILE.is_file():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Could not read {CONFIG_FILE}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{CONFIG_FILE} must contain a JSON object.")
    return data


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def _as_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def load_settings(
    *,
    provider: str | None = None,
    model: str | None = None,
    workdir: str | Path | None = None,
    temperature: float | None = None,
    max_steps: int | None = None,
    max_history: int | None = None,
    auto_approve: bool | None = None,
) -> Settings:
    """Merge config file, environment variables, and explicit arguments.

    Precedence (highest first): explicit arguments > environment > config file.
    """

    data = read_config_file()

    env_provider = os.environ.get("HERMES_PROVIDER")
    env_model = os.environ.get("HERMES_MODEL")
    env_temperature = os.environ.get("HERMES_TEMPERATURE")
    env_max_steps = os.environ.get("HERMES_MAX_STEPS")
    env_max_history = os.environ.get("HERMES_MAX_HISTORY")
    env_auto = os.environ.get("HERMES_AUTO_APPROVE")

    resolved_provider = (
        provider or env_provider or data.get("provider") or DEFAULT_CONFIG["provider"]
    )
    resolved_model = model or env_model or data.get("model")
    resolved_temperature = temperature
    if resolved_temperature is None:
        resolved_temperature = _as_float(
            env_temperature if env_temperature is not None else data.get("temperature"),
            DEFAULT_CONFIG["temperature"],
            0.0,
            2.0,
        )
    else:
        resolved_temperature = _as_float(
            resolved_temperature, DEFAULT_CONFIG["temperature"], 0.0, 2.0
        )
    resolved_max_steps = max_steps
    if resolved_max_steps is None:
        resolved_max_steps = _as_int(
            env_max_steps if env_max_steps is not None else data.get("max_steps"),
            DEFAULT_CONFIG["max_steps"],
        )
    else:
        resolved_max_steps = _as_int(
            resolved_max_steps, DEFAULT_CONFIG["max_steps"], minimum=1
        )
    resolved_max_history = max_history
    if resolved_max_history is None:
        resolved_max_history = _as_int(
            env_max_history if env_max_history is not None else data.get("max_history"),
            DEFAULT_CONFIG["max_history"],
            minimum=8,
        )
    else:
        resolved_max_history = _as_int(
            resolved_max_history, DEFAULT_CONFIG["max_history"], minimum=8
        )
    resolved_auto = auto_approve
    if resolved_auto is None:
        resolved_auto = _as_bool(
            env_auto if env_auto is not None else data.get("auto_approve"),
            DEFAULT_CONFIG["auto_approve"],
        )

    resolved_workdir = Path(workdir or data.get("workdir") or Path.cwd()).expanduser()
    if not resolved_workdir.is_absolute():
        resolved_workdir = (Path.cwd() / resolved_workdir).resolve()
    if not resolved_workdir.is_dir():
        raise ConfigError(f"Work directory does not exist: {resolved_workdir}")

    return Settings(
        provider=str(resolved_provider).lower().strip(),
        model=str(resolved_model).strip() if resolved_model else None,
        temperature=float(resolved_temperature),
        max_steps=int(resolved_max_steps),
        max_history=int(resolved_max_history),
        auto_approve=bool(resolved_auto),
        workdir=resolved_workdir,
    )


def init_app(force: bool = False) -> list[str]:
    """Create the app directory, config template, and env template.

    Returns human-readable lines describing what happened.
    """

    messages: list[str] = []
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    if CONFIG_FILE.exists() and not force:
        messages.append(f"Config already exists: {CONFIG_FILE}")
    else:
        CONFIG_FILE.write_text(
            json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8"
        )
        messages.append(f"Created config: {CONFIG_FILE}")

    if ENV_FILE.exists():
        messages.append(f"Env file already exists (left unchanged): {ENV_FILE}")
    else:
        ENV_FILE.write_text(_ENV_TEMPLATE, encoding="utf-8")
        messages.append(f"Created env template: {ENV_FILE}")

    messages.append(f"Sessions directory: {SESSIONS_DIR}")
    return messages


def mask_secret(value: str | None) -> str:
    if not value:
        return "not set"
    if len(value) <= 8:
        return "set (****)"
    return f"set (****{value[-4:]})"
