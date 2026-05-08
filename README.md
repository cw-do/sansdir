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
| `q`            | Quit                                                               |

### File operations (MDIR / Norton convention)

| Key       | Op                                                          |
|-----------|-------------------------------------------------------------|
| `F2`      | **Rename** the file under the cursor (in-place dialog)       |
| `F3`      | View file in the *other* pane (Tab into it; `Esc` / `F3` close) |
| `F4`      | Edit in `$EDITOR`                                            |
| `F5`      | **Refresh** both panes (re-read directory listings)          |
| `F6`      | Copy tagged → other pane (with confirm)                      |
| `F7`      | Move tagged → other pane                                     |
| `F8` / `Del` | Delete tagged (confirm; `send2trash` with cluster fallback)|
| `F9`      | Make directory (active pane)                                 |
| `F10`     | Toggle catalog / list (other pane) — Phase 4                 |
| `z`       | Zip tagged → prompt for archive name                         |
| `e`       | Email tagged (`mail` / `mutt` shell-out)                     |

`F5` reloads both panes; useful when an external process (the mask
editor subprocess, a separate shell, an NFS catch-up) drops files
into a pane's cwd. The in-process flows (copy / move / mkdir / batch
extract / mask save into the inactive pane / zip / rename) refresh
automatically.

After a delete, the cursor sticks to the entry just below the
deleted file (or the new bottom row, if the deleted file was last)
— mc / Norton convention. Without that you'd jump to row 0 every
time you cleaned up a single file.

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
| `K` | Create a detector mask from the cursor's raw NeXus file (Phase 9.6)      |

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
| `F10`| Show / hide the right-pane catalog                                           |
| `Space` *(in catalog)* | Tag a run                                            |
| `Enter` / `p` *(in catalog)* | Plot the cursor's raw NeXus run                  |
| `m` *(in catalog)* | HDF5 tree of the cursor's run                              |
| `M` *(in catalog)* | Batch extract (tagged runs, or just the cursor row)       |
| `K` *(in catalog)* | Mask editor on the cursor row's raw NeXus                  |

The catalog always lives on the right pane regardless of where you press
`i`, so the layout is predictable; `Ctrl+U` swaps file pane cwds without
moving the catalog.

The IPTS browser (the screen `i` opens) keeps input snappy on large
catalogs by debouncing the filter input (200 ms quiet window, so a
fast typist gets one rebuild instead of one per keystroke) and
capping the rendered window at the first 200 matches — an overflow
hint at the bottom (`+N more — narrow your filter`) tells you when
to keep typing.

---

### Mask creation

`sansdir mask` builds a Mantid-loadable detector mask from a raw
EQSANS `.nxs.h5` file in pure Python — no Mantid runtime required to
*create* the file. The output `.nxs` (Mantid Processed NeXus
`MaskWorkspace`) and `.xml` (Mantid `SaveMask` v1) loads back into
Mantid via `LoadNexusProcessed` / `LoadMask`.

Convention: **`1 = masked` (excluded), `0 = kept`** — same as
Mantid's `SpecialWorkspace2D`. Inverting the final mask is a single
flag (`--inverse`).

CLI shapes (pixel coordinates, repeatable):

- `--rect X0,Y0,X1,Y1`
- `--ellipse XC,YC,RX,RY`
- `--circle XC,YC,R`
- `--polygon X1,Y1,X2,Y2,...` (≥3 vertices)

Or replay an earlier mask via `--shapes-json mask.mask_log.json`
(a sidecar `.mask_log.json` is written next to every output).

```bash
# Beam-stop circle plus four corner masks → MaskWorkspace .nxs.
sansdir mask /SNS/EQSANS/IPTS-XXXXX/nexus/EQSANS_172749.nxs.h5 \
  --circle 96,128,12 \
  --rect 0,0,15,15   --rect 176,0,191,15 \
  --rect 0,240,15,255 --rect 176,240,191,255 \
  --output beam_stop.nxs

# Then in Mantid: LoadNexusProcessed("beam_stop.nxs") yields a
# MaskWorkspace ready to feed into MaskDetectors.
```

**Interactive editor** (TUI `K` keystroke from a file pane *or* the
catalog): opens a matplotlib window on the cursor's NeXus heatmap.
Cell aspect is set to `1/1.3` to compensate for the EQSANS detector's
~5.2 mm tube pitch / ~3.9 mm pixel pitch, so an Ellipse drawn to
look round on screen is round on the actual detector. A faint dotted
boundary marks the detector edge; the canvas extends a few cells
past it on every side so you can drag rubber-band rectangles edge to
edge without having to land the first click on column 0 / row 0.

- **Draw modes:** `r` rectangle · `e` ellipse. Circle and Polygon
  Shapes still exist (CLI: `--circle`, `--polygon`) but were dropped
  from the GUI menu — Ellipse covers the same ground without the
  cell-aspect rubber-band weirdness, and the bank/tube **Mask spec**
  input below covers the strip-mask case better than freehand
  polygons.
- **Edit mode:** `v` (or click the **Edit (v)** button). Click a
  drawn shape to **select** it (yellow outline), drag to **move**,
  press `Delete` to **remove** that one shape. Outside edit mode
  `Delete` falls back to plain undo so the keystroke is never a
  no-op.
- **Mask spec** (the **Mask Spec... (k)** button or the `k`
  shortcut opens a Tk dialog): type `b3` / `t50` / `b5-7 t10-15`
  to mask whole banks / tubes by number. Bank → 4 tubes; ranges
  and mixed tokens work; the resulting Rectangles round-trip
  through `mask_log.json` like any other shape. (Earlier drafts
  used an inline matplotlib `TextBox` here — switched to a
  dialog because matplotlib's text-widget redraws on every
  keystroke, which on a 256x192 LogNorm imshow lands as visible
  per-character lag.)
- **Cursor readout:** matplotlib's status bar shows
  `tube=N pixel=M counts=K · bank=B tube_in_bank=T` as you hover.
- **Other action keys:** `z` undo · `i` invert · `k` mask spec
  dialog · `s` save · `Esc` quit. The bottom button row is
  `Rect (r) · Ellipse (e) · Edit (v) · Undo (z) · Clear · Invert (i)
  · Save... (s) · Quit (Esc)`, with `Mask Spec... (k)` on the row
  below.
- **Move-in-edit-mode is blit-fast.** When you press to start
  dragging a shape, the editor snapshots the static canvas; each
  motion event then restores that snapshot and re-blits only the
  patch you're moving — orders of magnitude cheaper than redrawing
  the whole heatmap on every mouse pixel.
- **Save dialog:** `Save... (s)` opens a Tk file chooser pre-filled
  with the default path (the inactive pane's cwd /
  `<source-stem>_mask.nxs`). Pick a different folder or filename if
  you want; Cancel writes nothing. The GUI saves NeXus only; the
  CLI still produces XML / npy when asked.

The on-disk mask encoding mirrors a real EQSANS beamstop file
(`tests/data/mask_4m2.nxs`): each *unmasked* detector carries one
synthetic event, masked detectors carry zero. So when you press
`p` (or load the file in any heatmap viewer), the masked region
appears grey — same visual convention as a beamstop. The
`MaskBuilder` still uses Mantid's `1 = masked` convention
internally; only the on-disk encoding inverts.

The detector mapping is recovered directly from the source file
(event_id ↔ detector_id), so no Mantid IDF lookup, no
instrument-specific code in `src/`, and no Mantid runtime imports
anywhere in the package.

## CLI examples

```bash
# Beam-stop circle + corner masks. Mantid-loadable .nxs MaskWorkspace.
sansdir mask EQSANS_172749.nxs.h5 \
  --circle 96,128,12 \
  --rect 0,0,15,15 --rect 176,0,191,15 \
  --output beam_stop.nxs

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

- Dual-pane MDIR-style TUI with the full F-key suite (F2 rename,
  F3 view, F5 refresh, F6 copy, F7 move, F8 delete, F9 mkdir,
  F10 catalog toggle, plus tag-by-glob, swap, sync). Auto-refresh
  after every in-process write (copy / move / rename / mkdir / batch
  extract / zip); `F5` is the manual fallback for files dropped in
  by external processes. After a delete the cursor sticks near the
  deleted file (mc / Norton convention) instead of jumping to row 0.
- 1D plotting (Iq, transmission), 2D plotting (Iqxqy single + tile mode),
  raw EQSANS NeXus detector heatmap, **processed Mantid NeXus** detector
  heatmap (incl. drtsans wavelength-banded output and event-workspace
  masks) — all in pure numpy, no Mantid dependency.
- Reduced 2D `I(qx, qy)` Mantid Workspace files render via `pcolormesh`
  with proper `q_x` / `q_y` axes.
- Generic linear-linear plotter for CSV/TSV (`l`) — picks up the column
  header as axis labels. Pairs naturally with the `M` extractor output.
- Image viewer on `Enter` for `*.png` / `*.jpg` / `*.tiff` etc.
- OnCat IPTS browser (`i`) with debounced filter input + 200-row cap
  for snappy typing on big catalogs; per-IPTS catalog on the right
  pane (`F10` toggles), runs taggable with `Space`. From the catalog:
  `p` plot, `m` HDF5 tree, `M` batch extract, `K` mask editor.
- **Interactive mask editor (`K`):** matplotlib window with
  cell-aspect-aware ellipses, edit-mode (click/drag/delete), a
  bank/tube spec input (`b3`, `t50`, `b5-7 t10-15`), live cursor
  readout (`tube=N pixel=M · bank=B tube_in_bank=T`), and a Tk file
  chooser on save. Output mirrors the EQSANS beamstop visual
  convention so masked regions plot grey.
- Batch metadata extract with tree-based key picker (in-place search);
  per-file *and* summary modes; output goes to the **inactive** pane's
  cwd by default to avoid raw-data write-permission errors.
- Themes via Textual's built-in palette + `[keys]`-rebinding.
- Coloured file-kind hints, top-of-pane path bar (with
  `/gpfs/neutronsfs/instruments` → `/SNS` rewrite), bottom status with
  catalog-loaded indicator.
- Cold start: ~50 ms.
- 500 tests, ruff-clean.

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
