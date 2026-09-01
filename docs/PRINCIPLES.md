# Principles

**`REFERENCE.md` holds the mechanics** — install, commands, configuration and the
benchmark. **`PRODUCT_DECISIONS.md` holds the reasoning**; read the decision before overturning something that looks
arbitrary. Several have been reversed once already, and both directions are
recorded.

This file is about judgment: what this product is for, and the handful of
principles that are easy to break without noticing.

## What we are building

A creator is about to send something to twelve thousand people and cannot take
it back. The last twenty minutes before that moment go on checking, badly — a
test send to themselves, a squint at a phone, clicking a few of the links. It
misses most of what actually goes wrong, because nobody eyeballs a contrast
ratio and nobody previews a dark screen.

We answer one question in under two seconds: **can I send this?** Then we repair
what we can safely repair, and leave everything else alone.

## Who we are serving

Two people, wanting opposite things.

The **hobbyist** writes in the composer, uses a stock template, has no CSS
opinions and nobody to ask. They want the problem gone, not explained. They will
not read a specification, and a wall of findings makes them feel their email is
broken when it is fine.

The **professional** has a hand-built template, brand guidelines, and revenue
riding on the send. They want to see the change before it happens, and they will
not forgive us for touching their styling uninvited.

Almost every decision here is a consequence of serving both without averaging
them into something neither wants. When a new decision is hard, ask which of the
two it is for; if the answer is "both, equally", it is probably wrong.

## The principles that are easy to break

**Never spend judgment on something arithmetic can answer.** Contrast is a
calculation. Whether a call to action is buried is not. Sending the first to a
model costs money, adds latency, and gives a less reliable answer than the
maths. The reviewer receives the numbers we already computed and is told not to
restate them — without that instruction it re-derives ratios, gets them wrong,
and invents problems the deterministic side already handled correctly.

**Never invent a number.** We refuse to output a spam score, because filter
behaviour is unknowable from the HTML and a confident "8.2 out of 10" would be a
lie. That standard points inward too: the readiness score was deleted because
nobody could defend its weights, and the prevalence headline stays empty until
real sent mail exists to fill it. When we cannot support a figure we say so,
rather than printing one and hoping.

**Write what it costs them, not what we measured.** Every finding leads with the
consequence, in words a creator uses, and keeps the measurement one level down
for whoever wants it. *"This disappears in dark mode"* comes first; the ratio
follows. Both survive — moving the number is an information-hierarchy decision,
not a simplification, and dropping it would fail the professional.

**Promise nothing the product will not do.** If we say a repair is one click, it
has to be one click. A fix we advertise and then skip costs more trust than the
problem we were fixing.

**The creator's voice is the product.** We flag a buried call to action and
spam-trigger copy. We do not rewrite them.

**Their disagreement is data, not noise.** A creator who waves a finding through
is telling us something precise, so we ask which finding and why. Overriding
everything says the product is wrong; dismissing one check says that check is.
Only the second should ever retire a rule, and only with enough of them to mean
anything.

## Where the judgment calls live

Each of these is a numbered decision in `PRODUCT_DECISIONS.md` with its
reasoning intact:

- **What a creator reads** — the two registers, and when a picture beats a
  sentence.
- **What blocks a send** — three tiers named by consequence, and why there is no
  score.
- **What we repair by default** — and why touching someone's stylesheet is
  always something they ask for.
- **What we hand back to them** — repairing one thing without disturbing
  another, and why undo is a set of choices rather than a stack of edits.
- **What we measure after shipping** — behaviour over counts, and why a rate
  without its denominator is worse than no rate at all.
- **What we refuse to claim** — prevalence, model quality, and anything the
  evidence does not carry.

## The two honesty rules

**Say where a number came from.** Replayed reviewer results are marked as
written by hand rather than captured from a live model, and the report says so
in yellow on every run. Never relabel one as the other, and never write one to
make a failing benchmark pass. The same applies to the human labels used to
check the reviewer: writing them to produce a good score recreates exactly the
circularity they exist to break.

**A measurement of the wrong thing is worse than no measurement.** This has
caught us three times: scoring an internal helper instead of the repair a
creator actually runs; blaming the parser's tidying on the repair; and showing a
rate beside a count that was not its denominator. All three reported problems
that did not exist, confidently. When something fails, establish what is being
measured before concluding the product is broken.
