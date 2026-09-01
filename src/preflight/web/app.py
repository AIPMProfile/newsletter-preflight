"""HTTP surface over the same audit engine the CLI uses.

There is exactly one implementation of every check. This module parses a
request, calls `audit_html` / `fix_document`, and serializes the result - it
contains no analysis logic of its own, because a second implementation would
drift from the one the benchmark measures.

Binds to localhost by default. The Gemini key lives in the server process and
is never sent to the browser.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import monitor
from ..audit import audit_html
from ..config import resolve
from ..fixer.autofix import apply_selected, fix_document, liquid_tokens
from ..models import SLA_MS, AuditReport
from ..parser import element_path, load

def _check_codes() -> set[str]:
    """Every check the engine can emit, read from the engine itself so the
    number a creator is shown cannot drift from what actually ran."""
    import re
    from .. import checks
    from pathlib import Path as _P
    src = "".join(p.read_text() for p in _P(checks.__file__).parent.glob("*.py"))
    from ..checks.llm_eval import LLMCode
    from typing import get_args
    return set(re.findall(r'code="([a-z_]+\.[a-z_]+)"', src)) | set(get_args(LLMCode))


CHECK_CODES = _check_codes()
MAX_HTML_BYTES = 2_000_000
PUBLISH = Path(__file__).parent / "publish.html"
EDITOR = Path(__file__).parent / "editor.html"
STARTER = Path(__file__).parent / "starter.html"
REVIEW = Path(__file__).parent / "review.html"


def _unique_selector(tag) -> str:
    """A CSS selector the canvas can resolve to exactly one element.

    Findings identify elements by `element_path`, which is built for human
    reading and is not always unique. The canvas needs to draw a box around one
    specific node, so this walks up to the nearest ancestor with an id, adding
    `:nth-of-type()` wherever a tag name repeats among its siblings.

    Descendant combinators, not child (`>`), on purpose: browsers synthesize a
    `<tbody>` that the parser never sees, so `table > tr` matches nothing in the
    live DOM - and every email is table-based. `:nth-of-type` still disambiguates
    because it is evaluated against the real parent either way.
    """
    if tag.get("id"):
        return f"#{tag['id']}"
    parts: list[str] = []
    node = tag
    while node is not None and getattr(node, "name", None) and node.name != "[document]":
        parent = node.parent
        if parent is None or not getattr(parent, "name", None) or parent.name == "[document]":
            parts.append(node.name)
            break
        siblings = parent.find_all(node.name, recursive=False)
        if len(siblings) > 1:
            # Identity, not equality: bs4 compares tags by content, so two
            # structurally identical cells would collapse to the same index.
            index = next(i for i, s in enumerate(siblings) if s is node) + 1
            parts.append(f"{node.name}:nth-of-type({index})")
        else:
            parts.append(node.name)
        if parent.get("id"):
            parts.append(f"#{parent['id']}")
            break
        node = parent
    return " ".join(reversed(parts))


def _selector_index(html: str) -> dict[str, str]:
    """Map each finding target back to a canvas-resolvable selector.

    `element_path` is deterministic, so re-running it over the same document
    recovers the element every finding came from without the engine having to
    know anything about the UI. Where a path is ambiguous the first match wins -
    the same ambiguity the finding itself carries.
    """
    soup, _ = load(html)
    index: dict[str, str] = {}
    for tag in soup.find_all(True):
        index.setdefault(element_path(tag), _unique_selector(tag))
    return index


def _report_payload(report: AuditReport, html: str | None = None) -> dict:
    selectors = _selector_index(html) if html is not None else {}
    return {
        "verdict": report.verdict,
        "blocking": len(report.blocking_findings),
        # What we looked at, not just what we found. On a clean send this is
        # the entire product: being told nothing will break by something that
        # visibly looked is the reassurance the flow does not otherwise give
        # (D39).
        "examined": {
            "checks": len(CHECK_CODES),
            "elements": report.stats.get("text_elements", 0)
                        + report.stats.get("links", 0) + report.stats.get("images", 0),
            "links": report.stats.get("links", 0),
            "images": report.stats.get("images", 0),
        },
        "llm_status": report.llm_status,
        "stats": report.stats,
        "sla_ms": SLA_MS,
        "timing": {
            **report.timing.model_dump(),
            "presend_ms": round(report.timing.presend_ms, 2),
            "within_sla": report.timing.within_sla,
        },
        "findings": [
            {
                **f.model_dump(mode="json"),
                "scored": f.scored,
                "label": f.label,
                "fixable_now": f.fixable_now,
                "selector": selectors.get(f.target, ""),
            }
            for f in report.findings
        ],
    }


def _validate(html: str) -> str:
    if not html or not html.strip():
        raise HTTPException(status_code=400, detail="No HTML provided.")
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Email exceeds {MAX_HTML_BYTES // 1000}KB. Real sends are far smaller.",
        )
    return html


def create_app() -> FastAPI:
    app = FastAPI(
        title="preflight-agent",
        description="Pre-send visual, accessibility, and deliverability audit.",
        version="0.1.0",
    )

    NO_CACHE = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}

    @app.get("/launch-check", response_class=HTMLResponse)
    async def launch_check() -> HTMLResponse:
        """The check itself - the step between composing and sending.

        Named, because it is a step in a flow. `/editor` and `/publish` say what
        they are; leaving this one at `/` made it the exception in a sequence a
        creator is being asked to follow.
        """
        return HTMLResponse(REVIEW.read_text(), headers=NO_CACHE)

    @app.get("/")
    async def root() -> RedirectResponse:
        """Whatever else is here, opening the server lands on the product."""
        return RedirectResponse("/launch-check", status_code=307)

    @app.get("/publish", response_class=HTMLResponse)
    async def publish() -> HTMLResponse:
        """The pre-send gate, sitting where Wren's publish step already is.

        A separate surface from the editor on purpose. The editor wants ambient
        feedback while someone writes; this wants to be the last thing between
        a draft and twelve thousand people who cannot be un-emailed.
        """
        return HTMLResponse(PUBLISH.read_text(), headers=NO_CACHE)

    @app.get("/editor", response_class=HTMLResponse)
    async def editor() -> HTMLResponse:
        """The same check, doing the other job.

        Wren already warns in this sidebar. This is that panel with a creator's
        vocabulary, a location on the canvas, and something to press - and a
        toggle so the two can be seen against each other. Ambient and never
        blocking: the decision belongs at publish.
        """
        return HTMLResponse(EDITOR.read_text(), headers=NO_CACHE)

    @app.get("/api/health")
    async def health() -> dict:
        """Reports which reviewer is wired up, without leaking the key."""
        config = resolve()
        return {
            "ok": True,
            "provider": config.provider,
            "model": config.model,
            "thinking_level": config.thinking_level,
            "reviewer_budget_s": config.budget,
            "reviewer_enabled": config.configured,
            "presend_sla_ms": SLA_MS,
        }

    @app.get("/api/starter", response_class=HTMLResponse)
    async def starter() -> str:
        """The broadcast the UI opens with.

        Deliberately not a benchmark sample: the corpus is generated and its
        ground truth is scored, so a document shaped for a demo has no business
        in it. This one is authored to exercise the drawer end to end - a
        missing alt, an unpainted canvas, two failing contrast pairs, and one
        real 404 that auto-fix is right to leave alone.
        """
        return STARTER.read_text()

    @app.get("/api/sample/{name}", response_class=HTMLResponse)
    async def sample(name: str) -> str:
        """Serve a benchmark sample so the UI is testable with zero setup."""
        from ..evals.generate import SAMPLES_DIR, write_all

        if not SAMPLES_DIR.exists() or not any(SAMPLES_DIR.glob("*.html")):
            write_all()
        # Resolve and confine: the name comes from the URL, so it never gets to
        # pick the path. Anything outside the corpus is a 404.
        target = (SAMPLES_DIR / f"{Path(name).name}.html").resolve()
        if target.parent != SAMPLES_DIR.resolve() or not target.is_file():
            raise HTTPException(status_code=404, detail="Unknown sample.")
        return target.read_text()

    @app.post("/api/resolve")
    async def resolve_send(
        action: str = Body(..., embed=True),
        doc: str = Body("", embed=True),
        session: str = Body("", embed=True),
        verdict_at_audit: str = Body("", embed=True),
        time_to_resolve_sec: float | None = Body(None, embed=True),
        fixes_kept: int | None = Body(None, embed=True),
        fixes_undone: int | None = Body(None, embed=True),
        reason: str = Body("", embed=True),
        code: str = Body("", embed=True),
        decided_in_sec: float | None = Body(None, embed=True),
    ) -> JSONResponse:
        """What the creator did after reading the report.

        This is the only place OVERRIDDEN can come from: it means they saw a
        HOLD and sent anyway, which nothing else in the system can observe. The
        row carries no email content - just the same document hash the audit
        row used, so the two join without either storing anything readable.
        """
        if action not in monitor.ACTIONS:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
        if reason and reason not in monitor.DISMISS_REASONS:
            raise HTTPException(status_code=400, detail=f"Unknown reason: {reason}")
        row = monitor.record_action(
            action, doc=doc, session=session, verdict_at_audit=verdict_at_audit,
            time_to_resolve_sec=time_to_resolve_sec,
            fixes_kept=fixes_kept, fixes_undone=fixes_undone,
            reason=reason, code=code, decided_in_sec=decided_in_sec, source="web",
        )
        return JSONResponse({"recorded": row is not None, "monitoring": monitor.enabled()})

    @app.post("/api/audit")
    async def audit(
        html: str = Body(..., embed=True),
        skip_llm: bool = Body(False, embed=True),
        check_links: bool = Body(True, embed=True),
        deep: bool = Body(False, embed=True),
        subject: str = Body("", embed=True),
        preheader: str = Body("", embed=True),
    ) -> JSONResponse:
        report = await audit_html(
            _validate(html),
            path="pasted email",
            skip_llm=skip_llm,
            # An empty status map replays every link as reachable - the way to
            # ask for a fast, offline structural pass. Link probing is the
            # slowest pre-send phase, so it is worth being able to turn off.
            offline_links=None if check_links else {},
            deep=deep,
            monitor_source="web",
            subject=subject,
            preheader=preheader,
        )
        payload = _report_payload(report, html)
        # The document hash is what an action row joins on later.
        payload["doc"] = monitor.digest(html)
        return JSONResponse(payload)

    def _keys(raw: list) -> set[tuple[str, str]]:
        """`[["code","target"], ...]` from the browser -> the engine's key set."""
        out: set[tuple[str, str]] = set()
        for item in raw or []:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                out.add((str(item[0]), str(item[1])))
        return out

    async def _recompute(source: str, keys: set, aggressive: bool, check_links: bool,
                         subject: str = "", preheader: str = "",
                         max_passes: int = 3):
        """Rebuild the draft with exactly this set of repairs carried out.

        The browser never sends a partly-repaired document back. It holds the
        creator's untouched draft and the set of repairs they have accepted, and
        every interaction rebuilds from that - so undoing one repair cannot
        disturb another, and the order things were clicked in cannot matter
        (D34).

        Rebuilding takes more than one pass, because a repair can surface a
        problem that did not exist before it: darkening pale text for
        readability can make it newly fail on a dark screen. That problem is
        invisible in the first look at the draft, so a single pass would accept
        a repair for it and quietly do nothing.

        Each pass looks at the document as it now stands, carries out whichever
        accepted repairs are visible, and stops as soon as a pass finds none.
        Findings are always resolved against the document they came from -
        applying a later pass's findings to the original draft would point them
        at the wrong elements.
        """
        offline = None if check_links else {}
        current = source
        applied: list = []
        done: set = set()
        report = await audit_html(current, path="draft", offline_links=offline, skip_llm=True)

        for _ in range(max_passes):
            todo = [f for f in report.findings if f.key in keys and f.key not in done]
            if not todo:
                break
            current, new = apply_selected(current, todo, None, aggressive=aggressive)
            applied += new
            done |= {f.key for f in todo}
            report = await audit_html(current, path="draft",
                                      offline_links=offline, skip_llm=True,
                                      subject=subject, preheader=preheader)

        if liquid_tokens(current) != liquid_tokens(source):
            raise HTTPException(
                status_code=422,
                detail="Aborted: that repair would have altered Liquid template logic.",
            )
        return current, applied, report

    @app.post("/api/apply")
    async def apply(
        html: str = Body(..., embed=True),
        keys: list = Body(default_factory=list, embed=True),
        aggressive: bool = Body(False, embed=True),
        check_links: bool = Body(True, embed=True),
        subject: str = Body("", embed=True),
        preheader: str = Body("", embed=True),
    ) -> JSONResponse:
        """Apply exactly this set of repairs to the original document.

        `html` is always the creator's untouched draft. Sending an already-fixed
        document here would compound the repairs and make undo unreliable.
        """
        source = _validate(html)
        fixed, applied, after = await _recompute(
            source, _keys(keys), aggressive, check_links, subject, preheader)
        return JSONResponse({
            "fixed_html": fixed,
            "applied": [{"code": a.code, "target": a.target, "detail": a.detail}
                        for a in applied],
            "report": _report_payload(after, fixed),
        })

    @app.post("/api/preview")
    async def preview(
        html: str = Body(..., embed=True),
        key: list = Body(..., embed=True),
        check_links: bool = Body(True, embed=True),
    ) -> JSONResponse:
        """What one repair would change, committing nothing.

        Returns the before and after documents so the canvas can render the
        element both ways. The Professional segment asked for a diff before
        approval; this is that, and nothing is written until they accept.
        """
        source = _validate(html)
        keys = _keys([key])
        if not keys:
            raise HTTPException(status_code=400, detail="Expected a [code, target] pair.")
        fixed, applied, after = await _recompute(source, keys, False, check_links)
        return JSONResponse({
            "before": source,
            "after": fixed,
            "changed": bool(applied),
            "applied": [{"code": a.code, "target": a.target, "detail": a.detail}
                        for a in applied],
            "verdict_after": after.verdict,
        })

    @app.post("/api/fix")
    async def fix(
        html: str = Body(..., embed=True),
        aggressive: bool = Body(False, embed=True),
        check_links: bool = Body(True, embed=True),
    ) -> JSONResponse:
        source = _validate(html)
        # Same switch `/api/audit` carries. Without it the fix path can only be
        # exercised against the live web, which makes it untestable offline -
        # and rule 7 says tests never hit the network.
        fixed, applied, report = await fix_document(
            source, aggressive=aggressive,
            offline_links=None if check_links else {},
        )
        if liquid_tokens(fixed) != liquid_tokens(source):
            # Same guarantee the CLI enforces: refuse rather than risk Liquid.
            raise HTTPException(
                status_code=422,
                detail="Aborted: the fix would have altered Liquid template logic.",
            )
        return JSONResponse({
            "fixed_html": fixed,
            "applied": [{"code": a.code, "target": a.target, "detail": a.detail}
                        for a in applied],
            "report": _report_payload(report, fixed),
        })

    return app


app = create_app()
