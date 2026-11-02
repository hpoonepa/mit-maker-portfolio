# Source history and provenance

Reviewed locally on 1 November 2026. File timestamps are not treated as Git history.

## Canonical working source

The canonical working folder is `lambert-ga/squash-vision`. Its Git top level is the enclosing `lambert-ga` repository, on `main` at `6666ff35d59b64a9aa9ab08c121e23dfbf77a96f` (21 October 2026). At inspection, **zero files beneath `squash-vision/` were tracked** and the folder appeared untracked in status. It is a working-tree source snapshot, not a version recovered from that parent commit.

The parent has 514 commits reachable from HEAD, from `087fb44cf18752b27f3c46956f9a3772f28aa524` (15 May 2024) to the HEAD above. Those commits belong to the enclosing project and do not establish SquashVision's development chronology. Local branches are `main`, `backup-before-rebase`, `backup-before-rebase-2` and `backup-before-rebase-3`; retained remote-tracking branches also include `feat/sidebar-writeup-alignment`, `fix/hp-consistency-20261021` and `navbar`. Parent status contains four untracked directories, including this one. A path-filtered history walk did not finish within the bounded read; no historical SquashVision commit count is inferred from it.

The other inspected working copy, `mosaic/src/squashvision`, is not inside a Git repository. It supplies no additional commit history.

## Existing portfolio history

The original `portfolio-mit` repository contains **two genuine commits**, both on 18 October 2026. Both touch the earlier SquashVision portfolio:

| Commit | Original time | Subject |
| --- | --- | --- |
| `de4a6bbdd896ad08bfe5edf5dd2566f977adeee3` | 12:26:22 −04:00 | Assemble MIT maker portfolio from four working trees |
| `fb1cabdbd50ab3821aaef0048ba3f93ea292f290` | 12:27:52 −04:00 | Fix stale fixture caption contradicting the figure beneath it |

Both original commit messages retain `Co-Authored-By: claude-flow <ruv@ruv.net>`. These are assembly/correction history, not an invented sequence of development milestones. The current portfolio working tree differs substantially from that older HEAD, including renames and the expanded source; its current files must not be described as identical to either commit.

## This source review

The review restored canonical bytes for 201 files only after removing one recorded snapshot-purpose comment left the remainder byte-identical to the available canonical source. Executable modes, shebangs, Vitest environment directives, original docstrings and upstream notices are retained. No functional implementation body was changed. Two existing TypeScript test typing repairs remain: eight unsupported `exact` options were removed from role queries; their literal accessible-name assertions remain.

Two canonical files are still iCloud-offloaded: `scripts/verify-stats.cjs` and `tests/squashvision/backend/test_playback_impacts.py`. Their previously recorded local fallback copies are retained and explicitly marked; canonical byte equality is not claimed. Three other files that formerly required fallbacks are now locally readable and have been compared against canonical bytes.

All nine canonical technical notes, the working README, eighteen local experiment helpers and four historical experiment notes are represented. Runtime data, dependency caches, model weights, uploads and database copies are excluded. [The receipt](SOURCE-SNAPSHOT.json) records source and final hashes and the bounded fallback limitations; [the code map](CODE_MAP.md) explains the layout. The prior receipt is retained as [the 31 October record](SOURCE-SNAPSHOT-2026-10-31.json).

This review used Codex assistance. Existing coauthor and upstream attribution is preserved; file-purpose comments are not evidence of exclusive human authorship.
