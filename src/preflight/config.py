"""Runtime configuration: credentials, provider selection, and budgets.

Everything the agent reads from the environment is resolved here, once, so that
`llm_eval.py` contains judgment logic and not credential archaeology.

Env files are loaded from the working directory and then the project root, so
`python cli.py audit ...` picks up a key regardless of where it is run from.
Within a directory, `.env.local` beats `.env` - the widespread convention where
`.local` is the machine-specific, never-committed override.

Real environment variables always win over any file: a key exported in a shell
or injected by CI is deliberate, and a stale file should never shadow it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Provider -> the environment variables that hold its key, in priority order.
KEY_VARS: dict[str, tuple[str, ...]] = {
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
}

DEFAULT_MODELS: dict[str, str] = {
    # Flash-Lite, not Flash: Module B judges prominence and tone over a few
    # hundred tokens, where latency buys more product quality than reasoning
    # depth does. Measured 2026-08-26 - flash-lite 2036ms and available,
    # gemini-3.7-flash 3502ms when healthy but returning 503 "high demand" under
    # load. A default has to work. See docs/PRODUCT_DECISIONS.md D5/D17/D20.
    "gemini": "gemini-3.5-flash-lite",
    "anthropic": "claude-haiku-4-5",
}

#: MINIMAL | LOW | MEDIUM | HIGH. Gemini 3.x Flash defaults to MEDIUM, which
#: spends latency on a judgment this size does not need.
#:
#: MINIMAL is rejected by gemini-3.7-flash with a 400 ("Thinking level MINIMAL is
#: not supported for this model") and is only available on the flash-lite tier,
#: so LOW is the floor for the default model.
DEFAULT_THINKING_LEVEL = "LOW"


#: Searched in order; the first file to define a variable wins, because
#: `load_dotenv(override=False)` will not overwrite what is already set.
ENV_FILENAMES = (".env.local", ".env")


def env_file_candidates() -> list[Path]:
    seen: list[Path] = []
    for directory in (Path.cwd(), PROJECT_ROOT):
        for name in ENV_FILENAMES:
            candidate = directory / name
            if candidate not in seen:
                seen.append(candidate)
    return seen


@lru_cache(maxsize=1)
def load_env() -> None:
    """Load env files once per process. Existing env vars are never overridden."""
    for candidate in env_file_candidates():
        if candidate.is_file():
            load_dotenv(candidate, override=False)


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    thinking_level: str
    budget: float
    deep_budget: float
    api_key: str | None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def missing_key_hint(self) -> str:
        return f"no {KEY_VARS[self.provider][0]}"


def resolve(deep: bool = False) -> LLMConfig:
    """Build the active LLM configuration from the environment."""
    load_env()
    provider = os.environ.get("PREFLIGHT_PROVIDER", "gemini").strip().lower()
    if provider not in KEY_VARS:
        known = ", ".join(sorted(KEY_VARS))
        raise ValueError(f"Unknown PREFLIGHT_PROVIDER {provider!r}. Expected one of: {known}.")

    api_key = next(
        (os.environ[var] for var in KEY_VARS[provider] if os.environ.get(var, "").strip()),
        None,
    )
    return LLMConfig(
        provider=provider,
        model=os.environ.get("PREFLIGHT_MODEL", "").strip() or DEFAULT_MODELS[provider],
        thinking_level=(
            os.environ.get("PREFLIGHT_THINKING_LEVEL", "").strip().upper()
            or DEFAULT_THINKING_LEVEL
        ),
        budget=float(os.environ.get("PREFLIGHT_LLM_BUDGET", "6.0")),
        deep_budget=float(os.environ.get("PREFLIGHT_LLM_TIMEOUT", "20.0")),
        api_key=api_key,
    )
