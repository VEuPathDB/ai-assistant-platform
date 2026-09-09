---
type: Backlog
title: check-knowledge does not resolve a cross-repo anchor
description: A page in this bundle cites a page in another repository as plain text, because a relative markdown link to it would not resolve. Nothing checks that the cited path still exists, so a page deleted in the other repository leaves a dead citation here.
tags: [docs, knowledge, tooling]
generated: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: open
---

# What is missing

`scripts/check-knowledge.mjs` resolves every relative markdown link and fails on
one that does not exist. A citation of a page in another repository cannot be a
relative link, so it is written as plain text with a repository prefix, for
example ``pathfinder: docs/knowledge/decisions/<page>.md``. Those citations are
unchecked, in this bundle and in the other three that use the same convention.

A page renamed or deleted in the cited repository therefore leaves a citation
here that reads as true and is not. This bundle carries at least one such
citation today, in
`decisions/the-client-is-a-package-with-three-rings.md`.

# What would close it

A check that reads the prefix, resolves the path against a sibling checkout when
one is present, and reports the citation as unverified rather than failing when
it is not. The four bundles share the checker byte for byte, so the change lands
in one file and is copied to the others.
