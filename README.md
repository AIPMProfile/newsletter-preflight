# Launch Check

*A pre-send confidence check for Wren broadcasts.*

> **Wren is a fictional newsletter platform**, invented for this study so the
> check can be judged where it would actually sit — inside a composer, between
> the draft and the send. The screens are a plausible host, not a real product.
> Any resemblance to an existing tool is incidental.

## If you have ten minutes

| | | |
| --- | --- | --- |
| **1** | [`STRATEGY.md`](STRATEGY.md) | The bet, the leverage, how I would know I am wrong. **One page.** |
| **2** | Open `/editor`, then hit **Continue** | Wren's one warning, then the check that replaces it — on Wren's own surface. |
| **3** | [Product decisions](docs/PRODUCT_DECISIONS.md) | What to build, what to refuse, what not to claim. |

Everything below is depth for whoever wants it. Nothing in it is required to
judge the idea.

```bash
uv venv --python 3.11 .venv && uv pip install -e ".[dev]"
python cli.py serve          # then /editor → /launch-check → /publish
```

---

**The category already believes this problem is real.** Walk the composer of a
shipping newsletter platform and you find a warning like this one, verbatim:
*"One or more of your links contains an empty HREF value."* One check, written in
markup vocabulary, that cannot tell you which link, cannot take you to it, and
cannot fix it. Someone built that, which is a validated problem statement nobody
had to fund. Between "Send email" and twelve thousand subscribers there is a
Continue button and nothing else.

**The bet:** confidence at the moment of send is a wedge into the composer. It is
the one point where every broadcast, every creator and every template converge,
and it is currently unguarded.

**The leverage:** creators do not start from a blank page. They start from
Digest, Aspen, Column, Note. So defects are not distributed, they are
*inherited* — in the sample broadcast, **23 of 25 findings trace back to styling
the template decided once.** Reproduce it with
`python cli.py audit src/preflight/web/starter.html --offline`. A per-send check
helps one creator. The same signal aggregated to the template layer fixes the
defect across every broadcast built on it, including the ones nobody has written
yet.

That is the whole argument, and [`STRATEGY.md`](STRATEGY.md) is the one page that
makes it — including how I would know I am wrong, and what I would stop doing.

---

This repository is a working version of the sensor: a pre-send check that
answers one question in under two seconds — **can I send this?** — and repairs
what it safely can.

```
╭──────────────────────────────────────────────────────────────────╮
│  10 things to sort before this goes out                          │
│  10 will look wrong to your readers.                             │
╰──────────────────────────────────────────────────────────────────╯

  WILL EMBARRASS YOU

  This disappears in dark mode. Roughly half your readers open email
  on a dark screen, and they will see a blank space here.
    ┌ Light screen ─┐ ┌ Dark screen ──┐
    │  Aa your text │ │               │     ← what half your list gets
    └───────────────┘ └───────────────┘
    [ Fix it for me ]  [ Review it myself ]  [ Send as is ▾ ]
```

Every finding says **what it costs you** first, and keeps the measurement one
level down for anyone who wants it. Findings are graded by consequence — *will
break*, *will embarrass*, *could be better* — never by engine severity, and
there is no invented score. Each one offers a repair, a way to review it
yourself, or a way to send anyway with a reason we record.

**Ready is the product.** Most broadcasts are fine, and on those the value is
being told so by something that visibly looked — so a clean result says what it
examined rather than returning silence. Creators send test emails to themselves
because nothing in the flow supplies that reassurance; published research puts
manual pre-send checking at roughly 20–25% of email marketers.

**It learns from what creators do.** Four signals — approved, overridden,
dismissed with a reason, and *ignored* — read against a per-check rubric that
defines what a good and a bad finding look like. Ignored is the one that matters
for this audience: they will not hand-edit markup and will not argue with a
panel, so silence is the feedback. The loop proposes recalibrations; it never
retunes a check on its own.

**Three screens, one flow.** `/editor` is Wren's composer as it ships today, with
its single warning. `/launch-check` is the check, between draft and send. And
`/publish` reports what the check decided, then sends. Nothing audits twice: one
document, checked in one place.

**Who it is for, and the guarantee that follows:** hobbyists want the problem
gone in one click; professionals want a diff and no unrequested CSS mutation. So
the default repair never touches your stylesheet. See
[`docs/PROBLEM.md`](docs/PROBLEM.md).

> **On the numbers.** There are no prevalence figures here yet. The harness is
> built and the corpus is honest: the only sources sampled so far were archive
> *web pages*, which showed a **0%** dark-mode failure rate — because web pages
> paint their own backgrounds and email templates frequently do not. A number
> from that sample would be confidently wrong about the exact failure this
> exists to catch, so there is no number until real exports land.

## Going deeper

| | |
| --- | --- |
| [`STRATEGY.md`](STRATEGY.md) | The bet, the leverage, how I would know I am wrong. One page. |
| [`docs/PRODUCT_DECISIONS.md`](docs/PRODUCT_DECISIONS.md) | What we build, what we refuse to build, what we refuse to claim. |
| [`docs/PROBLEM.md`](docs/PROBLEM.md) | Who it is for, the metrics, and the criteria that would kill it. |
| [`docs/PRINCIPLES.md`](docs/PRINCIPLES.md) | The handful of principles that are easy to break without noticing. |
| [`docs/REFERENCE.md`](docs/REFERENCE.md) | Install, flags, configuration, the benchmark, the calibration. |

## License

MIT — see [`LICENSE`](LICENSE).
