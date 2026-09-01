# Product Decisions

> The full record, including the decisions that were reversed. Implementation calls live in
> [`ENGINEERING_DECISIONS.md`](ENGINEERING_DECISIONS.md); numbering is shared
> and continuous across both.

Running log of the calls that shaped `preflight-agent`, why they were made, and what
would change them. Decisions live here rather than in commit messages because the
reasoning outlives the diff.

---

## The problem we are actually solving

The bottleneck in creator publishing velocity is not writing. It is the last ten
minutes before send: the pixel tweaking, the "did I break dark mode again", the
link nobody clicked because it 404'd. That anxiety is expensive and invisible —
it never shows up in analytics because it happens before the send.

So the product is not a linter. It is the answer to one question, asked with a
thumb already on the send button: **can I send this?**

Everything below follows from that framing.

---

## D1 — The verdict leads *(superseded in part by D28)*

**Decision.** The report opens with the answer to "can I send this", not with a
measurement.

**Why.** A number on its own forces a creator to invent a threshold — is 74
good? The verdict answers the question they actually have, and the findings
underneath explain it. Three buckets lose nuance; nuance is what the list is
for.

**What changed.** The original version paired the verdict with a 0–100 score.
The verdict half held up and is still how the report opens. The score did not,
and D28 removed it. Kept here rather than rewritten, because a decision log that
quietly edits its own history is worth less than one that shows where it was
wrong.

---

## D2 — A clean email must be able to score perfectly *(superseded by D28)*

**Decision, at the time.** Weighted penalties per finding, with advisory notes
costing nothing.

**Why it mattered.** If a well-built email lands at 93 because of an optional
shortfall, the number stops meaning anything and creators learn to ignore it. A
tool that always finds something is a tool that is always ignored.

**What survived.** The instinct was right and is now enforced more directly: an
advisory note never blocks a send, and the best possible email can reach the
best possible verdict — which is why the clean sample was tightened until it
could. What did not survive was the arithmetic. The weights were indefensible,
and D28 replaced the whole scheme rather than retuning it.

---

## D3 — Arithmetic never goes to a language model

**Decision.** Contrast ratios, luminance, text-to-link ratios, image-to-copy
ratios, alt-text presence, and href structure are all computed in Module A. The
LLM receives those numbers as evidence and is explicitly forbidden from
re-reporting them.

**Why.** Latency and cost are the obvious reasons. Correctness is the real one: a
model asked to eyeball a contrast ratio will sometimes be wrong, and a wrong
accessibility claim is worse than no claim.

**Where we deviated from the brief.** The brief filed "text-to-link ratio
anomalies" under Module B. It is division. It moved to Module A, and the computed
ratio is passed into the prompt as context. The architectural principle beat the
module boundary.

---

## D6 — The dark-mode check simulates the repaint instead of guessing at "dark"

**Decision.** Rather than "is this text color dark?", the check asks: *if a client
paints `#1a1a1a` behind this element, does the text still clear WCAG AA?*

**Why.** The first version used a luminance threshold and flagged `#767676` —
mid-grey, and arguably fine. Thresholds like that are unarguable in both
directions: you cannot defend `0.2` to a creator, and you cannot tune it without
breaking something else. The simulation is defensible, self-documenting, and
produced identical results on the corpus with a rationale we can print in the
finding itself.

**Second bug, second code.** `darkmode.no_bg_override` (nothing paints behind the
text) and `darkmode.unsafe_override` (a `prefers-color-scheme` rule recolors text
without recoloring its surface) are separate codes because the fixes differ.

---

## D7 — Auto-fix is conservative by default, and converges

**Decision.** The default pass only makes changes that are provably safe and
reversible: shift a failing color to the *nearest* compliant shade, pin an
existing background so a client cannot repaint it, add alt text, wrap bare URLs.
It writes **inline overrides** and never edits the creator's stylesheet. Anything
that touches creator CSS is behind `--aggressive`.

**Why "nearest".** A fix that snaps low-contrast grey to pure black is a fix
creators revert, and a reverted fix teaches them to stop running the tool. The
binary search finds the minimum shift that clears AA, so brand colors stay
recognizably themselves (`#aaaaaa` → `#767676`, not `#000000`).

**Why it loops.** One pass is a lie: darkening text can push it into the
dark-mode risk band, and pinning a background changes the contrast pair. `fix`
audits, fixes, and re-audits until the fixable set is empty (max 3 passes), then
prints the resulting score as a receipt.

---

## D8 — Liquid is sacred

**Decision.** `{{ ... }}` and `{% ... %}` pass through byte-identical. `fix`
compares the token list before and after and **aborts with exit code 3** if it
changed, discarding the output.

**Why.** A fix that breaks personalization is worse than the bug it fixed, and it
fails silently at send time to thousands of people. This is the one place the
tool would rather do nothing than do something.

---

## D9 — We detect broken links; we never guess their replacement

**Decision.** `link.broken` is not auto-fixable.

**Why.** Every other fix has one obviously correct answer. "Which URL did you
mean?" does not. Guessing here would be the single most damaging thing this tool
could do.

Related: an unanswered link probe is reported as *unknown*, never as broken.
Telling a creator that a working link is dead is worse than staying silent.

---

## D10 — Alt text is boring on purpose

**Decision.** Generated alt text is derived from the nearest heading, then the
link text, then the filename slug, then a neutral fallback.

**Why.** A confidently wrong image description is worse than a plain one, and the
creator will edit it either way. When an API key is present the surrounding copy
gives the model better context — but the deterministic path has to be safe on its
own, because it is the one that always runs.

---

## D11 — The benchmark's negative control is a first-class metric

**Decision.** `sample_6_clean.html` is a fully compliant email. Every scored
finding on it is a false positive, reported on its own line in the telemetry
table, and `eval --strict` fails if the count is above zero.

**Why.** Precision and recall over five broken files reward aggression. The clean
control is the only number that punishes it, and crying wolf on a good send is
the fastest way to lose a creator permanently. Current: **0**.

Each of the other five samples also contains a deliberate *passing* control — a
compliant paragraph, a live link, a real alt attribute — so a check that fires at
everything fails the benchmark even on the file it is supposed to catch.

---

## D12 — Module B's benchmark numbers are labeled, not laundered

**Decision.** Shipped LLM fixtures are marked `"provenance": "authored"`, and the
eval output says so in yellow, every run: *authored fixtures verify wiring and
scoring, not model quality.*

**Why.** Reference answers written by the same author as the ground truth score
100% by construction. That number is real as a regression test on the *harness*
and meaningless as a measurement of *the model*. Printing the caveat is cheaper
than being asked about it later. `eval --record` captures real assessments
(marked `"recorded"`), and `eval --live` measures the model directly.

---

## D13 — Ground truth is authored from intent, and the agent is not allowed to edit it

**Decision.** `ground_truth.json` says what a careful human reviewer would flag.
When the agent and the table disagreed during development, the disagreement was
resolved by deciding who was *right* — twice the agent was, and ground truth
changed; the dark-mode threshold change came from the opposite conclusion.

**Why.** A benchmark regenerated from the agent's own output measures nothing.
The `--regenerate` flag rewrites samples and ground truth together from
the generator, where the intent is written down once and every change to it shows up in review.

---

## D18 — The 2.0s SLA now covers what it can actually govern

**The measurement.** Once a real key was in place (2026-08-26, `sample_4`, free
tier, one call each):

| Configuration | Intent-review latency |
|---|---|
| `gemini-3.7-flash` @ `thinking_level=LOW` | 3502 ms |
| `gemini-3.5-flash-lite` @ `LOW` | 2036 ms |
| `gemini-3.5-flash-lite` @ `MINIMAL` | 2299 ms |

**No live model fits inside a 2.0s total budget.** The fastest configuration
measured spends the entire SLA on its own call, before parsing, link probing, or
rendering. D4 anticipated this tension and guessed the budget could absorb it;
the numbers say otherwise.

**Decision.** `SLA_MS` now governs the *pre-send* phases — the deterministic
engine and link probing, everything answerable without a model. That is the part
that must feel instant, and it does: 2 ms on this corpus, ~1.3 s with live link
probing. The intent reviewer gets its own budget (`PREFLIGHT_LLM_BUDGET`,
default 6.0 s) and its cost is printed next to the SLA line rather than folded
into it.

**Why not just keep the 1.6s budget.** Because it produced a default where
Module B *always* timed out. A feature that silently never runs is worse than a
feature that honestly takes four seconds.

**Why not silently redefine the number.** A 2.0 s claim covering a phase that
measurably takes 3.5 s is a number that lies. The footer now reads
`pre-send 2ms / 2000ms SLA ✓ · intent review adds 3502ms`, so both facts are on
screen and neither is doing PR for the other.

**The better answer, not yet built.** Two-phase rendering: print the
deterministic report the moment it is ready (2 ms) and append the intent review
when it lands. That makes time-to-first-useful-output the SLA, which is the
number a creator actually experiences. It changes the report UX, so it is
flagged here rather than done unilaterally.

---

## D25 — Monitoring is opt-in, content-free, and only watches the mix

Everything above is pre-deployment. It answers "how did we do on these six
files", which cannot answer "is the agent still right about the mail people are
sending now". Three checks have real reasons to drift: `link.broken` depends on
the live web, dark-mode behaviour changes as clients change, and export HTML
changes whenever an ESP updates its templates.

`PREFLIGHT_MONITOR=1` appends one line per audit; `preflight monitor` reports
the finding mix and flags any code whose share of documents moved by 20 points
or more.

**Off by default.** A pre-send tool that starts writing files nobody asked for
is a tool people stop trusting with unpublished drafts.

**No email content, ever.** Not the HTML, not the subject, not a URL. A 12-char
SHA-256 prefix identifies repeat audits of one document and reverses to nothing.
Tested by asserting known strings from a draft never appear in the log.

**Failure is silent.** A read-only home or a full disk must not fail a pre-send
check. The creator's email matters; the telemetry does not.

**Share counts documents, not findings.** One email with forty contrast failures
is one email with a contrast problem. Rating by raw count would let a single
pathological document redefine the baseline.

Drift says *look here*. It does not say what broke, and it is not wired to
anything automatic — with this volume, a threshold that acted on its own would
be noise.

---

## D26 — The real-email split is empty, and that is the honest state

Our reference emails are generated from the checks that score them.
That circularity has a hard consequence: **the corpus cannot contain a failure
mode its author did not already think of.** Every sample exists because a check
exists, so a perfect F1 means the checks agree with themselves.

`evals/real/` is where hand-labelled newsletters that were not generated from
the checks belong — real exports, scored on their own line, never blended into
the synthetic numbers. Averaging them would hide which one moved, and they
measure different things: "passes the checks I wrote" versus "works on mail
people actually send".

It ships empty rather than seeded, because a "real" sample written to look real
is just another synthetic sample with a misleading label — the same dishonesty
D11 forbids for fixtures. Expect the score there to be lower when it is filled.
That gap is the finding.

---

## D27 — Severity names the consequence, not our opinion

The old tiers were error, warning and info. That is an engineering taxonomy. It
tells a creator nothing about whether to stop, and it invites the wrong argument
— is a missing image description really an *error*? The question a creator is
actually asking is what it will cost them.

- **Will break** — the email does not work. A dead link, a link to nowhere,
  personalisation that arrives as raw code.
- **Will embarrass** — it sends, it works, and it costs them. Text too pale to
  read, a surface that inverts on a dark screen, an image with no description,
  a send so image-heavy that filters may bury it.
- **Could be better** — advisory. Never blocks, never scored.

Two assignments are worth defending. A raw web address left unlinked is
advisory: it is ugly, it is still readable, and blocking a send over it would
infuriate someone. A send that is mostly pictures is not advisory: the
subscriber may never see it at all, which is a real cost even though it is a
probability rather than a certainty.

Dark-mode collapse sits under "will embarrass" rather than "will break". It is
arguably a broken render — invisible text — but both tiers stop the send, so the
verdict is identical and only the wording differs. Worth flipping if the label
ever reads wrong; nothing downstream depends on the choice.

---

## D28 — The readiness score is gone

The score took a hundred points and subtracted twelve for each serious finding
and five for each moderate one. Nobody could say why a serious finding was worth
two and a bit moderate ones, because there was no reason — the weights were
picked to feel right.

That is the same fabrication we refuse to commit elsewhere. We will not print a
deliverability score, because filter behaviour cannot be known from the markup
and a confident number would be a lie. Applying that standard outward and not
inward is not a standard.

It was also unusable. "Sixty-four out of a hundred" is not something a creator
can act on. What they can act on is how many things will break and how many will
embarrass them.

So the verdict is derived rather than scored:

- **Hold** — something will break or embarrass. Do not send.
- **Review** — nothing blocking, but we noticed things.
- **Ready** — nothing found at all.

**Ready is deliberately strict.** A single advisory note drops a send to review,
because saying "ready" over something we just flagged is a small lie. That makes
ready hard to reach — so we tightened our own reference email until it could
reach it. A verdict the best possible email cannot achieve is a dead tier, and
an untested one.

The report now opens with a count a creator can act on: *two will break, nine
will embarrass, one could be better*.

---

## D29 — What the button promises, the button delivers

The one-click repair listed a dark-mode problem as fixable, then skipped it. A
creator clicked "fix eleven issues", watched the count fall to ten, and was left
with the same broken email and rather less trust than before they started.

Two things were wrong, and only one of them was the repair.

**We were writing a correction nobody could see.** In email, styling attached
directly to an element normally beats styling in a stylesheet — except when the
stylesheet insists, which is the one mechanism a dark-mode rule has for
repainting a surface that was already painted. We were discarding that insistence
while reading the document, so the correction we wrote was real, correct, and
invisible to the check that was supposed to notice it. Fixed where the fault
was: in how we read styling, not in how we repair it.

**Fixable turned out to be two questions.** Some repairs only work by rewriting
the creator's own stylesheet, and the professional segment has told us plainly
that we do not touch their styling uninvited. So a repair now declares whether
the default path can perform it. The one-click button counts only those;
anything needing permission is offered separately, with the cost stated. The
professional's guarantee is structural rather than a promise: the default path
has no route to their stylesheet at all.

The benchmark holds it there. Every repair the button advertises must land, or
the build fails.

**A correction worth recording.** We first reported the repair as needing two
attempts to settle, and it does not. We had measured an internal step rather
than the repair a creator actually runs — which already repeats itself, for
exactly the reason we were "discovering". The lesson generalises: a measurement
aimed at the wrong thing will report a defect that does not exist, and it will
do so confidently.

---

## D31 — We record what the creator did, not only what we found

A log of findings measures us. The questions that decide whether this product
works are about them, and every one of them happens after the report is on
screen:

- **Did they send anyway?** The trust question. Someone who reads a hold and
  ships regardless is telling us the verdict was wrong, and they are usually
  right.
- **Did they change something first?** The product working as intended.
- **Did they keep the repair, or undo it?** Whether what we offer is wanted.
- **How long did it take?** The tax we are adding to shipping.

Three constraints keep those numbers worth having.

**Nothing is inferred.** "Closed the tab and never came back" cannot be seen
from inside a request, so we never write it down. Checks with no recorded
outcome are reported as unresolved, which is what they are — deriving
abandonment from a timeout would be a guess wearing the clothes of data.

**A rate with no denominator is absent, not zero.** Nought per cent of no sends
is not a fact about the product, and it reads exactly like one. Every rate is
shown with the count behind it, and the report says out loud when that count is
too small to mean anything.

**Observing this needed a real send.** The send control was a stub, which meant
the trust question had no possible answer. It now confirms over a hold, records
what happened, and ties back to the check it followed. Without that, the most
important metric in the strategy would have been defined in a document and never
populated — which is worse than not defining it.

We store no content of any kind: not the email, not the subject, not a web
address. A short fingerprint links a decision to the check it followed and
reverses to nothing.

---

## D32 — Prevalence is measured from sent email, or not claimed

`scripts/run_prevalence_study.py` exists to answer "how often does this actually
happen", and the first thing it establishes is what does **not** count as
evidence.

A Substack or Beehiiv archive page is a responsive web page. Its CSS comes from
a React app and has almost nothing to do with the MIME part that reached an
inbox. The first sample makes the point with data: across six real archive
pages, **0%** showed dark-mode collapse — because web pages paint their own
backgrounds, and email templates routinely do not. A headline built from that
sample would be confidently wrong about the exact failure this tool exists to
catch.

So sources are ranked and never blended. `sent_email` — exports, saved inbox
HTML, view-in-browser pages that serve the sent HTML — is the only category that
supports a claim about email. `web_archive` is reported on its own line, behind
a required `--allow-web-archive` flag, with the caveat printed above the table.

The headline is currently empty, and the report says so rather than filling it.
`evals/real/*.html` is gitignored: real exports can carry subscriber data, and
the manifest makes the corpus reproducible without committing anyone's mail.

---

## D33 — Two registers: what it costs you, and the number behind it

We had written down that our largest group of creators has no patience for
specification vocabulary — that a contrast ratio means nothing to them and "this
will be hard to read" means everything. The product then said this:

> *This element sets #1a1a1a text but nothing between it and the client paints a
> background. Forced dark mode drops it to 1.00:1.*

Which is precisely the vocabulary we had just finished saying does not work. The
principle was in the strategy and absent from the product — the same failure as
claiming a metric we could not compute.

Every finding now says two things:

- **What it costs them**, in their words. *"This disappears in dark mode.
  Roughly half your readers open email on a dark screen, and they will see a
  blank space here."*
- **The measurement**, one level down — dimmed in the terminal, behind a "why"
  in the browser.

Nothing was deleted. The numbers moved down a level, which is the entire point:
this is an information-hierarchy decision, not a simplification. Removing the
evidence would have failed the professional, who may need to defend the change
to someone else.

**Enforced rather than aspirational.** The build fails if any creator-facing
sentence contains a colour code, a ratio, a markup name, or specification
jargon — and separately if the measurement has gone missing rather than moved.
Passing by deleting the evidence is not available. Checked against the old
wording: every previous message trips it.

### Evidence you can look at

A ratio is a number a creator has to take on trust. The same two colours shown
side by side is something they can judge in a second. So contrast findings
render their own text on their own background beside the corrected shade, and
dark-mode findings show the same text on a light ground and a dark one — the
second being what roughly half the list actually receives.

Deliberately not everywhere. A dead link gets no picture; a picture that adds
nothing is decoration, and decoration in a pre-send report is noise.

### The moment it clears

Going from blocked to sendable is the emotional payoff of the entire product,
and it used to be a silent re-render. It now gets one short beat: the old
verdict struck through, the new one, what changed, and what still needs them. It
stays on screen rather than flashing past, because the creator is deciding
whether to send and the answer should still be there when they look back.

The motion is a third of a second and respects a reduced-motion preference. Our
job is to get out of the way, not to celebrate.

---

## D34 — Repair one thing without disturbing another

Until now the repair was all or nothing in both directions: fix everything, or
undo everything. That suits the hobbyist and fails the professional, who told us
plainly that they want to see a change and approve it, not receive it.

It also quietly broke the most important number we collect. A creator who
disagrees with one finding had exactly one move available — send anyway — so the
log could not tell "this particular check is wrong" from "I do not trust this
product". Both arrived as the same event, and the criterion that is supposed to
retire a bad check would have fired on an accumulation of small, reasonable
disagreements and pointed at the wrong thing entirely.

So each finding now carries four choices: repair it, preview what the repair
would do, undo it, or wave it through with a reason.

**The state is the untouched draft plus the set of repairs they have accepted.**
Everything is recomputed from that, every time. The obvious alternative — edit
in place, keep a stack of undos — produces a class of bug that is very hard to
get out again: undo the second repair, and the fourth one that was applied on
top of it quietly breaks. Recomputing removes the possibility rather than
managing it. There is no ordering between repairs to get wrong.

Batch repair stays exactly where it was. It is the hobbyist's path, and it now
runs through the same machinery rather than a second one that can drift.

**One repair must touch one thing.** Fixing a single unlinked web address used
to rewrite every unlinked address in the document, because that repair ignored
what it had been asked to do. Correct for a batch, wrong for a single click, and
a creator who asked for one change and received five would be right never to
trust the button again.

---

## D35 — Ask which check was wrong, not whether we were

Sending over a hold tells us something is wrong with our judgment. It cannot
tell us *what*, and a product that only knows it is disliked cannot improve.

Waving through a single finding is a precise signal, so we collect the reason:
the creator meant it, we flagged it wrongly, or they will deal with it later.

**Only "flagged wrongly" counts against a check.** This distinction is the whole
value of collecting reasons. A check can be dismissed constantly and be working
perfectly — a creator who deliberately ships an image with no description is
telling us about their priorities, not about our accuracy. Counting those would
retire checks that are right.

**A check is never retired on thin evidence.** Something dismissed as wrong
three times out of three is a rumour, not a finding. Nothing is flagged for
recalibration below twenty decisions.

**The automatic pause was removed.** This decision originally shipped one behind
a flag, and D40 then stated the loop only ever proposes. Both were in the
repository at once, which meant the log asserted two opposite things and the
weaker one was live code. It has been deleted rather than documented around: a
principle with an opt-out is not a principle, and the opt-out was the part a
sharp reader would have found first.

Worse, it was masked. The pause could not fire because the health calculation
was diluting its own denominator with ignores — so a check creators had called
wrong forty-five percent of the time read as nineteen percent and stayed quiet.
Fixing that arithmetic would have silently switched the pause on. Two defects,
each hiding the other.

The point is that recalibration can now aim at a rule rather than at the
product.

---

## D36 — The two lines they read before deciding to open

The subject and the preview text are not in the email. They sit beside it in the
composer, and until now our checks could not see them at all — which meant we
were silent about the two lines that decide whether anything else we check ever
gets read.

Three additions, all advisory, because none of them breaks a send: a subject
that a phone will cut off before the point arrives, a missing preview line that
lets the inbox fill the space with an unsubscribe notice, and link text that
tells a reader nothing about where it goes.

They are passed in rather than dug out of the document, which means a file
checked on its own simply skips them. That is the honest behaviour: inventing a
subject in order to have something to check would be worse than saying nothing.

The truncation threshold is deliberately generous. The exact cut-off moves with
device and text size, so we flag well past the edge rather than nagging someone
sitting near it — a check that fires on a reasonable subject line trains people
to ignore the ones that matter.

---

## D37 — Real mail found what generated mail could not

Our reference emails are generated from the checks that score them, so every
element in them has a tidy unique identity. Real newsletters do not. Twenty
article thumbnails sit at the same place in the structure, and that is normal.

We were treating an element's position as if it identified one element. When
twenty shared a position, nineteen of them vanished from our view: the repair
edited the same thumbnail twenty times over and reported twenty repairs
completed. Nineteen images kept no description, and the creator was told they
had all been fixed.

That is the D29 failure again — claiming work we had not done — and the
generated samples could never have shown it, because we had given every element
a unique name ourselves. It surfaced within minutes of pointing the repair
harness at real documents.

The fix hands out each matching element once. The honest count fell immediately:
one document went from sixty reported repairs to twenty-two real ones, and from
nineteen images silently unrepaired to none.

The general lesson is the one the empty prevalence headline is also about. A
corpus built from your own assumptions confirms your assumptions. It cannot
contradict them, and the things it cannot show you are exactly the things worth
knowing.

---

## D38 — Silence is the feedback this audience actually gives

The first version of the telemetry assumed a creator who disagreed with us would
say so. Most will not. They do not hand-edit markup, and they will not argue with
a panel — they scroll past it and send.

So the loudest signal we had was landing nowhere. A finding shown, understood
well enough to skip, and left alone is feedback, and we were recording nothing at
all for it. Every finding still open at send is now written down as **ignored**.

**Ignoring is not dismissing.** Dismissing is a decision — the creator looked,
disagreed, and told us why. Ignoring is the absence of one. They point at
different problems: a dismissed check is probably wrong, an ignored check
probably failed to explain why it mattered. Collapsing them would send us
recalibrating a check whose only fault was its wording.

Ignores are also deliberately excluded from the decision count. Scrolling past is
not judging, and letting it inflate the denominator would let a check clear the
evidence floor without a single creator having formed an opinion about it.

**We also time the decision.** Not for performance — the engine answers in
milliseconds — but for comprehension. A correct finding that takes ninety seconds
to act on has failed, because at that price creators stop reading the panel. Each
check's rubric carries the budget it should need, and consistently exceeding it
gets a different prescription from being wrong: shorten the sentence, do not
touch the check.

---

## D39 — Ready is the product; hold is the exception

Walking a shipping platform's publish flow, the thing that is missing is not a warning. It is
reassurance. Subject line, canvas, Continue, Send email, Continue — at no point
does anything say the broadcast is in good shape. You do not send because you are
confident; you send because there is nothing left to click.

That is what the test-email-to-yourself ritual actually is. Creators are not
hunting for defects, they are manufacturing a reassurance by hand because the
product does not supply one.

Framing it that way inverts what matters. **Most broadcasts are fine.** If the
job were catching defects, we would be worthless on those sends. If the job is
confidence, those are the sends where we earn our keep.

So the clean result cannot be silence. It says what was examined — how many
checks, across how many elements, links and images — because a check that returns
nothing has given a creator no more confidence than the Continue button already
did. The count comes from the engine itself rather than a constant, so the number
shown cannot drift from what actually ran.

The consequence for the roadmap is larger than the copy change: it means the
product is measured on how often it says *ready* and is believed, not on how much
it finds.

---

## D40 — The loop proposes; it never retunes itself

Creator behaviour is read against each check's rubric — the definition of what a
good finding and a bad finding look like for that specific check. Without those
definitions a dismissal rate is a number; with them you can ask which half of the
definition the check has drifted into.

Four signals, three prescriptions:

- **Waved through as "flagged wrongly"** → the check is wrong. Recalibrate it,
  starting from the lever its own rubric nominates.
- **Shown and ignored** → the check did not land. Rewrite what it costs the
  creator before questioning whether it earns its place.
- **Decided slower than its budget** → comprehension, not accuracy. Shorten the
  sentence and leave the check alone.
- **Waved through as "I meant it"** → evidence about the creator, not the check.
  Counted, and never held against it.

**It stops at a proposal.** A check that quietly retunes itself on its own
telemetry is a check nobody can reason about, and the failure mode is vicious:
creators ignore a check because the wording is poor, the loop reads that as
inaccuracy, loosens the threshold, and the check stops catching the thing it
existed for. Nobody notices, because the number moved the right way.

**Coverage is reported before any recommendation.** Proposals about four checks
out of sixteen is a different statement from proposals about all of them, and
leading with the recommendations would let silence read as approval. Checks
nobody has ever acted on are listed by name.

The evidence floor is the same twenty decisions the kill criteria use. Below it,
a rate is a rumour, and retiring a working check on a rumour is the more
expensive mistake.

---

## What we deliberately did not build

- **Rendering screenshots across real mail clients.** The highest-fidelity answer
  and completely incompatible with a 2-second budget. The dark-mode simulation is
  the cheap 80% of the value.
- **Spam-score prediction as a number.** Filter scores are unknowable from the
  HTML alone; a fabricated "8.2/10 deliverability" would be a confident lie.
  Named, quotable signals are honest.
- **Rewriting copy.** The tool flags a buried CTA and a spam-trigger headline. It
  does not rewrite them. The creator's voice is the product.
- **A daemon or watch mode.** The moment of value is the moment before send.
