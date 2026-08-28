#!/usr/bin/env python3
"""site_paths.py - resolve LiveCheck's runtime resources in a relocatable way.

The distribution layout is:
    <dist>/
      lsp/livecheck/   this module + the LSP files
      databases/       SVD + RM databases
      scripts/         F4/F5/F6 helper scripts + summary viewer
      toolchain/       gema, patterns, swd2, swdd, swdd-upload.py
      kernel/          the F051 debug kernel binary

Every consumer asks this module for a resource.  Resolution order:
  1. the DISTRIBUTION layout (relative to this file's location), so a
     freshly-cloned livecheck-dist works with zero configuration;
  2. the development /home/tp layout (swdai / mecrisp-stellaris-lsp / ~/scripts),
     so the same code works when edited in the source checkouts.

No hardcoded /home/tp paths should live anywhere else in the LSP.
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_DIST = os.path.normpath(os.path.join(_HERE, "..", ".."))   # <dist>/


def _first(*paths):
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return ""


def toolchain(name: str) -> str:
    """gema, swd2, swdd, swdd-upload.py - <dist>/toolchain/<name>."""
    return _first(
        os.path.join(_DIST, "toolchain", name),
        os.path.expanduser(f"~/fossil/swdai/{name}"),
        os.path.expanduser(f"~/fossil/swdai/swdcom/{name}"),
    )


def pattern(name: str) -> str:
    """gema pattern files - <dist>/toolchain/patterns/<name>."""
    return _first(
        os.path.join(_DIST, "toolchain", "patterns", name),
        os.path.expanduser(f"~/fossil/swdai/patterns/{name}"),
    )


def database(name: str) -> str:
    """SVD / RM databases - <dist>/databases/<name>."""
    return _first(
        os.path.join(_DIST, "databases", name),
        os.path.expanduser(f"~/fossil/swdai/databases/{name}"),
    )


def script(name: str) -> str:
    """helper shell scripts + the summary viewer - <dist>/scripts/<name>."""
    return _first(
        os.path.join(_DIST, "scripts", name),
        os.path.expanduser(f"~/scripts/{name}"),
    )


def kernel(name: str) -> str:
    """debug kernel binary - <dist>/kernel/<name>."""
    return _first(
        os.path.join(_DIST, "kernel", name),
        os.path.expanduser(f"~/fossil/kernels/regmon-saved-kernels/{name}"),
    )


def lsp_db(name: str = "mecrisp_stellaris.db") -> str:
    """the Mecrisp dictionary DB - <dist>/lsp/livecheck/<name>."""
    return _first(
        os.path.join(_HERE, name),
        os.path.expanduser(f"~/fossil/mecrisp-stellaris-lsp/{name}"),
    )
