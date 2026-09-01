"""Orchestration: run the cheap engine first, then the expensive ones in parallel.

Phase order is the architecture in one function - deterministic parsing and math
run to completion before any network or token spend, and the two slow phases
(link probing, LLM assessment) then overlap so the wall clock is max(), not sum().
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from .checks import deterministic, links as links_mod, llm_eval
from .config import resolve as llm_config
from .models import SEVERITY_RANK, AuditReport, Finding, Timing
from . import monitor
from .parser import load

def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Report order: what will break first, then by module and source line."""
    return sorted(
        findings,
        key=lambda f: (SEVERITY_RANK[f.severity], f.module != "deterministic",
                       f.line if f.line is not None else 10**6, f.code),
    )


async def audit_html(
    html: str,
    path: str = "<memory>",
    *,
    offline_links: dict | None = None,
    llm_fixture: str | Path | None = None,
    skip_llm: bool = False,
    link_budget: float = links_mod.PHASE_BUDGET,
    deep: bool = False,
    monitor_source: str | None = None,
    subject: str = "",
    preheader: str = "",
) -> AuditReport:
    total_start = time.perf_counter()

    det_start = time.perf_counter()
    soup, sheet = load(html)
    findings = deterministic.run_all(soup, sheet, html, subject, preheader)
    stats = deterministic.document_stats(soup, sheet)
    det_ms = (time.perf_counter() - det_start) * 1000

    async def _links() -> tuple[list[Finding], float]:
        # Timed inside the coroutine: the two phases overlap, so measuring
        # around the gather would report each one's wall clock as both.
        started = time.perf_counter()
        found = await links_mod.check_links(soup, offline=offline_links, budget=link_budget)
        return found, (time.perf_counter() - started) * 1000

    async def _llm() -> tuple[list[Finding], str, float]:
        if skip_llm:
            # Both --no-llm and --offline land here, so name the state
            # rather than a flag that may not be the one that was passed.
            return [], "skipped: reviewer not run", 0.0
        config = llm_config()
        budget = config.deep_budget if deep else config.budget
        return await llm_eval.assess(soup, stats, fixture=llm_fixture, budget=budget)

    (link_findings, link_ms), (llm_findings, llm_status, llm_ms) = await asyncio.gather(
        _links(), _llm()
    )

    findings.extend(link_findings)
    findings.extend(llm_findings)
    total_ms = (time.perf_counter() - total_start) * 1000

    report = AuditReport(
        path=path,
        findings=sort_findings(findings),
        timing=Timing(
            deterministic_ms=round(det_ms, 2),
            links_ms=round(link_ms, 2),
            llm_ms=round(llm_ms, 2),
            total_ms=round(total_ms, 2),
        ),
        llm_status=llm_status,
        stats=stats,
    )
    if monitor_source is not None:
        # Opt-in and failure-proof: `record` is a no-op unless PREFLIGHT_MONITOR
        # is set, and swallows its own I/O errors. The benchmark passes None so
        # a scored run never writes telemetry.
        monitor.record(report, html, source=monitor_source)
    return report


async def audit_file(path: str | Path, **kwargs) -> AuditReport:
    p = Path(path)
    return await audit_html(p.read_text(), path=str(p), **kwargs)


def audit_file_sync(path: str | Path, **kwargs) -> AuditReport:
    return asyncio.run(audit_file(path, **kwargs))
