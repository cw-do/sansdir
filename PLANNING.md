# PLANNING.md

Architecture, design decisions, and data-format specifications for **sansdir**.

This document is the source of truth for *why* and *what*. Implementation lives in
code; this file is updated when a design changes, not when code changes.

---

## 1. High-Level Architecture

```
                    ┌────────────────────────────────────┐
                    │           Textual App              │
                    │  ┌─────────────┐  ┌─────────────┐  │
                    │  │ FilePanel L │  │ FilePanel R │  │
                    │  │  (active*)  │  │             │  │
                    │  └─────────────┘  └─────────────┘  │
                    │  ┌──────────────────────────────┐  │
                    │  │          StatusBar           │  │
                    │  └──────────────────────────────┘  │
                    │  ┌──────────────────────────────┐  │
                    │  │     CommandInput (`:`)        │  │
                    │  └──────────────────────────────┘  │
                    └──────────────┬─────────────────────┘
                                   │ async calls
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
   ┌─────────┐                ┌────────┐                 ┌──────────┐
   │  core/  │                │  hdf/  │                 │  plot/   │
   │ FS,zip, │                │ h5py   │                 │ plotext  │
   │ OnCat,  │                │ reader │                 │  + mpl   │
   │ mailer  │                │ batch  │                 │ backend  │
   └─────────┘                └────────┘                 └──────────┘
```

Two `FilePanel` widgets share the same widget class but maintain independent
state (cwd, cursor, tags, sort, filter). At any moment exactly one panel is
*active* (visually distinguished by border color); `Tab` switches activity.
File operations dispatched from key bindings always read from the active panel
and use the inactive panel's cwd as the default destination for copy/move.

The Textual App owns no business logic; it dispatches to the layers below.
All long-running work (OnCat HTTP, HDF5 reads, plot rendering) runs in
`asyncio.to_thread` or as Textual `@work` background tasks.

---

## 2. Why Python + Textual

We considered Rust (ratatui) and Go (bubbletea). Python wins because:

- The scientific stack at SNS is Python (Mantid, drtsans, sasmodels).
- HDF5/NeXus has first-class Python support (`h5py`, `mantid`); Rust HDF5 is
  immature and Mantid bindings would be a non-starter.
- Plotting fidelity matters; matplotlib parity in Rust is years away.
- Startup time is solved by lazy imports — we'll defer matplotlib and h5py
  imports until the first plot or HDF5 open.

**Cold-start budget**: 300 ms for `sansdir` to first paint. Achieved by:

- Importing only Textual + click + tomllib at top level.
- Lazy-importing plot/, hdf/, core/oncat at first use.
- Caching directory listings keyed by mtime.

---

## 3. UI Layout (MDIR / Norton Commander style)

```
┌─ /SNS/EQSANS/IPTS-12345/shared ──── ▒ ─┬─ ~/work/triage ──────── 17 files ──┐
│  ..                            <DIR>   │  ..                       <DIR>     │
│  autoreduce                    <DIR>   │  notes.md             1.2 KB Jul 14 │
│  data                          <DIR>   │  baseline_Iq.dat      8.4 KB Jul 11 │
│ *EQSANS_98765_Iq.dat       12.3 KB Jul │ *side_by_side.zip     4.1 MB Jul 12 │ ← inactive pane
│ *EQSANS_98765_Iqxqy.dat     2.1 MB Jul │  ...                                │
│  EQSANS_98765_trans.txt     0.8 KB Jul │                                     │
│  EQSANS_98765.nxs.h5        3.4 GB Jul │                                     │
│  ...                                   │                                     │
│ ◄ active                               │                                     │
├────────────────────────────────────────┴─────────────────────────────────────┤
│ Tagged L: 2 files, 2.1 MB │ Free: 487 GB │ Tab:swap F5:copy→ F6:move→ ?:help │
├──────────────────────────────────────────────────────────────────────────────┤
│ : _                                                                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

- **Two panes** (left and right) — independent cwd, cursor, tags, sort,
  and filter. Active pane has highlighted border (shown as `▒` in the mock).
- **Header** of each pane: cwd (truncated middle if long), file count.
- **Pane body**: file list with name, size, mtime; selection cursor; `*` prefix
  on tagged rows.
- **Status bar**: tag summary for active pane, free space on its filesystem,
  hot keys hint (changes contextually).
- **Command line** (`:` prefix, vim-style): internal commands (`:plot`,
  `:zip foo.zip`, `:ipts neutron-bio`) and shell-out (`:!ls -la`).

`Tab` switches active pane. `Ctrl+U` swaps left/right contents. `=` syncs the
inactive pane's cwd to match the active pane (useful before a same-directory
copy with renames). `Ctrl+O` toggles a maximized single-pane view if the user
wants more vertical real estate temporarily.

A folder-browser modal (`g` then `Tab`) gives a tree view for typing-averse
navigation; it loads into the active pane.

---

## 4. SANS Data Format Specifications

### 4.1 1D reduced data — `*Iq.dat`, `*_Iq.txt`

Whitespace-delimited ASCII, optional header lines starting with `#`.

| Columns | Layout | Notes |
|---|---|---|
| 2 | `q  I(q)` | Plot as line; default log-log |
| 3 | `q  I(q)  σI` | Errorbars on I; default log-log |
| 4 | `q  I(q)  σI  σq` | Same as 3-col; ignore col 4 |

Detection rule: count non-comment columns on the first data line.

### 4.2 Transmission — `*trans*.txt`

| Columns | Layout |
|---|---|
| 2 | `λ  T(λ)` |
| 3 | `λ  T(λ)  σT` |

X-axis: wavelength (Å), linear. Y-axis: transmission (0–1), linear.
Title and labels differ from I(q) plots.

### 4.3 2D reduced data — `*Iqxqy*.dat`, `*_2D.dat`

| Columns | Layout |
|---|---|
| 4 | `qx  qy  I  σI` |
| 6 | `qx  qy  I  σI  dqx  dqy` |

Plot as scatter / pcolormesh on a regular grid.
Auto-detect grid by sorting unique qx, qy.

### 4.4 NeXus raw — `*.nxs.h5`

Conventional paths at SNS:
```
/entry/instrument/bank<N>/data            (event-summed pixel array)
/entry/instrument/bank<N>/total_counts    (scalar)
/entry/DASlogs/<name>/value               (scalar or 1D time series)
/entry/DASlogs/<name>/time                (time axis)
/entry/sample/...                         (sample meta)
```

For "total detector sum" plot: sum across all bank arrays into a 2D image
(banks may be tiled; for v1, plot each bank as a tile).

### 4.5 Tile mode for multiple 2D files

When >1 file is tagged for 2D plot:

- Auto-grid: `ceil(sqrt(n))` columns.
- Filename as subplot title.
- Two colorbar modes:
  - **shared**: one colorbar, common vmin/vmax (mean ± 3σ across all data).
  - **independent**: per-subplot colorbar.
- User picks via `P` (capital) options dialog.

---

## 5. Plot Backend Strategy

**Decision: matplotlib in its own window is the primary and default path.**
Character-based in-terminal plotting (plotext, etc.) was considered and rejected
— SANS users need to read log-log axes precisely, inspect 2D heatmap features
at the pixel level, and interactively zoom/pan, none of which terminal plots
do well.

```
                  ┌────────────────────────┐
                  │     plot/detect.py      │
                  │   (file → plot kind)    │
                  └──────────┬──────────────┘
                             ▼
                  ┌────────────────────────┐
                  │     plot/backend.py     │
                  │  (probe display first)  │
                  └──────────┬──────────────┘
              ┌──────────────┼──────────────────┐
              ▼              ▼                  ▼
       has $DISPLAY?    no display       --no-window flag set
              │              │                  │
              ▼              ▼                  ▼
       matplotlib       matplotlib         matplotlib
       interactive         Agg                Agg
       (QtAgg/TkAgg)    PNG to disk        PNG to disk
       window opens     + xdg-open?       (CI / scripted)
```

### Display probe (called once at first plot, cached)

```python
def has_display() -> bool:
    if os.environ.get("SANSDIR_HEADLESS"):
        return False
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
```

### Backend selection

- **Display present** → try `QtAgg`, then `TkAgg`, then `GTK4Agg`. Use whichever
  imports successfully. Window opens in non-blocking mode (`plt.show(block=False)`)
  so the TUI stays responsive. Multiple plot calls open multiple figure windows.
- **Headless** → `matplotlib.use("Agg")`. Save to `~/.cache/sansdir/plots/<timestamp>_<title>.png`.
  Print path in status bar with a copyable shortcut.

### Coexistence with Textual

Textual runs in alt-screen mode; matplotlib windows are separate OS windows
and do not conflict. When the user closes a matplotlib window, the TUI stays
alive. If the user `q`-quits the TUI, any open figures are also closed
(`plt.close("all")` on shutdown).

### Plot quality conventions

- I(q): default log-log; errorbars on if 3+ columns; legend with filename if
  multiple curves; `q` in Å⁻¹, `I(q)` in cm⁻¹ unless overridden.
- Transmission: linear-linear; x = wavelength (Å), y = transmission (0–1).
- 2D Iqxqy: `pcolormesh` on auto-detected grid; symmetric `qx`/`qy` axes
  unless data isn't symmetric; default colormap `viridis`; log colorscale
  toggle in options dialog.
- Tile mode: `matplotlib.pyplot.subplots(nrows, ncols)` with shared or
  independent colorbars per the user's choice.

### Configuration

`~/.config/sansdir/config.toml`:
```toml
[plot]
prefer_window = true              # if false, always Agg→PNG
window_backend_priority = ["QtAgg", "TkAgg", "GTK4Agg"]
plot_cache_dir = "~/.cache/sansdir/plots"
default_xscale_iq = "log"
default_yscale_iq = "log"
default_xscale_trans = "linear"
default_yscale_trans = "linear"
auto_open_png = false             # try xdg-open after Agg→PNG fallback
colormap_2d = "viridis"
```

---

## 6. OnCat Integration

Port from <https://github.com/cw-do/eqsanscli> (the `/load ipts` command).
Re-implement, do not vendor.

### Endpoints (cross-checked against eqsanscli's pyoncat usage)
- `https://oncat.ornl.gov/oauth/token` — OAuth2 client_credentials grant.
- `https://oncat.ornl.gov/api/experiments?facility=SNS&instrument=EQSANS&projection=...`
  — list experiments. Per-experiment fields used: `id` ("IPTS-NNNNN"),
  `title`, `members` (list of PI/co-investigators), `rank`, `size`,
  `activity` (last-active date).
- `https://oncat.ornl.gov/api/datafiles?facility=SNS&instrument=EQSANS&experiment=IPTS-NNNNN&exts=.nxs.h5&projection=...`
  — list runs within an IPTS.

### Auth
OnCat requires an OAuth2 access token even for read-only endpoints. We
use the same `client_credentials` flow eqsanscli uses but **do not**
hardcode credentials — read them from `[oncat]` in
`~/.config/sansdir/config.toml`, the env vars `ONCAT_CLIENT_ID` /
`ONCAT_CLIENT_SECRET`, or fall back to anonymous (which fails with a
clear status-bar message and a pointer to the config).

### Free-text "keyword search"
OnCat's REST API doesn't expose a fuzzy keyword endpoint. We list all
experiments for the configured instrument once, cache that list (TTL
per config — default 24 h), then filter client-side: substring match on
`title`, `id`, and any element of `members`. This keeps every search
sub-second after the first call without burdening OnCat.

### UX
1. User types `i` or `:ipts <keyword>`.
2. Modal opens; results stream in (async httpx).
3. Each row: `IPTS-NNNNN  | Title | PI | Date`.
4. `Enter` on a row → cd into `/SNS/<INST>/IPTS-NNNNN/` (instrument-aware).
5. `f` on a row → fuzzy-search runs within that IPTS.

### Caching
Results cached in-memory for the session. Optional disk cache at
`~/.cache/sansdir/oncat/<query-hash>.json` with TTL = 1 day.

### Auth
Read-only public endpoints first. If authenticated endpoints are needed,
read token from `~/.config/sansdir/oncat_token` (file mode 600).

---

## 7. HDF5 Metadata Workflow

### 7.1 Single-file inspection (`m`)
- Open file with `h5py.File(path, 'r', swmr=True)`.
- Show a tree dialog of the HDF5 hierarchy (lazy-expand).
- Selecting a leaf shows: path, dtype, shape, value preview, units (from attrs).

### 7.2 Batch extraction (`M`)
Workflow:
1. User tags N HDF5 files.
2. Press `M` → dialog asks for keys (autocomplete from first file).
3. User can pick multiple keys (e.g. `DASlogs/shear/value`,
   `DASlogs/temperature/value`, `duration`).
4. Choose output: TSV, CSV, or columnar text.
5. Output path defaults to `./extracted_<keys>.tsv`.

Output format example:
```
filename	shear	temperature	duration
EQSANS_12345.nxs.h5	1.5	298.15	600.0
EQSANS_12346.nxs.h5	3.0	298.15	600.0
...
```

DASlogs values: take `.mean()` of `value[]` if it's a time series; flag
`stdev` and `n_points` as optional extra columns.

Async/parallel: use `concurrent.futures.ThreadPoolExecutor` (h5py releases GIL
on read). Show a progress bar in the dialog.

---

## 8. File Operation Semantics

All operations act on the **active** pane's tagged files (or current row if
no tags). Copy/move default destination is the **inactive** pane's cwd —
user can override at the prompt.

| Op | Key | Behavior |
|---|---|---|
| Tag / untag | `Space` | Per-pane selection set; cleared on cd within that pane |
| Glob tag | `+` / `*` | Prompts for pattern; matches against active pane's view |
| Glob untag | `-` | Same, but unsets matching tags |
| Copy | `F5` | Default dest = inactive pane cwd; uses `shutil.copy2`; progress bar |
| Move/rename | `F6` | Same as copy + delete; cross-device safe; rename if dest is in same dir |
| Make dir | `F7` | Inline prompt in active pane; refuses to overwrite |
| Delete | `F8` / `Del` | **Always confirms**; uses `send2trash` if available, else `os.remove` |
| Zip | `z` | `zipfile.ZipFile` deflate; default name `<active-cwd-basename>.zip` written into inactive pane cwd |
| Mail | `e` | Pipes tagged files to `mail -a` or `mutt -a`; prompts recipient + subject |
| Sync panes | `=` | Set inactive pane cwd to match active pane |
| Swap panes | `Ctrl+U` | Exchange left and right panel state entirely |

All destructive operations log to `~/.cache/sansdir/history.log`.

---

## 9. Configuration

Default config file: `~/.config/sansdir/config.toml`. Created on first run.

```toml
[ui]
theme = "monokai"
hidden_files = false
sort = "name"           # name | mtime | size | ext
sort_reverse = false

[oncat]
default_instrument = "EQSANS"
cache_ttl_seconds = 86400

[plot]
default_backend = "plotext"
default_xscale_iq = "log"
default_yscale_iq = "log"

[hdf5]
default_batch_keys = ["DASlogs/temperature/value", "DASlogs/shear/value"]

[mail]
command = "mail"        # or "mutt"
default_subject = "[sansdir] data"
```

Per-key bindings in `[keys]` section so power users can rebind.

---

## 10. Performance Targets

| Operation | Budget |
|---|---|
| App cold start | < 300 ms |
| Directory of 1000 files | < 100 ms to render |
| OnCat search response | < 2 s typical |
| 1D plot in plotext | < 50 ms |
| 2D plot in plotext (heatmap, 256×256) | < 200 ms |
| HDF5 metadata read (single key) | < 50 ms |
| Batch metadata extract, 100 files, 5 keys | < 10 s |

Profile with `pyinstrument` when a target is missed.

---

## 11. Testing Strategy

- **Unit tests** for every `core/`, `hdf/`, `plot/detect.py` module.
- **TUI snapshot tests** with `pytest-textual-snapshot` for FilePanel,
  StatusBar, dialogs.
- **Integration tests** with `tests/data/` fixtures: tiny synthetic
  Iq.dat, Iqxqy.dat, and a minimal NeXus file generated by a fixture script.
- **OnCat tests** use `pytest-httpx` to mock responses; never hit real OnCat.
- **No tests on real cluster paths.**

CI: GitHub Actions, matrix on Python 3.10/3.11/3.12, Linux only.

---

## 12. Command Registry & LLM Readiness

This is the most consequential architectural decision in the project, because
it determines whether the planned natural-language layer (Phase 10+) is a
drop-in feature or a months-long rewrite.

### 12.1 The pattern

Every user-facing action — `cd`, `tag`, `copy`, `plot.iq`, `plot.tile_2d`,
`hdf.extract_metadata`, `oncat.search`, `zip`, `mail`, … — is implemented as
a `Command` registered in a single `CommandRegistry`. The registry is the
**only** path through which user intent becomes execution.

```python
# src/sansdir/commands/registry.py (sketch)

from dataclasses import dataclass, field
from typing import Callable, Any, Awaitable

@dataclass
class CommandParam:
    name: str
    type: str                # "path" | "glob" | "string" | "int" | "float" | "bool" | "enum" | "files"
    description: str
    required: bool = True
    default: Any = None
    choices: list[str] | None = None    # for type=="enum"

@dataclass
class Command:
    name: str                            # dotted, e.g. "plot.iq"
    description: str                     # one sentence, human-readable
    params: list[CommandParam]
    handler: Callable[..., Awaitable[Any] | Any]   # may be async
    aliases: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    danger: bool = False                 # destructive ops; LLM must confirm

class CommandRegistry:
    def register(self, cmd: Command) -> None: ...
    def get(self, name_or_alias: str) -> Command: ...
    def all(self) -> list[Command]: ...
    async def dispatch(self, name: str, **kwargs) -> Any: ...
    def to_json_schema(self) -> list[dict]:
        """Return list of tool schemas usable directly by Anthropic / OpenAI tool-calling."""
```

### 12.2 What dispatches through the registry

| Caller | Path |
|---|---|
| **Keybinding** | `keys.py` maps `F5` → `("file.copy", {"src": active_tags, "dst": inactive_cwd})` → `registry.dispatch(...)` |
| **`:` command line** | `command_input.py` parses `cp foo.txt /tmp` → `("file.copy", {...})` → `registry.dispatch(...)` |
| **CLI subcommand** | `sansdir extract --keys ...` → builds args → `registry.dispatch("hdf.extract_metadata", ...)` |
| **LLM layer (Phase 10+)** | NL prompt + `registry.to_json_schema()` → Anthropic tool-call returns command name + args → `registry.dispatch(...)` |

There must be **no** business-logic call path that bypasses the registry.
Code reviewers (and Claude Code, which reads this file) reject PRs that do.

### 12.3 Naming convention

Dotted, scoped, lowercase: `<scope>.<verb>`. Examples:
`nav.cd`, `nav.up`, `pane.swap`, `pane.sync`, `tag.toggle`, `tag.glob`,
`file.copy`, `file.move`, `file.delete`, `file.mkdir`, `archive.zip`,
`archive.mail`, `view.file`, `edit.file`, `plot.iq`, `plot.transmission`,
`plot.iqxqy`, `plot.tile_2d`, `plot.detector_sum`, `hdf.show_keys`,
`hdf.extract_metadata`, `oncat.search`, `oncat.list_runs`, `app.quit`,
`app.help`.

### 12.4 LLM layer (Phase 10+, optional)

When the optional `[llm]` extra is installed:

1. User types `\` (backslash) or `:ask <NL prompt>` in the TUI.
2. `llm/translator.py` builds an Anthropic `messages.create` call:
   - System prompt includes context: cwd of both panes, list of tagged files,
     cluster awareness ("you are operating on the ORNL SANS analysis cluster").
   - Tools are the JSON schema returned by `registry.to_json_schema()`.
   - Few-shot examples from `llm/prompt.py` show NL-to-tool-call mappings:
     - "tag all the trans files and zip them" → `tag.glob *trans*` then `archive.zip`.
     - "plot the I(q) of run 12345" → `plot.iq` with the resolved file path.
     - "pull shear and temperature from these into a tsv" → `hdf.extract_metadata`.
3. The model returns one or more tool calls.
4. **Plan preview**: the TUI shows the proposed command list with arguments
   in a modal. User reviews, edits if needed, and confirms with `Enter`
   (or rejects with `Esc`). For commands marked `danger=True` (delete, move,
   overwrite), confirmation is mandatory and unconditional.
5. On confirm, commands run through `registry.dispatch` exactly as if the user
   had typed them.

The LLM never executes code or shell directly — it can only emit
registry-defined commands with typed arguments. This is the safety boundary.

### 12.5 What this buys us today (before Phase 10)

Even with no LLM yet, the registry pattern delivers immediate value:

- **Testability**: command handlers can be tested in isolation, decoupled
  from Textual.
- **Documentation**: `:help <command>` and `?` overlay are auto-generated
  from registry metadata.
- **Macros**: a `:do <cmd1>; <cmd2>; <cmd3>` becomes trivial.
- **Replay/history**: `~/.cache/sansdir/history.log` records command names
  + arguments, enabling future undo and "rerun last".
- **CLI consistency**: subcommands and TUI commands cannot diverge —
  they're the same code path.

### 12.6 What Claude Code must NOT do

- Do not write a Textual `on_key` handler that directly calls
  `shutil.copy(...)` — register `file.copy` and bind the key to it.
- Do not have two implementations of "list a directory" (one for TUI, one
  for CLI) — one command, two callers.
- Do not introduce `eval`, `exec`, or natural-language parsing inside the
  command-line input. The `:` line takes only registered command names with
  positional/keyword args. Natural language goes through `llm/`.

---

## 12.7 Mask architecture *(Phase 9.6)*

Detector-mask creation lives in `src/sansdir/mask/`. Three strict
boundaries:

- **No Mantid runtime imports anywhere in `src/sansdir/`.** `grep -r
  "import mantid" src/` returns nothing. The on-cluster Mantid env
  is exercised only by an out-of-source verification script.
- **No instrument-specific code in `src/`.** No `mask/instruments/`
  subdirectory, no per-instrument pixel-to-detector formula. The
  detector mapping comes from the source NeXus file itself.
- **Pixel-ordering is one-place-only.** `mask.flatten()[k]` aligns
  with `source_meta.pixel_ids[k]` by construction in
  `mask/detector.py`; the writer is a thin function that reads that
  invariant and writes detector-id-indexed output.

Module breakdown:

- `mask/core.py` — `Shape` (Rectangle / Ellipse / Circle / Polygon),
  vectorised `rasterise(detector_shape) -> bool`, `MaskBuilder`
  unions shapes and applies the optional `inverse` flag at the end.
  **Convention**: `1 = masked` (excluded), `0 = kept`. Mirrors
  Mantid's `SpecialWorkspace2D` so a Mantid `MaskDetectors` call on
  our output excludes exactly the cells the user drew.
- `mask/detector.py` — wraps the existing
  `sansdir.plot.hdf5_detector.load_eqsans_raw` heatmap. Pairs the
  `(256, 192)` image with a `pixel_ids` array such that
  `image.flatten()[k]` == detector ID `pixel_ids[k]`. When the file
  ships an explicit `bank1/pixel_id` dataset, that's used verbatim;
  otherwise the canonical EQSANS event-mode mapping is derived
  from the same `_reorder_tubes` permutation the heatmap loader
  applies — so the writer's detector list always matches the
  pixels the user drew on.
- `mask/writers.py` — pure stdlib + h5py + numpy.
  - `write_xml` emits Mantid SaveMask v1 (`<detector-masking>` with
    range-compressed `<detids>`).
  - `write_nxs` emits a Mantid Processed-NeXus MaskWorkspace (group
    `mask_workspace` under `mantid_workspace_1`, `definition =
    "Mantid Processed Workspace"`, the canonical 5-dataset
    `instrument/detector` block). Mantid 6.13 reworked NeXus loading
    so the older "workspace" group + lowercase definition no longer
    load — the writer matches what Mantid 6.15's own
    `SaveNexus(MaskWorkspace)` writes.
  - `write_npy` is `np.save` plus a `.meta.json` sidecar.
  - `write_log` writes `mask_log.json` next to every output for
    round-trip via `MaskBuilder.from_log`.
- `mask/api.py` — single `create_mask(source, shapes, output, fmt,
  inverse) -> MaskResult` plus the `--rect`/etc. CLI parsers. Used
  by both the CLI subcommand (`sansdir mask`) and the registry
  command (`mask.create` / `K` keystroke).

The interactive matplotlib editor is a separate iteration; the CLI
form is the canonical entry point until then.

---

## 13. Open Questions (to resolve as we build)

- Should `Ctrl+O` (maximize active pane) be a true single-pane mode or just
  a 90/10 split? (Default proposal: true maximize, restore on second press.)
- Should HDF5 reader use Mantid when available for richer metadata? (Maybe Phase 8.)
- Should we add a `:diff` command for two reduced datasets, with the two
  files coming from the two panes by default? (Future, but the dual-pane
  layout makes this natural.)
- USANS-specific plotting (slit-smeared)? Out of scope for v1.
- For the LLM layer: local model (e.g. Llama 3 via vLLM on the cluster) vs
  Anthropic API as default? Probably Anthropic API for v1; local backend
  pluggable in `llm/translator.py`.

