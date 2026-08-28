# Using LiveCheck

## The two faces of LiveCheck

LiveCheck has two roles, and knowing which one to reach for is half the art.

### `make` is the fire-fighter

When a prebuilt code tree is full of broken things, the big hammer wins
first: run `make`, blast the whole build, and knock out the structural
issues.  It is coarse, it is fast, and it tells you where the mountain is.

This is the traditional embedded loop, and it is the right tool for the
"heap of serious errors" moment.

### LiveCheck is the gold-panner

Once the mountain is cleared, the real work is fine: going line by line,
turning each orange check mark into blue.  It is slower, but it is certain.
Every single line gets the chip's personal stamp of approval before you move
on.

The orange-to-blue arc is addictive precisely because it is one small,
verifiable victory at a time — and unlike `make`'s "fix five things and
pray", each blue dot is a promise kept by the silicon.

## The recommended flow

1. **Open the project in your LSP-capable editor** (Helix, VS Code, Neovim,
   Emacs, Zed, ...) and run `livecheck-reset.sh` (reset + build + upload).
2. **Handle the serious errors with `make` first** — solve the first few
   structural problems the traditional way.
3. **Then settle down to the satisfying part**: work through the remaining
   orange marks one at a time.  Hover an orange dot to see why it failed,
   fix the line, run the reset command again, watch it turn blue.
4. **`summary-refresh.sh`** refreshes the summary from the live chip (no
   rebuild).
5. **`livecheck-assert.sh`** runs the `( "check": ... )` asserts — not just
   "did it compile" but "does it do what I think I told it to do".

Each of these is a plain shell command that touches a sentinel the LSP's
background poller watches — so any editor that can run a shell command in
your project directory works, and you can bind them to your own keys.

## What a blue check mark means

Desktop IDEs check your code against a grammar.  LiveCheck checks it against
the silicon you are actually programming.  A blue mark means the line passed
the two language servers **and** the real chip accepted it over Serial Wire
Debug — the chip's own DBG peripheral, the same facility professionals use
with expensive debuggers.  Wrong register, wrong bit, wrong clock setting —
the editor cannot catch those, but the chip can.

## Why it feels good

The transition from *clearing the rubble* to *walking the finished tunnel
with a lamp* is the reward loop: every step is solid, and the chip told you
so the moment you made it.  That is the difference between dreading the
editor and wanting to use it.

## Commands

| Command | Action |
|---|---|
| `livecheck-reset.sh` | reset the board + `make upload` + map errors to the gutter |
| `summary-refresh.sh` | refresh the summary from the live chip (no rebuild) |
| `livecheck-assert.sh` | run the `( "check": ... )` asserts |

## Mapping the commands to keys (Helix example)

These commands are easy to bind to function keys.  In Helix, add to the
`[keys.normal]` section of `~/.config/helix/config.toml`:

```toml
F4 = ":run-shell-command livecheck-reset.sh"    # reset + make upload (errors to gutter)
F5 = ":run-shell-command summary-refresh.sh"    # refresh the live summary (no rebuild)
F6 = ":run-shell-command livecheck-assert.sh"   # run the asserts (pass/fail to gutter)
```

Then F4 / F5 / F6 run the three actions.  Other editors are similar — you
are just binding a shell command to a key (VS Code Task, Neovim
`:!livecheck-reset.sh`, Emacs `shell-command`).  Bind to whatever keys suit
you.
