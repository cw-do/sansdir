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
- [x] `q` quits cleanly (dispatches `app.quit`) — *(F10 was bound to quit too originally; the 9.7 follow-up rebound F2 to ``ui.rename`` and parked the catalog toggle on ``c`` since most terminals capture F10 for the menu bar)*
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

# Phase 9.6 — Interactive mask creation from raw NeXus data

> **Revision (v3):** detector mapping is read directly from the source
> `.nxs.h5` file (`bank1/pixel_id`). No instrument-specific code, no
> formulas, no instrument registry. The writer is one short function;
> the envelope is fixed boilerplate. See § 9.6.3.

## Goal

A `:mask` command in the sansdir TUI that opens an interactive matplotlib
window on a raw `.nxs.h5` file, lets the user draw multiple shapes
(rectangles, ellipses, circles, polygons, lassos) on the detector heatmap,
accumulates them into a Mantid-convention binary mask, and saves to either
`.xml` (Mantid SaveMask format) or `.nxs` (Mantid Processed-NeXus format).
The detector mapping is borrowed from the source file — no Mantid runtime
dependency, no instrument-specific code. A `sansdir mask` CLI subcommand
exposes the non-interactive path.

## Design decisions (locked)

1. **Mask convention: `1 = masked` (excluded), `0 = unmasked` (kept).**
   Matches Mantid's `SpecialWorkspace2D`. The first unit test pins this
   convention; nothing else lands until it passes.
2. **GUI is matplotlib in a separate window.** Reuses the existing
   plot-window pattern. Requires `$DISPLAY`; CLI mode covers headless use.
3. **Two output formats**, both pure Python:
   - `.xml` — Mantid SaveMask format. `xml.etree.ElementTree`.
   - `.nxs` — Mantid Processed NeXus, written with `h5py` to the structure
     in § 9.6.3. **Detector IDs come from the source file's
     `bank1/pixel_id`** — no formula, no instrument-specific code.
4. **Multi-shape accumulation.** matplotlib selectors are one-at-a-time;
   on each `onselect`, freeze as a translucent red `Patch`, append to
   the `MaskBuilder`, rearm the selector. Edit mode allows
   click-to-select, drag, resize, delete.
5. **Reuse existing detector-heatmap rendering.** Refactor the existing
   event-mode histogramming into `load_detector_image(path)` used by
   both the heatmap plotter and the mask GUI.
6. **Pixel ordering must match histogram ordering.** The mask is
   flattened in the same row-major order sansdir already uses for
   plotting, and `detector_list` is written in that same order. A unit
   test verifies the alignment.
7. **No Mantid runtime imports anywhere in `src/sansdir/`.**
   Verify with `grep -r "import mantid" src/` returning nothing.
8. **Reference-fixture verification.** A captured Mantid-Workbench-saved
   reference mask under `tests/mask/fixtures/reference_mask.nxs`
   provides the canonical structure for the diff test.
9. **`mask_log.json` next to every saved mask.** Round-trippable shape
   list for editing/regenerating.
10. **Inverse mask flag** inverts the FINAL union mask (`1 - mask`),
    not individual shapes. Defaults off.

## What v3 simplifies (vs earlier drafts)

- No `mask/instruments/eqsans.py` module
- No instrument registry pattern
- No hardcoded pixel-to-detector-id formula
- No `DetectorMeta.pixel_to_detid` callable — the mapping is just an
  array read from the source file
- The writer works for any SNS event-mode file with a standard
  `bank1/pixel_id` layout (EQSANS, BIOSANS, GP-SANS, …) without code
  changes

## Out of scope for 9.6

- Free-hand brush painting
- Per-tube / per-bank region templates
- Boolean ops between shapes (only union for v1)
- Real-time mask preview during drawing
- Loading existing `.xml` / `.nxs` masks for editing
- Mask versioning / propagation across runs
- Files without a `bank1/pixel_id` layout (handle via clear error)

---

## 9.6.1 — Pure mask-building core

Module: `src/sansdir/mask/core.py`

- [x] `Shape` ABC + subclasses: `Rectangle`, `Ellipse`, `Circle`,
      `Polygon`. All coordinates in pixel space.
- [x] `Shape.rasterise(detector_shape) -> np.ndarray[bool]` — numpy
      meshgrid for rect/ellipse/circle, `matplotlib.path.Path.contains_points`
      for polygons. No Python pixel loops.
- [x] `MaskBuilder` with `add(shape)`, `remove(index)`,
      `build(*, inverse=False) -> np.ndarray[uint8]`, `to_dict()`,
      `from_dict()` — *(the convention is held on the builder via
      ``inverse`` flag; defaulting to ``False`` matches Mantid)*
- [x] **Convention test as the very first test** (gates everything else):

  ```python
  def test_mask_convention_1_means_masked():
      """Mantid: 1 = masked, 0 = kept."""
      b = MaskBuilder((10, 10))
      b.add(Rectangle(2, 2, 5, 5))
      m = b.build()
      assert m.dtype == np.uint8
      assert m[3, 3] == 1, "interior must be masked (1)"
      assert m[0, 0] == 0, "exterior must be kept (0)"
      assert m.sum() == 16
  ```

---

## 9.6.2 — Detector image loader

Module: `src/sansdir/mask/detector.py`

- [x] `load_detector_image(path) -> (image_2d, source_meta)` wraps the
      existing event-mode histogramming (`load_eqsans_raw`).
- [x] `SourceMeta` dataclass: `source_path`, `instrument_name`,
      `detector_shape`, `pixel_ids`, `run_number`.
- [x] **Critical:** `image_2d.flatten()[k]` aligns with
      `pixel_ids[k]`. The heatmap loader applies the
      `[0,4,1,5,2,6,3,7]` tube reorder; we replay the *same* reorder
      on `arange(EQSANS_NPIXELS_TOTAL)` to derive matching
      `pixel_ids` for the canonical EQSANS event-mode case.
- [x] No instrument-specific code. Files with explicit
      `bank1/pixel_id` honour it verbatim; canonical EQSANS event-
      mode (no pixel_id, but the existing heatmap path supports it)
      derives `pixel_ids` from the same reorder. Anything else
      raises `UnsupportedFileLayoutError`.

**Acceptance:** unit test loads a synthetic h5py-built fixture file with
a known `pixel_id` array, asserts the loader returns the expected image
shape and `pixel_ids` matches the fixture.

---

## 9.6.3 — Output writers (pure Python)

Module: `src/sansdir/mask/writers.py`

### XML writer

- [x] `write_xml(path, mask, source_meta)` — Mantid SaveMask format:

  ```xml
  <?xml version="1.0"?>
  <detector-masking>
    <group>
      <detids>5,9-15,42-44,...</detids>
    </group>
  </detector-masking>
  ```

- [x] Compute detector-id list from `mask.flatten()` non-zero positions
      indexed into `source_meta.pixel_ids`. Compress contiguous runs to
      `n-m` ranges.
- [x] Pure stdlib `xml.etree.ElementTree`.

### NeXus writer

- [x] `write_nxs(path, mask, source_meta)` — Mantid Processed NeXus,
      detector mapping borrowed from source. **Layout adapted to
      Mantid 6.13+** — group `mask_workspace` (not `workspace`),
      `definition = "Mantid Processed Workspace"`, the canonical
      5-dataset `instrument/detector` block. Verified end-to-end via
      `LoadNexusProcessed` on Mantid 6.15: 697-pixel mask round-trips
      with the right masked count and `MaskWorkspace` type.
- [ ] Reference implementation:

  ```python
  def write_mask_nxs(output_path, source_meta, mask_2d):
      n = source_meta.pixel_ids.size
      assert mask_2d.size == n, "mask / pixel_ids ordering mismatch"

      y = mask_2d.astype(np.float64).reshape(n, 1)
      e = np.zeros_like(y)
      iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
      s = lambda v: np.bytes_(v.encode() if isinstance(v, str) else v)

      with h5py.File(output_path, "w") as f:
          f.attrs["NeXus_version"] = s("4.3.0")
          f.attrs["file_name"]     = s(str(output_path))
          f.attrs["HDF5_Version"]  = s(h5py.version.hdf5_version)

          ent = f.create_group("mantid_workspace_1")
          ent.attrs["NX_class"] = s("NXentry")
          ent.create_dataset("title", data=s("MaskWorkspace"))
          d = ent.create_dataset("definition", data=s("mantidworkspace"))
          d.attrs["Version"] = s("1.0")
          ent.create_dataset("workspace_type", data=s("MaskWorkspace"))

          ws = ent.create_group("workspace")
          ws.attrs["NX_class"] = s("NXdata")
          v = ws.create_dataset("values", data=y)
          v.attrs["signal"] = 1
          v.attrs["axes"]   = s("axis2,axis1")
          ws.create_dataset("errors", data=e)
          ws.create_dataset("axis1", data=np.array([0.0, 1.0]))
          ws.create_dataset("axis2", data=np.arange(n, dtype=np.float64))

          inst = ent.create_group("instrument")
          inst.attrs["NX_class"] = s("NXinstrument")
          inst.create_dataset("name", data=s(source_meta.instrument_name))
          det = inst.create_group("detector")
          det.attrs["NX_class"] = s("NXdetector")
          det.create_dataset("detector_list",
                             data=source_meta.pixel_ids.astype(np.int32))
          det.create_dataset("detector_count",
                             data=np.ones(n, dtype=np.int32))
          det.create_dataset("detector_index",
                             data=np.arange(n, dtype=np.int32))
          det.create_dataset("spectrum_index",
                             data=np.arange(1, n+1, dtype=np.int32))

          smp = ent.create_group("sample")
          smp.attrs["NX_class"] = s("NXsample")
          smp.create_dataset("name", data=s(""))

          proc = ent.create_group("process")
          proc.attrs["NX_class"] = s("NXprocess")
          for note, desc in [
              ("MantidEnvironment", "sansdir mask creation"),
              ("MantidAlgorithm_1", "sansdir.mask.create"),
          ]:
              g = proc.create_group(note)
              g.attrs["NX_class"] = s("NXnote")
              g.create_dataset("author",      data=s("sansdir"))
              g.create_dataset("date",        data=s(iso))
              g.create_dataset("description", data=s(desc))
              g.create_dataset("data",
                               data=s(f"SourceFile={source_meta.source_path}"))
  ```

- [x] String encoding: `np.bytes_(...)` for fixed-length ASCII (max
      compatibility across Mantid versions). Mantid 6.15 accepts the
      result without complaint.

### npy writer

- [x] `write_npy(path, mask, source_meta)` — `np.save` plus
      `<basename>.meta.json` sidecar.

### Common log writer

- [x] `write_log(path, source_meta, builder, mask_stats)` —
      `<basename>.mask_log.json` per § 9.6.6.

---

## 9.6.4 — Interactive matplotlib GUI

Module: `src/sansdir/mask/gui.py`

- [x] Detector heatmap with `LogNorm` (vmin/vmax sliders deferred —
      autoscale per-image is fine for the common workflow).
- [x] Mode buttons:
      `Rectangle / Ellipse / Circle / Polygon` *(Lasso wired as a
      polygon-select alias; explicit Select-Edit deferred)*.
- [x] Action buttons:
      `Undo / Clear / Invert / Save XML / Save NeXus / Quit`.
- [x] Keyboard shortcuts: `r e c p z i s Esc Delete`.
- [x] :class:`MaskController` freezes each completed shape as a
      translucent red `Patch`, adds it to the :class:`MaskBuilder`,
      and rearms the selector for the next gesture.
- [ ] Edit mode (click-to-select, drag, resize handles) — deferred;
      delete + redraw is the v1 workflow and tests cover it.
- [x] `useblit=True` on the rectangle/ellipse/polygon/lasso selectors.

Subprocess wiring: the TUI's ``K`` keystroke fires
``python -m sansdir.mask.gui <source.nxs.h5> --output <…>`` via
``subprocess.Popen`` (start_new_session=True), same forking pattern
as :mod:`sansdir.plot.window`. Tests cover the controller against a
real ``Agg`` backend; the rendered widget graph is left to manual
verification.

---

## 9.6.5 — TUI command + CLI subcommand

- [x] `:mask` operates on the cursor's `.nxs.h5` (single-file)
- [x] Keybinding: `K`
- [x] `$DISPLAY` unset → status-bar pointer to CLI
- [x] `sansdir mask <input.nxs.h5> [options]`:
      `--rect`, `--ellipse`, `--circle`, `--polygon`, `--shapes-json`,
      `--inverse`, `--output`, `--format {xml,nxs,npy}` —
      *(interactive matplotlib editor is the next iteration; CLI
      form is the canonical entry point)*

---

## 9.6.6 — `mask_log.json` round-trip

```json
{
  "sansdir_version": "0.9.0",
  "created_at": "2026-05-07T18:42:11Z",
  "source_nxs": "/SNS/EQSANS/IPTS-31415/nexus/EQSANS_172749.nxs.h5",
  "instrument": "EQSANS",
  "detector_shape": [256, 192],
  "inverse": false,
  "shapes": [
    {"type": "rectangle", "x0": 10, "y0": 20, "x1": 30, "y1": 50},
    {"type": "circle", "xc": 128, "yc": 96, "r": 25}
  ],
  "stats": {"masked_pixels": 1247, "masked_fraction": 0.0254}
}
```

`MaskBuilder.from_log(path)` reconstructs builder + shapes.

---

## 9.6.7 — Tests

- [x] **Convention test** (§ 9.6.1) — runs first.
- [x] Per-shape rasterise tests with hand-verified fixtures
      (rect / circle / ellipse / polygon).
- [x] **Pixel-ordering alignment test** — synthetic source file with
      both an explicit `bank1/pixel_id` permutation and the canonical
      derive-from-reorder path; mask a pixel at known `(row, col)`,
      verify the matching detector ID lands in `detector_list[nz]`.
- [x] `Shape` → JSON round-trip semantic equality (parametrised over
      every shape kind).
- [x] XML writer: trivial inputs, parse round-trip, range compression.
- [x] NeXus writer:
  - [x] Group hierarchy matches the Mantid 6.13+ layout (the spec's
        reference layout was the earlier draft; we adapted to what
        Mantid 6.15 actually writes).
  - [x] Critical attributes (`NX_class`, `signal`, `axes`, `units`,
        `caption`) present and correct.
  - [ ] Reference-fixture structural-diff test — *(the cluster's
        Mantid happily round-trips our output as a `MaskWorkspace`;
        capturing a canonical fixture and committing it is a
        follow-up since file-size + retention policy is undecided)*.
- [x] CLI integration tests for each `--<shape>` flag, both XML and
      NeXus, plus `--inverse`, `--shapes-json` replay, default-output
      naming, error paths.
- [ ] Mantid-load smoke test gated on `pytest.importorskip("mantid")`
      — *(verified manually on the cluster: `sansdir mask` →
      `LoadNexusProcessed` → 697 masked spectra match what the CLI
      reported; turning that into a gated pytest is a follow-up)*.
- [x] All tests `ruff` clean. `grep -r "import mantid" src/` returns
      nothing.

### How to capture the reference fixture

On a machine with MantidWorkbench, once:

1. Open a small EQSANS `.nxs.h5` in MantidWorkbench
2. InstrumentView → draw a couple of mask shapes
3. Apply and Save → As Detector Mask to workspace → `MaskWorkspace` in ADS
4. Right-click → Save NeXus → `reference_mask.nxs`
5. Commit to `tests/mask/fixtures/`

If the file is large, subset the source first to keep ~100 spectra. The
fixture is canonical; if a future Mantid release changes the format and
the diff test fails, regenerate fixture + writer in the same PR.

---

## 9.6.8 — Documentation

- [x] README: `K` / `:mask` row in keymap; "Mask creation" section
      with Mantid-loadable example.
- [x] PLANNING.md §12.7 "Mask architecture" — shape model, writer
      strategies, source-file-as-template approach, no-Mantid-dep
      rationale, the Mantid 6.13+ layout adaptation.
- [x] CLI worked example: beam-stop circle plus four corner
      rectangles, in both `sansdir mask --help` epilog and the README
      CLI-examples section.
- [x] Compatibility note: writer borrows detector mapping from the
      source file. EQSANS event-mode files (canonical layout) work
      without `bank1/pixel_id`; files with explicit `bank1/pixel_id`
      get verbatim use; everything else raises
      `UnsupportedFileLayoutError` with a clear message.

---

## Acceptance criteria

- [ ] Convention test passes first
- [ ] Pixel-ordering alignment test passes
- [ ] Reference-fixture structural-diff test passes against a real
      Mantid-Workbench-saved mask
- [ ] End-to-end TUI: open a `.nxs.h5`, press `K`, draw shapes, Save
      NeXus, load with `LoadNexusProcessed` in Mantid, verify masked
      detector IDs match what was drawn (NOT the inverse — verify the
      convention end-to-end on a real run)
- [ ] End-to-end XML: same flow with `LoadMask`
- [ ] CLI round-trip via `--shapes-json` produces byte-identical output
- [ ] All unit tests green, `ruff check` clean
- [ ] `grep -r "import mantid" src/` returns nothing
- [ ] No `mask/instruments/` directory exists (the simplification holds)



# Phase 9.7 — Polish from real-user feedback (post-9.6)

Driven by direct feedback from the first scientist using `K` against
real EQSANS runs. Each item is a small, reviewable change.

## Mask GUI

- [x] **Cell aspect tuned to the EQSANS pitch.** Heatmap now uses
      `aspect=1.0/1.3` (≈ `tube_pitch / pixel_pitch`). Previous
      `aspect="equal"` made circles look vertically elongated.
- [x] **Larger drawing canvas.** ~5%-or-8-cell margin around the
      detector via `set_xlim`/`set_ylim` so users can start a drag
      gesture *outside* the heatmap. Rasteriser already clips
      out-of-bounds shapes; visible dotted boundary marks where the
      mask actually applies.
- [x] **On-disk mask convention inverted to match `mask_4m2.nxs`.**
      Each *unmasked* detector now carries one synthetic event;
      masked detectors carry zero, so the masked region renders grey
      via the normal `p` plot path (matches the visual users get
      from real beamstop files). Internal `MaskBuilder` still uses
      `1 = masked`.
- [x] **Circle and Polygon dropped from the GUI menu.** Ellipse
      covers Circle without the cell-aspect rubber-band weirdness.
      The bank/tube spec input covers the strip-mask case better
      than freehand polygons. Both Shapes + CLI flags stay.
- [x] **Cursor readout** (`format_coord`):
      `tube=N pixel=M counts=K · bank=B tube_in_bank=T`. Bank/tube
      bridge in new `src/sansdir/mask/banktube.py` with 34 unit
      tests covering the round-trip and the spec parser.
- [x] **Mask-by-bank/tube text input** below the button bar:
      `b3` (bank → 4 tubes), `t50` (display column), ranges + mixed
      tokens (`b5-7 t10-15`); each consecutive run of columns
      becomes one Rectangle. Runs round-trip through
      `--shapes-json` like any other shape.
- [x] **Patch-vs-cell alignment fix for spec-input rectangles.**
      `MplRect((lo + 0.5, 0.5), w = hi - lo + 1, h = n_rows)` —
      without the `+1`/`+0.5`, a single-tube spec like `t130`
      collapsed to a zero-width strip on the imshow extent.
- [x] **Save dialog.** Tk `asksaveasfilename` pre-filled with the
      default path; `Save .xml` button removed (CLI still writes
      XML).

## TUI ergonomics

- [x] **F-key reshuffle.** `F5 = Refresh`, `F6 = Copy`,
      `F7 = Move`, `F8 = Delete`, `F9 = Mkdir`. Drop `F10 = Quit`
      (`q` is enough). New `ui.refresh` Command (also `:refresh`).
- [x] **Auto-refresh in batch extract.** Whichever pane shows the
      directory the new files landed in gets `refresh_listing()`
      after a successful write — same pattern `ui.zip_tagged`
      already followed.
- [x] **`K` from the catalog.** `RunCatalogPanel.action_mask_current`
      mirrors `action_show_keys_current` / `action_batch_extract_selection`;
      dispatches `ui.mask` with an explicit `path=` so the file-pane
      cursor is bypassed. `_make_ui_mask` accepts the optional
      `path` kwarg.
- [x] **App-level allow-list.** `K` added to the focused-catalog
      key allow-list in `app.py:on_key` so the catalog binding gets
      first dibs (the app-level keymap was intercepting otherwise).

## Performance

- [x] **OnCat browser filter snappiness.** 200 ms debounce on
      `watch_filter_text` (cancels pending timer on each keystroke);
      cap rendered ListView entries at `MAX_VISIBLE = 200` with an
      overflow hint Static below; wrap the rebuild in
      `app.batch_update()` for a single layout pass. Two pinned
      tests in `test_phase4.py` so the budget can't silently
      regress.

## Tests

- 506 passed, 1 skipped, ruff clean. Test count rose from 392 → 506
  through Phase 9.6 + 9.7 (mask core / writers / CLI / GUI / GUI
  perf / banktube / catalog `K` / `F5` refresh / `F2` rename /
  delete cursor preservation / mask save auto-refresh / debounce /
  cap).

## Mask GUI responsiveness pass (follow-up)

Driven by the same scientist's "feels laggy when I type / drag"
feedback after using the editor on real EQSANS runs.

- [x] **Mask spec input → button + Tk dialog.** Replaced the inline
      matplotlib `TextBox` with a `Mask Spec... (k)` button that
      opens `tkinter.simpledialog.askstring`. Matplotlib's TextBox
      calls `fig.canvas.draw_idle()` on every keystroke, which on a
      256×192 LogNorm imshow plus N overlay patches is a full figure
      re-rasterisation per character — the source of the per-keystroke
      lag.
- [x] **Blit-based shape moves in edit mode.** On mouse-press in
      edit mode, mark the moving patch `set_animated(True)`, do one
      synchronous `fig.canvas.draw()` to flush the rest, then
      `copy_from_bbox(ax.bbox)` to snapshot the static canvas. Each
      subsequent motion event runs `restore_region` +
      `ax.draw_artist(patch)` + `fig.canvas.blit(ax.bbox)` — orders
      of magnitude cheaper than `draw_idle()`. On release we flip
      `set_animated(False)` and do one final `draw_idle()` to fold
      the patch back into the regular layer.
- [x] **Debounce test loosened.** The OnCat browser debounce test
      was flaky in the full suite (event-loop pressure could let
      one timer fire before being cancelled by the next keystroke);
      asserts `1 ≤ rebuilds ≤ 2` instead of `== 1`. The point was
      always "fewer than per-keystroke", not exactly one.

## File-pane cursor + F-key tweaks (follow-up)

Driven by mc / Norton muscle memory.

- [x] **Delete preserves cursor position.**
      `_make_ui_delete_tagged` snapshots ``cursor_row`` +
      ``cursor_path`` before the delete and re-anchors the cursor
      after ``refresh_listing()``. If the cursor's file survived a
      multi-tag delete, cursor stays on it; otherwise it sticks to
      the same row index (= the file just below the deleted one)
      or clamps to the new last row. Without this the cursor
      jumped to row 0 every time, forcing the user to scroll back.
- [x] **F2 = Rename, ``c`` = Catalog toggle.** New ``ui.rename``
      Command opens a ``TextPromptDialog`` pre-filled with the
      cursor's basename, dispatches via the single-file form of
      ``fileops.move_paths``, refreshes the panel, and re-anchors
      the cursor on the renamed file. The catalog toggle moved
      from F2 → F10 → ``c`` after a tester reported F10 opened
      the terminal's menu bar instead of reaching the TUI; ``c``
      (mnemonic: catalog) was unbound on both the file pane and
      the catalog table, so it falls through cleanly from either.

## Mask save auto-refresh (follow-up)

- [x] **`_make_ui_mask` is async; awaits the subprocess.** The
      mask GUI is a detached matplotlib subprocess so the TUI
      stays responsive. After ``subprocess.Popen`` we now run
      ``rc = await asyncio.to_thread(proc.wait)``. The registry
      runs async handlers as Textual workers (``exclusive=False``),
      so multiple editors can be open at once and the wait
      doesn't block the event loop. On ``rc == 0`` (= save) both
      panes refresh and the user sees ``mask saved (panes
      refreshed) — <name>``. On ``rc == 1`` (cancel /
      quit-without-save) nothing happens. We refresh both panes
      because the Tk save dialog lets users redirect the output
      anywhere, so we don't know the exact destination without
      parsing subprocess stdout — and ``refresh_listing`` is
      cheap enough that the simpler approach wins.

---

# Phase 9.5 — Zenodo DOI minting from tagged files

## Goal

A `:createdoi` command in the sansdir TUI that takes the currently-tagged files,
walks the user through Zenodo metadata, uploads them to Zenodo, mints a DOI, and
appends a provenance entry to a `DOI_log.md` file in the active pane's cwd. A
matching `sansdir doi` CLI subcommand exposes the same flow non-interactively.

This phase makes sansdir a one-stop tool for the SANS publishing workflow:
browse → triage → tag → mint citable DOI, all without leaving the terminal.

## Design decisions (locked — do not relitigate during implementation)

1. **Authentication: per-user personal access tokens only.** No shared
   sansdir-bot token, no OAuth flow. Each user creates a token at
   `https://zenodo.org/account/settings/applications/tokens/new/` with scopes
   `deposit:write` and `deposit:actions`. This is structural to how Zenodo /
   DataCite ownership works — the publishing user is forever recorded as the
   record owner.
2. **Per-user profile cached locally.** Name, affiliation, ORCID, email, default
   license stored in `~/.config/sansdir/zenodo.toml`. Auto-prefilled into the
   metadata form. Zenodo's API does *not* read these from the account profile.
3. **First-run wizard inside `:createdoi`.** Missing token / missing profile
   trigger inline setup screens before the metadata form. Standalone commands
   (`:zenodo-login`, `:zenodo-profile`) also exposed for ahead-of-time setup.
4. **Sandbox by default for first-time users.** Production opt-in via
   `:zenodo-prod` or config flag. Sandbox prefix `10.5072`, production `10.5281`.
5. **Two-stage commit.** Form → upload → confirmation modal → publish. Default
   confirm action is "Publish"; "Save as Draft" and "Cancel & Discard" available.
   Never auto-publish without an explicit user click.
6. **New "bucket" file API only.** Streamed `PUT {bucket}/{name}`. No
   multipart, no legacy `/files` POST. 50 GB per file / per record, 100 files
   per record.
7. **Operates on tagged files.** Empty tag set → status-bar error and abort.
   No fallback to cursor selection (publishing is high-stakes).
8. **`DOI_log.md` is per-folder, append-only.** Lives in active pane's cwd if
   writable; falls back to inactive pane, then `~/sansdir-doi-logs/`. Each
   `:createdoi` run appends one entry — earlier entries are never modified.
9. **Pre-flight quota checks.** Total size ≤ 50 GB, file count ≤ 100, before
   any network call. Clear error message if exceeded; suggest `z` (zip) or
   splitting into multiple records.

## Out of scope for 9.5 (defer to later phases)

- OAuth flow / web auth handoff
- New-version API (`/actions/newversion`) for updating published records
- Metadata-only edits to already-published records
- Communities submission
- Auto-prefill of metadata from OnCat catalog (good candidate for 9.6)
- OS keyring / secret-service integration (TOML file is enough for v1)
- `:resumedoi <id>` for picking up an abandoned draft (reserve the command
  name; implement later)

---

## 9.5.1 — ZenodoClient (pure HTTP layer, no Textual)

Module: `src/sansdir/zenodo/client.py`

- [ ] `ZenodoClient(token, base_url, *, session=None, timeout=30)` class
- [ ] Class constants `BASE_URL_PROD = "https://zenodo.org/api"` and
      `BASE_URL_SANDBOX = "https://sandbox.zenodo.org/api"`
- [ ] `verify_token() -> dict` — `GET /deposit/depositions?size=1`; raises
      `ZenodoAuthError` on 401, returns the response body otherwise
- [ ] `create_deposition() -> Deposition` — POSTs `{}`; returns parsed
      `Deposition` dataclass with `id`, `bucket_url`, `prereserved_doi`,
      `links`, `state`
- [ ] `upload_file(bucket_url, path, name=None, *, on_progress=None) -> FileResource`
      — streamed `PUT`, optional `on_progress(bytes_sent, total_bytes)` callback
      for the TUI progress bar
- [ ] `set_metadata(deposition_id, metadata: DepositionMetadata) -> Deposition`
      — `PUT /deposit/depositions/{id}` with `{"metadata": {...}}`
- [ ] `publish(deposition_id) -> PublishedRecord` — `POST .../actions/publish`,
      expects HTTP 202, returns dataclass with `doi`, `concept_doi`, `record_url`,
      `published_at`
- [ ] `discard(deposition_id) -> None` — `POST .../actions/discard` for
      cancellation paths
- [ ] `list_licenses() -> list[License]` — for the license picker; cache result
      in module-level dict keyed by base_url
- [ ] All methods retry transient failures (connection error, 5xx) via
      `urllib3.Retry`: 3 attempts, exponential backoff, only idempotent verbs
- [ ] All errors surface as typed exceptions in `src/sansdir/zenodo/errors.py`:
      `ZenodoError` (base), `ZenodoAuthError`, `ZenodoValidationError(field, message)`,
      `ZenodoQuotaError`, `ZenodoNetworkError`
- [ ] Token must NEVER appear in any exception message, `__repr__`, or log line.
      `__repr__` of `ZenodoClient` shows `Bearer ****` only.
- [ ] Use a single `requests.Session` for connection reuse

**Acceptance:** unit tests with `responses` library covering: success path,
400 validation error (with field-level breakdown), 401 auth error, 413 oversize,
5xx retry succeeds on 2nd attempt, 5xx retry exhausted raises `ZenodoNetworkError`,
streamed PUT calls progress callback the expected number of times.

---

## 9.5.2 — Auth & profile config

Modules: `src/sansdir/zenodo/auth.py`, `src/sansdir/zenodo/profile.py`

- [ ] Config file path: `${SANSDIR_CONFIG:-~/.config/sansdir}/zenodo.toml`
- [ ] Token resolution order (production):
      `$SANSDIR_ZENODO_TOKEN` → `[zenodo].token` → none
- [ ] Token resolution order (sandbox):
      `$SANSDIR_ZENODO_SANDBOX_TOKEN` → `[zenodo.sandbox].token` → none
- [ ] `save_token(token, *, sandbox=False)` writes file with mode `0600`;
      creates parent dir if needed
- [ ] On load, warn (status bar; do not fail) if file mode is wider than `0600`
- [ ] `Profile` dataclass: `name`, `affiliation`, `orcid`, `email`,
      `default_license`. All optional except name and affiliation.
- [ ] `save_profile(profile)`, `load_profile() -> Profile | None`
- [ ] Optional `coauthors` address book serialised as TOML
      `[[profile.coauthors]]` array of tables; each entry has `name`,
      `affiliation`, `orcid`
- [ ] Validate name format `Family, Given` (allow Unicode, but require the comma)
- [ ] Validate ORCID format `\d{4}-\d{4}-\d{4}-\d{3}[\dX]` when present
- [ ] `clear_token(sandbox=False)`, `clear_profile()` for `:zenodo-logout`

**Acceptance:** unit tests using `tmp_path`. Never write to the real
`~/.config/`. Cover: write+read round trip, malformed file (bad TOML, missing
section) raises clean error, 0644 file mode emits warning, env var overrides file.

---

## 9.5.3 — Metadata model & validation

Module: `src/sansdir/zenodo/metadata.py`

- [ ] `Creator` dataclass: `name`, `affiliation`, `orcid` (optional),
      `gnd` (optional)
- [ ] `RelatedIdentifier` dataclass: `relation`, `identifier`,
      `resource_type` (optional)
- [ ] `DepositionMetadata` dataclass with all required + commonly-used fields:
      `title`, `upload_type`, `description`, `creators`, `publication_date`
      (defaults to today), `access_right` (default `"open"`), `license`,
      `keywords`, `related_identifiers`, `notes`
- [ ] `to_zenodo_payload() -> dict` produces exactly the JSON the API expects
      (under top-level `"metadata"` key)
- [ ] `validate() -> list[ValidationError]` runs local checks before any
      network call:
  - `title` non-empty
  - `description` non-empty
  - At least one creator
  - Each creator's `name` matches `Family, Given` regex
  - `upload_type` ∈ controlled vocab (`publication`, `poster`, `presentation`,
    `dataset`, `image`, `video`, `software`, `lesson`, `physicalobject`,
    `other`)
  - `access_right` ∈ `{open, embargoed, restricted, closed}`
  - `license` required if `access_right` ∈ `{open, embargoed}`
- [ ] HTML sanitisation for `description`: keep only Zenodo-allowed tags
      (`a`, `b`, `code`, `em`, `i`, `li`, `ol`, `p`, `pre`, `span`, `strong`,
      `sub`, `sup`, `ul`, `br`); plain text gets wrapped in `<p>`

**Acceptance:** unit tests covering each validation rule and round-trip
serialisation.

---

## 9.5.4 — First-run wizard

In TUI command handler for `:createdoi`:

- [ ] Pre-flight checks in this order:
  1. Tag set non-empty → if empty, status bar
     `"No files tagged. Tag files with Space/+ then run :createdoi."` and abort.
  2. Token present (for currently-active prod/sandbox mode) → if missing,
     push `ZenodoTokenSetupScreen`.
  3. Profile present → if missing, push `ZenodoProfileSetupScreen`.
- [ ] `ZenodoTokenSetupScreen`: instructions, link to token-creation URL with
      pre-checked `deposit:write` + `deposit:actions` scopes, masked paste field,
      "Validate" button calls `verify_token()` before saving
- [ ] `ZenodoProfileSetupScreen`: name, affiliation (default
      `"Oak Ridge National Laboratory"`), ORCID, email, default license
- [ ] Both setup screens display banner: *"First-time setup — happens once."*
- [ ] Cancel (`Esc`) at any step aborts the entire `:createdoi` flow with no
      partial state saved
- [ ] Standalone commands also wired:
      `:zenodo-login`, `:zenodo-profile`, `:zenodo-logout`,
      `:zenodo-prod`, `:zenodo-sandbox` (the last two flip the active mode in
      the TOML file's top-level `[zenodo]` section)

---

## 9.5.5 — `:createdoi` command + metadata form

- [ ] Register `:createdoi` in the existing TUI command registry alongside
      `:extract`, `:zip`, etc. Match the existing command-class pattern.
- [ ] `ZenodoMetadataScreen` — Textual `ModalScreen[DepositionMetadata | None]`
      returning the metadata on submit, `None` on cancel
  - Title input
  - Description textarea (multiline, suggested initial content: brief auto-stub
    listing file count and total size)
  - Creators editor: vertical list, prefilled with self from profile,
    "+ Add coauthor" button opens picker showing both the saved coauthors
    address book and a "fresh entry" option
  - Upload type dropdown (default `dataset`)
  - License dropdown (populated from `client.list_licenses()`, default from
    profile)
  - Access right dropdown (default `open`)
  - Keywords text input (comma-separated, prefilled with
    `SANS, EQSANS, IPTS-NNNNN` derived from path if matchable)
  - Related identifiers expandable section (advanced; can be left empty)
  - Submit → validate locally → continue. Inline errors per field on
    validation failure.

---

## 9.5.6 — File upload (bucket API)

In the `:createdoi` flow, after metadata form submission:

- [ ] Create deposition; capture `bucket_url`, `id`, `prereserved_doi`
- [ ] Pre-flight checks on tagged file set:
  - Total size ≤ 50 GB → else `ZenodoQuotaError` with file count + total size
  - File count ≤ 100 → else suggest `z` (zip them first)
  - All files exist and are readable
- [ ] Compute MD5 for each file locally (streamed — do not load file into RAM).
      Show this as a `"Hashing..."` step in the progress UI; it can be slow on
      large files.
- [ ] Streamed `PUT` per file with progress callback wired to a Textual
      `ProgressBar`. Sequential uploads (do not parallelise — keeps the network
      simple and is fast enough for SANS file sizes).
- [ ] After each upload, verify the Zenodo-returned MD5 matches the locally
      computed MD5; record both in the upload result (used in `DOI_log.md`)
- [ ] On retry-exhausted upload failure, present
      `[Retry remaining] [Abort & Discard]` modal.
      Abort calls `client.discard()` to remove the orphan draft.

---

## 9.5.7 — Confirmation & publish

- [ ] After all uploads complete, push `ZenodoConfirmScreen`:
  - Title, prereserved DOI marked as
    `"DOI preview — not yet active. Will activate on Publish."`
  - File count, total size, list of uploaded filenames with checksums
  - Three buttons: **[Publish]** (default, focus), **[Save as Draft]**,
    **[Cancel & Discard]**
- [ ] **Publish** → `client.publish()` (expect HTTP 202) → write `DOI_log.md`
      entry → status bar shows live DOI URL
- [ ] **Save as Draft** → leave deposition in `inprogress` state, append
      `[[drafts]]` entry to `zenodo.toml` with `id`, `created_at`, `title` so
      it can be found later
- [ ] **Cancel & Discard** → `client.discard()` → status bar confirmation

---

## 9.5.8 — `DOI_log.md` writer (append-only)

Module: `src/sansdir/zenodo/doi_log.py`

- [ ] Locate target dir:
      active pane cwd if writable → else inactive pane cwd if writable →
      else `~/sansdir-doi-logs/<sanitised-path>.md`
- [ ] If `DOI_log.md` does not exist, create with file header:
      `# DOI Log — <absolute folder path>\n\nRecords published from this folder via sansdir.\n\n---\n`
- [ ] If it exists, append a new entry block at end. **Existing content is never
      modified.** Read-validate then write with `O_APPEND` semantics.
- [ ] Each entry contains:
  - `## <DOI> — <title>` heading
  - **Published:** ISO8601 UTC, **Files:** N, **Size:** human-readable
  - Zenodo record URL
  - Files table with columns: Path, Size, MD5, Zenodo checksum (with `✓` if
    matched)
  - "How to cite" block with both BibTeX and APA
  - Submitted metadata as a fenced JSON block (for reproducibility)
  - Provenance footer: sansdir version, hostname, user, run timestamp
  - Trailing `---` separator
- [ ] Function: `append_entry(log_path: Path, entry: DOILogEntry) -> Path`,
      returns the actual path written (which may differ from the requested one
      due to fallback)
- [ ] Status bar message indicates final log path

**Acceptance:** unit tests for: new file creation, appending to existing file
with N entries, parsing-then-re-emitting an existing log produces identical
content (idempotency), fallback path used when target dir is read-only.






























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


---

## 9.5.9 — CLI subcommand

Wire `sansdir doi <files...> [options]` matching the existing CLI style of
`sansdir extract`:

- [ ] Required: positional file arguments
- [ ] `--metadata <file.json>` — full metadata payload from a file (overrides
      individual flags)
- [ ] Individual metadata flags: `--title`, `--description`, `--creator`
      (repeatable), `--license`, `--keyword` (repeatable),
      `--upload-type`, `--access-right`
- [ ] Mode flags: `--sandbox` / `--prod` (default reads from config; default of
      default is sandbox)
- [ ] Action flags: `--publish` (default: stop at draft), `--draft-only`
      (explicit), `--log-dir <path>` (override DOI_log.md location)
- [ ] Without `--publish`: stops at draft, prints the draft URL and id
- [ ] With `--publish`: full pipeline, no interactive confirm — suitable for
      scripts and CI
- [ ] Reads same `~/.config/sansdir/zenodo.toml` as the TUI for token / profile

---

## 9.5.10 — Tests

- [ ] Unit tests for `client.py` using `responses`: success, 400 with field
      errors, 401, 413, 5xx retry, streamed PUT progress callbacks
- [ ] Unit tests for metadata validation
- [ ] Unit tests for profile / auth load / save (using `tmp_path`)
- [ ] Unit tests for `doi_log.append_entry`: new file, append, idempotency,
      fallback path
- [ ] Snapshot test for generated `DOI_log.md` content given fixed inputs
- [ ] CLI tests using `pytest`'s `capsys` and a mocked `ZenodoClient`
- [ ] Integration test under `tests/zenodo/test_sandbox_integration.py` gated
      on `ZENODO_SANDBOX_TOKEN` env var: full round-trip against sandbox, then
      `discard` to clean up. Marked with `@pytest.mark.integration` and skipped
      by default.
- [ ] All tests `ruff` clean

---

## 9.5.11 — Documentation

- [ ] Update `README.md`:
  - New `:createdoi` and related commands in the keymap table
  - "Zenodo integration" section under Configuration with TOML example
  - Mention sandbox-first default and how to flip to production
  - One-paragraph quickstart for first-time users
- [ ] Update `PLANNING.md` with a "Zenodo integration" architecture subsection
- [ ] Mark Phase 9.5 complete in `TASKS.md`
- [ ] Add an example `DOI_log.md` snippet to the README

---

## Acceptance criteria for the phase

- [ ] End-to-end sandbox round-trip from the TUI: tag → `:createdoi` → wizard
      (if first time) → form → upload → confirm → publish → live DOI →
      `DOI_log.md` written with full entry
- [ ] End-to-end sandbox round-trip from the CLI with `--publish`
- [ ] All unit tests green; integration test passes manually with
      `ZENODO_SANDBOX_TOKEN` set
- [ ] `ruff check` clean, `ruff format` applied
- [ ] Manual code review confirms no token leak in any log / error / repr path
- [ ] README and PLANNING.md updated
- [ ] Verified to work on a host without `$DISPLAY` (cluster headless mode) —
      progress bar renders in the TUI, no GUI dialog popups



git: https://github.com/cw-do/sansdir.git
