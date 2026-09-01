"""Provider selection, credential resolution, and .env loading."""

import pytest

from preflight.config import DEFAULT_MODELS, KEY_VARS, LLMConfig, load_env, resolve

ALL_KEY_VARS = [var for vars_ in KEY_VARS.values() for var in vars_]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Every test starts from a known-empty environment."""
    load_env.cache_clear()
    for var in [*ALL_KEY_VARS, "PREFLIGHT_PROVIDER", "PREFLIGHT_MODEL",
                "PREFLIGHT_THINKING_LEVEL", "PREFLIGHT_LLM_BUDGET", "PREFLIGHT_LLM_TIMEOUT"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("preflight.config.PROJECT_ROOT", __import__("pathlib").Path("/nonexistent"))
    monkeypatch.chdir("/")
    yield
    load_env.cache_clear()


def test_gemini_is_the_default_provider():
    config = resolve()
    assert config.provider == "gemini"
    assert config.model == "gemini-3.5-flash-lite"


def test_thinking_level_defaults_to_low_not_the_model_default():
    """Gemini 3.x Flash defaults to MEDIUM; the SLA cannot afford it."""
    assert resolve().thinking_level == "LOW"


def test_reviewer_budget_allows_a_real_call_to_finish():
    """Measured: 3502ms for the default model, 2036ms for flash-lite (D18).
    A budget under those numbers means Module B never runs at all."""
    assert resolve().budget * 1000 > 3502


@pytest.mark.parametrize("var", ["GEMINI_API_KEY", "GOOGLE_API_KEY"])
def test_either_google_key_name_works(monkeypatch, var):
    monkeypatch.setenv(var, "k")
    assert resolve().configured is True


def test_gemini_key_wins_over_google_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "google")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini")
    assert resolve().api_key == "gemini"


def test_blank_key_is_not_a_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    config = resolve()
    assert config.configured is False
    assert config.missing_key_hint == "no GEMINI_API_KEY"


def test_anthropic_provider_selects_its_own_model_and_key(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    config = resolve()
    assert config.model == DEFAULT_MODELS["anthropic"]
    assert config.api_key == "k"


def test_a_gemini_key_does_not_satisfy_the_anthropic_provider(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_PROVIDER", "anthropic")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert resolve().configured is False


def test_model_override_applies_to_any_provider(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_MODEL", "gemini-3.5-flash-lite")
    assert resolve().model == "gemini-3.5-flash-lite"


@pytest.mark.parametrize("given,expected", [("low", "LOW"), (" high ", "HIGH"), ("MINIMAL", "MINIMAL")])
def test_thinking_level_is_normalized(monkeypatch, given, expected):
    monkeypatch.setenv("PREFLIGHT_THINKING_LEVEL", given)
    assert resolve().thinking_level == expected


def test_unknown_provider_is_rejected_with_a_useful_message(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_PROVIDER", "openai")
    with pytest.raises(ValueError, match="gemini"):
        resolve()


def test_provider_name_is_case_and_space_insensitive(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_PROVIDER", "  GEMINI ")
    assert resolve().provider == "gemini"


def test_dotenv_file_is_loaded(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text('GEMINI_API_KEY="from-file"\n# a comment\n')
    monkeypatch.chdir(tmp_path)
    load_env.cache_clear()
    assert resolve().api_key == "from-file"


def test_real_environment_beats_the_dotenv_file(monkeypatch, tmp_path):
    """A key exported in the shell or injected by CI is deliberate."""
    (tmp_path / ".env").write_text("GEMINI_API_KEY=from-file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "from-shell")
    load_env.cache_clear()
    assert resolve().api_key == "from-shell"


def test_config_is_frozen():
    with pytest.raises(Exception):
        resolve().model = "other"


def test_deep_budget_exceeds_the_interactive_budget():
    config = resolve()
    assert config.deep_budget > config.budget


@pytest.mark.parametrize("filename", [".env", ".env.local"])
def test_both_env_filenames_are_honored(monkeypatch, tmp_path, filename):
    """`.env.local` is the common machine-specific convention; support it."""
    (tmp_path / filename).write_text("GEMINI_API_KEY=from-file\n")
    monkeypatch.chdir(tmp_path)
    load_env.cache_clear()
    assert resolve().api_key == "from-file"


def test_env_local_takes_precedence_over_env(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=shared\n")
    (tmp_path / ".env.local").write_text("GEMINI_API_KEY=machine-specific\n")
    monkeypatch.chdir(tmp_path)
    load_env.cache_clear()
    assert resolve().api_key == "machine-specific"


def test_every_env_filename_is_gitignored():
    """A file that holds a real key must never be committable."""
    from pathlib import Path

    from preflight.config import ENV_FILENAMES

    # Not config.PROJECT_ROOT - the autouse fixture repoints it at /nonexistent.
    repo_root = Path(__file__).resolve().parents[1]
    ignored = (repo_root / ".gitignore").read_text().split()
    for name in ENV_FILENAMES:
        assert name in ignored, f"{name} is not gitignored"
