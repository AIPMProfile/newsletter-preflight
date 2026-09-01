# Reference

Everything you need to run, configure and verify this — kept out of the README
so the README can be about the product.

## Install

```bash
uv venv --python 3.11 .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

Then add a key for Module B:

```bash
cp .env.example .env      # then fill in GEMINI_API_KEY
```

No API key is required to run the tool. Without one the deterministic engine
still runs and the report names the variable that would enable CTA prominence
and spam-signal review.

## Use

```bash
python cli.py audit email.html      # score it, list what would break
python cli.py fix   email.html      # write fixed_email.html
python cli.py eval                  # benchmark the agent against ground truth
python cli.py serve                 # browser UI at http://localhost:8000
```

### Browser UI

`python cli.py serve` runs the three screens against the same engine the CLI
uses — there is no second implementation, so what the browser shows is what the
benchmark measures.

`/editor` is Wren's composer as it ships. Hit **Continue** and it runs the check:
clean sends go straight to `/publish`, anything else opens `/launch-check`.

On the check, **Viewing as → Dark screen** paints `#1a1a1a` behind anything the
email did not paint itself — precisely the failure `darkmode.no_bg_override`
reports. Flip it, watch the text vanish, press **Fix all**, flip back.

Binds to `127.0.0.1`. `--host 0.0.0.0` works but warns. The browser never calls
the model — every request sets `skip_llm`, so a deployed copy cannot spend your
quota.

| Flag | Effect |
|---|---|
| `--strict` | exit 1 on a `HOLD` verdict — for CI and pre-send hooks |
| `--no-llm` | deterministic engine only |
| `--offline` | replay pinned link statuses instead of live HTTP |
| `--deep` | let the intent reviewer run past the 2s SLA |
| `--json` | machine-readable report |
| `--aggressive` | (`fix`) also rewrite the dark-mode stylesheet block |
| `--host` / `--port` | (`serve`) bind address and port |
| `--dry-run` | (`fix`) print the result instead of writing it |

### Configuration

Read from the environment or `.env` (real env vars win over the file).

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | — | `GOOGLE_API_KEY` also works |
| `PREFLIGHT_PROVIDER` | `gemini` | or `anthropic` (`pip install -e ".[anthropic]"`) |
| `PREFLIGHT_MODEL` | `gemini-3.5-flash-lite` | `gemini-3.7-flash` is stronger but slower and 503s under load |
| `PREFLIGHT_THINKING_LEVEL` | `LOW` | `MINIMAL` is flash-lite only; 3.7-flash rejects it |
| `PREFLIGHT_LLM_BUDGET` | `6.0` | seconds for the intent reviewer |

## What it checks

**Module A — deterministic engine.** Runs first, always, in single-digit
milliseconds. WCAG 2.1 AA/AAA contrast against each element's resolved
background; a simulated forced dark-mode repaint that catches text with no
surface of its own and `prefers-color-scheme` rules that recolor text without
recoloring what it sits on; concurrent HTTP probing of every link under a hard
budget; missing and lazy `alt` attributes; bare URLs; text-to-link and
image-to-copy ratios.

**Module B — visual & intent reviewer.** One structured `gemini-3.5-flash-lite`
call at `thinking_level=LOW`, budget-bounded, on a token-efficient digest of the
email. Judges only what parsing
cannot: whether the CTA is prominent and above the fold, and whether the copy
trips spam intuitions. It receives Module A's measurements as evidence and is
prompted never to re-derive them.

**Module C — auto-fix.** Conservative and converging. Shifts failing colors to
the *nearest* compliant shade (`#aaaaaa` → `#767676`, not `#000000`), pins
backgrounds against dark-mode repaint, derives alt text from surrounding context,
wraps bare URLs. Writes inline overrides; never touches the creator's stylesheet
without `--aggressive`. Liquid template logic, layout structure, and attribute
order pass through byte-identical — the command aborts (exit 3) rather than risk
the Liquid. Broken links are reported, never guessed at.

### Latency

The 2.0s SLA covers the **pre-send** phases — the deterministic engine and link
probing, everything answerable without a model. That is the part that must feel
instant: 2ms on the sample corpus, ~1.3s with live link probing.

The intent reviewer is measured and reported separately, because no live model
fits inside 2 seconds. Measured 2026-08-26: `gemini-3.5-flash-lite` @ LOW takes
**~2.0s**; `gemini-3.7-flash` takes **~3.5s** when healthy. The footer prints both
numbers rather than folding one into the other. `--no-llm` skips it entirely.

> **Free-tier keys allow 5 requests/minute per model.** `eval --live` runs six
> samples and will trip that limit; rate-limited rows are reported as such.

## Benchmark

Six synthetic samples, each isolating one failure mode and each containing a
deliberate passing control. Ground truth is authored from intent, not derived
from the agent's output.

```
Module                     Precis.   Recall       F1    TP   FP   FN   FP rate
A · Deterministic engine    100.0%   100.0%   100.0%    26    0    0      0.0%
B · Intent reviewer         100.0%   100.0%   100.0%     5    0    0      0.0%
Blended                     100.0%   100.0%   100.0%    31    0    0      0.0%

clean-control false positives: 0     mean latency: 2.8ms / 2000ms SLA
verdict accuracy: 100%   fix resolution: 100%  reviewer degraded: 0%
```

`sample_6_clean.html` is a negative control: every scored finding on it is a
false positive, tracked as a first-class metric because a tool that cries wolf on
a good send gets uninstalled.

The benchmark scores the whole product, not just detection. **Verdict accuracy**
scores HOLD/REVIEW/READY — the one output a creator acts on. The **fix pass** runs
the fixer over every sample, re-audits it, and reports what fraction of fixable
findings actually resolved, whether Liquid survived, and whether a second pass is
a no-op. **Severity** is part of the match key for Module A, because the right
check at the wrong weight moves both the score and the verdict.

That pass immediately found a real defect and closed it: `darkmode.unsafe_override`
was counted in the one-click button and then skipped, because the parser dropped
`!important` and the override the fixer wrote could never beat the inline
background a previous fix had pinned. Fixed in the parser, where the bug was.
Fix resolution is now gated at 1.0 — advertise a repair you do not apply and the
build fails (D29).

Module B's replayed numbers come from **authored** fixtures — they verify harness
wiring and scoring, not model quality. `eval --live` measures the model directly;
`eval --record` captures real assessments for offline replay. Because provider
and model are env vars, `eval --live` runs the same corpus, prompt, and ground
truth against Gemini or Anthropic — which is the point of having a benchmark.

### Calibrating the reviewer

An F1 against an authored fixture cannot say anything about the model — the same
author wrote the prompt, the ground truth, and the fixture. `python cli.py
calibrate` compares the reviewer against labels a human wrote independently and
reports **Cohen's kappa**, which discounts the agreement two raters would reach
by chance. Raw agreement would flatter a sparse label set: a judge that found
nothing at all can score 98%.

`evals/labels/` ships empty on purpose, and the command says so rather than
printing a number it cannot justify. Labels must be written before reading the
model's output; one non-blind file makes the whole run non-blind.

### After it ships

`evals/real/` is where hand-labelled real newsletters go — the synthetic corpus
is generated from the checks that score it, so it can only contain failure modes
its author already thought of. It ships empty too, because a "real" sample
written to look real is just a synthetic one with a misleading label.

`PREFLIGHT_MONITOR=1` records one **content-free** line per audit — counts,
score, verdict, timings, and a hash of the document; never the HTML, the subject,
or a URL. `python cli.py monitor` shows the finding mix and flags any code whose
share of documents moved sharply, which is the cheapest signal that a check, a
mail client, or the incoming mail has changed. Off by default.

## Development

`PRODUCT_DECISIONS.md` — why the tool behaves the way it does.

```bash
pytest -q                     # full suite, ~5s, no network
python cli.py eval --strict   # gate: F1, clean-control FP, SLA, verdict, controls, severity
python scripts/run_prevalence_study.py   # regenerate the prevalence report
python cli.py calibrate       # reviewer vs. human labels
python cli.py history         # benchmark results over time (local, gitignored)
python cli.py monitor         # finding mix, creator behaviour, rule health
python cli.py loop            # creator signals -> proposed changes, per check
python cli.py harness         # does a click make real mail sendable?
```

