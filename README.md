# LiveCheck — live-silicon checking for Mecrisp-Stellaris Forth

_Copyright (c) 2026 Terry Porter — MIT license, see COPYING._

**Check your Forth against the real chip as you type.**  LiveCheck runs two
language servers over your code in any LSP-capable editor (Helix, VS Code,
Neovim, Emacs, Zed, ...) — the same kind a big IDE uses — but it goes
further: it sends each line to the live microcontroller over Serial Wire
Debug, and the *actual silicon* accepts or rejects it.  A blue check mark in
the gutter means the line passed the language servers *and* the chip
compiled it.  An orange mark means something's wrong — hover to see why, fix
the line, run the reset command again, watch it turn blue.

No preloaded monitor, no UART program stealing clock cycles — it uses the
chip's DBG debug peripheral, the same facility professionals use with
expensive debuggers.

This download contains everything, self-contained:

```
kernel/       the F051 debug kernel binary + flash script (the one hard dep)
lsp/livecheck/  the two language servers + the linter + the summary writer
databases/    SVD + reference-manual databases (F0/F1/F4/L0/G0)
toolchain/    gema (CMSIS-name resolver), patterns, swd2, swdd, uploader
demo/         a vimtutor for LiveCheck — six real bugs to fix
scripts/      the F4/F5/F6 helpers + the summary viewer
setup.sh      the manual installer (this is a human install — no AI needed)
test/         an isolated test harness (builds in a container)
```

## What you need

- **Linux** (any recent distro)
- **any LSP-capable editor** — Helix, VS Code, Neovim, Emacs, Zed, etc.
- **Python 3** with tkinter
- an **ST-Link** SWD probe (a few dollars, or the Discovery board has one built in)
- a **STM32F051** board (Discovery or similar)

## Manual install

```sh
./setup.sh
```

It checks your tools, installs the LSP's python deps, links the helper
scripts, and — if you use Helix — appends the language config.  For any
other LSP-capable editor, point it at the two standard LSP servers
(`lsp/livecheck/mecrisp_lsp.py` + `lsp/livecheck/cmsis_svd_lsp.py`).  Then
two manual steps:

```sh
# 1. flash the debug kernel (one time, needs the ST-Link wired to the board)
cd kernel && ./flash-kernel.sh

# 2. try the demo
./scripts/demo /tmp/livecheck-work
cd /tmp/livecheck-work/src
hx demo.fs          # or open demo.fs in your own editor
```

Work through `demo.fs` top to bottom — each STEP is a real bug (the
canary-variable, the non-existent `continue`, the hidden `;`, the
parsing-word `char`, reversed bitfield operands, and the live assert).

## The three commands (editor-agnostic)

LiveCheck is driven by three shell commands, each of which touches a sentinel
file that the cmsis-svd LSP's background poller watches.  Run them in your
project directory via your editor's "run shell command" facility (Helix:
`:run-shell-command`; Neovim: `:!`; VS Code: a terminal), or from a terminal
— bind them to whatever keys suit you.

| What it does | Command |
|---|---|
| Reset the board + `make upload` + map errors to the gutter | `livecheck-reset.sh` |
| Refresh the summary from the live chip (no rebuild) | `summary-refresh.sh` |
| Run the `( "check": ... )` asserts | `livecheck-assert.sh` |

Blue check mark = the chip accepted the line; orange = hover to see the
problem, fix, re-run the reset command, watch it turn blue.

## What "the chip accepted it" means

Desktop IDEs check your code against a grammar.  LiveCheck checks it against
the silicon you're actually programming.  Wrong register, wrong bit, wrong
clock setting — the editor can't catch those, but the chip can, because the
chip is the thing that has to live with them.  The assert test goes one
further: not just "did it compile" but "does it do what I think I told it to
do", verified by reading the register back from the live device.

## Development

This is the distribution repo — a curated snapshot of the pieces that live in
Terry's development checkouts (`mecrisp-stellaris-lsp`, `swdai`,
`kernels`).  The source of truth is the Fossil repository; the GitHub mirror
is a file mirror of the working tree.
