# Assets

Terminal captures, and the rules any later visual asset has to follow.

## What is here

[`captures/`](captures/) holds one plain-text file per screenshotable surface, each the
exact rendered output of a synthetic benchmark case, plus
[`captures/index.json`](captures/index.json) naming the family, the result artifact, the
case and the field every capture was taken from.

```
doctor.txt                        Doctor on an ordinary repository
doctor-fail-closed.txt            Doctor declining a question it cannot answer
                                  without executing what the repository configured
check-reviewable-candidate.txt    a completely green check
check-unknown.txt                 fail-closed: consent withheld, outcome UNKNOWN
receipt-precommit-incomplete.txt  the pre-commit receipt for that green check
commit-reviewable.txt             the bounded completion commit
receipt-postcommit-reviewable.txt the post-commit receipt — the only REVIEWABLE
```

Regenerate them, and the README's benchmark block, from the retained results:

```bash
python3 bench/render-assets.py --write
```

Without `--write` the same command reports drift and exits non-zero.
`tests/test_documentation.py` runs the same comparison, so a capture cannot quietly
stop being the output it claims to be.

## Why captures exist at all

An SVG contains live text. A terminal cast recorded on a working machine embeds that
machine's absolute paths, its username, and often the repository's real name — and it
will pass any review that only reads the Markdown. So no asset is ever recorded against
a real repository. These captures come from synthetic fixtures built from nothing by
the benchmark builders, and any later visual asset is rendered from a capture here
rather than from somebody's terminal.

## Rules for a rendered asset

The visual system is frozen in [`../product-spec.md`](../product-spec.md). The parts
that decide whether an asset may ship:

```
NO FABRICATION      a cast is rendered from a recorded transcript of real
                    output, or it does not ship
PASS IS INK         PASS and REVIEWABLE render in the foreground colour, never
                    green: a green check reads as a safety score, and this
                    product publishes no safety score
AMBER IS THE POINT  INCOMPLETE and UNKNOWN carry the one emphasis colour,
                    because surfacing the unknown is what the product is for
NO SHIELD           no badge, seal or shield implying universal safety
BOTH THEMES         ship -light.svg / -dark.svg pairs and verify both as
                    rendered; a media query inside a single SVG is unreliable
                    under Markdown sanitisation
```

No SVG has been rendered yet, and none is needed for the README to be honest. The
captures are the input for when one is.
