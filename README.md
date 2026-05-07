# SansDIR

▣ **SansDIR v0.8** — a fast, keyboard-driven dual-pane terminal file manager
for Small-Angle Neutron Scattering data on the ORNL analysis cluster.
Inspired by the DOS-era **MDIR** and Norton Commander.

> **Status**: beta. Daily-driven for EQSANS workflows. See
> [`TASKS.md`](./TASKS.md) for the phase plan, [`PLANNING.md`](./PLANNING.md)
> for architecture.

---

## Why

SANS users on the analysis cluster spend a lot of time:

- hopping between `/SNS/EQSANS/IPTS-*` directories,
- triaging runs by quickly plotting `*Iq.dat` / `*Iqxqy.dat` / raw NeXus,
- peeking at DASlogs (temperature, shear, …) across many runs,
- exporting a few keys × many files to a CSV for analysis,
- zipping results to email to collaborators.

GUI tools want X11 forwarding and feel sluggish over SSH. `sansdir` is a
true terminal app — no display-server required — and renders the actual
matplotlib plots in their own windows when one *is* available.

---

## Install

### Option A — Zero-install on the ORNL analysis cluster *(recommended)*

The repo at `/SNS/EQSANS/shared/script/sansdir` ships its own bundled
venv. Anyone with read access — every cluster user — can run it
directly, with no Python or pip steps:

```bash
/SNS/EQSANS/shared/script/sansdir/bin/sansdir
/SNS/EQSANS/shared/script/sansdir/bin/sansdir /SNS/EQSANS/IPTS-12345/shared
```

To save typing, drop a symlink (or a copy) into your `PATH`:

```bash
mkdir -p ~/bin
ln -s /SNS/EQSANS/shared/script/sansdir/bin/sansdir ~/bin/sansdir
# (~/bin and ~/.local/bin are on your PATH on the analysis nodes by default)
sansdir --version
```

Or prepend the shared bin directory:

```bash
echo 'export PATH="/SNS/EQSANS/shared/script/sansdir/bin:$PATH"' >> ~/.bashrc
```

You can also **just copy the script** and run it from anywhere:

```bash
cp /SNS/EQSANS/shared/script/sansdir/.venv/bin/sansdir ~/bin/
~/bin/sansdir
```

This works because the script's shebang is the *absolute* path
`#!/gpfs/.../sansdir/.venv/bin/python` — the kernel always exec's the
original bundled Python regardless of where the script file itself
lives. The chain when you run the copy:

```
[your copy of the script]
  → /gpfs/.../sansdir/.venv/bin/python   (via absolute shebang)
    → /gpfs/.../sansdir/src/sansdir/cli.py  (via the venv's editable install)
```

A **symlink is preferable to a copy** in practice: when I refresh the
shared venv, every user with a symlink picks up the new build for free,
no re-copying.

What still has to live on the shared mount (don't move these):

- `/SNS/EQSANS/shared/script/sansdir/.venv/` — the bundled Python + deps.
- `/SNS/EQSANS/shared/script/sansdir/src/sansdir/` — the source the egg-link points to.

What's portable (copy / symlink wherever):

- `.venv/bin/sansdir` — the Python entry-point script. Shebang stays absolute.
- `bin/sansdir` — the bash launcher; self-locates relative to the shared root.

Either uses absolute paths internally, so it doesn't care about your
conda env, current working directory, or whichever Python you have on
PATH.

### Option B — Local development install

```bash
git clone <repo-url> sansdir
cd sansdir
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
sansdir --version
```

Python ≥ 3.10. The TUI doesn't need a display; for interactive plots, install
either Qt (`pip install "sansdir[qt]"`) or system Tk (`dnf install python3-tkinter`).

---

## Quick start

```bash
sansdir                                # TUI in cwd
sansdir /SNS/EQSANS/IPTS-12345/shared  # TUI rooted at a folder
sansdir extract -k /entry/duration *.nxs.h5  # CLI: batch metadata, no TUI
```

Inside the TUI, press `?` for the live keymap. The most-used keys:

| Key            | What it does                                                      |
|----------------|-------------------------------------------------------------------|
| `Tab`          | Switch active pane (left ↔ right)                                  |
| `Enter`        | Smart open: cd into folder · view image · *(catalog)* plot run     |
| `↑ ↓ j k`      | Move cursor in the active pane                                     |
| `Backspace`    | Up one directory                                                   |
| `Space`        | Tag/untag the cursor row                                           |
| `+` / `*` / `-`| Tag / tag-by-glob / untag-by-glob in the active pane               |
| `u`            | Untag all                                                          |
| `=`            | Sync inactive pane's cwd to active                                 |
| `Ctrl+U`       | Swap left/right pane *cwds* (catalog stays put on the right)       |
| `Ctrl+O`       | Maximize the active pane (toggle)                                  |
| `/`            | Filter active pane (or catalog) by substring; `Esc` clears         |
| `g` / `G`      | `:cd <path>` prompt / fullscreen folder-tree picker                |
| `:`            | Command line — every action is also a `:command` (see `?`)         |
| `?`            | Help overlay (auto-generated from the registry)                    |
| `q` / `F10`    | Quit                                                               |

### File operations (MDIR / Norton convention)

| Key       | Op                                                          |
|-----------|-------------------------------------------------------------|
| `F3`      | View file in the *other* pane (Tab into it; `Esc` / `F3` close) |
| `F4`      | Edit in `$EDITOR`                                            |
| `F5`      | Copy tagged → other pane (with confirm)                      |
| `F6`      | Move/rename tagged → other pane                              |
| `F7`      | Make directory (active pane)                                 |
| `F8` / `Del` | Delete tagged (confirm; `send2trash` with cluster fallback)|
| `z`       | Zip tagged → prompt for archive name                         |
| `e`       | Email tagged (`mail` / `mutt` shell-out)                     |

### Plotting

| Key | What it plots                                                            |
|-----|-------------------------------------------------------------------------|
| `p` | Smart-plot the active selection: routes by file kind                    |
|     | • `*Iq*.dat` (2/3/4-col) → log-log overlay                              |
|     | • `*trans*.txt` → linear T(λ)                                            |
|     | • `*Iqxqy*.dat` → 2D heatmap (single) or tile (multi)                    |
|     | • `*.nxs.h5` raw event-mode → 256×192 detector heatmap                  |
|     | • `*.nxs` Mantid processed (Workspace2D / EventWorkspace) → same        |
|     |   detector heatmap, computed pure-numpy (no Mantid dependency)          |
| `l` | Linear-linear plot of any tabular CSV/TSV — uses header row as labels   |

Plots open in their own matplotlib windows so you keep the TUI responsive.
On a host without `$DISPLAY` they fall back to PNGs under
`~/.cache/sansdir/plots/`.

### NeXus / metadata

| Key | What it does                                                             |
|-----|--------------------------------------------------------------------------|
| `m` | Open the cursor's `.nxs(.h5)` in a tree browser (lazy expansion)         |
| `M` | Batch metadata extract: tag NeXus files → `M` opens the picker dialog    |

The **Batch metadata extract** dialog has two modes:

- **Per-file** *(default)* — one CSV per input with the *full* DASlogs
  arrays preserved. Output template uses `<filename>` as a placeholder
  (e.g. `<filename>_temp.csv`); if you forget the placeholder, sansdir
  auto-prepends `<filename>_` so you still get one file per input.
- **Summary** — one row per input file, time-series reduced to means.
  Optional `_stdev` and `_n` columns (Ctrl+T).

Pick keys via the **fullscreen tree picker** (Ctrl+B from the dialog,
auto-opens on first mount): `Space` toggles, `/` searches across all keys
in the file, `Ctrl+S` returns to the form.

### OnCat & catalog

| Key | What it does                                                                 |
|-----|-----------------------------------------------------------------------------|
| `i` | Search OnCat by IPTS / experiment keyword. Pick one → cds the active pane    |
|     | into `<IPTS>/shared/` and loads the run catalog on the **right** pane.      |
| `F2`| Show / hide the right-pane catalog                                            |
| `Space` *(in catalog)* | Tag a run                                            |
| `Enter` / `p` *(in catalog)* | Plot the cursor's raw NeXus run                  |
| `m` *(in catalog)* | HDF5 tree of the cursor's run                              |
| `M` *(in catalog)* | Batch extract (tagged runs, or just the cursor row)       |

The catalog always lives on the right pane regardless of where you press
`i`, so the layout is predictable; `Ctrl+U` swaps file pane cwds without
moving the catalog.

---

## CLI examples

```bash
# Summary table — one row per file, time-series reduced to means.
sansdir extract \
  -k /entry/DASlogs/temperature/value \
  -k /entry/duration \
  --out summary.tsv \
  /SNS/EQSANS/IPTS-12345/nexus/EQSANS_*.nxs.h5

# Per-file tables — each input gets its own CSV with full arrays.
sansdir extract \
  -k /entry/DASlogs/temperature/time \
  -k /entry/DASlogs/temperature/value \
  --out '<filename>_temp.csv' \
  EQSANS_172749.nxs.h5 EQSANS_172750.nxs.h5

# Add stdev / n columns (summary mode only).
sansdir extract --with-stats -k /entry/DASlogs/temperature/value *.nxs.h5
```

`sansdir --help` (and per-subcommand `--help`) shows worked examples.

---

## File-kind colors in the panel

A subtle palette so you can scan a folder by glance:

| Kind                         | Color           |
|------------------------------|-----------------|
| Folder                       | bold blue       |
| Symlink                      | cyan            |
| `*Iq*.dat` (1D reduced)      | green           |
| `*Iqxqy*.dat` (2D reduced)   | magenta         |
| `*trans*.txt`                | cyan            |
| `*.nxs.h5` / `*.nxs` (NeXus) | bright yellow   |
| Executable (mode `+x`)       | bold red        |
| Tagged row                   | bold yellow `*` prefix |

---

## Configuration

`~/.config/sansdir/config.toml`. Override path via `$SANSDIR_CONFIG`.
Sections (all optional):

```toml
[ui]
theme = "monokai"   # any of textual-dark/light, monokai, nord, dracula,
                    # gruvbox, catppuccin-mocha, tokyo-night, rose-pine,
                    # solarized-{dark,light}, ansi-{dark,light}, …

[keys]
"ctrl+y" = "view.toggle_hidden"   # rebind anything; unknown commands
f5 = "ui.move_tagged"             # are silently dropped at startup

[oncat]
default_instrument = "EQSANS"
cache_ttl_seconds  = 86400

[mail]
command = "mail"        # or "mutt"
default_subject = "[sansdir] data"
```

Switch theme live: `:theme monokai` (bare `:theme` lists available names).

---

## What's in v0.8

- Dual-pane MDIR-style TUI with the full F-key suite (F3 view, F5 copy,
  F6 move, F7 mkdir, F8 delete, plus tag-by-glob, swap, sync).
- 1D plotting (Iq, transmission), 2D plotting (Iqxqy single + tile mode),
  raw EQSANS NeXus detector heatmap, **processed Mantid NeXus** detector
  heatmap (incl. drtsans wavelength-banded output and event-workspace
  masks) — all in pure numpy, no Mantid dependency.
- Reduced 2D `I(qx, qy)` Mantid Workspace files render via `pcolormesh`
  with proper `q_x` / `q_y` axes.
- Generic linear-linear plotter for CSV/TSV (`l`) — picks up the column
  header as axis labels. Pairs naturally with the `M` extractor output.
- Image viewer on `Enter` for `*.png` / `*.jpg` / `*.tiff` etc.
- OnCat IPTS browser (`i`), per-IPTS catalog on the right pane, F2
  toggle, runs taggable with `Space`, raw-file plot from the catalog.
- Batch metadata extract with tree-based key picker (in-place search);
  per-file *and* summary modes; output goes to the **inactive** pane's
  cwd by default to avoid raw-data write-permission errors.
- Themes via Textual's built-in palette + `[keys]`-rebinding.
- Coloured file-kind hints, top-of-pane path bar (with
  `/gpfs/neutronsfs/instruments` → `/SNS` rewrite), bottom status with
  catalog-loaded indicator.
- Cold start: ~50 ms.
- 392 tests, ruff-clean.

---

## Project documents

- [`CLAUDE.md`](./CLAUDE.md) — instructions for the AI coding agent.
- [`PLANNING.md`](./PLANNING.md) — architecture & data-format reference.
- [`TASKS.md`](./TASKS.md) — phased implementation checklist.

---

## Author

Changwoo Do — Neutron Scattering Division, Oak Ridge National Laboratory
(`doc1@ornl.gov`).

## License

MIT.
