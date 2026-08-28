#!/usr/bin/env python3
"""summary-tk.py — F6: display the F4 project summary.md in a standalone
Tkinter window with colour tags.  No table bars, no backticks — clean
'Field → meaning' lines (Terry 2026-08-27).

Behaviours:
  - SINGLE INSTANCE: only one window ever.  A second launch (F6 pressed
    again) signals the running instance to reload + raise itself, then exits.
  - AUTO-RELOAD: the open window watches summary.md; when F4 regenerates it,
    the parked window refreshes itself within ~0.5s.  No need to close first.
"""
import os
import re
import sys
import tkinter as tk

LOCK = "/tmp/summary-tk.pid"
TRIGGER = "/tmp/summary-tk.reload"
FILE = sys.argv[1] if len(sys.argv) > 1 else "summary.md"


def _live_pid():
    try:
        pid = int(open(LOCK).read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError, FileNotFoundError):
        return None


def _signal_existing():
    try:
        open(TRIGGER, "w").write("reload\n")
    except OSError:
        pass


def _check_single_instance():
    """If another instance is alive, tell it to reload+raise and exit here."""
    pid = _live_pid()
    if pid:
        _signal_existing()
        sys.exit(0)
    with open(LOCK, "w") as f:
        f.write(str(os.getpid()))


root = tk.Tk()
_check_single_instance()
root.title("Project Summary")
root.geometry("880x700")

frame = tk.Frame(root)
frame.pack(fill=tk.BOTH, expand=True)

text = tk.Text(frame, wrap=tk.WORD, font=("JetBrains Mono", 14),
               bg="#1e1e1e", fg="#e0e0e0", insertbackground="#e0e0e0",
               padx=14, pady=10)
sb = tk.Scrollbar(frame, command=text.yview)
text.configure(yscrollcommand=sb.set)
sb.pack(side=tk.RIGHT, fill=tk.Y)
text.pack(fill=tk.BOTH, expand=True)

text.tag_configure("h1", foreground="#7ec8ff", font=("JetBrains Mono", 18, "bold"))
text.tag_configure("h2", foreground="#ffd75f", font=("JetBrains Mono", 15, "bold"))
text.tag_configure("reg", foreground="#9cdcfe", font=("JetBrains Mono", 14, "bold"))
text.tag_configure("addr", foreground="#b5cea8")
text.tag_configure("hex", foreground="#6fcf97")
text.tag_configure("field", foreground="#e8a838")
text.tag_configure("mean", foreground="#d4d4d4")
text.tag_configure("deps", foreground="#7ec8ff")


def insert_line(line):
    """Insert one summary line with colour tags.  No table bars, no backticks."""
    line = line.rstrip("\n")
    if line.startswith("# "):
        text.insert(tk.END, line[2:] + "\n", "h1")
        return
    if line.startswith("## "):
        text.insert(tk.END, "\n" + line[3:] + "\n", "h2")
        return
    if line.strip() in ("---", "----"):
        text.insert(tk.END, "─" * 60 + "\n", "h2")
        return
    m = re.match(r"\*\*(.+?)\*\*\s*(.*)", line)
    if m:
        text.insert(tk.END, m.group(1), "reg")
        rest = m.group(2)
        pos = 0
        for hx in re.finditer(r"(\$[0-9A-Fa-f]+|0x[0-9A-Fa-f]+)", rest):
            a, b = hx.span()
            if a > pos:
                text.insert(tk.END, rest[pos:a], "mean")
            text.insert(tk.END, hx.group(1), "hex")
            pos = b
        text.insert(tk.END, rest[pos:] + "\n", "mean")
        return
    if " → " in line:
        name, rest = line.split(" → ", 1)
        text.insert(tk.END, name + " ", "field")
        text.insert(tk.END, "→ ", "mean")
        text.insert(tk.END, rest + "\n", "mean")
        return
    if " = 0x" in line:
        name, rest = line.split(" = ", 1)
        text.insert(tk.END, name + " ", "field")
        text.insert(tk.END, "= ", "mean")
        text.insert(tk.END, rest + "\n", "hex")
        return
    text.insert(tk.END, line + "\n", "mean")


def render():
    text.configure(state=tk.NORMAL)
    text.delete("1.0", tk.END)
    try:
        for line in open(FILE, encoding="utf-8"):
            insert_line(line)
    except OSError:
        text.insert(tk.END, "summary.md not found — press F4 first.\n", "mean")
    text.configure(state=tk.DISABLED)


# watch summary.md (auto-reload on F4 regen) + the F6 trigger (reload+raise)
_mtime = None
_watch_dir = os.path.dirname(os.path.abspath(FILE))


def _poll():
    global _mtime
    try:
        now = os.path.getmtime(FILE)
        if now != _mtime:
            _mtime = now
            render()
    except OSError:
        pass
    if os.path.isfile(TRIGGER):
        try:
            os.remove(TRIGGER)
        except OSError:
            pass
        _mtime = None
        render()
        root.lift()
        root.focus_force()
    root.after(500, _poll)


render()
root.after(500, _poll)
root.mainloop()

try:
    os.remove(LOCK)
except OSError:
    pass
