"""What a good finding looks like, per check — and what a bad one looks like.

A check can be perfectly accurate and still be wrong for the product. "This text
is 4.3:1" can be true, and firing it on a decorative caption nobody reads is
still a false alarm from where the creator sits. Precision against ground truth
cannot see that; only a definition of *useful* can.

So every check carries a rubric with three parts:

* **good** — the case this check exists to catch, stated as a creator would
  experience it.
* **bad** — the case where it is technically right and unhelpful. This is the
  half that usually goes unwritten, and it is the half that tells you what to
  fix when creators start waving a check through.
* **decides_in** — how long a creator should need to decide what to do about it.
  A finding that takes ninety seconds to act on has failed even if it was
  correct, because at that price they will stop reading.

The rubric is what makes creator feedback interpretable. Without it, a 40%
dismissal rate is a number. With it, you can ask which half of the definition
the check has drifted into.

Nothing here is scored automatically against a model. These are the standard a
human applies when a check gets flagged for recalibration, and the language the
proposal is written in.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rubric:
    good: str
    bad: str
    #: Seconds a creator should need to decide. Comprehension budget, not a
    #: performance budget - it measures whether the wording landed.
    decides_in: int
    #: What we would change first if creators say this check is wrong.
    first_lever: str


RUBRICS: dict[str, Rubric] = {
    "liquid.unparsed": Rubric(
        good="A personalisation tag was left unclosed and will reach subscribers as "
             "raw code where their name should be. Unambiguous, embarrassing, and "
             "invisible in every preview a creator would think to run.",
        bad="Firing on a stray brace inside ordinary copy, or inside a code sample "
            "the creator is deliberately showing. Both read as us not understanding "
            "their writing.",
        decides_in=10,
        first_lever="Tighten what counts as a tag opening before touching severity.",
    ),
    "liquid.unclosed_block": Rubric(
        good="A conditional block was opened and never closed, so a section may "
             "vanish or render raw depending on the sending engine.",
        bad="Firing on a block closed by a variant spelling we do not recognise. "
            "The creator sees a correct email being called broken.",
        decides_in=15,
        first_lever="Widen the recognised closing forms.",
    ),
    "link.broken": Rubric(
        good="A link returns an error. Anyone who clicks reaches a dead end and the "
             "email cannot be recalled to fix it.",
        bad="Firing on a site that blocks automated requests, is briefly down, or "
            "sits behind a login. The link is fine and we called it dead - the "
            "fastest way to lose a creator's trust in every other finding.",
        decides_in=15,
        first_lever="Treat request-blocking responses as unknown rather than broken.",
    ),
    "link.empty_href": Rubric(
        good="A button or link has no destination. Readers click it and nothing "
             "happens, which wastes the one action the email was asking for.",
        bad="Firing on an anchor used purely for layout, or one the editor has not "
            "finished writing while the creator is mid-edit.",
        decides_in=10,
        first_lever="Ignore anchors with no visible text.",
    ),
    "contrast.aa_fail": Rubric(
        good="Body copy a reader has to work to read - on a phone, in sunlight, at "
             "the end of the day. The creator chose a colour without seeing it in "
             "those conditions.",
        bad="Firing on decorative or intentionally quiet text: a caption, a legal "
            "line, a watermark. Technically below the threshold, deliberately so, "
            "and telling the creator their design is broken when it is not.",
        decides_in=20,
        first_lever="Exempt small print by role before loosening the ratio.",
    ),
    "contrast.aaa_fail": Rubric(
        good="A quiet note that a design already clearing the readable bar could go "
             "further. Never blocks, never insists.",
        bad="Appearing often enough to feel like nagging. This check earns its place "
            "only while creators ignore it without irritation.",
        decides_in=5,
        first_lever="Stop reporting it at all if it accounts for most ignores.",
    ),
    "darkmode.no_bg_override": Rubric(
        good="Text pinned to a colour with nothing painting behind it, so a client "
             "forcing dark mode renders it invisible. Roughly half the audience sees "
             "a blank space and the creator never finds out.",
        bad="Firing on text that would survive the repaint anyway, or on a template "
            "whose background is set somewhere we did not look. A creator seeing a "
            "correct email flagged learns to skip the whole panel.",
        decides_in=25,
        first_lever="Widen where we look for a painted surface before changing tier.",
    ),
    "darkmode.unsafe_override": Rubric(
        good="A dark-mode rule recolours text without recolouring what it sits on, "
             "so the creator's own dark styling produces unreadable output.",
        bad="Firing where the surface is painted by a rule we did not resolve. Same "
            "cost as above and harder to explain.",
        decides_in=25,
        first_lever="Improve surface resolution inside media rules.",
    ),
    "img.missing_alt": Rubric(
        good="An image carrying meaning has no description, so it is silent to "
             "anyone using a screen reader and a blank gap wherever images are "
             "blocked - which is most inboxes, by default.",
        bad="Firing on spacers, dividers and tracking pixels. Nothing is lost when "
            "those are silent, and asking a creator to describe a one-pixel image "
            "makes the whole check look mechanical.",
        decides_in=15,
        first_lever="Exclude images below a size threshold and known spacer patterns.",
    ),
    "img.filename_alt": Rubric(
        good="The description is the filename, which tells a reader nothing and "
             "usually means it was filled in automatically.",
        bad="Firing on a description that legitimately resembles a filename.",
        decides_in=15,
        first_lever="Require stronger filename evidence.",
    ),
    "link.bare_url": Rubric(
        good="An address written out but not clickable, so readers have to copy it "
             "by hand.",
        bad="Firing where the address is shown deliberately - a domain the creator "
            "is naming rather than linking.",
        decides_in=10,
        first_lever="Skip addresses inside quotes or code.",
    ),
    "link.vague_text": Rubric(
        good="Link text carrying none of the promise - 'click here' beside a "
             "sentence doing all the work. Costs the click, and reads as nothing to "
             "anyone moving link to link.",
        bad="Firing on short link text that is clear in context. This is a judgment "
            "call and the check should stay advisory for exactly that reason.",
        decides_in=15,
        first_lever="Shrink the phrase list to the least defensible cases.",
    ),
    "subject.too_long": Rubric(
        good="The point of the subject line falls past where a phone truncates, so "
             "the part that earns the open is never seen.",
        bad="Firing on a subject whose point lands early and simply runs long. The "
            "length is not the problem; where the meaning sits is.",
        decides_in=15,
        first_lever="Judge where the meaning falls, not the character count.",
    ),
    "preheader.missing": Rubric(
        good="No preview text, so the inbox fills that space with whatever the email "
             "starts with - often an unsubscribe line.",
        bad="Firing where the template supplies preview text somewhere we do not "
            "read it.",
        decides_in=10,
        first_lever="Detect template-supplied preview text.",
    ),
    "spam.link_ratio": Rubric(
        good="Dense linking with little writing between, which filters read as "
             "promotional. The subscriber may never see the email at all.",
        bad="Firing on a genuine link roundup, which is a legitimate and common "
            "newsletter format. The creator knows what they are doing.",
        decides_in=25,
        first_lever="Recognise roundup formats before adjusting the ratio.",
    ),
    "deliverability.image_heavy": Rubric(
        good="Mostly pictures with almost no writing - a spam signature, and empty "
            "for anyone whose client blocks images.",
        bad="Firing on a deliberately visual send from a creator whose whole format "
            "is imagery.",
        decides_in=25,
        first_lever="Account for alt text as copy before adjusting the threshold.",
    ),
}


def rubric_for(code: str) -> Rubric | None:
    return RUBRICS.get(code)


def missing_rubrics(codes: set[str]) -> set[str]:
    """Checks shipping without a definition of good and bad.

    A check nobody can describe the failure mode of cannot be recalibrated when
    creators start waving it through - there is nothing to compare the feedback
    against.
    """
    return {c for c in codes if c not in RUBRICS}
