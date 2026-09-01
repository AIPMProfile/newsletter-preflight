"""Terminal rendering.

The report is the product. A creator reads it in the ten seconds before they
hit send, so it is ordered by what would stop a send: the verdict first, the
score second, then errors, then everything else. Every row answers "what do I
change" - a finding with no remedy is a finding we should not have shipped.
"""

from __future__ import annotations

import re

from rich.box import SIMPLE_HEAD
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import SLA_MS, AuditReport, Finding, Severity

SEVERITY_STYLE = {
    Severity.WILL_BREAK: ("●", "bold red", "WILL BREAK"),
    Severity.WILL_EMBARRASS: ("●", "bold yellow", "WILL EMBARRASS"),
    Severity.COULD_BE_BETTER: ("○", "dim cyan", "COULD BE BETTER"),
}

VERDICT_STYLE = {
    "READY": ("bold white on green", "Nothing found. Send it."),
    "REVIEW": ("bold black on yellow", "Nothing blocking - a few things worth a look."),
    "HOLD": ("bold white on red", "Do not send yet - these break in real inboxes."),
}

VERDICT_COLOR = {"READY": "green", "REVIEW": "yellow", "HOLD": "red"}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _headline(report: AuditReport) -> Panel:
    """The verdict, then what it is made of.

    No composite number. The old readiness score subtracted 12 per error and 5
    per warning - weights nobody could defend - and a creator cannot act on
    "64/100" anyway. What they can act on is the count of things that will
    break and the count of things that will embarrass them (D28).
    """
    style, blurb = VERDICT_STYLE[report.verdict]
    breaks = sum(1 for f in report.findings if f.severity is Severity.WILL_BREAK)
    embarrass = sum(1 for f in report.findings if f.severity is Severity.WILL_EMBARRASS)
    polish = sum(1 for f in report.findings if f.severity is Severity.COULD_BE_BETTER)

    verdict_line = Text(f" {report.verdict} ", style=style)
    verdict_line.append("  " + blurb, style="dim")

    counts = Text()
    counts.append(f"{breaks} will break", style="bold red" if breaks else "dim")
    counts.append("  ·  ", style="dim")
    counts.append(f"{embarrass} will embarrass", style="bold yellow" if embarrass else "dim")
    counts.append("  ·  ", style="dim")
    counts.append(f"{polish} could be better", style="dim")
    stats = Text(
        f"{_plural(report.stats.get('words', 0), 'word')} · "
        f"{_plural(report.stats.get('links', 0), 'link')} · "
        f"{_plural(report.stats.get('images', 0), 'image')}",
        style="dim",
    )
    return Panel(
        Group(verdict_line, Text(), counts, stats),
        title=f"[bold]preflight[/] · {report.path}",
        border_style="grey37",
    )


def _findings_block(findings: list[Finding]) -> Table:
    """One finding per stanza: what, where, and the single change to make.

    A table with five narrow columns technically holds the same data, but at 80
    columns it shreds every sentence into three-word ribbons. Creators scan this
    with a send button already under their thumb - readability is the feature.
    """
    grid = Table.grid(padding=(0, 1), expand=True)
    grid.add_column(width=1, no_wrap=True)
    grid.add_column(width=5, justify="right", no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")

    for i, finding in enumerate(findings):
        glyph, style, _ = SEVERITY_STYLE[finding.severity]
        head = Text(finding.code, style=style)
        head.append(" · ", style="grey37")
        head.append(finding.target, style="cyan")
        line = Text(f"L{finding.line}" if finding.line else "—", style="grey50")
        grid.add_row(Text(glyph, style=style), line, head)
        # Consequence first, in the creator's words. The measurement sits
        # underneath it, dimmed: a professional needs it to defend the change
        # and a hobbyist never has to read it (D33).
        grid.add_row("", "", Text(finding.message, style="white"))
        if finding.detail:
            grid.add_row("", "", Text(finding.detail, style="grey50"))
        if finding.remedy:
            grid.add_row("", "", Text("↳ " + finding.remedy,
                                      style="green" if finding.fixable_now else "dim"))
        if i != len(findings) - 1:
            grid.add_row("", "", "")
    return grid


def _footer(report: AuditReport) -> Text:
    t = report.timing
    sla_ok = t.within_sla
    text = Text()
    text.append(f"  {t.total_ms:.0f}ms total", style="bold")
    text.append(
        f"  ·  engine {t.deterministic_ms:.0f} · links {t.links_ms:.0f} · reviewer {t.llm_ms:.0f}",
        style="dim",
    )
    text.append("\n  pre-send ", style="dim")
    text.append(f"{t.presend_ms:.0f}ms", style="bold green" if sla_ok else "bold red")
    text.append(f" / {SLA_MS:.0f}ms SLA {'✓' if sla_ok else '✗ EXCEEDED'}",
                style="dim" if sla_ok else "bold red")
    if t.llm_ms > 0:
        text.append(f"   ·  intent review adds {t.llm_ms:.0f}ms (--no-llm to skip)", style="dim")
    if report.llm_status != "ok":
        text.append(f"\n  Module B: {report.llm_status}", style="yellow")
        missing_key = re.match(r"skipped: no ([A-Z_]+_API_KEY)$", report.llm_status)
        if missing_key:
            text.append(f"  → add {missing_key.group(1)} to .env for CTA and spam review",
                        style="dim")
    fixable = sum(1 for f in report.findings if f.fixable)
    if fixable:
        text.append(f"\n  {fixable} of these are auto-fixable: ", style="dim")
        text.append(f"preflight fix {report.path}", style="bold cyan")
    return text


def render_audit(report: AuditReport, console: Console | None = None) -> None:
    console = console or Console()
    console.print()
    console.print(_headline(report))
    if not report.findings:
        console.print("\n  [green]Nothing to fix. Every surface, link, and image checked out.[/]\n")
    else:
        by_module = [
            ("Deterministic engine · contrast, dark mode, links, assets", report.by_module("deterministic")),
            ("Visual & intent reviewer · CTA, deliverability", report.by_module("llm")),
        ]
        for title, group in by_module:
            if not group:
                continue
            console.print(f"\n[bold grey62]{title}[/]\n")
            console.print(_findings_block(group))
    console.print(_footer(report))
    console.print()


def render_fix(path: str, out_path: str, applied: list, report: AuditReport,
               before_verdict: str, console: Console | None = None) -> None:
    console = console or Console()
    table = Table(box=SIMPLE_HEAD, expand=True, show_edge=False, pad_edge=False)
    table.add_column("Fix", width=24, style="green", no_wrap=True)
    table.add_column("Element", width=18, style="cyan", no_wrap=True)
    table.add_column("Change", ratio=1, overflow="fold")
    for fix in applied:
        table.add_row(fix.code, fix.target[:18], fix.detail)

    remaining = [f for f in report.findings if f.scored]
    summary = Text()
    summary.append(f"  {before_verdict} → {report.verdict}", style="bold")
    summary.append(f"   ·  {len(applied)} changes applied", style="dim")
    if remaining:
        summary.append(f"\n  {len(remaining)} findings need a human: ", style="yellow")
        summary.append(", ".join(sorted({f.code for f in remaining})), style="dim")
    aggressive = [f for f in report.findings if f.requires_aggressive]
    if aggressive:
        summary.append(
            f"\n  {len(aggressive)} need --aggressive (rewrites your stylesheet): ",
            style="yellow")
        summary.append(", ".join(sorted({f.code for f in aggressive})), style="dim")
    summary.append(f"\n  Written to ", style="dim")
    summary.append(out_path, style="bold cyan")
    summary.append("\n  Liquid logic, layout structure, and attributes are byte-identical;", style="dim")
    summary.append("\n  indentation on blank lines is normalized by the parser.", style="dim")

    console.print()
    console.print(Panel(
        Group(table, Text(), summary) if applied else Text("  Nothing was auto-fixable in this file.", style="dim"),
        title=f"[bold]preflight fix[/] · {path}", border_style="grey37",
    ))
    console.print()


def _fp_rate(value: float) -> Text:
    return Text(f"{value * 100:.1f}%", style="green" if value < 0.05 else "yellow")


def _pct(value: float) -> Text:
    color = "green" if value >= 0.95 else "yellow" if value >= 0.8 else "red"
    return Text(f"{value * 100:.1f}%", style=color)


def render_eval(result, console: Console | None = None) -> None:
    """Executive telemetry: is the agent accurate, is it fast, does it cry wolf."""
    console = console or Console()
    totals = result.totals()
    overall = result.overall

    modules = Table(box=SIMPLE_HEAD, expand=True, show_edge=False, pad_edge=False,
                    title="[bold]Accuracy by module[/]", title_justify="left")
    modules.add_column("Module", width=24, no_wrap=True)
    modules.add_column("Precis.", justify="right", width=8)
    modules.add_column("Recall", justify="right", width=7)
    modules.add_column("F1", justify="right", width=7)
    modules.add_column("TP", justify="right", width=4)
    modules.add_column("FP", justify="right", width=4)
    modules.add_column("FN", justify="right", width=4)
    modules.add_column("FP rate", justify="right", width=8)

    labels = {
        "deterministic": "A · Deterministic",
        "llm": "B · Intent reviewer",
    }
    rows = [(labels[k], totals[k]) for k in ("deterministic", "llm")]
    rows.append(("Blended", overall))
    for name, c in rows:
        modules.add_row(
            Text(name, style="bold" if name == "Blended" else ""),
            _pct(c.precision), _pct(c.recall), _pct(c.f1),
            str(c.tp),
            Text(str(c.fp), style="red" if c.fp else "green"),
            Text(str(c.fn), style="red" if c.fn else "green"),
            _fp_rate(c.false_positive_rate),
        )

    cases = Table(box=SIMPLE_HEAD, expand=True, show_edge=False, pad_edge=False,
                  title="[bold]Per-sample[/]", title_justify="left")
    cases.add_column("Sample", width=22, no_wrap=True)
    cases.add_column("Blocking", justify="right", width=9)
    cases.add_column("Verdict", width=8)
    cases.add_column("Exp", justify="right", width=4)
    cases.add_column("TP", justify="right", width=4)
    cases.add_column("FP", justify="right", width=4)
    cases.add_column("FN", justify="right", width=4)
    cases.add_column("Latency", justify="right", width=9)

    for case in result.cases:
        c = case.total
        latency = case.report.timing.total_ms
        cases.add_row(
            case.sample.replace(".html", ""),
            str(len(case.report.blocking_findings)),
            Text(case.report.verdict, style=VERDICT_COLOR[case.report.verdict]),
            str(case.expected_count), str(c.tp),
            Text(str(c.fp), style="red" if c.fp else "grey50"),
            Text(str(c.fn), style="red" if c.fn else "grey50"),
            Text(f"{latency:.1f}ms", style="green" if latency <= SLA_MS else "red"),
        )

    headline = Text()
    headline.append("  Blended F1 ", style="dim")
    headline.append(f"{overall.f1 * 100:.1f}%", style="bold green" if overall.f1 >= 0.95 else "bold yellow")
    headline.append("   ·  clean-control false positives ", style="dim")
    headline.append(str(result.clean_control_fp),
                    style="bold green" if result.clean_control_fp == 0 else "bold red")
    headline.append("   ·  mean latency ", style="dim")
    headline.append(f"{result.mean_latency_ms:.1f}ms", style="bold green" if not result.sla_breaches else "bold red")
    headline.append(f" / {SLA_MS:.0f}ms SLA", style="dim")
    if result.sla_breaches:
        headline.append(f"\n  SLA breached on: {', '.join(result.sla_breaches)}", style="bold red")

    product = Text("\n  Verdict accuracy ", style="dim")
    product.append(f"{result.verdict_accuracy * 100:.0f}%",
                   style="bold green" if result.verdict_accuracy == 1.0 else "bold red")
    product.append("   ·  fix resolution ", style="dim")
    product.append(f"{result.fix_resolution_rate * 100:.0f}%",
                   style="bold green" if result.fix_resolution_rate == 1.0 else "bold yellow")
    product.append("   ·  reviewer degraded ", style="dim")
    product.append(f"{result.llm_degradation_rate * 100:.0f}%",
                   style="bold green" if result.llm_degradation_rate == 0 else "bold yellow")
    for sample, want, got in result.verdict_misses:
        product.append(f"\n  Verdict wrong on {sample}: expected {want}, got {got}", style="bold red")
    for sample, code, target, want, got in result.severity_drift:
        product.append(f"\n  Severity drift {sample} · {code} on {target}: "
                       f"expected {want}, got {got}", style="bold red")
    for sample, code, target, sev in result.control_violations:
        product.append(f"\n  Control violated {sample} · {code} on {target} ({sev})", style="bold red")
    if result.unsafe_fixes:
        product.append(f"\n  Fix did not converge in one pass: {', '.join(result.unsafe_fixes)}",
                       style="bold yellow")
    for sample, code in result.mis_advertised_fixes:
        product.append(f"\n  {sample} · {code} is marked fixable but only --aggressive repairs it",
                       style="bold yellow")

    mode = Text("\n  Module B input: ", style="dim")
    if result.live_llm:
        mode.append("live Anthropic API", style="bold green")
    else:
        mode.append(f"replayed fixtures ({result.llm_provenance})", style="yellow")
        if "authored" in result.llm_provenance:
            mode.append(
                "\n  Authored fixtures verify wiring and scoring, not model quality."
                "\n  Run `preflight eval --live` with an API key to measure the model itself.",
                style="dim yellow",
            )

    console.print()
    console.print(Panel(Group(headline, product, mode), title="[bold]preflight benchmark[/]",
                        border_style="grey37"))
    console.print()
    console.print(modules)
    console.print()
    console.print(cases)
    console.print()
    room = max(28, console.width - 30)
    for case in result.cases:
        desc = case.description
        desc = desc if len(desc) <= room else desc[: room - 1] + "…"
        console.print(f"  [grey50]{case.sample.replace('.html', ''):<24}[/][dim]{desc}[/]")

    misses = [i for c in totals.values() for i in c.fn_items]
    spurious = [i for c in totals.values() for i in c.fp_items]
    if misses or spurious:
        console.print()
        for sample, code, target in misses:
            console.print(f"  [red]MISS[/]  {sample} · {code} on {target}")
        for sample, code, target in spurious:
            console.print(f"  [yellow]FALSE POSITIVE[/]  {sample} · {code} on {target}")
    console.print()


def render_calibration(result, console: Console | None = None) -> None:
    """Does the reviewer agree with a human, beyond what chance would give?

    Kappa leads because raw agreement is flattered by every candidate both
    raters passed over. The blind flag sits next to it because a labeller who
    read the model's answer first is not evidence, whatever the number says.
    """
    from .evals.calibration import interpret

    console = console or Console()
    if not result.samples:
        console.print()
        console.print(Panel(
            Text.from_markup(
                "  No human labels yet — Module B has no reliability evidence.\n\n"
                "  [dim]Write one file per sample in [/][bold]evals/labels/[/][dim], then rerun.\n"
                "  Until then the benchmark's Module B row measures harness wiring,\n"
                "  not the model. See evals/labels/README.md.[/]"),
            title="[bold]reviewer calibration[/]", border_style="yellow"))
        console.print()
        return

    t = result.total
    kappa = t.kappa
    head = Text("  Cohen's κ ", style="dim")
    head.append("n/a" if kappa is None else f"{kappa:.3f}",
                style="bold green" if (kappa or 0) >= 0.6 else "bold red")
    head.append(f"  ({interpret(kappa)})", style="dim")
    head.append("\n  Raw agreement ", style="dim")
    head.append(f"{t.observed * 100:.0f}%", style="bold")
    head.append(f"   ·  chance {t.expected * 100:.0f}%", style="dim")
    head.append(f"   ·  {t.n} candidates across {result.labelled_samples} samples", style="dim")
    head.append("\n  Labelling ", style="dim")
    head.append("blind" if result.blind else "NOT blind — labeller saw the model output",
                style="bold green" if result.blind else "bold red")
    head.append(f"\n  Judge input: {result.provenance}", style="dim")

    console.print()
    console.print(Panel(head, title="[bold]reviewer calibration[/]", border_style="grey37"))

    table = Table(box=SIMPLE_HEAD, expand=True, show_edge=False, pad_edge=False,
                  title="[bold]Agreement[/]", title_justify="left")
    table.add_column("Outcome", width=34, no_wrap=True)
    table.add_column("Count", justify="right", width=7)
    for label, value, style in (
        ("Both called it real", t.both_real, "green"),
        ("Judge missed it", t.human_only, "red" if t.human_only else "grey50"),
        ("Judge invented it", t.judge_only, "red" if t.judge_only else "grey50"),
        ("Both passed over it", t.both_absent, "grey50"),
    ):
        table.add_row(label, Text(str(value), style=style))
    console.print()
    console.print(table)

    disputes = [(s.sample, c, tg, w) for s in result.samples for c, tg, w in s.disputes]
    if disputes:
        console.print()
        for sample, code, target, who in disputes:
            console.print(f"  [yellow]DISPUTE[/]  {sample} · {code} on {target} — {who}")
    console.print()


def _rate(value, n: int, good_low: bool = True) -> Text:
    """A rate always arrives with the n behind it. A percentage computed from
    four sends is not a trend, and printing it bare invites treating it as one."""
    if value is None:
        return Text(f"n/a  ({n} observed)", style="dim")
    style = "bold" if n >= 20 else "dim"
    return Text(f"{value * 100:.0f}%  (n={n})", style=style)


def render_behaviour(b: dict, console: Console | None = None) -> None:
    """What creators did about the verdicts.

    Override rate leads because it is the credibility metric: a creator who
    sees HOLD and sends anyway is telling us the check was wrong.
    """
    console = console or Console()
    table = Table(box=SIMPLE_HEAD, expand=True, show_edge=False, pad_edge=False,
                  title="[bold]Creator behaviour[/]", title_justify="left")
    table.add_column("Metric", width=30, no_wrap=True)
    table.add_column("Value", justify="right", width=18)
    table.add_column("Reads as", ratio=1)
    table.add_row("Override rate", _rate(b["override_rate"], b["hold_outcomes"]),
                  Text("saw HOLD, sent anyway — the trust signal", style="dim"))
    table.add_row("Action rate on HOLD", _rate(b["action_rate_on_hold"], b["hold_outcomes"]),
                  Text("saw HOLD, changed something first", style="dim"))
    table.add_row("Fix acceptance", _rate(b["fix_acceptance_rate"], b["fix_decisions"]),
                  Text("one-click repairs kept rather than undone", style="dim"))
    median = b["median_time_to_resolve_sec"]
    table.add_row("Median time to resolve",
                  Text(f"{median:.0f}s" if median is not None else "n/a",
                       style="bold" if median is not None else "dim"),
                  Text("the tax this adds to shipping", style="dim"))
    table.add_row("Unresolved audits", Text(str(b["unresolved_audits"]), style="dim"),
                  Text("audited, no send recorded yet", style="dim"))
    console.print()
    console.print(table)
    if b["hold_outcomes"] < 20:
        console.print("  [dim]Too few resolved sends to read as a trend. Each rate "
                      "carries its own n, and nothing is inferred.[/]")
    console.print("  [dim]Audit rate is not here: the denominator is drafts that were "
                  "never audited, which only the composer can see.[/]")


def render_rule_health(health: dict, console: Console | None = None) -> None:
    """Which check creators keep waving through, and whether that is our fault.

    A high dismissal rate on its own means nothing - creators mean what they
    write. What matters is the share dismissed as "flagged wrongly", because
    only that is evidence against the rule.
    """
    console = console or Console()
    if not health:
        return
    table = Table(box=SIMPLE_HEAD, expand=True, show_edge=False, pad_edge=False,
                  title="[bold]Rule health[/]", title_justify="left")
    table.add_column("Rule", width=28, no_wrap=True)
    table.add_column("Decisions", justify="right", width=10)
    table.add_column("Dismissed", justify="right", width=10)
    table.add_column("“Wrongly”", justify="right", width=10)
    table.add_column("Verdict", ratio=1)
    for code, h in health.items():
        if h["needs_recalibration"]:
            note, style = Text("recalibrate — creators say this is wrong", style="bold red"), "red"
        elif h["underpowered"]:
            note, style = Text(f"too few decisions to judge (n<{20})", style="dim"), "grey50"
        else:
            note, style = Text("holding up", style="green"), "grey50"
        table.add_row(code, str(h["decisions"]), f"{h['dismiss_rate'] * 100:.0f}%",
                      Text(f"{h['false_alarm_rate'] * 100:.0f}%", style=style), note)
    console.print()
    console.print(table)
    console.print("  [dim]Only “flagged wrongly” counts against a rule — “I meant it” "
                  "says something\n  about the creator, not the check. Nothing here "
                  "switches a check off; run\n  `preflight loop` for what the evidence "
                  "proposes changing.[/]")


def render_monitor(summary: dict, drifts: list[dict], path, on: bool,
                   console: Console | None = None) -> None:
    """The finding mix across real sends, and anything that moved."""
    console = console or Console()
    console.print()
    if not summary.get("documents"):
        state = ("recording" if on else
                 "off — set PREFLIGHT_MONITOR=1 to record audits")
        console.print(Panel(
            Text.from_markup(
                f"  No audits recorded yet.  [dim]Monitoring is {state}.[/]\n"
                f"  [dim]Log: {path}[/]"),
            title="[bold]production monitor[/]", border_style="yellow"))
        console.print()
        return

    head = Text(f"  {summary['documents']} audits", style="bold")
    head.append(f" · {summary['unique_documents']} distinct documents", style="dim")
    head.append(f"\n  HOLD rate {summary['hold_rate'] * 100:.0f}%", style="dim")
    head.append(f"   ·  reviewer degraded {summary['degraded'] * 100:.0f}%", style="dim")
    head.append(f"   ·  SLA breached {summary['sla_breach_rate'] * 100:.0f}%", style="dim")
    head.append(f"\n  Log: {path}", style="dim")
    console.print(Panel(head, title="[bold]production monitor[/]", border_style="grey37"))

    table = Table(box=SIMPLE_HEAD, expand=True, show_edge=False, pad_edge=False,
                  title="[bold]Finding mix[/]", title_justify="left")
    table.add_column("Code", width=30, no_wrap=True)
    table.add_column("Documents", justify="right", width=11)
    table.add_column("Share", justify="right", width=8)
    for code, row in summary["codes"].items():
        table.add_row(code, str(row["documents"]), f"{row['share'] * 100:.0f}%")
    console.print()
    console.print(table)

    if drifts:
        console.print()
        console.print("  [bold yellow]Finding mix moved[/] [dim](recent window vs. everything before)[/]")
        for d in drifts:
            arrow = "↑" if d["delta"] > 0 else "↓"
            console.print(f"  [yellow]{arrow}[/] {d['code']}: "
                          f"{d['baseline_share'] * 100:.0f}% → {d['recent_share'] * 100:.0f}%")
        console.print("  [dim]A check, a mail client, or the incoming mail changed. "
                      "This says look; it does not say what.[/]")
    console.print()


def render_history(rows: list[dict], deltas: dict, console: Console | None = None) -> None:
    """Benchmark results over time, newest last."""
    console = console or Console()
    console.print()
    if not rows:
        console.print(Panel(Text("  No runs recorded yet. `preflight eval` appends one per run."),
                            title="[bold]benchmark history[/]", border_style="yellow"))
        console.print()
        return

    table = Table(box=SIMPLE_HEAD, expand=True, show_edge=False, pad_edge=False,
                  title="[bold]Benchmark history[/]", title_justify="left")
    table.add_column("When", width=17, no_wrap=True)
    table.add_column("Model", width=22, no_wrap=True)
    table.add_column("Mode", width=20, no_wrap=True)
    table.add_column("F1", justify="right", width=7)
    table.add_column("Verdict", justify="right", width=8)
    table.add_column("Fix", justify="right", width=7)
    table.add_column("FP", justify="right", width=4)
    for r in rows:
        table.add_row(
            (r.get("at") or "")[:16].replace("T", " "),
            r.get("model", "") or "—",
            r.get("llm_mode", "") or "—",
            _pct(r["f1"]) if isinstance(r.get("f1"), (int, float)) else "—",
            _pct(r["verdict_accuracy"]) if isinstance(r.get("verdict_accuracy"), (int, float)) else "—",
            _pct(r["fix_resolution_rate"]) if isinstance(r.get("fix_resolution_rate"), (int, float)) else "—",
            Text(str(r.get("clean_control_fp", "—")),
                 style="red" if r.get("clean_control_fp") else "grey50"),
        )
    console.print(table)

    if deltas:
        console.print()
        for key, d in deltas.items():
            if d["delta"] == 0:
                continue
            style = "green" if d["delta"] > 0 else "red"
            console.print(f"  [{style}]{'▲' if d['delta'] > 0 else '▼'}[/] {key}: "
                          f"{d['from']} → {d['to']} ({d['delta']:+})")
    console.print()


def render_harness(r: dict, console: Console | None = None) -> None:
    """Would these documents be sendable after one click, and did they survive it?"""
    console = console or Console()
    console.print()
    if not r["documents"]:
        console.print(Panel(
            Text.from_markup(
                "  No documents to check.\n\n"
                "  [dim]Add real broadcasts to [/][bold]evals/real/[/][dim] and run again.\n"
                "  Nothing is inferred from an empty corpus.[/]"),
            title="[bold]repair harness[/]", border_style="yellow"))
        console.print()
        return

    ok = r["passes"]
    head = Text(f"  {r['documents']} documents", style="bold")
    head.append("\n  Sendable after repair ", style="dim")
    head.append(f"{r['clearance_rate'] * 100:.0f}%",
                style="bold green" if r["clearance_rate"] >= r["clearance_target"] else "bold red")
    head.append(f"  (target {r['clearance_target'] * 100:.0f}%)", style="dim")
    head.append("\n  Layout untouched ", style="dim")
    head.append(f"{r['layout_safe_rate'] * 100:.0f}%",
                style="bold green" if r["layout_safe_rate"] >= r["layout_target"] else "bold red")
    head.append("  (target 100%)", style="dim")
    if r["ready_rate"] is not None:
        head.append(f"\n  Completely clean afterwards {r['ready_rate'] * 100:.0f}%", style="dim")
    head.append("\n  [dim]Clearance means nothing blocks a send. It is not the same as "
                "nothing found —\n  the repair aims at the readable floor, so advisory "
                "notes survive on purpose.[/]", style="dim")
    console.print(Panel(head, title="[bold]repair harness[/]",
                        border_style="green" if ok else "red"))

    if r["unsafe"]:
        console.print()
        for f in r["unsafe"]:
            console.print(f"  [bold red]LAYOUT CHANGED[/]  {f}")
    if r["uncleared"]:
        console.print()
        for f in r["uncleared"]:
            console.print(f"  [yellow]STILL BLOCKED[/]  {f}")
    console.print()


def render_loop(s: dict, console: Console | None = None) -> None:
    """What creators told us, and what it says to change.

    Coverage leads. Proposals about four checks out of sixteen is a different
    statement from proposals about all of them, and putting the recommendations
    first would let silence read as approval.
    """
    console = console or Console()
    cov = s["coverage"]
    console.print()
    head = Text(f"  {cov['checks_with_enough_evidence']} of {cov['checks_total']} checks "
                f"have enough creator evidence to judge", style="bold")
    head.append(f"\n  {cov['checks_with_evidence']} have been decided on at all · "
                f"a check needs {cov['min_decisions']} decisions before it is read",
                style="dim")
    if cov["unheard"]:
        head.append(f"\n  Never acted on by anyone: {', '.join(cov['unheard'][:6])}"
                    + (" …" if len(cov["unheard"]) > 6 else ""), style="dim")
    console.print(Panel(head, title="[bold]improvement loop[/]", border_style="grey37"))

    rows = {c: v for c, v in s["checks"].items() if not v["underpowered"]}
    if rows:
        table = Table(box=SIMPLE_HEAD, expand=True, show_edge=False, pad_edge=False,
                      title="[bold]Per check[/]", title_justify="left")
        table.add_column("Check", width=26, no_wrap=True)
        table.add_column("Approved", justify="right", width=9)
        table.add_column("“Wrong”", justify="right", width=8)
        table.add_column("Ignored", justify="right", width=8)
        table.add_column("Decide", justify="right", width=11)
        for code, v in rows.items():
            def pct(x): return "—" if x is None else f"{x * 100:.0f}%"
            med, budget = v["median_decide_sec"], v["budget_sec"]
            timing = "—" if med is None else f"{med:.0f}s / {budget}s"
            style = "red" if (med and budget and med > budget) else "grey50"
            table.add_row(code, pct(v["approval_rate"]),
                          Text(pct(v["false_alarm_rate"]),
                               style="red" if (v["false_alarm_rate"] or 0) >= .4 else "grey50"),
                          Text(pct(v["ignore_rate"]),
                               style="red" if (v["ignore_rate"] or 0) >= .6 else "grey50"),
                          Text(timing, style=style))
        console.print()
        console.print(table)

    if not s["proposals"]:
        console.print("\n  [green]Nothing the evidence supports changing.[/]\n")
        return
    console.print()
    tone = {"recalibrate": "bold red", "rewrite": "bold yellow", "reword": "bold cyan"}
    for p in s["proposals"]:
        console.print(f"  [{tone.get(p['severity'],'bold')}]{p['severity'].upper()}[/]  "
                      f"[bold]{p['code']}[/]  [dim]← {p['signal']}[/]")
        console.print(f"      {p['reading']}", style="dim")
        console.print(f"      [bold]Propose:[/] {p['propose']}\n")
    console.print("  [dim]Proposals only. Nothing here changes a check on its own — "
                  "a check that\n  retunes itself on its own telemetry is one nobody "
                  "can reason about.[/]\n")
