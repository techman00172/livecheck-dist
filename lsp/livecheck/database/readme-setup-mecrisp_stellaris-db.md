# Mecrisp Stellaris LSP - Quick Setup Guide

This repository contains the database generator for the **Mecrisp Stellaris Language Server (LSP)** — a smart, real-time coding assistant for Mecrisp-Stellaris Forth.

## What This Does

The `setup-mecrisp_stellaris-db.py` script generates a **SQLite database** called `mecrisp-stellaris.db` that powers the `mecrisp.lsp.py` server.

- It includes core Mecrisp-Stellaris Forth words like: `dup`, `drop`, `+`, `if`, `begin`, `@`, `!`, and more
- This database enables **code completion**, **diagnostics**, and **syntax hints** in your editor
- The database is used only by the LSP server — it’s safe and lightweight

> ✅ This database is essential for `mecrisp.lsp.py` to work properly.

## How to Use It (Step-by-Step)

### 1. Install Fossil (if not already installed)

On Debian/Ubuntu:
```bash
sudo apt update
sudo apt install fossil
```

On Fedora/RHEL/CentOS:
```bash
sudo dnf install fossil
```

On Arch Linux:
```bash
sudo pacman -S fossil
```

### 2. Clone the Project Repository

```bash
fossil clone https://chiselapp.com/user/tp/repository/mecrisp-stellaris-lsp mecrisp-stellaris-lsp.fossil
```

This creates a local Fossil database file: `mecrisp-stellaris-lsp.fossil`

### 3. Open the Repository

```bash
fossil open mecrisp-stellaris-lsp.fossil
```

This creates a working directory with all project files (including `setup-mecrisp_stellaris-db.py`)

### 4. Run the Setup Script

```bash
python3 setup-mecrisp_stellaris-db.py
```

✅ If successful, you’ll see: `Database file created: mecrisp-stellaris.db`

### 5. Verify the Output

```bash
ls -l mecrisp-stellaris.db
```

You should see a non-zero-sized file (e.g., ~10KB), confirming creation.

## Integration with `mecrisp.lsp.py`

After generating the database:

- The `mecrisp.lsp.py` server will **automatically detect** the db on startup
- It should work with **any LSP-capable editor**, (but has only been tested on Helix) including:
  - ✅ [Helix](https://github.com/helix-editor/helix) (developed with)
  - ✅ VS Code (with LSP extension)
  - ✅ Neovim
  - ✅ Emacs
  - ✅ Vim

Just open a `.fs` file, and you’ll get intelligent autocompletion!

## Notes
- The script can be **run multiple times** — it overwrites the existing database
- You can customize the list of Forth words in the script to expand completions
- No internet or external dependencies needed after setup

## Project Home
- 🔗 **Fossil SCM Repository:** [https://chiselapp.com/user/tp/repository/mecrisp-stellaris-lsp](https://chiselapp.com/user/tp/repository/mecrisp-stellaris-lsp)
- Full history, source code, and issue tracking managed via Fossil

## Support & Contributions
- Report bugs or suggest improvements in the [Fossil issue tracker](https://chiselapp.com/user/tp/repository/mecrisp-stellaris-lsp/issues)
- Contribute via Fossil check-ins or patches

---
© 2025 Mecrisp Stellaris LSP Project
Open, portable, and built to improve Forth development
