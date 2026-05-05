# TASKS.md

Phased implementation plan for **sansdir**. Work top-to-bottom. Tick boxes
as you complete tasks. Each phase produces a runnable milestone.

> **Rule for Claude Code**: Pick the lowest unchecked task. Implement it
> with tests. Update this file. Commit. Repeat.

---

## Phase 0 — Bootstrap *(setup + command registry foundation)*

- [x] Initialize git repo, set `.gitignore` for Python + `__pycache__/`, `.venv/`, `*.png` under `.cache/`
- [x] Create `pyproject.toml` with deps from `CLAUDE.md` §3 (no plotext) — *(file pre-existed; verified aligned, no changes needed)*
- [x] Create `src/sansdir/` package with `__init__.py`, `__main__.py`, `cli.py`
- [x] `cli.py` with `click` group: `tui` (default), `extract`, `version` — *(custom `_SansdirGroup` lets `sansdir /path` mean `sansdir tui /path`)*
- [x] Verify `python -m sansdir version` works
- [x] Add `ruff.toml` (line length 100) and `pre-commit` hook config — *(ruff config lives in `pyproject.toml` `[tool.ruff]`; no separate ruff.toml)*
- [x] Add GitHub Actions CI: lint + pytest on 3.10/3.11/3.12
- [x] **`commands/registry.py`** with `Command`, `CommandParam`, `CommandRegistry` per `PLANNING.md` §12
- [x] **`commands/builtins.py`** stub with a single `app.quit` command registered as proof of pattern
- [x] **`commands/schema.py`** — `to_json_schema()` returning Anthropic-tool-call-compatible list — *(public helpers are `command_to_tool_schema` / `registry_to_tool_schemas`)*
- [x] Unit tests for the registry: register / get / dispatch / schema export — *(24 tests, sync + async dispatch, validation, alias collisions)*
- [x] `README.md` skeleton with install & "hello world" instructions — *(file pre-existed; left as-is)*
- [x] **DoD**: `pip install -e .` succeeds, `sansdir version` prints version, registry can dispatch `app.quit`, `to_json_schema()` returns valid JSON, CI green. *(local: pytest 24/24, ruff clean, cold start ~40 ms vs. 300 ms budget; CI not yet pushed to GitHub)*

---

## Phase 1 — Minimal TUI *(navigate only, dual-pane, registry-routed)*

- [ ] `src/sansdir/app.py` with a Textual `App` shell
- [ ] `ui/panel.py` `FilePanel` widget (will be instantiated twice) showing cwd contents (name, size, mtime)
- [ ] App lays out **two FilePanel instances** side-by-side, equal width
- [ ] Track `active_panel` state on the App; visually highlight active border
- [ ] **`ui/keys.py` is a pure mapping `key → (command_name, args_resolver)`** — handlers must dispatch through `CommandRegistry`, never call business logic directly (per `PLANNING.md` §12.6)
- [ ] Register Phase-1 commands in `commands/builtins.py`: `nav.cd`, `nav.up`, `pane.activate`, `pane.swap`, `pane.sync`, `pane.toggle_max`, `view.toggle_hidden`, `view.set_sort`, `app.quit`, `app.help`
- [ ] `Tab` switches active panel; cursor focus follows active
- [ ] Arrow keys / `j` `k` move cursor in active panel only
- [ ] `Enter` enters dir; `Backspace` or selecting `..` goes up — within active panel
- [ ] `Ctrl+U` swaps left/right panel contents
- [ ] `=` syncs inactive panel's cwd to match active panel
- [ ] `Ctrl+O` toggles active-panel maximize (full-width); restores on 2nd press
- [ ] `ui/statusbar.py` shows active panel's path, file count, free disk
- [ ] `q` / `F10` quits cleanly (dispatches `app.quit`)
- [ ] `?` opens help overlay — generated from `registry.all()` metadata
- [ ] Hidden file toggle (`H`) — affects active panel only
- [ ] Sort menu (`s` cycles name/mtime/size/ext; `S` toggles reverse) — active panel only
- [ ] **DoD**: Two panes browse independently by keyboard, every action is a registry dispatch, `Tab` flips active, sub-100 ms response on 1000-file dirs.

---

## Phase 2 — Selection & basic file ops *(MDIR / Norton F-keys)*

- [ ] `Space` toggles tag on current row of active pane
- [ ] `+` / `*` prompts for glob and tags matches in active pane; `-` untags by glob
- [ ] Tagged rows render with `*` prefix and distinct color
- [ ] Tags are per-pane, per-directory; cleared on cd within that pane
- [ ] `g <path>` jump to path in active pane with tab-completion
- [ ] Folder browser modal (`G`) — Textual `Tree` of the FS; `Enter` to cd in active pane
- [ ] `F7` make new folder in active pane (inline prompt, refuses overwrite)
- [ ] `F8` / `Del` delete tagged in active pane (confirm dialog; uses `send2trash` if available)
- [ ] **`F5` copy tagged from active pane → inactive pane cwd** (dest editable in prompt; progress bar)
- [ ] **`F6` move/rename tagged from active pane → inactive pane cwd** (dest editable; if same dir, treat as rename)
- [ ] `F3` view current file in built-in pager (Textual `RichLog` or similar)
- [ ] `F4` edit current file via `$EDITOR` (suspend TUI, resume after)
- [ ] `:` opens command line; implement `:cd`, `:mkdir`, `:rm`, `:cp`, `:mv`, `:!cmd`
- [ ] `/` filter active pane by substring; `Esc` clears
- [ ] **DoD**: All MDIR-equivalent ops work via F-keys; `F5`/`F6` always default to opposite pane; destructive ops always confirm; history log written.

---

## Phase 3 — Archive & mail

- [ ] `core/archive.py` — `make_zip(paths, out_path, progress_cb)`
- [ ] `z` keypress: prompts for archive name (default `<dirname>.zip`), shows progress dialog
- [ ] Support tar.gz via `:tar foo.tar.gz` command
- [ ] `core/mailer.py` — shells out to `mail` or `mutt`, attaches tagged files
- [ ] `e` keypress: dialog for recipient + subject + body, then sends
- [ ] Honor `[mail].command` from config
- [ ] **DoD**: Tag 3 files, zip them, then email the zip in <30 s of keystrokes.

---

## Phase 4 — OnCat IPTS search

- [ ] Study `eqsanscli` `/load ipts` implementation; document endpoints in `PLANNING.md` §6
- [ ] `core/oncat.py` async client using `httpx.AsyncClient`
- [ ] `search_experiments(keyword, instrument=None, limit=50)` returns list of dataclasses
- [ ] `list_runs(ipts, instrument)` for browsing within an IPTS
- [ ] Cache layer (in-memory dict + optional disk JSON cache, TTL from config)
- [ ] `i` keypress / `:ipts <kw>` opens results modal; arrows + Enter to cd into the IPTS
- [ ] Error handling: timeout, network down, empty results — surface in status bar
- [ ] Mock-based tests with `pytest-httpx`
- [ ] **DoD**: Type `i bio-membrane`, see candidate IPTS list within 2 s, Enter jumps to `/SNS/EQSANS/IPTS-NNNNN/`.

---

## Phase 5 — 1D plotting *(matplotlib windows)*

- [ ] `plot/detect.py` — sniff file by extension + first non-comment line column count
- [ ] `plot/ascii1d.py` — read 2/3/4-col data with numpy; respect `#` comments
- [ ] `plot/backend.py` — display probe (`$DISPLAY` / `$WAYLAND_DISPLAY` / `SANSDIR_HEADLESS`); pick interactive backend (`QtAgg` → `TkAgg` → `GTK4Agg`) or `Agg`
- [ ] **matplotlib interactive figure** as default: log/lin axes, errorbars when σI present, title from filename, multiple files overlaid with legend
- [ ] **Headless fallback**: `Agg` → PNG to `~/.cache/sansdir/plots/` with timestamped name; status bar shows path; optional `xdg-open`
- [ ] Non-blocking show (`plt.show(block=False)`) so TUI stays responsive; `plt.close("all")` on app exit
- [ ] Transmission detection (`*trans*.txt`): different default scales + axis labels (λ, T(λ))
- [ ] Register commands: `plot.iq`, `plot.transmission`, `plot.show_options`
- [ ] `p` keypress dispatches `plot.iq` / `plot.transmission` based on detected file kind
- [ ] `P` opens options dialog (a `plot.show_options` command); user picks x/y scale, errorbars on/off, legend
- [ ] **DoD**: Plot a 3-col Iq.dat in <500 ms in a real matplotlib window; correctly handles 4-col by ignoring last column; transmission gets correct axis labels; headless run produces PNG without crashing.

---

## Phase 6 — 2D plotting *(matplotlib windows + tile mode)*

- [ ] `plot/ascii2d.py` — read 4/6-col qx,qy,I[,σI[,dqx,dqy]]
- [ ] Auto-grid detection from unique qx, qy → reshape into 2D arrays
- [ ] Single 2D plot: matplotlib `pcolormesh` with `viridis`, optional log color scale, colorbar
- [ ] `plot/tile.py` — multi-2D tile via `plt.subplots(nrows, ncols)`; `ceil(sqrt(n))` grid
- [ ] Colorbar mode: `shared` (one bar, common vmin/vmax = mean ± 3σ across all data) vs `independent` (per-subplot)
- [ ] Filename as subplot title
- [ ] Register commands: `plot.iqxqy`, `plot.tile_2d`
- [ ] `P` options dialog adds: tile mode toggle, colorbar mode, log-intensity toggle
- [ ] Headless mode: subplots saved to a single PNG
- [ ] **DoD**: Tag 4 Iqxqy.dat files, dispatch `plot.tile_2d`, get a real 2×2 matplotlib window with shared colorbar; closing the window doesn't kill the TUI.

---

## Phase 7 — HDF5 / NeXus support

- [ ] `hdf/reader.py` — safe open with `swmr=True`, key resolution helpers
- [ ] `hdf/metadata.py` — extract scalar or time-averaged DASlogs values
- [ ] `m` keypress on a `.nxs.h5` opens a tree dialog; preview leaf values
- [ ] `plot/hdf5_detector.py` — sum bank arrays, render as 2D heatmap (per bank as tiles for v1)
- [ ] `p` on a `.nxs.h5` plots total detector sum
- [ ] **DoD**: Inspect any SNS NeXus file; plot its detector sum without writing intermediate files.

---

## Phase 8 — Batch metadata extraction

- [ ] `hdf/batch.py` — parallel extract across N files using `ThreadPoolExecutor`
- [ ] `M` opens dialog: list of keys (autocomplete from first tagged file)
- [ ] User picks 1+ keys; chooses output format (TSV / CSV / aligned columns)
- [ ] Progress bar during extraction
- [ ] Output to `./extracted_<timestamp>.tsv` by default, prompt to override
- [ ] Optional: include `stdev` and `n_points` columns for time-series values
- [ ] CLI subcommand: `sansdir extract --keys ... --out file.tsv FILES...`
- [ ] **DoD**: Tag 100 NeXus files, hit M, pick 3 keys, get a clean TSV in <10 s.

---

## Phase 9 — Polish

- [ ] Themes: at least `dark`, `light`, `monokai`
- [ ] Per-user key rebinding via config `[keys]` section
- [ ] Profile cold start; lazy-import where it helps
- [ ] Snapshot tests for all dialogs
- [ ] `man sansdir` page or `--help` for every subcommand
- [ ] `README.md` with screenshots (asciicast)
- [ ] Tag v1.0.0 and write release notes

---

## Phase 10 — LLM Natural-Language Layer *(optional extra; do not start without explicit go-ahead)*

Prerequisite: Phases 0–9 complete; command registry covers every user action.

- [ ] Add `[llm]` optional dependency group: `anthropic>=0.40`
- [ ] `llm/prompt.py` — system prompt template + few-shot examples mapping NL phrases to command sequences (use realistic SANS workflows)
- [ ] `llm/translator.py` — `async translate(prompt: str, context: AppContext) -> list[CommandCall]`
  - context = active pane cwd, inactive pane cwd, tagged files, recent commands
  - calls Anthropic `messages.create` with `tools=registry.to_json_schema()`
  - returns parsed list of `CommandCall(name, args)`
- [ ] Plan-preview modal: shows numbered list of proposed commands with arguments; user can edit args inline, drop a step, or reject
- [ ] `Enter` confirms & executes sequentially via `registry.dispatch`; commands marked `danger=True` get an extra per-command confirmation
- [ ] Bind `\` and `:ask <prompt>` to open the NL input
- [ ] Auth: read API key from `~/.config/sansdir/anthropic_key` (mode 600) or `$ANTHROPIC_API_KEY`
- [ ] Telemetry: log NL prompt + chosen command list to `~/.cache/sansdir/llm_history.jsonl` (local only; no upload)
- [ ] Tests: mock the Anthropic client; assert NL → expected command sequences for ~20 representative phrases
- [ ] **DoD**: User types `\ tag every Iq.dat in this folder, plot them all overlaid with log-log axes`, sees a 2-step plan, confirms, gets the matplotlib window. No command bypasses the registry.

---

## Stretch / Future *(do not start without user request)*

- [ ] Mantid-aware metadata reading
- [ ] `:diff` command for two reduced 1D datasets (defaults to one file from each pane)
- [ ] USANS slit-smearing-aware plot
- [ ] Save/load "workspace" (both panes' cwd, tags, view options)
- [ ] Plugin system for instrument-specific commands
- [ ] Bookmark system (`b` set, `'` jump) for frequent IPTS dirs
- [ ] Local-model LLM backend (vLLM / Ollama) as alternative to Anthropic API

