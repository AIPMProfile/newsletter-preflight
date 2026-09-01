"""`preflight` command line interface.

Three verbs, because a creator has three moments: check it, fix it, and (for
whoever maintains the agent) prove it still works.
"""

from __future__ import annotations

import argparse
import os
import asyncio
import inspect
import json
import sys
from pathlib import Path

from rich.console import Console

from .audit import audit_file
from .config import resolve
from .evals.generate import GROUND_TRUTH_PATH, SAMPLES_DIR, write_all
from .evals.calibration import run_calibration
from .evals.harness import FIXTURES_DIR, run_benchmark
from .evals import history
from .fixer.autofix import fix_document, fixed_path, liquid_tokens
from . import monitor
from .report import (render_audit, render_behaviour, render_calibration, render_eval,
                     render_fix, render_harness, render_history, render_loop,
                     render_monitor, render_rule_health)

console = Console()


def _load_link_status(offline: bool) -> dict | None:
    if not offline:
        return None
    if not GROUND_TRUTH_PATH.exists():
        write_all()
    return json.loads(GROUND_TRUTH_PATH.read_text())["link_status"]


async def cmd_audit(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        console.print(f"[red]No such file:[/] {path}")
        return 2
    report = await audit_file(
        path,
        offline_links=_load_link_status(args.offline),
        # --offline means offline. The reviewer is a network call that ships
        # the document to a provider, so the flag has to cover it too.
        skip_llm=args.no_llm or args.offline,
        deep=args.deep,
        monitor_source="cli",
        subject=args.subject,
        preheader=args.preheader,
    )
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        render_audit(report, console)
    # Exit code is the contract for CI and pre-send hooks: non-zero blocks.
    return 1 if report.verdict == "HOLD" and args.strict else 0


async def cmd_fix(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        console.print(f"[red]No such file:[/] {path}")
        return 2
    source = path.read_text()
    before = await audit_file(path, offline_links=_load_link_status(args.offline), skip_llm=True)
    fixed, applied, after = await fix_document(
        source,
        aggressive=args.aggressive,
        offline_links=_load_link_status(args.offline),
    )
    if liquid_tokens(source) != liquid_tokens(fixed):
        console.print("[red]Aborted:[/] the fix would have altered Liquid template logic.")
        return 3
    out = Path(args.output) if args.output else fixed_path(path)
    if args.dry_run:
        console.print(fixed)
    else:
        out.write_text(fixed)
    render_fix(str(path), str(out), applied, after, before.verdict, console)
    return 0


async def cmd_eval(args: argparse.Namespace) -> int:
    if args.regenerate:
        written = write_all()
        console.print(f"[green]Regenerated[/] {len(written)} benchmark files in {SAMPLES_DIR}")
    if args.record:
        return await _record_fixtures()
    result = await run_benchmark(live_llm=args.live)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        render_eval(result, console)
    if not args.no_history:
        config = resolve()
        history.record(result.to_dict(), provider=config.provider,
                       model=config.model, note=args.note)

    if args.strict:
        # Detection gates, unchanged. A regression here has always meant the
        # agent got worse at finding things.
        failed = (
            result.overall.f1 < args.min_f1
            or result.clean_control_fp > 0
            or bool(result.sla_breaches)
            # Product-level gates. The verdict is the one output a creator acts
            # on, a violated control is ground truth contradicted, and severity
            # drift moves both the score and the verdict.
            or result.verdict_accuracy < 1.0
            or bool(result.control_violations)
            or bool(result.severity_drift)
        )
        # Fix gates, on by default since D29 closed the two defects that kept
        # them opt-in. What the one-click button advertises, it must repair.
        if args.gate_fix:
            failed = failed or result.fix_resolution_rate < args.min_fix_resolution \
                or bool(result.unsafe_fixes)
        return 1 if failed else 0
    return 0


async def _record_fixtures() -> int:
    """Capture live model assessments so CI can replay them for free."""
    from .checks.llm_eval import LLMAssessment, LLMFinding, assess
    from .parser import load
    from .checks.deterministic import document_stats

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for sample in sorted(SAMPLES_DIR.glob("*.html")):
        soup, sheet = load(sample.read_text())
        findings, status, ms = await assess(soup, document_stats(soup, sheet))
        if not status.startswith(("ok", "replayed")):
            console.print(f"[red]{sample.name}[/]: {status}")
            return 4
        payload = LLMAssessment(
            cta_summary="recorded from live API",
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
        ).model_dump()
        payload = {"provenance": "recorded", **payload}
        (FIXTURES_DIR / f"{sample.stem}.json").write_text(json.dumps(payload, indent=2) + "\n")
        console.print(f"[green]recorded[/] {sample.name} ({len(findings)} findings, {ms:.0f}ms)")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the browser UI. Localhost by default - the key lives server-side.

    Deliberately synchronous: uvicorn owns its event loop, so this must not be
    wrapped in `asyncio.run` the way the audit commands are.
    """
    try:
        import uvicorn
    except ImportError:
        console.print('[red]Missing web deps.[/] Install with: pip install -e ".[web]"')
        return 2

    url = f"http://{'localhost' if args.host == '127.0.0.1' else args.host}:{args.port}"
    config = resolve()
    console.print(f"\n  [bold]preflight[/] → [cyan]{url}[/]")
    console.print(
        f"  reviewer: [dim]{config.provider} · {config.model}[/]"
        if config.configured
        else f"  reviewer: [yellow]no {config.provider} key — deterministic engine only[/]"
    )
    if args.host != "127.0.0.1":
        console.print("  [yellow]Bound beyond localhost. Anyone who can reach this host "
                      "can spend your API quota.[/]")
    console.print()
    uvicorn.run("preflight.web:app", host=args.host, port=args.port,
                reload=args.reload, log_level="warning")
    return 0


async def cmd_calibrate(args: argparse.Namespace) -> int:
    """Agreement between the reviewer and a human labeller."""
    result = await run_calibration(live_llm=args.live)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        render_calibration(result, console)
    if not result.samples:
        return 0
    if args.strict:
        kappa = result.total.kappa
        # An undefined kappa is not a pass: it means the labels carried no
        # disagreement to measure, so the run proved nothing.
        if kappa is None or kappa < args.min_kappa or not result.blind:
            return 1
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    """Finding mix across audits recorded in production."""
    rows = monitor.load(limit=args.limit)
    audits = [r for r in rows if r.get("kind", "audit") == "audit"]
    if args.json:
        print(json.dumps({"summary": monitor.summarize(audits),
                          "behaviour": monitor.behaviour(rows),
                          "rule_health": monitor.rule_health(rows),
                          "drift": monitor.drift(audits, window=args.window)}, indent=2))
        return 0
    render_monitor(monitor.summarize(audits), monitor.drift(audits, window=args.window),
                   monitor.log_path(), monitor.enabled(), console)
    if rows:
        render_behaviour(monitor.behaviour(rows), console)
        render_rule_health(monitor.rule_health(rows), console)
    return 0


def cmd_loop(args: argparse.Namespace) -> int:
    """Read creator behaviour against each check's rubric."""
    from .evals import loop

    rows = monitor.load(limit=args.limit)
    summary = loop.summary(rows)
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        render_loop(summary, console)
    if args.strict and summary["proposals"]:
        return 1
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    """Benchmark results over time."""
    rows = history.load(limit=args.limit)
    if args.json:
        print(json.dumps({"runs": rows, "deltas": history.deltas(rows)}, indent=2))
    else:
        render_history(rows, history.deltas(rows), console)
    return 0


def cmd_harness(args: argparse.Namespace) -> int:
    """Two-pass repair check over the real-email corpus."""
    from .evals import run_harness

    results = run_harness.run_sync(check_links=args.check_links)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        render_harness(results, console)
    if not args.no_write:
        path = run_harness.write(results)
        if not args.json:
            console.print(f"  [dim]Written to {path}[/]\n")
    # An empty corpus is not a pass and not a failure - there was nothing to
    # measure, and saying otherwise either way would be a claim we cannot make.
    if args.strict and results["documents"]:
        return 0 if results["passes"] else 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="preflight",
        description="Pre-send visual, accessibility, and deliverability audit for newsletters.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Score an email and list what would break in real inboxes.")
    audit.add_argument("file")
    audit.add_argument("--no-llm", action="store_true", help="Deterministic engine only.")
    audit.add_argument("--deep", action="store_true",
                       help="Let the intent reviewer run past the 2s SLA instead of degrading.")
    audit.add_argument("--offline", action="store_true",
                       help="No network at all: replay pinned link statuses and skip the reviewer.")
    audit.add_argument("--subject", default="",
                       help="Subject line, so the envelope checks can run.")
    audit.add_argument("--preheader", default="", help="Preview text.")
    audit.add_argument("--json", action="store_true", help="Machine-readable report.")
    audit.add_argument("--strict", action="store_true", help="Exit 1 when the verdict is HOLD.")
    audit.set_defaults(func=cmd_audit)

    fix = sub.add_parser("fix", help="Write fixed_<file>.html with the safe repairs applied.")
    fix.add_argument("file")
    fix.add_argument("-o", "--output", help="Write somewhere other than fixed_<file>.html.")
    fix.add_argument("--aggressive", action="store_true",
                     help="Also rewrite the dark-mode stylesheet block (touches creator CSS).")
    fix.add_argument("--dry-run", action="store_true", help="Print the result instead of writing it.")
    fix.add_argument("--offline", action="store_true")
    fix.set_defaults(func=cmd_fix)

    ev = sub.add_parser("eval", help="Run the benchmark against ground truth.")
    ev.add_argument("--live", action="store_true", help="Call the real API instead of replaying fixtures.")
    ev.add_argument("--record", action="store_true", help="Re-record LLM fixtures from the live API.")
    ev.add_argument("--regenerate", action="store_true", help="Rewrite the sample corpus and ground truth.")
    ev.add_argument("--json", action="store_true")
    ev.add_argument("--strict", action="store_true", help="Exit 1 if the benchmark regresses.")
    ev.add_argument("--min-f1", type=float, default=0.9)
    ev.add_argument("--no-gate-fix", dest="gate_fix", action="store_false",
                    help="Do not fail --strict on fix resolution or unsafe fixes.")
    ev.set_defaults(gate_fix=True)
    ev.add_argument("--min-fix-resolution", type=float, default=1.0,
                    help="Floor for the share of fixable findings the default fix resolves.")
    ev.add_argument("--no-history", action="store_true", help="Do not append to history.jsonl.")
    ev.add_argument("--note", default="", help="Label this run in the history log.")
    ev.set_defaults(func=cmd_eval)

    cal = sub.add_parser("calibrate",
                         help="Agreement between the intent reviewer and human labels.")
    cal.add_argument("--live", action="store_true", help="Call the real API instead of replaying.")
    cal.add_argument("--json", action="store_true")
    cal.add_argument("--strict", action="store_true", help="Exit 1 on weak or non-blind agreement.")
    cal.add_argument("--min-kappa", type=float, default=0.6,
                     help="Floor for Cohen's kappa. 0.6 is the bottom of 'substantial'.")
    cal.set_defaults(func=cmd_calibrate)

    mon = sub.add_parser("monitor", help="Finding mix and drift across recorded audits.")
    mon.add_argument("--limit", type=int, default=None, help="Only the most recent N audits.")
    mon.add_argument("--window", type=int, default=20, help="Recent-window size for drift.")
    mon.add_argument("--json", action="store_true")
    mon.set_defaults(func=cmd_monitor)

    harn = sub.add_parser("harness",
                          help="Two-pass repair check over the real-email corpus.")
    harn.add_argument("--check-links", action="store_true",
                      help="Probe links live. Off by default so runs are reproducible.")
    harn.add_argument("--strict", action="store_true",
                      help="Exit 1 if clearance or layout safety misses target.")
    harn.add_argument("--no-write", action="store_true",
                      help="Do not write HARNESS_RESULTS.json.")
    harn.add_argument("--json", action="store_true")
    harn.set_defaults(func=cmd_harness)

    lp = sub.add_parser("loop",
                        help="What creators did, read against each check's rubric.")
    lp.add_argument("--limit", type=int, default=None)
    lp.add_argument("--strict", action="store_true",
                    help="Exit 1 when the evidence supports changing something.")
    lp.add_argument("--json", action="store_true")
    lp.set_defaults(func=cmd_loop)

    hist = sub.add_parser("history", help="Benchmark results over time.")
    hist.add_argument("--limit", type=int, default=20)
    hist.add_argument("--json", action="store_true")
    hist.set_defaults(func=cmd_history)

    serve = sub.add_parser("serve", help="Run the browser UI at localhost:8000.")
    serve.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"),
                       help="Bind address. Defaults to localhost; anything else is exposed. "
                            "$HOST overrides, for a platform that assigns it.")
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")),
                       help="$PORT overrides, which is how every host assigns one.")
    serve.add_argument("--reload", action="store_true", help="Auto-reload on code changes.")
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = args.func(args)
    # Most commands are coroutines; `serve` runs its own loop and is not.
    if inspect.iscoroutine(result):
        return asyncio.run(result)
    return result


if __name__ == "__main__":
    sys.exit(main())
