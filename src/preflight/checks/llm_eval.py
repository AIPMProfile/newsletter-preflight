"""Module B - the LLM visual & intent assessor.

Scope discipline: this module is only allowed to judge things a parser cannot -
whether the call to action reads as prominent, whether the copy trips human or
filter intuitions about spam, whether the email is cognitively easy to act on.
Counting links, measuring contrast, and resolving colors already happened in
Module A, and their results are handed to the model as *evidence* so it never
re-derives (or contradicts) arithmetic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import Literal

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from ..config import LLMConfig, resolve
from ..models import Finding, Severity

MAX_DIGEST_CHARS = 6000
MAX_OUTPUT_TOKENS = 2000
#: The Gemini API rejects transport deadlines below this with a 400.
MIN_SERVER_DEADLINE_S = 10.0
#: Transient server-side capacity. 429 is deliberately absent: quota does not
#: heal in 200ms, and retrying it just spends the budget before reporting it.
RETRYABLE_STATUSES = (500, 502, 503, 504)

LLMCode = Literal[
    "cta.buried",
    "cta.weak_prominence",
    "spam.trigger_phrase",
    "copy.cognitive_friction",
]


class LLMFinding(BaseModel):
    code: LLMCode = Field(description="Which judgment this is.")
    target: str = Field(
        description="The `id` attribute of the element at fault, exactly as it "
        "appears in the digest, or 'document' for whole-email judgments."
    )
    severity: Literal["will_break", "will_embarrass", "could_be_better"]
    message: str = Field(
        description="One sentence naming what this costs the creator, in their "
                    "words. No jargon, no measurements, no element names."
    )
    detail: str = Field(
        default="",
        description="The reasoning behind the message, for a creator who wants to "
                    "know why. Optional, and never a restatement of the message.",
    )
    remedy: str = Field(description="One concrete change to make.")
    quote: str = Field(default="", description="The offending copy, verbatim, if any.")


class LLMAssessment(BaseModel):
    cta_summary: str = Field(description="One line on the primary CTA and its prominence.")
    findings: list[LLMFinding] = Field(default_factory=list)


SYSTEM_PROMPT = """You are the visual-and-intent reviewer inside a pre-send newsletter audit tool.

A deterministic engine has ALREADY measured contrast ratios, link counts, word counts, image counts, and alt text. Never re-report those - they are given to you only as context.

Judge exactly four things:
1. cta.buried - the primary call to action sits below the fold or after long copy the reader must wade through. The digest marks the estimated fold.
2. cta.weak_prominence - the CTA exists near the top but does not read as a button: no visual isolation, no weight, competing with neighbouring links.
3. spam.trigger_phrase - copy that inbox filters and readers both punish: urgency screaming, ALL CAPS, excess punctuation, money/guarantee/risk-free claims, "click here now".
4. copy.cognitive_friction - the reader cannot tell what this email wants from them, or is asked to make several decisions at once. Severity could_be_better unless it is genuinely disorienting.

Rules:
- Report only what is actually there. A clean, well-built email must return an empty findings list. False positives cost the creator trust in the tool.
- `target` must be an `id` from the digest, or `document`.
- Severity names what it costs the creator, not how serious it sounds:
  - `will_break` - a subscriber cannot act on this email at all. Rare for the judgments you make; prefer the tier below.
  - `will_embarrass` - it sends and it works, but it costs them: a CTA the reader will plausibly never see, or overt spam-trigger copy that risks the promotions tab.
  - `could_be_better` - polish. Never blocks a send. Use this when in doubt.
- At most 6 findings. One finding per distinct problem."""


def build_digest(soup: BeautifulSoup, stats: dict) -> str:
    """A compact, id-anchored linearization of the email.

    We send structure and copy, not markup: the model does not need the
    creator's table scaffolding, and stripping it cuts tokens ~5x while
    keeping every anchor the findings must point at.
    """
    body = soup.body or soup
    lines: list[str] = []
    chars = 0
    fold_marked = False
    for tag in body.find_all(
        ["h1", "h2", "h3", "h4", "p", "a", "li", "img", "button", "td", "blockquote"]
    ):
        text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
        if tag.name == "img":
            desc = f'IMG alt="{tag.get("alt") or ""}"'
        elif not text:
            continue
        elif tag.name == "td" and tag.find(["p", "h1", "h2", "h3", "a"]):
            continue  # a layout cell; its children are described on their own
        elif tag.name == "a":
            desc = f'LINK "{text[:90]}" -> {(tag.get("href") or "")[:60]}'
        else:
            desc = f"{tag.name.upper()} {text[:220]}"
        ident = tag.get("id") or "-"
        style = (tag.get("style") or "").replace("\n", " ")[:110]
        lines.append(f"[id={ident}] {desc}" + (f"  |style: {style}" if style else ""))
        chars += 600  # rough px of vertical rhythm per block
        if not fold_marked and chars > 3000:
            lines.append("--- estimated fold (most readers stop scrolling near here) ---")
            fold_marked = True
    digest = "\n".join(lines)[:MAX_DIGEST_CHARS]
    evidence = json.dumps(
        {k: stats[k] for k in ("words", "links", "images") if k in stats}, sort_keys=True
    )
    return f"MEASURED (do not re-report): {evidence}\n\nEMAIL DIGEST:\n{digest}"


def _to_findings(assessment: LLMAssessment) -> list[Finding]:
    out: list[Finding] = []
    for item in assessment.findings:
        out.append(Finding(
            code=item.code,
            module="llm",
            severity=Severity(item.severity),
            detail=item.detail,
            target=item.target or "document",
            message=item.message,
            remedy=item.remedy,
            evidence={"quote": item.quote} if item.quote else {},
        ))
    return out


def load_fixture(path: str | Path) -> list[Finding]:
    """Replay a recorded assessment - the offline path for evals and CI."""
    data = json.loads(Path(path).read_text())
    return _to_findings(LLMAssessment.model_validate(data))


async def _call_gemini(digest: str, config: LLMConfig) -> LLMAssessment | None:
    """Structured JSON via `response_schema`; `.parsed` is a validated model.

    `thinking_level` is the lever that makes a Flash model fit the budget:
    Gemini 3.x Flash defaults to MEDIUM, which spends latency on a judgment
    this size does not need. It stays configurable so `eval --live` can measure
    that claim instead of us asserting it.
    """
    from google import genai
    from google.genai import types

    # The SDK warns that automatic function calling is better used via Chat.
    # We declare no tools, so AFC never engages - the warning is pure noise in
    # a report a creator reads, and stderr is part of that report's surface.
    logging.getLogger("google_genai.models").setLevel(logging.ERROR)

    # Retry transient capacity (5xx), never quota. The SDK retries every
    # retryable status by default, which turns a 429 into silence until
    # `wait_for` fires - "exceeded 6.0s budget" sends the user chasing latency
    # when the real problem is quota. A 503 "high demand", by contrast, is worth
    # exactly one more attempt.
    #
    # The transport deadline is floored at MIN_SERVER_DEADLINE_S because the API
    # rejects anything shorter with a 400 ("Manually set deadline 6s is too
    # short"). Our real budget stays client-side in `wait_for`, so a budget under
    # 10s is still enforced - just by us rather than by the server.
    client = genai.Client(
        api_key=config.api_key,
        http_options=types.HttpOptions(
            timeout=int(max(config.budget, MIN_SERVER_DEADLINE_S) * 1000),
            retry_options=types.HttpRetryOptions(
                attempts=2, http_status_codes=list(RETRYABLE_STATUSES)
            ),
        ),
    )
    response = await client.aio.models.generate_content(
        model=config.model,
        contents=digest,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=LLMAssessment,
            thinking_config=types.ThinkingConfig(thinking_level=config.thinking_level),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.0,
        ),
    )
    parsed = response.parsed
    if isinstance(parsed, LLMAssessment):
        return parsed
    if isinstance(parsed, dict):
        return LLMAssessment.model_validate(parsed)
    return None


async def _call_anthropic(digest: str, config: LLMConfig) -> LLMAssessment | None:
    """Kept alongside Gemini so `eval --live` can compare providers on one
    corpus. Install with `pip install -e ".[anthropic]"`."""
    import anthropic

    client = anthropic.AsyncAnthropic(
        api_key=config.api_key, timeout=config.budget, max_retries=0
    )
    response = await client.messages.parse(
        model=config.model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": digest}],
        output_format=LLMAssessment,
    )
    return response.parsed_output


_PROVIDERS = {"gemini": _call_gemini, "anthropic": _call_anthropic}


def _degradation_reason(exc: BaseException, config: LLMConfig) -> str:
    """Turn a provider exception into something a creator can act on."""
    if isinstance(exc, asyncio.TimeoutError):
        return f"exceeded {config.budget:.1f}s budget - rerun with --deep"
    if isinstance(exc, ImportError):
        return f"{config.provider} sdk not installed"
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "api key" in text or "api_key" in text or "unauthenticated" in text or "authentication" in name:
        return config.missing_key_hint
    if "permission" in text or "403" in text:
        return f"{config.provider} rejected the key (permission denied)"
    if "not found" in text or "404" in text:
        return f"model {config.model!r} not available to this key"
    if "resource_exhausted" in text or "429" in text or "rate limit" in text:
        return f"{config.provider} rate limited - free tier allows 5 req/min per model"
    if "503" in text or "unavailable" in text or "high demand" in text:
        return f"{config.model} is busy right now (503) - try PREFLIGHT_MODEL=gemini-3.5-flash-lite"
    if "timeout" in name:
        return f"exceeded {config.budget:.1f}s budget - rerun with --deep"
    # Unrecognized: carry the provider's own words through. "ClientError" alone
    # tells a user nothing, and this is the line they will paste into a search.
    detail = " ".join(str(exc).split())[:120]
    return f"{config.provider}: {detail}" if detail else f"{config.provider}: {type(exc).__name__}"


async def assess(
    soup: BeautifulSoup,
    stats: dict,
    fixture: str | Path | None = None,
    budget: float | None = None,
    config: LLMConfig | None = None,
) -> tuple[list[Finding], str, float]:
    """Returns (findings, status, elapsed_ms).

    Status is one of `ok`, `replayed`, `skipped: <reason>`. A missing key or a
    slow API degrades the report; it never fails the audit, because a creator
    with a broken link still deserves to hear about the broken link.
    """
    started = time.perf_counter()

    def elapsed_ms() -> float:
        return (time.perf_counter() - started) * 1000

    if fixture is not None:
        return load_fixture(fixture), "replayed", elapsed_ms()

    try:
        config = config or resolve()
    except ValueError as exc:
        return [], f"skipped: {exc}", elapsed_ms()
    if budget is not None:
        config = replace(config, budget=budget)

    if not config.configured:
        # Checked before dispatch so the common case costs no import and no
        # socket - and so the hint names the variable the user actually needs.
        return [], f"skipped: {config.missing_key_hint}", elapsed_ms()

    try:
        parsed = await asyncio.wait_for(
            _PROVIDERS[config.provider](build_digest(soup, stats), config),
            timeout=config.budget,
        )
    except Exception as exc:  # noqa: BLE001 - degradation is the contract here
        return [], f"skipped: {_degradation_reason(exc, config)}", elapsed_ms()

    if parsed is None:
        return [], "skipped: model returned no structured output", elapsed_ms()
    return _to_findings(parsed), "ok", elapsed_ms()


def record_fixture(soup: BeautifulSoup, stats: dict, out_path: Path) -> str:
    """Capture a live assessment to disk so evals can replay it. Used by
    `python cli.py eval --record`."""
    findings, status, _ = asyncio.run(assess(soup, stats))
    payload = LLMAssessment(
        cta_summary="recorded",
        findings=[
            LLMFinding(
                code=f.code,  # type: ignore[arg-type]
                target=f.target,
                severity=f.severity.value,  # type: ignore[arg-type]
                message=f.message,
                remedy=f.remedy,
                quote=f.evidence.get("quote", ""),
            )
            for f in findings
        ],
    )
    out_path.write_text(json.dumps(payload.model_dump(), indent=2) + "\n")
    return status
