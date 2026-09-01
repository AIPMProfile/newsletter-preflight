# Engineering decisions

Implementation calls, split out of `PRODUCT_DECISIONS.md` so that file holds
product judgment and this one holds the mechanics. Numbering is unchanged and
deliberately not compacted: the codebase and the other documents reference these
by number, and renumbering to look tidy would break every one of those links.

Nothing here was deleted or rewritten in the move. A log that quietly edits its
own history is worth less than one that shows where it was wrong.

---

## D4 — The 2.0s SLA is enforced by budget, not by hope

**Decision.** The deterministic engine and link probe run first and in parallel;
the LLM phase gets a hard `1.6s` budget derived from the SLA. If it overruns, the
report ships without Module B and says so. `--deep` lifts the cap to 20s.

**Why.** A real API round-trip plus a live link probe cannot be *guaranteed*
under 2 seconds, and the honest options were: silently blow the SLA, block the
report, or degrade. Degrading is the only one that respects the creator — someone
with a dead link still deserves to hear about the dead link, even if the CTA
review timed out.

**Consequence to watch.** On a slow network, Module B silently stops running. The
footer states the reason on every degraded run; if creators start missing CTA
feedback without noticing, this becomes a two-phase render instead.

---

## D5 — Module B runs on the Flash/Haiku tier, never the frontier tier

**Decision.** `gemini-3.7-flash` at `thinking_level=LOW` (see D17 for the
provider choice). On Anthropic, `claude-haiku-4-5`. Both overridable via
`PREFLIGHT_MODEL`.

**Why.** Not cost. Module B judges prominence and tone over a digest of a few
hundred tokens — a task where the marginal quality of a larger model is small and
the marginal latency is not. Inside a 2-second budget, the faster model produces
a better *product*. The env vars exist so the benchmark can measure that claim
rather than assume it.

**Why `thinking_level=LOW` and not the default.** Gemini 3.x Flash defaults to
`MEDIUM`, which spends reasoning tokens — and wall clock — on a judgment this
size does not need. `MINIMAL` through `HIGH` are all reachable via
`PREFLIGHT_THINKING_LEVEL`, so the tradeoff is measurable with `eval --live`
instead of asserted here.

---

## D14 — Missing credentials degrade; they never fail the run

**Decision.** No API key means Module A still runs, the report still renders, and
the footer explains what is missing and how to enable it.

**Why.** Roughly 70% of the findings on a typical broken email come from Module
A. Refusing to run without a key would withhold all of them over a feature the
creator may not have configured yet.

---

## D15 — `audit` exits 0 unless you ask it not to

**Decision.** Non-zero exit only under `--strict`.

**Why.** Interactive use should never look like a crash. CI and pre-send hooks
opt into blocking explicitly; `eval --strict` is the same contract for the agent's
own quality gate (F1 floor, zero clean-control false positives, no SLA breach).

---

## D16 — Serialization churn is minimized, and the residue is disclosed

**Decision.** The fixer serializes with a custom formatter that preserves
attribute order, void-tag style (`<img ...>`, not `<img ... />`), and the
creator's own doctype casing. It does **not** preserve indentation on
whitespace-only lines, because BeautifulSoup's parser collapses those before the
fixer ever sees them.

**Why it matters.** The `fix` command prints a change summary and invites the
creator to diff the result. Alphabetized attributes and XHTML-closed void tags
made that diff unreadable — real changes buried in cosmetic ones — which defeats
the purpose of showing the work. Fixing the formatter removed most of it.

**Why the rest stays.** Eliminating the indentation churn means either a
different parser (`html5lib`: a new dependency, and roughly an order of magnitude
slower) or fragile post-processing. The residue is invisible in every mail client.
So the CLI says exactly what it preserved rather than claiming the file is
untouched.

---

## D17 — Gemini is the default provider; the Anthropic adapter stays

**Decision.** Module B calls `gemini-3.7-flash` through `google-genai` by
default. The Anthropic adapter remains behind `PREFLIGHT_PROVIDER=anthropic` as
an optional extra (`pip install -e ".[anthropic]"`).

**Why keep both.** Deleting a working adapter would have been the tidier diff and
the worse engineering. The entire point of Module D is to *measure* Module B, and
a benchmark that can only ever see one provider cannot answer the first question
anyone will ask: is this model the right one for this job? `eval --live` now runs
the same corpus, the same prompt, and the same ground truth against either
provider. The seam costs one dispatch dict and one config dataclass.

**What made it cheap.** `LLMAssessment` was already a Pydantic model driving
structured output. Gemini's `response_schema` accepts it directly and returns a
validated instance on `.parsed`, exactly as Anthropic's the provider's own structured-output call does.
The prompt, the digest, the finding codes, and the ground truth were untouched by
the switch — which is the payoff for having made the structured contract the
boundary in the first place.

**Failure handling is provider-shaped.** `_degradation_reason` maps each
provider's exceptions onto statuses a creator can act on — missing key, wrong
model for this key, rate limited, budget exceeded — because "APIError" in a
pre-send report is not information. The no-key path is checked before dispatch so
it costs neither an import nor a socket.

---

## D19 — Our budget is the authority over the SDK's retries

**Decision.** The Gemini client is constructed with
`HttpOptions(timeout=budget, retry_options=HttpRetryOptions(attempts=1))`.

**Why.** The SDK retries retryable statuses by default. On a rate-limited key
that turned a fast, precise `429 RESOURCE_EXHAUSTED` into six seconds of silence
followed by `exceeded 6.0s budget` — a status that sends the user to investigate
latency when the actual problem is quota. Retrying inside a budget the caller
owns trades an accurate error for an inaccurate one.

**Related.** `MINIMAL` is rejected by `gemini-3.7-flash` with a 400; it exists
only on the flash-lite tier. `LOW` is the floor for the default model.

---

## D20 — The default model is the one that is actually available

**Decision.** `gemini-3.5-flash-lite`, not `gemini-3.7-flash`. This reverses the
initial recommendation, on evidence gathered after the key was live.

**What changed.** `gemini-3.7-flash` measured 3502 ms when healthy, then began
returning `503 UNAVAILABLE - this model is currently experiencing high demand`,
hanging ~20 s before failing. `gemini-3.5-flash-lite` completed in 2036-2299 ms
across every attempt and produced the same finding codes on `sample_4`
(`spam.trigger_phrase`, `cta.buried`, `cta.weak_prominence`).

**Why availability outranks a quality edge here.** Module B's job is a judgment
on a few hundred tokens, and both tiers make it correctly on the benchmark. A
model that is measurably faster and answers every time beats a slightly stronger
model that intermittently does not answer at all — especially in a tool used in
the last minute before a send. `PREFLIGHT_MODEL=gemini-3.7-flash` remains one env
var away for anyone who wants the stronger reviewer and can absorb the variance.

**Retry policy follows from the same evidence.** Transient capacity (500/502/
503/504) gets one extra attempt; `429` never does. Quota does not heal in 200 ms,
and retrying it burns the budget before reporting the real cause — which is how
a rate limit first showed up as `exceeded 6.0s budget` rather than as a rate
limit. Unrecognized provider errors now carry the provider's own message
through, because `ClientError` on its own told the user nothing.

---

## D21 — Severity is part of the match key, for deterministic findings only

The benchmark used to match on `(code, target)`. A check that emitted the right
code at the wrong severity scored as a clean true positive — while severity is
what sets the readiness score (ERROR −12, WARN −5) and what decides the verdict.
An `ERROR` silently demoted to `WARN` turns a HOLD into a REVIEW, and the number
said everything was fine.

Expected entries for Module A now carry a severity and the match enforces it. A
mismatch is recorded as a **severity drift**, itemized separately from a plain
miss: the check did fire, so calling it a false negative would misdescribe the
failure and send someone looking for a check that is not broken.

**LLM entries deliberately carry no expected severity.** Severity there is the
model's judgment, and the fixture supplying it is authored — pinning it would
score the author against their own opinion. This is the same reasoning that
already lets Module B entries use a wildcard target: where the judgment is
genuinely arguable, ground truth does not pretend otherwise.

---

## D22 — Controls are assertions, and ground truth may not contradict itself

Every case already carried a `controls` list — `"good-copy passes at 12.6:1"`,
`"logo has real alt text"`. It was prose. Nothing read it.

Each case now also carries `forbidden`: the same negative expectations, machine
readable. Two things follow that plain false-positive counting could not do.

**Controls see INFO findings.** False positives only ever look at scored
findings, so an advisory note on an element a control calls correct was
invisible. A control asserts a fact about the corpus; contradicting it is a
defect at any severity.

**Ground truth is checked against itself before anything is scored.** The
cheapest way to make a failing benchmark pass is to move the goalposts — add the
finding you are emitting to `expected`. If a control already said that element
was clean, the corpus now asserts two opposite things, and `run_benchmark`
raises instead of reporting a win. D13 said the agent may not edit ground truth;
this is the part that notices when a human does it by hand.

A wildcard control (`target: "*"`) forbids a code anywhere in the sample, which
is how "contrast, links, and alt text are all correct here" becomes enforceable.

---

## D23 — We score the verdict and the repair, not just the finding

What we promise a creator is an answer to "can I send this", and a repair that
makes the answer yes. We were measuring neither. We measured findings, which is
the middle of the pipeline and neither end of it.

Three things changed.

**The verdict is scored.** Hold, review or ready is the one output a creator
acts on, and it is now right or wrong rather than merely implied by the findings
underneath.

**The repair is scored.** Every reference email is repaired, re-checked, and
judged on how much of what we offered actually landed, whether personalisation
survived, and whether running it again is a no-op.

**Repairs that need permission are named.** A repair we advertise as one click
and then decline to perform is a promise broken, so it is reported by name
rather than averaged into a rate that hides it.

**"Settles" means a second attempt changes nothing**, not that it produces an
identical file. Re-reading and re-writing a document tidies its indentation, and
comparing text would measure our formatter rather than our repair.

**We measure the repair a creator actually runs**, not the internal step beneath
it. Repairing pale text changes a colour, which can create a new dark-mode
problem — so the real repair already runs more than once, on purpose. Scoring
the internal step reported a defect the product does not have.

### What this immediately found

The one-click button was advertising a repair it would not perform. That is
D29, and it was invisible until the repair itself was measured.

---

## D24 — Module B's reliability is a calibration statistic, not an F1

Module B has always reported 100% F1 against an authored fixture. That measures
the harness. It cannot measure the model, and the arrangement is circular: the
same author writes the prompt, the ground truth, and the fixture scored against
it — three artifacts, one opinion, no independent check.

`preflight calibrate` compares the reviewer against labels a human wrote
independently and reports **Cohen's kappa**.

**Kappa, not raw agreement.** The rater and the judge mostly agree that most
things are fine, so raw agreement is inflated by the empty cells — a judge that
found nothing at all would score 98% on a sparse label set. Kappa discounts the
agreement two raters would reach by chance at the same base rates.

**An undefined kappa is not a pass.** When both raters answer identically for
every candidate there is no variance to correct for and the statistic does not
exist; reporting `0.0` would read as total disagreement. `--strict` treats
undefined as a failure, because a label set with no disagreement in it proved
nothing.

**Blindness is recorded and can fail the run.** A labeller who read the model's
output first is not a second opinion. One non-blind file makes the whole run
non-blind.

Only Module B codes are scored. A human re-deciding whether a contrast ratio is
below 4.5:1 is not calibrating a judge; they are redoing multiplication.

`evals/labels/` is empty on purpose. Authoring labels here to produce a number
would recreate exactly the circularity this decision exists to break — the same
reason D11 refuses to relabel an authored fixture as recorded.

---

## D30 — Matching is asymmetric: advisories can be expected, never punished

Ground truth may expect a `COULD_BE_BETTER` finding, and recall counts it. An
*unexpected* advisory is never a false positive.

Without the asymmetry, tier assignment gets corrupted by scoring pressure: a
check would have to be promoted out of advisory to keep its benchmark coverage,
which means choosing a tier for how it scores rather than for what it costs a
creator. That is exactly backwards, and it is how `link.bare_url` nearly ended
up blocking sends.

The old rule — advisory findings must never cost a false positive — is intact.
It just no longer costs recall as the price.

---

