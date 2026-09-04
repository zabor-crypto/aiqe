# Product specification

This document freezes the product's identity, its presentation rules, and the visual
system. It exists so that presentation decisions are made once, on the record, rather
than repeatedly and inconsistently later.

## Identity

```
PRODUCT NAME   AIQE — AI Quant Engineering
CLI            aiqe
CONFIG         aiqe.toml
CATEGORY       quant engineering assurance layer
```

The lockup is normally written in full as **AIQE — AI Quant Engineering**. The expansion
is not decoration: read alone, the acronym is commonly taken to mean "AI Quality
Engineering", which is a different category. The word *quant* appears in the first
sentence of any description of this product.

## Positioning

Primary:

```
DONE ISN'T EVIDENCE.
```

Supporting:

```
AIQE is the assurance layer for AI-assisted quant engineering.
It bounds the change, keeps unrelated Git state out of the commit,
runs your project-native checks, and shows what remains unknown.
```

Secondary hook:

```
Your agent said tests pass.
AIQE says what that actually proves.
```

AIQE is not described as an AI coding framework, an agent toolkit, a Claude workflow, or
a developer productivity tool. It is deterministic infrastructure that happens to be
most useful when an agent is writing the code.

## Truthfulness rules

These bind every public surface — README, documentation, assets, and release notes.

1. No claim may imply that software exists which does not.
2. Any command block describing future behaviour is immediately preceded by
   `DESIGN TARGET — specified, not yet implemented.` A block showing behaviour that
   exists carries the case identity of the retained artifact it was copied from, and is
   never typed by hand.
3. No benchmark number appears anywhere until it is generated from a retained result
   artifact. Prose observations never become published numbers.
   Every claim is classified against its evidence in [`claims.md`](claims.md), and a
   claim absent from that inventory may not appear on a public surface.
4. No fabricated terminal output, screenshots, or receipts. Terminal casts are rendered
   from real recorded output or they do not ship.
5. No CI badge until CI runs a real test suite against a real implementation. A green
   badge on a documentation workflow reads as "tests pass" and is therefore misleading.
   CI now runs a real suite; a badge still waits for a released artifact, because a
   badge above the fold on an unreleased project reads as a maturity claim.
6. No coverage, download, or star badges.
7. Failed, unsupported, and not-run cases are always shown. Nothing is filtered out of a
   result view to make it look better.

## README information architecture

Frozen section order:

```
hero / status / first command
AIQE in 30 seconds — the chain, before/after, the three unknowns
failure-first demo
five-minute quickstart
how it works
change integrity
evidence integrity
numerical integrity
working with Claude Code and Codex
benchmarks
where it runs — support, packaging, external CI
security and trust model
what AIQE does not do — and cannot prove
milestones
contributing
license
```

Sections without substance yet are omitted or reduced to a single pointer line. Empty
headings are not shipped.

Above the fold, in order: wordmark, hero statement, one-sentence explanation, the Task
Receipt, one paragraph reading it, the status line, the first command, and the support
line. Nothing else.

The Task Receipt in the hero is the **post-commit** one — the only place `REVIEWABLE`
appears. A pre-commit receipt above the fold would put the product's central refusal in
the position a reader takes for its result.

## Visual system

The hero image is the **Task Receipt**, not a logo. There is no logomark in v1.

```
WORDMARK        text only, monospace grotesque, single weight,
                approximately +0.08em tracking

DIAGRAMS        SVG, 2px strokes, orthogonal routing,
                no gradients, no shadows, no dimensional effects,
                at most five nodes per row, monospace labels

RECEIPT CARD    1280 x 640 SVG, fixed field order:
                task, owned scope, foreign staged, checked content,
                commit, verdict

BENCHMARK CARD  generated from result JSON only, never hand-authored;
                NOT_RUN rendered explicitly, never omitted

TERMINAL CAST   static SVG rendered from a capture in
                docs/assets/captures/, which is itself the exact output of a
                synthetic benchmark case; never a screenshot of a real
                terminal, never hand-typed

ASSETS          SVG throughout, in docs/assets/.
                Sole raster exception: the GitHub social preview,
                which the platform requires as a 1280 x 640 PNG.

THEMES          ship -light.svg / -dark.svg pairs selected with <picture>
                and prefers-color-scheme. Do not rely on media queries
                inside a single SVG; markdown SVG sanitisation makes that
                unreliable. Verify both themes as rendered before shipping.
```

### Colour

Monochrome-dominant, high density, semantic colour only.

```
REVIEWABLE / PASS       ink (foreground). No colour.
INCOMPLETE / UNKNOWN    amber   — the signature state
NOT_REVIEWABLE / FAIL   red
UNSUPPORTED             slate
```

**Pass is rendered in plain ink, never green.** This is a product decision, not an
aesthetic one: a green check is read as a safety score, the product publishes no safety
score, and `PASS` means only that a validator succeeded. Amber is the one state that
receives emphasis, because surfacing the unknown is what the product is for.

### Asset generation and privacy

Every generated asset — receipt cards, terminal casts, benchmark cards — is produced
inside a synthetic fixture environment using a synthetic repository path and a synthetic
user.

SVG assets contain live text. An asset generated on a real machine embeds real absolute
paths, a real username, and possibly a real repository name, and it will pass a review
that only reads the Markdown. The sanitisation scanner therefore covers SVG text content,
and asset generation never runs against a real working repository.

## Funding

Deferred until a real installable public alpha exists. No funding file, no sponsor
button, no wallet address, and no donation language at bootstrap. When it arrives it
stays understated and never appears above the fold.
