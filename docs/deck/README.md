# Architecture deck

A slide deck that explains how subtitler works: the path from a media file to an
`.srt`, the cue model every provider reduces to, the providers and how
`azure-hybrid` aligns its two passes, translation, the command line, updates and
releases. [`docs/system.md`](../system.md) is the same design in prose; the deck
walks through it the way a talk would, and every content slide names the files it
describes along its bottom edge.

## What it describes

The deck describes the code in [source PR #32](https://github.com/leduftw/subtitler/pull/32),
named on its cover and its last slide. The pull request's head remains fetchable
after a squash merge. To see what has changed since then:

```sh
git fetch origin refs/pull/32/head
git diff --stat FETCH_HEAD -- src scripts pyproject.toml .github/playbook.toml
```

Nothing listed means those code paths are unchanged. The deck also cites design
docs and repository instructions; review changes to those sources too.
When a change makes a slide wrong, fix the slide and update the source PR reference
in all three places: the cover, the last slide and this file.

## The files

The folder is a [Claude](https://claude.ai) Slides deck, kept as plain files so it
can be reviewed and changed like the code:

- `project/deck.json` lists the slides in order, the outline and the typefaces.
- `project/slides/<id>.html` is one 1920×1080 slide: a single `<section>` in the
  Slides HTML subset, with every style inline.

Claude can publish the folder as a Slides deck, which can be presented, paged
through and downloaded as PowerPoint or PDF.
