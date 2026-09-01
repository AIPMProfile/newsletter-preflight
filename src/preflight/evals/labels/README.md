# Checking the reviewer against a person

Most of what this product finds is arithmetic, and arithmetic does not need
checking. A handful of judgments do — whether a call to action is really buried,
whether copy really reads as promotional — and those come from a language model.

A model's score against expectations someone wrote by hand tells you the
scoring works. It tells you nothing about the model. Worse, the same person
usually wrote the prompt, the expectations, and the recorded answer: three
artefacts, one opinion, no independent check.

This folder is the independent check. One file per sample, holding what a person
thought before they saw what the model said.

```json
{
  "sample": "sample_4_cta_spam.html",
  "labelled_by": "your name",
  "labelled_at": "2026-08-30",
  "blind": true,
  "labels": [
    {"code": "cta.buried",              "target": "*", "real": true},
    {"code": "spam.trigger_phrase",     "target": "*", "real": true},
    {"code": "copy.cognitive_friction", "target": "*", "real": false}
  ]
}
```

Three things keep the resulting number worth quoting.

**Decide before you look.** Mark `blind` false if you read the model's answer
first. Someone who has seen the answer is not a second opinion, and one such
file makes the whole run non-blind rather than quietly averaging in.

**Write down the noes.** A `false` entry is what makes an invented finding
visible. A file of nothing but agreement cannot tell a careful reviewer from an
eager one — it can only reward the eager one.

**Never write a label to produce a good score.** That recreates precisely the
circularity this folder exists to break, and it is the same dishonesty as
relabelling a hand-written result as a measured one.

It is empty on purpose. Until it is not, the reviewer's reliability is unknown,
and the report says so rather than implying otherwise.
