"""Module B: prompt construction, structured parsing, and graceful degradation.

No network in these tests - the API path is exercised by `eval --live`.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from preflight.checks.deterministic import document_stats
from preflight.checks.llm_eval import (
    LLMAssessment,
    assess,
    build_digest,
    load_fixture,
)
from preflight.config import LLMConfig, load_env
from preflight.evals.harness import FIXTURES_DIR
from preflight.models import Severity
from preflight.parser import load

HTML = ("<body><h1 id='h'>Big news</h1><p id='p'>Some copy {{ subscriber.first_name }}</p>"
        "<a id='c' href='https://wren.email/x'>Read it</a><img id='i' src='a.png' alt='A desk'></body>")


def _digest():
    soup, sheet = load(HTML)
    return build_digest(soup, document_stats(soup, sheet)), soup, sheet


def test_digest_anchors_every_line_to_an_id():
    digest, _, _ = _digest()
    for line in digest.splitlines():
        if line.startswith("["):
            assert line.startswith("[id=")


def test_digest_carries_deterministic_evidence_so_the_model_never_recounts():
    digest, _, _ = _digest()
    measured = json.loads(digest.splitlines()[0].split("MEASURED (do not re-report): ")[1])
    assert measured == {"images": 1, "links": 1, "words": 6}


def test_digest_omits_markup_but_keeps_copy_and_hrefs():
    digest, _, _ = _digest()
    assert "<body>" not in digest and "<h1" not in digest
    assert "Big news" in digest
    assert "https://wren.email/x" in digest


def test_digest_marks_the_fold_on_long_emails():
    body = "".join(f"<p id='p{i}'>{'word ' * 40}</p>" for i in range(12))
    soup, sheet = load(f"<body>{body}</body>")
    assert "estimated fold" in build_digest(soup, document_stats(soup, sheet))


def test_digest_is_bounded():
    body = "".join(f"<p id='p{i}'>{'word ' * 200}</p>" for i in range(200))
    soup, sheet = load(f"<body>{body}</body>")
    assert len(build_digest(soup, document_stats(soup, sheet))) < 7000


async def test_missing_credentials_degrade_rather_than_fail(monkeypatch):
    monkeypatch.setattr("preflight.config.PROJECT_ROOT", Path("/nonexistent"))
    monkeypatch.chdir("/")
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    load_env.cache_clear()
    soup, sheet = load(HTML)
    findings, status, elapsed = await assess(soup, document_stats(soup, sheet), budget=0.5)
    assert findings == []
    assert status == "skipped: no GEMINI_API_KEY"
    assert elapsed < 200, "the no-key path must not open a socket"
    load_env.cache_clear()


async def test_unknown_provider_degrades_instead_of_raising(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_PROVIDER", "openai")
    soup, sheet = load(HTML)
    findings, status, _ = await assess(soup, document_stats(soup, sheet))
    assert findings == []
    assert "Unknown PREFLIGHT_PROVIDER" in status


async def test_gemini_request_is_built_from_the_resolved_config(monkeypatch):
    """Pins the request shape: model, schema, thinking level, system prompt."""
    captured = {}

    async def fake_generate_content(*, model, contents, config):
        captured.update(model=model, contents=contents, config=config)
        return SimpleNamespace(parsed=LLMAssessment(cta_summary="s", findings=[]))

    import google.genai as genai
    monkeypatch.setattr(
        genai.Client, "aio",
        property(lambda self: SimpleNamespace(
            models=SimpleNamespace(generate_content=fake_generate_content))),
    )
    soup, sheet = load(HTML)
    config = LLMConfig(provider="gemini", model="gemini-3.7-flash", thinking_level="LOW",
                       budget=5.0, deep_budget=20.0, api_key="k")
    findings, status, _ = await assess(soup, document_stats(soup, sheet), config=config)

    assert status == "ok" and findings == []
    assert captured["model"] == "gemini-3.7-flash"
    assert captured["config"].response_schema is LLMAssessment
    assert captured["config"].response_mime_type == "application/json"
    assert captured["config"].thinking_config.thinking_level.value == "LOW"
    assert "ALREADY measured" in captured["config"].system_instruction
    assert "MEASURED (do not re-report)" in captured["contents"]


async def test_provider_errors_become_actionable_statuses(monkeypatch):
    from preflight.checks.llm_eval import _degradation_reason
    config = LLMConfig(provider="gemini", model="gemini-3.7-flash", thinking_level="LOW",
                       budget=1.6, deep_budget=20.0, api_key="k")
    assert _degradation_reason(asyncio.TimeoutError(), config).startswith("exceeded 1.6s")
    assert _degradation_reason(Exception("API key not valid"), config) == "no GEMINI_API_KEY"
    assert "not available" in _degradation_reason(Exception("404 model not found"), config)
    assert "rate limited" in _degradation_reason(Exception("429 RESOURCE_EXHAUSTED"), config)
    assert "sdk not installed" in _degradation_reason(ImportError("x"), config)


async def test_a_provider_exception_never_escapes(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setitem(
        __import__("preflight.checks.llm_eval", fromlist=["_PROVIDERS"])._PROVIDERS,
        "gemini", boom,
    )
    soup, sheet = load(HTML)
    config = LLMConfig(provider="gemini", model="m", thinking_level="LOW",
                       budget=1.0, deep_budget=5.0, api_key="k")
    findings, status, _ = await assess(soup, document_stats(soup, sheet), config=config)
    assert findings == [] and status == "skipped: gemini: provider exploded"


async def test_unrecognized_errors_carry_the_providers_own_words():
    from preflight.checks.llm_eval import _degradation_reason
    config = LLMConfig(provider="gemini", model="m", thinking_level="LOW",
                       budget=6.0, deep_budget=20.0, api_key="k")
    reason = _degradation_reason(Exception("400 INVALID_ARGUMENT. deadline too short"), config)
    assert "INVALID_ARGUMENT" in reason and "deadline too short" in reason


async def test_fixture_replay_is_deterministic():
    soup, sheet = load(HTML)
    fixture = FIXTURES_DIR / "sample_4_cta_spam.json"
    findings, status, _ = await assess(soup, document_stats(soup, sheet), fixture=fixture)
    assert status == "replayed"
    assert {f.code for f in findings} == {"spam.trigger_phrase", "cta.buried", "cta.weak_prominence"}
    assert all(f.module == "llm" for f in findings)


def test_fixtures_all_parse_against_the_schema():
    for path in FIXTURES_DIR.glob("*.json"):
        LLMAssessment.model_validate(json.loads(path.read_text()))
        load_fixture(path)


def test_fixtures_declare_provenance():
    """The benchmark must be able to say whether Module B was measured or replayed."""
    for path in FIXTURES_DIR.glob("*.json"):
        assert json.loads(path.read_text()).get("provenance") in {"authored", "recorded"}


def test_severity_maps_onto_the_shared_scale():
    findings = load_fixture(FIXTURES_DIR / "sample_5_mixed.json")
    by_code = {f.code: f for f in findings}
    assert by_code["cta.weak_prominence"].severity is Severity.WILL_EMBARRASS
    assert by_code["copy.cognitive_friction"].severity is Severity.COULD_BE_BETTER
    assert by_code["copy.cognitive_friction"].scored is False


@pytest.mark.parametrize("code", ["cta.buried", "cta.weak_prominence",
                                  "spam.trigger_phrase", "copy.cognitive_friction"])
def test_prompt_documents_every_code_it_can_emit(code):
    from preflight.checks.llm_eval import SYSTEM_PROMPT
    assert code in SYSTEM_PROMPT


def test_prompt_forbids_re_reporting_deterministic_findings():
    from preflight.checks.llm_eval import SYSTEM_PROMPT
    assert "ALREADY measured" in SYSTEM_PROMPT
    assert "empty findings list" in SYSTEM_PROMPT


async def test_gemini_retries_capacity_errors_but_never_quota(monkeypatch):
    """A 503 is worth one more attempt; a 429 must surface immediately."""
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        @property
        def aio(self):
            async def generate_content(*, model, contents, config):
                return SimpleNamespace(parsed=LLMAssessment(cta_summary="s", findings=[]))
            return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))

    import google.genai as genai
    monkeypatch.setattr(genai, "Client", FakeClient)
    soup, sheet = load(HTML)
    config = LLMConfig(provider="gemini", model="m", thinking_level="LOW",
                       budget=4.0, deep_budget=20.0, api_key="k")
    _, status, _ = await assess(soup, document_stats(soup, sheet), config=config)

    assert status == "ok"
    http = captured["http_options"]
    # Floored at the API's 10s minimum deadline; our 4s budget is enforced
    # client-side by wait_for instead.
    assert http.timeout == 10_000
    assert http.retry_options.attempts == 2
    assert 503 in http.retry_options.http_status_codes
    assert 429 not in http.retry_options.http_status_codes, "quota does not heal on retry"


async def test_transport_deadline_tracks_a_budget_above_the_floor(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        @property
        def aio(self):
            async def generate_content(*, model, contents, config):
                return SimpleNamespace(parsed=LLMAssessment(cta_summary="s", findings=[]))
            return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))

    import google.genai as genai
    monkeypatch.setattr(genai, "Client", FakeClient)
    soup, sheet = load(HTML)
    config = LLMConfig(provider="gemini", model="m", thinking_level="LOW",
                       budget=18.0, deep_budget=20.0, api_key="k")
    await assess(soup, document_stats(soup, sheet), config=config)
    assert captured["http_options"].timeout == 18_000
