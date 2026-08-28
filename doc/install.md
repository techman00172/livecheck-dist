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
- the **SVD databases** they consult (F0/F1/F4/L0/G0 + ARM-core)
- the **toolchain** (gema, swd2, swdd, the uploader)
- the **demo** — a vimtutor that teaches you LiveCheck with six real bugs
- the **helper scripts** (F4/F5/F6) and the summary viewer
- `setup.sh` — the installer

To install it, follow these steps.

## Requirements

- **Linux** (any recent distro)
- **Helix** editor (free) — LiveCheck plugs into it
- **Python 3** with tkinter
- an **ST-Link** SWD probe (a few dollars; the Discovery board has one built in)
- a **STM32F051** board

## Install

```sh
# 1. Run the installer
./setup.sh
```

`setup.sh` checks your tools, installs the LSP's python dependencies, links
the helper scripts into `~/.local/bin`, and appends the Helix language
config.  Then two manual steps:

```sh
# 2. Flash the debug kernel (one time, ST-Link wired to the board's
#    SWDIO/SWCLK)
cd kernel
./flash-kernel.sh

# 3. Try the demo
cd ..
./scripts/demo /tmp/livecheck-work
cd /tmp/livecheck-work/src
hx demo.fs
```

## Use it

In Helix, press **F4** (reset + build + upload).  Blue check mark = the
chip accepted the line.  Orange = hover to see why, fix it, press F4 again,
watch it turn blue.  Work through `demo.fs` top to bottom — each STEP is a
real bug.

| Key | Action |
|---|---|
| **F4** | reset the board + `make upload` + map errors to the gutter |
| **F5** | refresh the summary from the live chip (no rebuild) |
| **F6** | run the `( "check": ... )` asserts |

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
- **No blue check marks in Helix** — restart Helix after setup.sh appends
  the language config, and make sure `swdd` is running (the F4 script needs
  the daemon up).
- **Upload hangs / "chip wedged"** — press F4 again; it resets the chip
  first, then rebuilds.

If the 50-check harness passes on your machine, your LiveCheck is the same
known-good unit that was pre-tested here.
