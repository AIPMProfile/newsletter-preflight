# Product decisions

The calls that shaped what this is — grouped by the question they answer.
Each one names what would change it, because a decision you cannot argue with
later is a preference wearing a decision's clothes.

The numbers are not contiguous. The gaps are implementation decisions — CLI
exit codes, SDK retry authority, serialization churn — kept out of this record
because they are engineering, not product judgment. Nothing was renumbered to
close them: the code references these by number, and tidying would break every
one of those links.

---

## What we are building

**D39 — Ready is the product; hold is the exception.**
Walking the publish flow, what is missing is not a warning. It is reassurance:
nothing anywhere says the broadcast is in good shape, so you send because there
is nothing left to click. Most broadcasts are fine, which means a clean result
has to *show its work* — what it examined, how many ways — because silence gives
a creator no more confidence than the Continue button already did.
*Changes if:* creators skip the clean report entirely.

**D27 — Severity names the consequence, not our opinion.**
Error / warning / info is an engineering taxonomy that invites the wrong
argument — is a missing image description really an *error*? The tiers are
**will break**, **will embarrass you**, **could be better**, because the question
a creator is asking is whether to stop.
*Changes if:* creators act on the tiers in an order the names do not predict.

**D33 — Two registers: what it costs you, then the number behind it.**
We had written down that most creators have no patience for specification
vocabulary, then shipped *"this element sets #1a1a1a text but no background."*
The consequence leads; the measurement moves one level down and never
disappears — the professional needs it to defend the change.
*Changes if:* the measurement stops being reachable in one click.

**D36 — The two lines they read before deciding to open.**
Subject and preview text are not in the email; they sit beside it. We were
silent about the only two lines that decide whether anything else we check ever
gets read, so the check now takes them as input.
*Changes if:* the composer stops owning those fields.

**D18 — The pre-send SLA covers what it can actually govern.**
Two seconds bounds the *deterministic* phases — everything answerable without a
model. That is the part that must feel instant, and it does: ~30ms. A budget
that included a network round-trip would be a promise about someone else's
infrastructure.
*Changes if:* the model becomes fast enough to sit inside the same budget.

---

## What we refuse to build

**D9 — We detect broken links; we never guess their replacement.**
`link.broken` is not auto-fixable. We can prove a link is dead; only the creator
knows where it was meant to go. A wrong-but-live link is worse than a dead one,
because a dead link is visibly broken and a wrong one is not.
*Changes if:* we can propose a candidate and show the destination for approval —
propose, never apply.

**D8 — Liquid is sacred.**
`{{ ... }}` and `{% ... %}` pass through byte-identical. The fixer compares the
token list before and after and **aborts** if it changed, discarding its own
output. A repair that breaks personalisation for twelve thousand people is worse
than every problem it fixed.
*Changes if:* nothing. This is the one that has no trade.

**D28 — The readiness score is gone.**
A hundred points, minus twelve per serious finding, minus five per moderate one.
Nobody could say why a serious finding was worth two and a bit moderate ones,
because the weights were picked to feel right. We refuse to print a
deliverability score because filter behaviour is unknowable from markup —
applying that standard outward and not inward is not a standard.
*Changes if:* someone can defend the weights.

**D32 — Prevalence is measured from sent email, or not claimed.**
The first study established what does *not* count as evidence: an archive page
is a responsive web page whose CSS came from the publisher's site, not the mail
that was sent. It showed 0% dark-mode failure precisely because web pages paint
their own backgrounds. The headline figure stays empty.
*Changes if:* real exports land in `evals/real/`.

**D10 — Alt text is boring on purpose.**
Generated descriptions come from the nearest heading, then link text, then the
filename slug. Deliberately mechanical: the creator's voice is the product, and
an invented sentence in their email is a liberty we have not been given.
*Changes if:* creators ask us to write it.

---

## How we treat the creator's work

**D7 — Auto-fix is conservative by default, and converges.**
The default pass makes only provably safe, reversible changes, and never touches
the stylesheet. Repairing one thing can surface another — darkening pale text
can make it newly fail on a dark screen — so the batch path settles rather than
handing the creator a second button press for work our own repair created.
*Changes if:* fix acceptance falls below 50%.

**D29 — What the button promises, the button delivers.**
The one-click repair listed a dark-mode problem as fixable, then skipped it. A
creator clicked "fix eleven issues", watched the count fall to ten, and was left
with the same broken email and less trust than before. Fix resolution is now
gated at 1.0: advertise a repair you do not apply and the build fails.
*Changes if:* nothing. This is a promise, not a target.

**D34 — Repair one thing without disturbing another.**
Repair used to be all-or-nothing in both directions. That suits the hobbyist and
fails the professional, who wants to see a change and approve it. Undo is a set
of choices, not a stack of edits: every repair is derived from the untouched
draft plus the set you accepted.
*Changes if:* the derived model stops being fast enough to recompute live.

**D3 — Arithmetic never goes to a language model.**
Contrast, luminance, link ratios, alt presence and href structure are computed
before any token is spent, and handed to the model as evidence it is forbidden
to re-derive. Without that instruction it recomputes ratios, gets them wrong,
and invents problems the deterministic side already handled.
*Changes if:* a model becomes cheaper and more reliable than a formula.

**D6 — The dark-mode check simulates the repaint instead of guessing at "dark".**
Not "is this colour dark?" but: *if a client paints `#1a1a1a` behind this, does
the text still clear AA?* The first version used a luminance threshold and
flagged mid-grey. You cannot defend `0.2` to a creator, and you cannot tune it
without breaking something else.
*Changes if:* real client rendering diverges from the simulation.

---

## What we refuse to claim

**D12 — Benchmark numbers are labeled, not laundered.**
Replayed model fixtures are marked `"provenance": "authored"`, and every eval run
says so in yellow: *authored fixtures verify wiring and scoring, not model
quality.* Never relabel one as captured, and never write one to make a failing
benchmark pass.
*Changes if:* nothing.

**D26 — The real-email corpus is empty, and that is the honest state.**
Reference emails are generated from the checks that score them, so the corpus
cannot contain a failure mode its author did not already think of. A perfect F1
means the checks agree with themselves. Shipping a "real" sample written to look
real would be a synthetic one with a misleading label.
*Changes if:* hand-labelled real exports arrive.

**D37 — Real mail found what generated mail could not.**
Generated samples give every element a tidy unique identity. Real newsletters
have twenty thumbnails at the same structural position, and that is normal. We
were treating an artefact of our own corpus as a property of email.
*Changes if:* nothing — this is why D26 matters.

**D11 — The negative control is a first-class metric.**
`sample_6_clean.html` is a fully compliant email. Every scored finding on it is a
false positive, reported on its own line, and `eval --strict` fails if the count
is above zero. Crying wolf is the failure mode that kills tools like this.
*Changes if:* nothing.

**D13 — Ground truth is authored from intent, and the agent cannot edit it.**
The table says what a careful human reviewer would flag. When the agent and the
table disagreed, it was resolved by deciding who was *right* — twice the agent
was, and the table changed. Writing labels to produce a good score recreates
exactly the circularity they exist to break.
*Changes if:* nothing.

---

## How we find out we are wrong

**D35 — Ask which check was wrong, not whether we were.**
Sending over a hold says something is wrong with our judgment but not what.
Waving through a single finding is precise, so we collect the reason: they meant
it, we flagged it wrongly, or they will fix it later. Overriding everything says
the product is wrong; dismissing one check says that check is. Only the second
should ever retire a rule.
*Changes if:* the reasons stop distinguishing anything.

**D38 — Silence is the feedback this audience actually gives.**
The first telemetry assumed a creator who disagreed would say so. Most will not
— they do not hand-edit markup and will not argue with a panel. They scroll past
and send. A finding shown and ignored is the signal, so *ignored* is recorded as
its own outcome.
*Changes if:* creators start using the dismiss reasons at volume.

**The rubrics live in a spreadsheet, not in the code.**
`src/preflight/evals/rubrics.csv` — one row per check: what a good finding looks
like, what a bad-but-technically-correct one looks like, how many seconds a
creator should need to decide, and what we would change first if creators say
the check is wrong. It opens in Sheets, and the code reads it. A rubric is the
definition of *useful*, which is a product artefact; keeping it in Python put it
where the person who owns that definition could not reach it.
*Changes if:* the sheet stops being complete — a test fails the build when a
check has no rubric.

**D40 — The loop proposes; it never retunes itself.**
Behaviour is read against each check's rubric — what a good and a bad finding
look like for that specific check. Without those definitions a dismissal rate is
a number. The loop proposes recalibrations and a human decides; a check that
disables itself is a check nobody notices is gone.
*Changes if:* nothing.

**D31 — We record what the creator did, not only what we found.**
A log of findings measures us. The questions that decide whether this works are
about them, and all of them happen after the report is on screen: did they send
anyway, keep the repair, undo it, ignore it.
*Changes if:* the signals stop predicting anything.

**D25 — Monitoring is opt-in, content-free, and only watches the mix.**
One line per audit — counts, verdict, timings, a document hash. Never the HTML,
the subject, or a URL. It answers whether the check is still right about the mail
people are sending now, which pre-deployment numbers cannot.
*Changes if:* the mix stops being a leading indicator.

---

## Reversed, and kept

**D1 — The verdict leads** *(superseded in part by D28)* — the report opened with
the answer rather than a measurement. Right instinct, wrong artefact: the
measurement it led with was the score, which D28 removed.

**D2 — A clean email must be able to score perfectly** *(superseded by D28)* —
weighted penalties, advisories costing nothing. If a well-built email lands at 93
for an optional shortfall, the number stops meaning anything. The fix was not
better weights. It was no score.
