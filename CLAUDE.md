# CLAUDE.md

This file is read by Claude Code at the start of every session in this repo.
Treat its contents as standing instructions.

---

## 1. Project Overview

**sansdir** is a fast, keyboard-driven terminal UI (TUI) for navigating, inspecting,
and plotting Small-Angle Neutron Scattering (SANS) data on the ORNL analysis cluster.
It is conceptually inspired by the DOS-era **MDIR** (and Norton Commander / Midnight
Commander) file manager: **two side-by-side file panels**, F-key driven actions,
prominent command line at the bottom, no mouse required. The two-pane layout is
core to the UX — copy/move operations default to "active pane → other pane",
which is why MDIR users could move files faster than any GUI.

**Primary users**: SANS instrument scientists and users at ORNL (EQSANS, BIOSANS,
GP-SANS, USANS) who already work on the analysis cluster via SSH or web terminal.

**Why a TUI and not a GUI**: The analysis cluster is accessed through SSH; X11
forwarding is slow; users want sub-second feedback when navigating thousands of
runs across IPTS directories. A TUI runs natively in any terminal with no display
server required.

---

## 2. Non-Negotiable Design Principles

1. **Speed first.** Every interaction must feel instant. No blocking I/O on the UI
   thread — use async or threads for OnCat calls, HDF5 reads, plotting.
2. **Keyboard-driven.** Every action must have a single-key or short-chord binding.
   Mouse support is acceptable but never required.
3. **Predictable.** A user who knows MDIR / Norton Commander / Midnight Commander
   should feel at home within minutes — that means **two panes**, F-key actions,
   and "copy/move from active pane to opposite pane" as the default semantics.
4. **Real plots, not text-art plots.** Plotting is a primary feature; SANS users
   need to read log-log axes precisely and inspect 2D heatmaps. Always render
   via matplotlib in its own window. Only fall back to PNG when no display is
   available. No character-based plotting.
5. **Command registry is the single source of truth.** Every user-facing action
   (open dir, copy, plot, zip, OnCat search, metadata extract, …) is a
   registered `Command` with name, typed parameters, description, and examples.
   Keybindings, the `:` command line, and the future LLM layer all dispatch
   through this same registry. **Never** wire a key handler directly to a
   business-logic function — go through the registry. This is what makes
   adding the natural-language layer later a drop-in, not a rewrite.
6. **Graceful degradation.** Default to interactive matplotlib; fall back to
   PNG export when headless; surface clearly which mode is active.
7. **Read-only by default for raw data.** Never modify files under
   `/SNS/EQSANS/IPTS-*` or similar instrument paths without explicit user
   confirmation.
8. **No surprise network calls.** OnCat queries only fire when the user types
   a command that needs them. The LLM layer (when present) must show its
   planned command list and wait for confirmation before executing destructive
   ops.

---

## 3. Tech Stack

| Concern | Library | Rationale |
|---|---|---|
| TUI framework | **Textual** (>=0.80) | Modern, async-native, themeable, excellent docs |
| Plotting (primary) | **matplotlib** with interactive backend (`QtAgg` / `TkAgg`) | Real publication-quality plots in a separate window; no compromise for scientific data |
| Plotting (headless fallback) | **matplotlib** `Agg` → PNG | Used only when `$DISPLAY` / `$WAYLAND_DISPLAY` are unavailable |
| HDF5 / NeXus | **h5py** | Standard at SNS for `*.nxs.h5` |
| Tabular data | **numpy** | I/O for `*.dat`, `*Iq*.dat`, etc. |
| OnCat API | **httpx** (async) | Already proven in `eqsanscli`; supports HTTP/2 + async |
| CLI entry | **click** | Subcommands for non-TUI invocations (e.g. batch metadata) |
| Inline formatting | **rich** (bundled with Textual) | Status bars, tables in dialogs |
| Config | **tomllib** (3.11+) / **tomli** | TOML at `~/.config/sansdir/config.toml` |
| Tests | **pytest**, **pytest-asyncio**, **pytest-textual-snapshot** | TUI snapshot regression |
| Future LLM layer | **anthropic** SDK (Phase 10+, optional) | Reads command registry → translates NL to command calls |

**Python version**: 3.10 minimum (analysis cluster has 3.11+ available via conda).

**Do not add** pandas, scipy, jupyter, plotext, or other heavy / character-based-plot
deps without justification. Keep startup time under 300 ms cold.

**Display detection**: at first plot request, probe for `$DISPLAY` /
`$WAYLAND_DISPLAY`. If present → matplotlib interactive backend, plot opens in
its own window alongside the terminal (Textual's alt-screen and matplotlib
windows coexist fine). If absent → `Agg` backend, save PNG under
`~/.cache/sansdir/plots/`, show path in status bar, attempt `xdg-open` if the
user opted in via config.

---

## 4. Repository Layout

```
sansdir/
├── CLAUDE.md            ← you are here
├── PLANNING.md          ← architecture & data format specs
├── TASKS.md             ← phased implementation checklist
├── README.md
├── pyproject.toml
├── src/sansdir/
│   ├── __init__.py
│   ├── __main__.py            # python -m sansdir
│   ├── cli.py                 # click entry: tui / extract / etc.
│   ├── app.py                 # main Textual App
│   ├── config.py
│   ├── commands/                 # central command registry — single source of truth
│   │   ├── registry.py           #   Command, CommandParam, CommandRegistry
│   │   ├── builtins.py           #   registers every built-in command
│   │   └── schema.py             #   JSON schema export for LLM tool-calling
│   ├── core/
│   │   ├── filesystem.py         # listing, sorting, wildcard expansion
│   │   ├── archive.py            # zip/tar creation
│   │   ├── mailer.py             # `mail` / `mutt` shell-out
│   │   └── oncat.py              # IPTS search (port from eqsanscli)
│   ├── ui/
│   │   ├── panel.py              # FilePanel widget (instantiated twice: L + R)
│   │   ├── statusbar.py
│   │   ├── command_input.py      # `:` line — parses then dispatches via registry
│   │   ├── dialogs.py            # confirm, prompt, picker
│   │   ├── tree.py               # folder browser modal
│   │   └── keys.py               # key → command name + args (no inline handlers)
│   ├── plot/
│   │   ├── detect.py             # sniff file type → choose plotter
│   │   ├── ascii1d.py            # 2/3/4-col I(q), transmission   (matplotlib)
│   │   ├── ascii2d.py            # 4/6-col qx,qy,I,σI[,dqx,dqy]   (matplotlib)
│   │   ├── tile.py               # multi-2D grid layout            (matplotlib)
│   │   ├── hdf5_detector.py      # total-counts heatmap from nxs.h5
│   │   └── backend.py            # display detection, mpl backend selection
│   ├── hdf/
│   │   ├── reader.py             # safe HDF5 open, key resolution
│   │   ├── metadata.py           # extract DASlogs scalars
│   │   └── batch.py              # batch extract → CSV/TSV/columns
│   ├── llm/                      # Phase 10+ (optional dependency group)
│   │   ├── translator.py         # NL prompt → list[CommandCall] via Anthropic API
│   │   └── prompt.py             # system prompt + few-shot examples
│   └── utils/
│       ├── async_io.py
│       ├── progress.py
│       └── logger.py
└── tests/
    ├── data/                  # tiny fixture files (real format, fake data), Actual test data also exists. there are nxs.h5 file for metadata extraction, plot test, two ascii files for 1d plot.
    └── ...
```

---

## 5. Workflow Rules for Claude Code

When you (Claude Code) start work on this repo:

1. **Always read `PLANNING.md` and `TASKS.md` first.** They contain decisions and
   the current phase. Do not invent architecture.
2. **Pick the lowest unchecked task in `TASKS.md`.** Complete it fully (code +
   tests + docs) before moving on.
3. **Update `TASKS.md`.** Tick the checkbox and add a one-line note if your
   implementation deviated from the plan. Commit the doc change with the code.
4. **Never bulk-implement multiple phases in one go** unless the user explicitly
   asks. Phases are designed to be reviewable.
5. **Run the test suite** (`pytest -q`) before declaring a task done.
6. **Check startup time** (`time python -m sansdir --help` or equivalent) after
   touching imports; flag if it exceeds 300 ms.
7. **Reference, don't copy, `eqsanscli`.** When porting OnCat search, study
   <https://github.com/cw-do/eqsanscli> for the API endpoints, auth flow, and
   keyword-matching logic, then re-implement cleanly within `core/oncat.py`.
   Do not vendor large chunks verbatim.
8. **Ask before adding dependencies.** If a task seems to need a new library,
   propose it in chat and wait for approval.
9. **Do not push to the cluster filesystem during development.** Use local
   fixtures under `tests/data/`.

---

## 6. Coding Conventions

- **Type hints** on every public function. `from __future__ import annotations`
  at the top of each module.
- **Async** for OnCat, HDF5 reads of large files, and any operation expected
  to take >50 ms. Use `asyncio.to_thread` for blocking libraries (h5py).
- **Docstrings**: Google style. Every public function gets one.
- **Error handling**: never `except:` bare. Catch the specific exception, log
  via `utils.logger`, and surface a user-visible message in the status bar.
- **No prints in library code.** Use the logger or Textual notifications.
- **Constants** in SCREAMING_SNAKE at module top.
- **Format**: `ruff format` (line length 100). **Lint**: `ruff check`.
- **Imports**: stdlib → third-party → local, separated by blank lines.

---

## 7. SANS Data Format Cheat Sheet

(See `PLANNING.md` §4 for full details. Quick reference here.)

- `*Iq.dat`, `*_Iq.txt`: 1D reduced data. Columns:
  - 2-col: `q  I(q)`
  - 3-col: `q  I(q)  σI`
  - 4-col: `q  I(q)  σI  σq`  ← ignore last column for plotting
- `*trans*.txt`: transmission. Columns: `wavelength  transmission [σT]`.
  Different axis labels; not log-log by default.
- `*Iqxqy*.dat` / 2D reduced: 4-col `qx qy I σI` or 6-col `qx qy I σI dqx dqy`.
- `*.nxs.h5`: NeXus HDF5 raw event data. Total detector counts at
  `/entry/instrument/bank{N}/total_counts` or summed from event arrays.
  DASlogs at `/entry/DASlogs/<name>/value` (scalar or time-averaged).

Files starting with `.` are hidden (toggleable). Symlinks are followed but flagged.

---

## 8. Key Bindings (target — may evolve)

Two panels, **left** and **right**. Exactly one is *active* at any time
(highlighted border). All file operations act on the active pane's tagged
files (or current row if none tagged); copy/move default destination is the
**other** pane's directory.

| Key | Action |
|---|---|
| `Tab` | Switch active pane (left ↔ right) |
| Arrows / `j` `k` | Move cursor in active pane |
| `Enter` | Enter dir / open file (smart by extension) |
| `Backspace` | Go up one level in active pane |
| `Space` | Tag/untag current row |
| `+` / `*` | Tag by glob (`*.txt`, `*Iq*.dat`); `-` to untag by glob |
| `F3` | View file (read-only pager) |
| `F4` | Edit file (`$EDITOR`) |
| `F5` | **Refresh** both panes (re-read directory listings) |
| `F6` | **Copy** tagged → other pane (with confirm) |
| `F7` | **Move/rename** tagged → other pane (with confirm) |
| `F8` / `Del` | Delete tagged (with confirm) |
| `F9` | Make directory (in active pane) |
| `q` | Quit |
| `p` | Plot current/tagged |
| `P` | Plot with options dialog (axes, colorbar mode) |
| `m` | Show metadata (HDF5 keys for `*.nxs.h5`) |
| `M` | Batch metadata extract dialog |
| `z` | Zip tagged → prompt for archive name |
| `e` | Email tagged |
| `:` | Command line (vim-style) — `:cd`, `:mkdir`, `:!cmd`, etc. |
| `/` | Filter active pane by substring |
| `g` | Go to path (with completion) |
| `i` | OnCat IPTS search |
| `Ctrl+U` | Swap left and right panes |
| `=` | Sync inactive pane to active pane's path |
| `?` | Help overlay |

---

## 9. Definition of Done

A task is "done" when:

- [ ] Code is implemented and matches the spec in `PLANNING.md`
- [ ] Type checks pass (`mypy src/sansdir` if configured)
- [ ] Lint passes (`ruff check`)
- [ ] Unit tests cover the happy path and at least one error case
- [ ] `pytest -q` is green
- [ ] `TASKS.md` is updated
- [ ] Startup time still under budget
- [ ] If user-facing: `README.md` mentions the new feature

---

## 10. What Not To Do

- Do not add a GUI (Qt/Tk) "for completeness."
- Do not write to instrument data directories without explicit confirmation.
- Do not silently retry network calls — surface errors immediately.
- Do not parse SANS files with regex when numpy can do it.
- Do not break the dual-pane MDIR/Norton aesthetic. Both panes must always
  be visible by default; a single-pane "maximized" mode is acceptable as a
  toggle (`Ctrl+O`) but not as default.
- Do not assume matplotlib is interactive on the cluster. Default backend is Agg.

