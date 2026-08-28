# Agents

## Change Rule
Do not change anything or restart system tools without permission.

## Markdown
All text documents created by the AI agent must be in Markdown as used by the Fossil DCVS Wiki unless otherwise specified

## Tables
Do not use SciMark wiki tables anywhere
All fossil chat communication and tables must be in Fossil Wiki Markdown

## Version Control
Use Fossil DCVS instead of GIT on this PC

## Wgetpaste
use 'wgetpaste <filename>' to paste text files

## Sign-off
Always conclude your response with '✅ finished' when a task is complete

## Completion over speed
Terry always prefers accurate completion over speed. Speed is of minor importance
to him — he is usually busy with other tasks after setting the AI a task to do.
Take the time needed to get the result right; do not cut corners or rush to finish
quickly at the expense of correctness.

## Code changes
After AI has made code changes, advise the user that the changes are waiting for
his review and commit. The AI does not commit; the user commits.

## Wiki → GitHub export (Terry 2026-08-29)
The fossil wiki is basically for Terry's own use. When a repo is mirrored to
GitHub and has a lot of wiki pages, convert the pages to text files and
include them in the GitHub repo. The handy CLI command:
    fossil wiki export PAGENAME outfile.md
There is no CLI delete/edit for wiki pages (web UI only) — the committed
file in the checkout is authoritative for the git mirror.
RELEASE PATTERN (Terry 2026-08-29): create a `wiki/` subdirectory in the
release / GitHub repo and put ALL the fossil wiki pages from the project
into it, so all documentation lists in one place there. No worse than any
other project's documentation — it's just the docs done the same way
everyone else does (a docs folder), sourced from the wiki.
NOTE (Terry 2026-08-29): fossilme no longer generates doc/readme.md — the
create_readme stub was removed from fossilme. Do not create or ship a
readme.md stub in new repos.
