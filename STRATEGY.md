# Launch Check — the bet

**One page. The claim, the leverage, the sequence, and how I would know I am wrong.**

---

## The claim

**This is not a defect-detection problem. It is an absence-of-confidence
problem, and that changes what we build.**

Walking the publish flow of a shipping newsletter platform: subject line,
canvas, Continue, Send email, Continue. At no point does anything tell you the
broadcast is in good shape. You
do not hit send because you are confident. You hit send because there is nothing
left to click.

That is why creators send test emails to themselves — and published research on
email marketers puts manual pre-send checking at roughly **20–25%** of them, an
external figure about marketers generally rather than any one platform's
creators specifically.
They are not hunting for bugs. They are manufacturing, by hand, a reassurance
the product does not give them.

**The bet: confidence at the moment of send is a wedge into the composer.** It is
the one point where every broadcast, every creator and every template converge,
and it is currently unguarded.

### What follows from framing it as confidence

Most broadcasts are probably fine. If the job were catching defects, the product
would be worthless on those sends. If the job is confidence, **those are the
sends where it earns its keep** — and being told "nothing here will break" by
something that visibly looked is the entire value.

So *ready* is the product and *hold* is the exception. Which means the check has
to show its work when it finds nothing: what it examined, how many ways, how
long it took. A check that returns silence has given a creator no more confidence
than the Continue button already did.

## What the shipping products already tell us

Three things, observed in the shipping product rather than assumed:

**The category has decided this matters.** A shipping platform has a pre-send
warning in its editor sidebar. Someone built it. That is a validated problem
statement we did not have to fund.

**It is the weakest possible version.** *"One or more of your links contains an
empty HREF value."* One check. Markup vocabulary. It does not say which link, it
cannot fix it, and it cannot take you to it. The distance between that and
something a creator can act on is the opportunity.

**The publish step is unguarded.** Between "Send email" and twelve thousand
subscribers there is a Continue button and nothing else.

## The leverage nobody is using

Creators do not start from a blank page. They start from Digest, Aspen, Column, Note — a small set of shared starting points.

Which means **defects are not distributed, they are inherited.** In the sample
broadcast, 23 of 25 findings trace back to styling the template decided once: text colours that vanish on a dark screen, surfaces that were never
painted, contrast set at design time. That is the deterministic engine on
`web/starter.html`, reproducible with `python cli.py audit
src/preflight/web/starter.html --offline` — the count is stated with the run
that produces it, because a ratio nobody can re-derive is the kind of number
this project refuses elsewhere.

That changes what this is. A per-send checker helps one creator. A quality
signal that aggregates to the template layer fixes the same defect across every
broadcast built on it, including the ones not written yet.

**The per-send check is the sensor. The template layer is where the fix scales.**
Nobody can see that today because nothing measures it.

## Sequence

**Now — the sensor.** Pre-send check at publish: what will break, what will
embarrass, what could be better, in the creator's words, with a one-click repair,
a way to review it themselves, and a way to send anyway. Built.

**Next — the signal.** Aggregate findings by template. If Aspen produces a
dark-mode failure in most broadcasts derived from it, that is one fix in one
place worth thousands of sends. This is the step that turns a utility into
leverage, and it costs almost nothing once the sensor is running.

**Then — prevention.** Move the check earlier: ambient in the editor as they
write, and eventually into the templates themselves so the defect cannot be
authored. The end state is that this product becomes unnecessary, which is the
correct ambition for it.

## How I would know I am wrong

Stated in advance, so they cannot be renegotiated later.

| Signal | Reading | Response |
| --- | --- | --- |
| Override rate above 40% | Creators do not believe the verdicts | Stop shipping checks. Recalibrate against what they overrode. |
| A single check dismissed as "flagged wrongly" above 40% | That check is wrong, not the product | Retire or recalibrate that check. The rest carries on. |
| Fix acceptance below 50% | We are repairing the wrong things | Fall back to flagging. Stop promising repair. |
| Audit rate below 10% once embedded | The moment is wrong, or the placement is | Question the placement before the checks. |
| Median resolution above 120 seconds | We replaced a twenty-minute tax with a two-minute one and called it a win | Cut checks until it is under a minute. |

The first two are the ones I would watch. A creator who overrides is telling us
the verdict was wrong, and they are usually right.

## What I would stop doing

**Adding checks.** Sixteen deterministic checks, plus four the reviewer can
raise, is already more than enough to test the bet, and
every additional one raises the odds of the failure mode that actually kills
tools like this: crying wolf. The next check ships only when telemetry shows
creators acting on the ones we have.

**Chasing accuracy.** The engine measures at 100% against its benchmark. That
number cannot go up and does not matter. Reach can.

**Building for the terminal.** Impact is reach times accuracy, and this has
spent almost all of its effort on the second term.

## What I do not know

The honest list, in the order I would resolve it:

1. **Is the pre-send moment the right one**, or does the anxiety actually live
   earlier, at template choice? The template insight above hints at the second.
2. **How often does this really happen in sent mail?** The harness is built and
   the corpus is empty. Archive pages cannot answer it — they showed a 0%
   dark-mode failure rate precisely because they are web pages.
3. **Which findings do creators act on?** Any check with a persistently low
   action rate should be deleted, not tuned.
4. **Does the dark-mode simulation match real clients?** It is modelled, not
   measured against Gmail, Outlook and Apple Mail.

None of these needs a quarter. All four are a week of creator conversations and
fifty real exports, and I would do that before writing another check.

---

*Detail: [`docs/PROBLEM.md`](docs/PROBLEM.md) — segments, metrics, kill criteria.
[`docs/PRODUCT_DECISIONS.md`](docs/PRODUCT_DECISIONS.md) — thirty-seven decisions, including
the reversed ones.*
