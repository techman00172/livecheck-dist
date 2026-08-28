# INSTALL

## First, what this is

This is **not** a collection of software that has been jumbled together.
This is an **installation-oriented release**.  It has been **pre-tested in
Docker** — the whole tree builds and the test harness passes **50 out of 50
checks** with no errors — so you are installing a known-good, coherent unit,
not assembling parts and hoping.

What the pre-tested release contains, all in one place:

- the **F051 debug kernel** (the one thing the chip must run)
- the **two language servers** (mecrisp + cmsis-svd) that power LiveCheck
- the **SVD databases** they consult (`*-svd.db`: F0/F1/F4/L0/G0 + `ARM-Core.db`)
- the **toolchain** (gema, swd2, swdd, the uploader)
- the **demo** — a vimtutor that teaches you LiveCheck with six real bugs
- the **helper scripts** (reset, summary, assert) and the summary viewer
- `setup.sh` — the installer

To install it, follow these steps.

## Requirements

- **Linux** (any recent distro)
- **any LSP-capable editor** — Helix, VS Code, Neovim, Emacs, Zed, Kate,
  etc.  (These days that's effectively all of them.)
- **Python 3** with tkinter
- an **ST-Link** SWD probe (a few dollars; the Discovery board has one built in)
- a **STM32F051** board

## Which chips does this work with?

This release ships everything needed for the **STM32F051** (the debug
kernel, the SVD database, and the reference-manual data all come converted
and ready).  The Discovery board is the reference target, and that's what
the demo runs on.

But **LiveCheck itself is not F051-only.**  It works with any STM32
microcontroller for which you have:

1. a **debug kernel** built for that chip (the same SWD ring-buffer kernel,
   compiled for your part);
2. the **SVD file** (the vendor's register description) converted in the
   correct manner into the database format this toolchain reads;
3. the **technical reference manual** converted the same way, so the
   register/bitfield meanings come up in completions and the summary.

The language servers, the toolchain, the demo method and the whole
live-silicon workflow are chip-agnostic — only the data (kernel + SVD +
manual) is chip-specific.  The F051 set is included so everything works out
of the box; for another chip you add its three converted pieces.

**What this distribution supplies, by chip:**

- **SVD databases** (the register maps) are supplied for **all five**
  families — so the language servers can complete registers and bitfields
  for any of these boards, not just the F051:
  - `STM32F051-svd.db`
  - `STM32F103-svd.db`
  - `STM32F407-svd.db`
  - `STM32L0xx-svd.db`
  - `STM32G030-svd.db`
  - `ARM-Core.db` (the ARM Cortex-M core registers common to all of them)
- **Reference Manual database** (the human-readable meanings) is supplied
  **only for the F051** (`STM32F051-rm.db`).

So: you can drive any board covered by those SVD databases, and the
register-map completions will work for all of them.  The full "meaning"
decorations (RM prose in completions and the summary) are currently only
available for the F051, because only its reference manual has been
converted so far.  Use the F051 Discovery for the fully-supported demo
experience, or bring your own board from the list and convert its manual
when you want the meanings too.

### Database naming

The databases follow a `-svd` / `-rm` suffix scheme so you always know what
you are looking at:

- `*-svd.db` — the **SVD** (register map) databases, built from the vendor's
  CMSIS-SVD file: every peripheral, register and bitfield.  `ARM-Core.db` is
  the same kind of data for the ARM Cortex-M core registers (SysTick, SCB)
  that ST's SVD omits.
- `*-rm.db` — the **Reference Manual** prose: the human-readable *meaning* of
  each register and bitfield, converted from the ST technical reference
  manual (shown in completions and the summary).

So `STM32F051-svd.db` is the F051's register map and `STM32F051-rm.db` is
the F051's manual meanings — a pair, one name, both halves.

## Install

```sh
# 1. Run the installer
./setup.sh
```

`setup.sh` checks your tools, installs the LSP's python dependencies, links
the helper scripts into `~/.local/bin`, and — if you use Helix — appends the
language config for you.  For any other editor, point it at the two LSP
servers (they are standard LSP servers, so any LSP client can attach them):

- `lsp/livecheck/mecrisp_lsp.py`  (Forth word completions + docs)
- `lsp/livecheck/cmsis_svd_lsp.py` (register/bitfield completions + the
  sentinel poller that drives the live-chip checking)

Then two manual steps:

```sh
# 2. Flash the debug kernel (one time, ST-Link wired to the board's
#    SWDIO/SWCLK)
cd kernel
./flash-kernel.sh

# 3. Try the demo
cd ..
./scripts/demo /tmp/livecheck-work
cd /tmp/livecheck-work/src
hx demo.fs          # or open demo.fs in your own editor
```

## Use it

LiveCheck is driven by three **editor-agnostic shell commands**.  Each one
touches a sentinel file that the cmsis-svd LSP's background poller watches —
the editor only has to run the command in your project directory.  Bind them
to whatever keys you like in your editor (everyone is precious about their
own keybindings, so that choice is yours).

| What it does | Command to run |
|---|---|
| Reset the board, `make upload`, map errors to the editor gutter | `livecheck-reset.sh` |
| Refresh the summary from the live chip (no rebuild) | `summary-refresh.sh` |
| Run the `( "check": ... )` asserts — "did it do the thing" | `livecheck-assert.sh` |

Every LSP-capable editor has a "run shell command" facility — for example
Helix uses `:run-shell-command`, VS Code has the terminal, Neovim has
`:!`.  Run the command in the project directory and the LSP does the rest.

A blue check mark appears in the gutter next to a line the chip accepted.
Orange = hover to see why, fix it, re-run `livecheck-reset.sh`, watch it
turn blue.  Work through `demo.fs` top to bottom — each STEP is a real bug.

You can always fall back to plain `make upload` from a terminal — that is
exactly what `livecheck-reset.sh` triggers on the chip side.

## Mapping the commands to keys

Running the commands from a command palette or terminal works, but it's
nicer to bind them to keys so they're one keystroke away.  Every editor
lets you do this; here is the Helix example so you can see the shape.

In Helix, add these to the `[keys.normal]` section of
`~/.config/helix/config.toml`:

```toml
F4 = ":run-shell-command livecheck-reset.sh"    # reset + make upload (errors to gutter)
F5 = ":run-shell-command summary-refresh.sh"    # refresh the live summary (no rebuild)
F6 = ":run-shell-command livecheck-assert.sh"   # run the asserts (pass/fail to gutter)
```

(With setup.sh installed the scripts are on your `PATH` via `~/.local/bin`,
so you can call them by name.  If you linked them elsewhere, give the full
path, e.g. `/home/you/livecheck-dist/scripts/livecheck-reset.sh`.)

Then in normal mode:

- **F4** — reset the board, `make upload`, errors mapped to the gutter
- **F5** — refresh the project summary from the live chip
- **F6** — run the `( "check": ... )` asserts

Other editors work the same way — you're just binding a shell command to a
key.  VS Code: Task + keybinding; Neovim: `vim.keymap.set("n", "<F4>",
":!livecheck-reset.sh<CR>")`; Emacs: `(global-set-key (kbd "<f4>")
'shell-command)`.  Bind them to whatever keys suit you — everyone is
precious about their own keybindings, and that's fine.

## Verify your install (optional)

The same test harness that pre-tested this release can re-verify your
checkout at any time:

```sh
./test/test-harness.sh        # needs podman; builds an isolated container
```

It runs 50 checks (layout, databases, python compile, the demo pipeline,
setup.sh) and reports pass/fail — nothing touches your system.

## Troubleshooting

- **"Missing required tools"** in setup.sh — install them (Arch: `sudo
  pacman -S tk stlink`; Debian: `sudo apt install python3-tk`) and re-run.
- **No blue check marks** — make sure the two LSP servers are attached to
  your editor's `.fs`/`source.forth` file type, and that `swdd` is running
  (the reset script needs the daemon up).
- **Upload hangs / "chip wedged"** — run `livecheck-reset.sh` again; it
  resets the chip first, then rebuilds.

If the 50-check harness passes on your machine, your LiveCheck is the same
known-good unit that was pre-tested here.
