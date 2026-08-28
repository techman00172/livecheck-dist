#!/usr/bin/env python3
"""Extract words from words-1.rst into FORTH.csv.

words-1.rst uses a consistent grid-table format:
    |word|stack|description|
with continuation lines for long descriptions (blank word/stack cells).

Parses every table row, joins continuation lines, and writes FORTH.csv
(id,word,stack,description,example) — the LSP's dictionary source.
"""
import csv
import os
import re

RST = "/home/tp/fossil/mecrisp-stellaris-userdoc/words-1.rst"
CSV = "/home/tp/fossil/mecrisp-stellaris-lsp/src/FORTH.csv"


def parse_table(lines):
    """Parse the single grid table in words-1.rst into (word, stack, desc)."""
    rows = []
    i = 0
    while i < len(lines):
        l = lines[i]
        s = l.strip()
        if s.startswith("|"):
            # positional split: | word | stack | desc | — keep column positions
            # so a blank description (2dup etc.) is preserved.
            cells = s.split("|")
            # cells[1]=word, cells[2]=stack, cells[3]=desc, cells[4]=''
            if len(cells) >= 4:
                word = cells[1].strip()
                stack = cells[2].strip()
                desc = cells[3].strip()
                if word:
                    # continuation lines: blank word+stack -> append to desc
                    j = i + 1
                    while j < len(lines):
                        nxt = lines[j].strip()
                        if nxt.startswith("|"):
                            nc = nxt.split("|")
                            if len(nc) >= 4 and nc[1].strip() == "" and nc[2].strip() == "":
                                desc += " " + nc[3].strip()
                                i = j
                                j += 1
                                continue
                        break
                    rows.append((word, stack, desc))
        i += 1
    return rows


def main():
    lines = open(RST).read().split("\n")
    rows = parse_table(lines)

    # dedupe + sort
    seen = set()
    out = []
    for word, stack, desc in rows:
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        # unescape RST: \* -> *, :ref: already handled
        word = word.replace("\\", "")
        out.append((word, stack, desc))

    out.sort(key=lambda x: x[0].lower())

    with open(CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "word", "stack", "description", "example"])
        for idx, (word, stack, desc) in enumerate(out, start=1):
            w.writerow([idx, word, stack, desc, ""])

    print(f"wrote {len(out)} words to {CSV}")
    for probe in ["begin", "until", "do", "loop", "if", "then", "case", "emit", "bis!", "0-foldable", 's"', "irq-fault", "reset", "2dup"]:
        found = any(word.lower().startswith(probe.lower()) for word, _, _ in out)
        print(f"  {probe}: {'YES' if found else 'NO'}")


if __name__ == "__main__":
    main()
