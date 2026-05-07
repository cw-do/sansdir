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

- [x] `src/sansdir/app.py` with a Textual `App` shell
- [x] `ui/panel.py` `FilePanel` widget (will be instantiated twice) showing cwd contents (name, size, mtime)
- [x] App lays out **two FilePanel instances** side-by-side, equal width
- [x] Track `active_panel` state on the App; visually highlight active border — *(via `.-active` CSS class)*
- [x] **`ui/keys.py` is a pure mapping `key → (command_name, args_resolver)`** — handlers must dispatch through `CommandRegistry`, never call business logic directly (per `PLANNING.md` §12.6) — *(`SansdirApp.on_key` is the only translation site)*
- [x] Register Phase-1 commands in `commands/builtins.py`: `nav.cd`, `nav.up`, `pane.activate`, `pane.swap`, `pane.sync`, `pane.toggle_max`, `view.toggle_hidden`, `view.set_sort`, `app.quit`, `app.help` — *(via `_make_*` factories that bind to an `AppProtocol`)*
- [x] `Tab` switches active panel; cursor focus follows active
- [x] Arrow keys / `j` `k` move cursor in active panel only — *(j/k via `FilePanel.BINDINGS`; arrows inherited from `DataTable`)*
- [x] `Enter` enters dir; `Backspace` or selecting `..` goes up — within active panel
- [x] `Ctrl+U` swaps left/right panel contents
- [x] `=` syncs inactive panel's cwd to match active panel
- [x] `Ctrl+O` toggles active-panel maximize (full-width); restores on 2nd press
- [x] `ui/statusbar.py` shows active panel's path, file count, free disk
- [x] `q` / `F10` quits cleanly (dispatches `app.quit`)
- [x] `?` opens help overlay — generated from `registry.all()` metadata
- [x] Hidden file toggle (`H`) — affects active panel only — *(bound to lowercase `h`; help overlay reflects this)*
- [x] Sort menu (`s` cycles name/mtime/size/ext; `S` toggles reverse) — active panel only — *(simplified: keys 1/2/3/4 set name/mtime/size/ext directly; `s` aliased to "name". Reverse-toggle deferred — handler accepts `reverse` kwarg, no key bound yet.)*
- [x] **DoD**: Two panes browse independently by keyboard, every action is a registry dispatch, `Tab` flips active, sub-100 ms response on 1000-file dirs. *(81/81 tests green incl. 12 Pilot end-to-end; 1000-file `list_dir` <100 ms; cold start 40 ms — Textual stays lazy.)*

---

## Phase 2 — Selection & basic file ops *(MDIR / Norton F-keys)*

- [x] `Space` toggles tag on current row of active pane — *(advances cursor by default; `tag.toggle advance=false` overrides)*
- [x] `+` / `*` prompts for glob and tags matches in active pane; `-` untags by glob — *(opens the `:` line pre-filled with `tag.glob ` / `tag.untag_glob `)*
- [x] Tagged rows render with `*` prefix and distinct color — *(bold yellow via Rich Text)*
- [x] Tags are per-pane, per-directory; cleared on cd within that pane
- [x] `g <path>` jump to path in active pane with tab-completion — *(opens `:` line pre-filled with `cd `; tab-completes command names; path completion deferred to a later phase)*
- [x] Folder browser modal (`G`) — Textual `Tree` of the FS; `Enter` to cd in active pane — *(uses Textual's `DirectoryTree`)*
- [x] `F7` make new folder in active pane (inline prompt, refuses overwrite) — *(F7 → `:` line pre-filled with `mkdir `; `file.mkdir` rejects existing names)*
- [x] `F8` / `Del` delete tagged in active pane (confirm dialog; uses `send2trash` if available)
- [x] **`F5` copy tagged from active pane → inactive pane cwd** (dest editable in prompt; progress bar) — *(confirm dialog; dest editing & progress bar deferred)*
- [x] **`F6` move/rename tagged from active pane → inactive pane cwd** (dest editable; if same dir, treat as rename) — *(rename form supported via `move_paths` single-src-to-nonexistent-path)*
- [x] `F3` view current file in built-in pager (Textual `RichLog` or similar) — *(`FileViewer` modal; refuses to render binary files)*
- [x] `F4` edit current file via `$EDITOR` (suspend TUI, resume after)
- [x] `:` opens command line; implement `:cd`, `:mkdir`, `:rm`, `:cp`, `:mv`, `:!cmd` — *(`:cd`, `:mkdir`, `:!cmd` implemented; copy/move/delete via the `file.copy` / `file.move` / `file.delete` commands; classic `cp`/`mv`/`rm` aliases not added — happy to add if you want them)*
- [x] `/` filter active pane by substring; `Esc` clears — *(`view.set_filter`; Esc on the active pane clears)*
- [x] **DoD**: All MDIR-equivalent ops work via F-keys; `F5`/`F6` always default to opposite pane; destructive ops always confirm; history log written. *(172/172 tests; 7 F-key Pilot tests; history at `~/.cache/sansdir/history.log`; cold start still 40 ms.)*

---

## Phase 3 — Archive & mail

- [x] `core/archive.py` — `make_zip(paths, out_path, progress_cb)` — *(also `make_tar_gz`; progress callback wired but no progress modal yet — small archives don't need it, can add later if a multi-GB IPTS dump becomes a thing)*
- [x] `z` keypress: prompts for archive name (default `<dirname>.zip`), shows progress dialog — *(prompt wired; progress modal deferred, see above)*
- [x] Support tar.gz via `:tar foo.tar.gz` command — *(`tar` is an alias for `archive.tar_gz`)*
- [x] `core/mailer.py` — shells out to `mail` or `mutt`, attaches tagged files
- [x] `e` keypress: dialog for recipient + subject + body, then sends — *(MailDialog; Ctrl+S sends, Esc cancels)*
- [x] Honor `[mail].command` from config — *(`config.py` reads `~/.config/sansdir/config.toml`; `SANSDIR_CONFIG` env override for tests)*
- [x] **DoD**: Tag 3 files, zip them, then email the zip in <30 s of keystrokes. *(`test_phase3_dod_tag_zip_mail` does exactly this in one Pilot session, with a mocked mail subprocess)*

---

## Phase 4 — OnCat IPTS search

- [x] Study `eqsanscli` `/load ipts` implementation; document endpoints in `PLANNING.md` §6 — *(eqsanscli uses `pyoncat` w/ OAuth client_credentials; we re-implement on `httpx`)*
- [x] `core/oncat.py` async client using `httpx.AsyncClient`
- [x] `search_experiments(keyword, instrument=None, limit=50)` returns list of dataclasses
- [x] `list_runs(ipts, instrument)` for browsing within an IPTS — *(named `list_datafiles`; not yet wired to a UI command — `:ipts` only opens the experiment results modal for now)*
- [x] Cache layer (in-memory dict + optional disk JSON cache, TTL from config)
- [x] `i` keypress / `:ipts <kw>` opens results modal; arrows + Enter to cd into the IPTS
- [x] Error handling: timeout, network down, empty results — surface in status bar — *(OnCatAuthError, OnCatNetworkError, empty list each notify)*
- [x] Mock-based tests with `pytest-httpx`
- [x] **DoD**: Type `i bio-membrane`, see candidate IPTS list within 2 s, Enter jumps to `/SNS/EQSANS/IPTS-NNNNN/`. *(test_phase4_dod_i_search_and_cd performs exactly this with mocked OnCat responses; cluster path is monkey-patched to a tmp_path so the test can verify `cd` happens)*

---

## Phase 5 — 1D plotting *(matplotlib windows)*

- [x] `plot/detect.py` — sniff file by extension + first non-comment line column count
- [x] `plot/ascii1d.py` — read 2/3/4-col data with numpy; respect `#` comments
- [x] `plot/backend.py` — display probe (`$DISPLAY` / `$WAYLAND_DISPLAY` / `SANSDIR_HEADLESS`); pick interactive backend (`QtAgg` → `TkAgg` → `GTK4Agg`) or `Agg`
- [x] **matplotlib interactive figure** as default: log/lin axes, errorbars when σI present, title from filename, multiple files overlaid with legend
- [x] **Headless fallback**: `Agg` → PNG to `~/.cache/sansdir/plots/` with timestamped name; status bar shows path; optional `xdg-open` — *(status bar message via `notify_user`; `xdg-open` left unwired for now)*
- [x] Non-blocking show (`plt.show(block=False)`) so TUI stays responsive; `plt.close("all")` on app exit
- [x] Transmission detection (`*trans*.txt`): different default scales + axis labels (λ, T(λ))
- [x] Register commands: `plot.iq`, `plot.transmission`, `plot.show_options` — *(`plot.iq`, `plot.transmission`, `ui.plot_auto`; options dialog deferred — see `P` task below)*
- [x] `p` keypress dispatches `plot.iq` / `plot.transmission` based on detected file kind — *(`ui.plot_auto` handler buckets the active selection by detected kind and runs both plots if needed)*
- [ ] `P` opens options dialog (a `plot.show_options` command); user picks x/y scale, errorbars on/off, legend — *(deferred to a polish pass)*
- [x] **DoD**: Plot a 3-col Iq.dat in <500 ms in a real matplotlib window; correctly handles 4-col by ignoring last column; transmission gets correct axis labels; headless run produces PNG without crashing. *(test_plot_iq_real_fixture_produces_png — warm plot in <500 ms; test_plot_transmission_uses_lambda_label — λ axis; bundled fixtures cover the 4-col path)*

---

## Phase 6 — 2D plotting *(matplotlib windows + tile mode)*

- [x] `plot/ascii2d.py` — read 4/6-col qx,qy,I[,σI[,dqx,dqy]]
- [x] Auto-grid detection from unique qx, qy → reshape into 2D arrays — *(GridError raised on irregular/sparse grids so caller can fall back later)*
- [x] Single 2D plot: matplotlib `pcolormesh` with `viridis`, optional log color scale, colorbar
- [x] `plot/tile.py` — multi-2D tile via `plt.subplots(nrows, ncols)`; `ceil(sqrt(n))` grid
- [x] Colorbar mode: `shared` (one bar, common vmin/vmax = mean ± 3σ across all data) vs `independent` (per-subplot)
- [x] Filename as subplot title
- [x] Register commands: `plot.iqxqy`, `plot.tile_2d` — *(single command `plot.iqxqy` covers both: 1 file → single, N>1 → tile)*
- [ ] `P` options dialog adds: tile mode toggle, colorbar mode, log-intensity toggle — *(deferred with the rest of P; cmdline already accepts `:plot.iqxqy …`, subprocess takes --cmap/--log-intensity/--colorbar-mode flags)*
- [x] Headless mode: subplots saved to a single PNG
- [x] **DoD**: Tag 4 Iqxqy.dat files, dispatch `plot.tile_2d`, get a real 2×2 matplotlib window with shared colorbar; closing the window doesn't kill the TUI. *(test_tile_four_files_uses_2x2_with_shared_colorbar + ui.plot_auto routes Iqxqy bucket through subprocess; tests written headless against synthetic 5×4 grids)*

---

## Phase 7 — HDF5 / NeXus support

- [x] `hdf/reader.py` — safe open with `swmr=True`, key resolution helpers
- [x] `hdf/metadata.py` — extract scalar or time-averaged DASlogs values
- [x] `m` keypress on a `.nxs.h5` opens a tree dialog; preview leaf values — *(`HdfTreeScreen` with lazy expansion + side preview; tested against the 350 MB cluster fixture)*
- [x] `plot/hdf5_detector.py` — sum bank arrays, render as 2D heatmap (per bank as tiles for v1) — *(handles pre-aggregated `data` AND event-mode `event_id` via `np.bincount` + best-effort reshape)*
- [x] `p` on a `.nxs.h5` plots total detector sum per pixel — *(`ui.plot_auto` routes NeXus → `plot.detector_sum`; one subprocess per file)*
- [x] **DoD**: Inspect any SNS NeXus file; plot its detector sum without writing intermediate files. *(17 tests cover open/walk/extract/detector for the synthetic 2-bank fixture + an event-mode bincount path on a synthetic 4x4 detector)*

---

## Phase 8 — Batch metadata extraction

- [x] `hdf/batch.py` — parallel extract across N files using `ThreadPoolExecutor`
- [x] `M` opens dialog: list of keys (autocomplete from first tagged file) — *(Space toggles a row; comma-separated input below for free-form keys; `s` toggles stats columns)*
- [x] User picks 1+ keys; chooses output format (TSV / CSV / aligned columns)
- [ ] Progress bar during extraction — *(progress callback wired through `extract_many`; UI progress modal deferred — sub-second on the 100-file DoD makes it low-priority)*
- [x] Output to `./extracted_<timestamp>.tsv` by default, prompt to override
- [x] Optional: include `stdev` and `n_points` columns for time-series values
- [x] CLI subcommand: `sansdir extract --keys ... --out file.tsv FILES...` — *(also `--with-stats` and `--workers`; prints written path on stdout)*
- [x] **DoD**: Tag 100 NeXus files, hit M, pick 3 keys, get a clean TSV in <10 s. *(test_dod_100_files_under_10s asserts the 10 s budget; 100 files × 3 keys is consistently under 1 s on the cluster filesystem with the default 8-thread pool.)*

---

## Phase 9 — Polish

- [x] Themes: at least `dark`, `light`, `monokai` — *(`[ui].theme` config; ~20 built-in Textual themes available; `:theme <name>` cmdline switches at runtime; unknown name notifies)*
- [x] Per-user key rebinding via config `[keys]` section — *(merged into the keymap at startup; unknown commands silently dropped so a typo doesn't dead-key F5)*
- [ ] Profile cold start; lazy-import where it helps — *(currently 50 ms vs 300 ms budget — well under, deferring)*
- [x] Snapshot tests for all dialogs — *(SVG snapshots for Confirm/TextPrompt/Mail/BatchExtract via pytest-textual-snapshot; HelpScreen skipped as too brittle, lazy-walk dialogs covered by Pilot tests)*
- [x] `man sansdir` page or `--help` for every subcommand — *(rich `--help` for `sansdir`, `tui`, `extract`, `version`; epilogs with realistic examples; `--version` flag added)*
- [ ] `README.md` with screenshots (asciicast) — *(deferred; user-driven content)*
- [ ] Tag v1.0.0 and write release notes — *(deferred; user-driven release)*

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

git: https://github.com/cw-do/sansdir.git
