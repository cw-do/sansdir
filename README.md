# SansDIR

▣ **SansDIR v0.10** — a fast, keyboard-driven dual-pane terminal file manager
for Small-Angle Neutron Scattering data on the ORNL analysis cluster.
Inspired by the DOS-era **MDIR** and Norton Commander.

> **Status**: beta. Daily-driven for EQSANS workflows. See
> [`docs/sansdir-report.pdf`](./docs/sansdir-report.pdf) for the full
> technical report, including the architecture.

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
| `Enter`        | Smart open: cd into folder · view image · preview any text file in the other pane · *(catalog)* plot run |
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
| `F3`      | View file in the *other* pane (Tab into it; `Esc` / `F3` close). `Enter` does the same for text files, but only ever opens |
| `F4`      | Edit in `$EDITOR`                                            |
| `F5`      | **Refresh** both panes — also repairs stale panes (see below) |
| `F6`      | Copy tagged → other pane (with confirm)                      |
| `F7`      | Move tagged → other pane                                     |
| `F8` / `Del` | Delete tagged (confirm; `send2trash` with cluster fallback)|
| `F9`      | Make directory (active pane)                                 |
| `c`       | Toggle catalog / list (other pane) — Phase 4                 |
| `z`       | Zip tagged → prompt for archive name                         |
| `e`       | Email tagged (`mail` / `mutt` shell-out)                     |

**Deleted out from under you.** If a pane is sitting *inside* a directory
that gets deleted — from the other pane, a `:!rm`, or another user on a
shared filesystem — it re-anchors to the nearest surviving ancestor and
says so, rather than showing zero rows at a dead path (which is
indistinguishable from an empty directory). An inline viewer whose file is
deleted closes instead of continuing to render content that no longer
exists. Both happen automatically on delete/move and on `F5`.

`F5` reloads both panes; useful when an external process (a separate
shell, an NFS catch-up) drops files into a pane's cwd. The in-process
flows (copy / move / mkdir / batch extract / zip / rename) refresh
automatically. The mask GUI runs as a detached subprocess but its
launcher awaits the exit code in a Textual worker — when the editor
exits with a save (rc=0) both panes refresh so the new
`*_mask.nxs` shows up without the user having to press F5.

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
| `K` | Create a detector mask from the cursor's NeXus file (raw or processed)  |

Inside the `m` tree browser, `/` switches to **keyword search** — the same
substring filter the `M` picker offers, so you don't have to expand your way
down to `/entry/DASlogs/…`. Type a fragment (case-insensitive), then `↑`/`↓`
to scan the hits without leaving the search box; the detail pane shows the
highlighted key's dtype, shape, units and value preview. `Esc` returns to the
tree, a second `Esc` (or `q`) closes the modal. Hits are capped at 500 — the
hint line tells you when a query was truncated.

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
| `c` | Show / hide the right-pane catalog                                            |
| `Space` *(in catalog)* | Tag a run                                            |
| `p` *(in catalog)* | Plot the cursor's raw NeXus run                            |
| `Enter` *(in catalog)* | Plot the raw run — or, in USANS mode, build the setup CSV |
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

### USANS reduction

sansdir runs in one of two **instrument modes**. SANS is the default;
launching under `/SNS/USANS/...` (or any path containing `usans`)
switches to USANS automatically, and `:instrument usans` /
`:instrument eqsans` flips it at runtime. The mode shows as a chip in the
title bar and decides what `i` searches, which columns the run catalog
shows, and whether the USANS key is live. **SANS behaviour and keys are
completely unchanged by this.**

USANS adds exactly two operations. Everything else — browsing, `F4`
editing, `p` plotting, `/` filtering — is the sansdir you already know.

USANS adds **one key**: `r`. It reduces the setup table under the cursor —
and when there isn't one, it offers to build it from the IPTS in the
current path. So the whole workflow from an empty folder is `r`, `F4`, `r`:

```
cd /SNS/USANS/IPTS-37679/shared

r    → "No setup table selected. Build a preliminary reduction table
        for IPTS-37679?"        → fetches the run list, shows the catalog
                                  on the right pane, writes the CSV + NOTE,
                                  and opens the CSV for review
F4   → correct anything the NOTE flagged
r    → reduce (prompts for the output directory)
p    → plot UN_*_det_1_lb.txt / _background_subtracted.txt
```

| Key | What it does                                                                |
|-----|-----------------------------------------------------------------------------|
| `r`  | **Reduce** the setup CSV under the cursor — or offer to build one          |
| `F4` | Review / correct the CSV in `$EDITOR`                                      |
| `p`  | Plot the reduced `UN_*_det_1_lb.txt` / `_background_subtracted.txt` curves |
| `i` | Browse USANS experiments — only needed for an IPTS you're *not* sitting in  |
| `Enter` *(in catalog)* | Build the setup CSV from the loaded catalog             |

The IPTS is read from the pane's path first, then a loaded catalog, then a
prompt — so `i` is optional, not a prerequisite. Command-line equivalents:
`:usans-init [start_run]`, `:usans-reduce [path]`.

`r` deliberately **stops after generating**: it never reduces a table you
haven't seen. A table that exists but fails validation (two `b` rows, say)
is reported for you to fix with `F4` — it is never silently regenerated
over your edits.

**The generated CSV is preliminary by design.** Generating groups the OnCat
run list into same-title blocks, auto-detects the empty-cell background,
and — critically — sets `num_of_scans` from the ARN-scan files actually on
disk rather than the OnCat title count. A titled block of *N* runs is
really *(N−1)* ARN rocking scans **plus one transmission run**; feeding the
engine the full *N* makes it die on the transmission run's missing ASCII.
*N* varies between experiments (5→4, 6→5, …), so it is derived, never
assumed. Anything the generator had to guess — restarts, odd block sizes,
blocks with no ARN files, dropped transmission runs — is written to
`<IPTS>_NOTE.md` for you to check before pressing `r`.

Every generated `NOTE.md` ends with a legend for the reduced-output
filenames, because they are the engine's and are easy to misread — most of
all `_lb.txt`, which is log-binned but is the subtraction's *input*:

| file | scaled | log-binned | background subtracted |
|---|---|---|---|
| `UN_<name>_det_1_unscaled.txt` | no | no | no |
| `UN_<name>_det_1.txt` | yes | no | no |
| `UN_<name>_det_1_lb.txt` | yes | yes | **no** |
| `UN_<name>_det_1_background_subtracted.txt` | yes | yes | **yes** ← plot this |

The last one is the final curve; the older loose `usans-reduction` script
called it `_lbs.txt`, and `usansred` renamed it. The background sample gets
no `_background_subtracted.txt` — nothing is subtracted from itself.

Reduction itself is **not** implemented in sansdir: `r` shells out to the
instrument team's installed `reduceUSANS` (`neutrons/usansred`) with `-l`
(log-binning) on by default. Two deployment details are handled for you:

- The pixi console script otherwise inherits your `~/.local`
  site-packages and can crash on a stale `pandas`/`pytz`, so sansdir
  always invokes it with `PYTHONNOUSERSITE=1` and an empty `PYTHONPATH`.
- The engine reads its per-run ASCII from *the directory holding the setup
  CSV*. Rather than writing your CSV into the instrument's `autoreduce`
  folder, sansdir stages a throwaway directory of symlinks and runs there.
  **Nothing under `/SNS` is ever written to.**

```bash
# Headless equivalents of the two TUI operations.
sansdir usans init 37679 --start-run 49434     # → IPTS-37679_setup.csv + _NOTE.md
$EDITOR IPTS-37679_setup.csv                   # review; this is the point
sansdir usans reduce IPTS-37679_setup.csv -o ./output
```

The setup CSV is the format `reduceUSANS` documents, so it stays readable
and hand-editable:

```
# USANS reduction table for IPTS-37679
# columns: flag,name,start_scan,num_of_scans,thickness_cm[,exclude]
#   flag: b=background(empty)  s=sample
b,emptyBanjo-restart,49434,4,0.1
s,S0-20C,49439,4,0.1
s,S0-40C,49444,4,0.1,49446
```

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
# USANS: build a preliminary reduction table, then reduce it.
sansdir usans init 37679 --start-run 49434
sansdir usans reduce IPTS-37679_setup.csv -o ./output

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

[instrument]
default     = "EQSANS"   # "" → fall back to [oncat].default_instrument
auto_detect = true       # a /SNS/USANS/... launch path overrides `default`

[usans]
pixi_manifest     = "/usr/local/pixi/usansred"   # where reduceUSANS lives
reduce_command    = ""                            # explicit argv override
data_dir_template = "/SNS/USANS/{ipts}/shared/autoreduce"
logbin            = true                          # pass -l by default
thickness_cm      = 0.1                           # default in new setup CSVs

[mail]
command = "mail"        # or "mutt"
default_subject = "[sansdir] data"
```

Switch theme live: `:theme monokai` (bare `:theme` lists available names).

---

## What's in v0.10

The v0.9 → v0.10 jump adds **USANS reduction** (Phase 9.8) and a
workflow-polish pass driven by using it on real IPTS-37679 data
(Phase 9.9).

- **Instrument mode** — one TUI for both families. SANS is the
  default; a `/SNS/USANS/...` launch path auto-switches, and
  `:instrument usans` / `:instrument eqsans` flips at runtime. The
  mode shows as a chip in the title bar and decides the OnCat
  instrument, the catalog's columns, and whether `r` is live.
  **No SANS key or behaviour changed.**
- **USANS reduction in two steps, on one key.** `r` reduces the setup
  table under the cursor — and when there isn't one, offers to build
  it from the IPTS in the current path (fetching the run list and
  showing the catalog on the right pane). So the whole flow from an
  empty folder is `r`, `F4`, `r`.
- **`num_of_scans` derived from disk, not guessed.** A titled block of
  *N* runs is *(N−1)* ARN scans plus one transmission run, and *N*
  varies per experiment. Feeding the engine the OnCat title count is
  what makes `reduceUSANS` die with `FileNotFoundError`.
- **The setup CSV is a first draft.** Restarts, odd block sizes and
  the background pick are all flagged in a companion `NOTE.md`, which
  also carries a legend for the reduced-output postfixes (`_lb.txt`
  is log-binned but *not* subtracted; the final curve is
  `_background_subtracted.txt`, once called `_lbs.txt`).
- **Reduction is delegated**, never reimplemented: sansdir shells out
  to the instrument team's `reduceUSANS` in a clean environment, via
  a staging directory of symlinks. **Nothing under `/SNS` is written.**
- `sansdir usans init` / `sansdir usans reduce` for headless use.
- Polish that applies to SANS too: `Enter` previews any text file in
  the other pane; the inline viewer frees its buffer when closed; a
  pane whose directory is deleted re-anchors to the nearest surviving
  ancestor instead of showing a dead path; a viewer whose file is
  deleted closes instead of rendering a ghost.

---

## What's in v0.9

The v0.8 → v0.9 jump bundles **Phase 9.6** (interactive mask
creation from raw NeXus) and **Phase 9.7** (a polish pass driven
by direct feedback from the first scientist using the mask
editor on real EQSANS data — cell aspect, drawing-area margin,
on-disk encoding inversion to match `mask_4m2.nxs`'s visual,
TextBox → Tk dialog and blit-based moves for responsiveness,
F-key reshuffle, OnCat browser debounce + cap, mask-save auto
refresh).

- Dual-pane MDIR-style TUI with the full F-key suite (F2 rename,
  F3 view, F5 refresh, F6 copy, F7 move, F8 delete, F9 mkdir;
  `c` for the catalog toggle since most terminals reserve F10
  for the menu bar; tag-by-glob, swap, sync). Auto-refresh
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
  for snappy typing on big catalogs; `r` (or `Ctrl+R`) forces a
  cache-bypassing re-fetch when a just-allocated IPTS is missing
  (the 24h disk cache occasionally serves stale data otherwise);
  per-IPTS catalog on the right pane (`c` toggles), runs taggable
  with `Space`. From the catalog: `p` plot, `m` HDF5 tree, `M` batch
  extract, `K` mask editor.
- **Interactive mask editor (`K`):** matplotlib window with
  cell-aspect-aware ellipses, edit-mode (click/drag/delete), a
  bank/tube spec input (`b3`, `t50`, `b5-7 t10-15`), live cursor
  readout (`tube=N pixel=M · bank=B tube_in_bank=T`), and a Tk file
  chooser on save. Output is **drtsans-compatible**: the save step
  shells out to the cluster's ``drtsans --classic`` (Mantid wrapper)
  to run ``Load → MaskDetectors → SaveNexus`` against the source
  NeXus, producing a file whose ``instrument_parameter_map`` carries
  the per-detector mask flags drtsans's reduction pipeline reads.
  Falls back to a legacy pure-numpy writer (visualisation-only, no
  reduction effect) when Mantid is unavailable.
- HDF5 tree browser (`m`) with lazy expansion and `/` keyword search
  over the whole key list.
- Batch metadata extract with tree-based key picker (in-place search);
  per-file *and* summary modes; output goes to the **inactive** pane's
  cwd by default to avoid raw-data write-permission errors.
- Themes via Textual's built-in palette + `[keys]`-rebinding.
- Coloured file-kind hints, top-of-pane path bar (with
  `/gpfs/neutronsfs/instruments` → `/SNS` rewrite), bottom status with
  catalog-loaded indicator.
- Cold start: ~50 ms.
- 506 tests, ruff-clean.

---

## Project documents

- [`docs/sansdir-report.pdf`](./docs/sansdir-report.pdf) — ORNL technical
  memorandum: architecture, data formats, full command and keybinding
  reference. Built from `docs/sansdir-report.tex`; see `docs/README.md`.

---

## Author

Changwoo Do — Neutron Scattering Division, Oak Ridge National Laboratory
(`doc1@ornl.gov`).

## License

MIT.
