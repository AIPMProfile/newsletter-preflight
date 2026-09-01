"""Asynchronous link reachability.

Network work is the one deterministic check that can blow the 2s SLA, so it
runs concurrently under a hard global budget: whatever has not answered by the
deadline is reported as `unknown`, never as broken. Telling a creator a working
link is dead is worse than saying nothing.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from ..models import Finding, Severity
from ..parser import element_path

#: Per-request ceiling. Real mail links answer well inside this.
REQUEST_TIMEOUT = 3.0
#: Whole-phase ceiling, enforced regardless of how many links there are.
PHASE_BUDGET = 1.2
MAX_CONCURRENCY = 12
USER_AGENT = "preflight-agent/0.1 (+link-check)"

_LIQUID_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)


@dataclass
class LinkResult:
    url: str
    status: int | None
    error: str | None = None

    @property
    def broken(self) -> bool:
        return self.error is not None or (self.status is not None and self.status >= 400)


#: Maps url -> status (or an error string) for reproducible, offline runs.
StatusMap = dict[str, int | str]


def collect_urls(soup: BeautifulSoup) -> dict[str, list]:
    """Group anchors by absolute http(s) URL, skipping Liquid-templated hrefs.

    A href of `{{ tracking_url }}` is not a URL yet - resolving it would mean
    guessing at merge data, so it is deliberately out of scope.
    """
    grouped: dict[str, list] = {}
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href.lower().startswith(("http://", "https://")):
            continue
        if _LIQUID_RE.search(href):
            continue
        grouped.setdefault(href, []).append(a)
    return grouped


async def _probe(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> LinkResult:
    async with sem:
        try:
            resp = await client.head(url)
            # Plenty of servers reject HEAD outright; retry those with GET
            # before calling a perfectly good link broken.
            if resp.status_code in (403, 405, 501):
                resp = await client.get(url)
            return LinkResult(url, resp.status_code)
        except httpx.TimeoutException:
            return LinkResult(url, None, "timeout")
        except httpx.HTTPError as exc:
            return LinkResult(url, None, type(exc).__name__)


async def probe_urls(urls: list[str], budget: float = PHASE_BUDGET) -> dict[str, LinkResult]:
    if not urls:
        return {}
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    results: dict[str, LinkResult] = {}
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        tasks = {asyncio.create_task(_probe(client, u, sem)): u for u in urls}
        done, pending = await asyncio.wait(tasks, timeout=budget)
        for task in done:
            res = task.result()
            results[res.url] = res
        for task in pending:
            task.cancel()
    return results


def findings_from_results(
    soup: BeautifulSoup, results: dict[str, LinkResult]
) -> list[Finding]:
    findings: list[Finding] = []
    for url, anchors in collect_urls(soup).items():
        res = results.get(url)
        if res is None or not res.broken:
            continue
        detail = res.error or f"HTTP {res.status}"
        for a in anchors:
            findings.append(Finding(
                code="link.broken",
                severity=Severity.WILL_BREAK,
                target=element_path(a),
                line=a.sourceline,
                message=(
                    f"The link \"{a.get_text(strip=True)[:40] or url[:40]}\" is dead. "
                    f"Anyone who clicks it hits an error page, and you cannot recall "
                    f"an email to fix it."
                ),
                detail=f"{url[:60]} returned {detail}.",
                remedy="Fix or remove the link before sending.",
                evidence={"url": url, "status": res.status, "error": res.error},
            ))
    return findings


async def check_links(
    soup: BeautifulSoup,
    offline: StatusMap | None = None,
    budget: float = PHASE_BUDGET,
) -> list[Finding]:
    """Live check, or a replay against a pinned status map when `offline`.

    The offline path is what makes the eval harness reproducible: benchmark
    scores must measure the agent, not today's DNS.
    """
    urls = list(collect_urls(soup))
    if offline is not None:
        results = {
            u: LinkResult(u, v if isinstance(v, int) else None, None if isinstance(v, int) else v)
            for u, v in ((u, offline.get(u, 200)) for u in urls)
        }
    else:
        results = await probe_urls(urls, budget=budget)
    return findings_from_results(soup, results)
