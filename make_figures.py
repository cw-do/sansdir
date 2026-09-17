#!/usr/bin/env python
"""Regenerate the figures used by ``docs/sansdir-report.tex``.

Every figure in the report is produced from the live code base rather than
drawn by hand, so the report cannot drift from the program it documents:

* Terminal screenshots are captured by driving the real :class:`SansdirApp`
  through Textual's headless pilot and calling ``save_screenshot``.
* Plots are produced by calling sansdir's own figure factories.

Run from the repository root::

    .venv/bin/python docs/make_figures.py

SVG screenshots are converted to PDF with ``rsvg-convert``; if it is missing
the SVGs are left in place and a warning is printed (LaTeX cannot include SVG
directly, so the previously converted PDFs remain in use).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIG_DIR = REPO_ROOT / "docs" / "figures"
SCRATCH = Path("/tmp/sansdir_figures")

# Plausible contents for the demonstration pane. Sizes are cosmetic --- the
# files are stubs; only the listing is photographed.
DEMO_FILES: tuple[tuple[str, int], ...] = (
    ("porsil_20C_2o5m_Iq.dat", 8_412),
    ("porsil_20C_4m_Iq.dat", 8_390),
    ("porsil_20C_2o5m_Iqxqy.dat", 2_140_887),
    ("porsil_30C_4m_Iq.dat", 8_401),
    ("porsil_20C_2o5m_trans.txt", 812),
    ("porsil_30C_4m_processed.nxs", 4_182_233),
    ("EQSANS_172749.nxs.h5", 3_401_882_112),
    ("EQSANS_172750.nxs.h5", 2_884_113_920),
    ("merged_20C.dat", 16_204),
    ("merged_30C.dat", 16_198),
    ("reduction_log.txt", 4_411),
    ("summary.tsv", 2_048),
)

TERMINAL_SIZE = (140, 38)


def _svg_to_pdf(stem: str) -> None:
    """Convert ``FIG_DIR/stem.svg`` to PDF, warning if the tool is absent."""
    svg = FIG_DIR / f"{stem}.svg"
    pdf = FIG_DIR / f"{stem}.pdf"
    if shutil.which("rsvg-convert") is None:
        print(f"  ! rsvg-convert not found; {svg.name} left unconverted")
        return
    subprocess.run(
        ["rsvg-convert", "-f", "pdf", "-o", str(pdf), str(svg)],
        check=True,
        capture_output=True,
    )
    print(f"  -> {pdf.relative_to(REPO_ROOT)}")


def _build_demo_tree() -> tuple[Path, Path]:
    """Create the synthetic proposal directory photographed in Figure 2."""
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    left = SCRATCH / "IPTS-35270" / "shared" / "output1"
    right = SCRATCH / "triage"
    left.mkdir(parents=True)
    right.mkdir(parents=True)
    for name, size in DEMO_FILES:
        (left / name).write_bytes(b"# sansdir demo\n" + b"0" * min(size, 4096))
    (left / "autoreduce").mkdir()
    (left / "figures").mkdir()
    for name in ("notes.md", "baseline_Iq.dat", "side_by_side.zip"):
        (right / name).write_text("# placeholder\n")
    return left, right


async def _capture_panes() -> None:
    """Figure: the dual-pane interface with three tagged files."""
    from sansdir.app import SansdirApp
    from sansdir.core.history import CommandHistory

    left, right = _build_demo_tree()
    app = SansdirApp(
        start_path=left,
        right_path=right,
        history=CommandHistory(path=SCRATCH / "hist", load=False),
    )
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await pilot.pause()
        for _ in range(3):
            await pilot.press("down")
        for _ in range(3):
            await pilot.press("space")
        await pilot.pause()
        app.save_screenshot(str(FIG_DIR / "tui-panes.svg"))


async def _capture_hdf_and_help() -> None:
    """Figures: the HDF5 keyword search, and the generated help overlay."""
    from sansdir.app import SansdirApp
    from sansdir.core.history import CommandHistory
    from sansdir.ui.hdf_tree import HdfTreeScreen

    source = REPO_ROOT / "tests" / "data" / "EQSANS_172749.nxs.h5"
    if not source.is_file():
        print(f"  ! missing fixture {source}; skipping HDF figures")
        return

    root = SCRATCH / "nexus_demo"
    left, right = root / "nexus", root / "work"
    left.mkdir(parents=True, exist_ok=True)
    right.mkdir(parents=True, exist_ok=True)
    target = left / source.name
    shutil.copy(source, target)

    app = SansdirApp(
        start_path=left,
        right_path=right,
        history=CommandHistory(path=root / "hist", load=False),
    )
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await pilot.pause()
        app.push_screen(HdfTreeScreen(target))
        await pilot.pause()
        await pilot.press("slash")
        for char in "temperature":
            await pilot.press(char)
        await app.workers.wait_for_complete()
        await pilot.pause()
        # Move off row 0 so the detail pane shows a dataset, not the group.
        await pilot.press("down")
        await pilot.press("down")
        await pilot.pause()
        app.save_screenshot(str(FIG_DIR / "hdf-search.svg"))

        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        app.save_screenshot(str(FIG_DIR / "help-overlay.svg"))


async def _capture_metadata_workflow() -> None:
    """Figure: metadata extraction + plot, on a real IPTS-37828 file.

    Unlike every other figure here, this one is *not* reproducible from a
    committed fixture: it walks the actual keyword-search / extract / plot
    workflow against a real 147 MB processed NeXus file
    (``IPTS-37828/shared/output/3_0.1phr/..._processed.nxs``) that lives only
    on the analysis cluster. On any other host, or if the file has moved,
    this silently no-ops and the four panels already in ``figures/`` are
    left untouched --- same convention as the ``EQSANS_172749.nxs.h5``
    check above.

    The four panels are captured in the exact order a user presses keys:
    ``M`` -> search "LC" in the key picker and select two datasets ->
    the extraction form with the format set to CSV -> the destination
    pane after the CSV lands -> the plotted curve from ``l``.
    """
    from sansdir.app import SansdirApp
    from sansdir.core.history import CommandHistory

    ipts_dir = Path("/SNS/EQSANS/IPTS-37828/shared")
    source = ipts_dir / "output" / "3_0.1phr" / "70.30PBD_0.1_phr_d10_4m2.5a30hz_processed.nxs"
    if not source.is_file():
        print(f"  ! missing {source}; skipping metadata-workflow figure")
        return

    root = SCRATCH / "metadata_workflow"
    root.mkdir(parents=True, exist_ok=True)
    app = SansdirApp(
        start_path=source.parent,
        right_path=ipts_dir,
        history=CommandHistory(path=root / "hist", load=False),
    )
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        app.active_panel.move_cursor_to_path(source.resolve())
        await pilot.pause()

        # -- panel 1: 'M' -> auto-launched picker -> '/' search "LC" ---------
        # -> Tab onto the results table (search-input has focus after
        # typing) -> skip the parent group row -> select the two leaves.
        #
        # NB: do NOT ``await app.workers.wait_for_complete()`` while the
        # dialog is open — the batch-extract *command* runs as a worker
        # that is itself awaiting the dialog's result, so that call
        # deadlocks. Wait for the search-results table instead.
        await pilot.press("M")
        picker = None
        for _ in range(100):
            await pilot.pause(0.05)
            if type(app.screen).__name__ == "HdfKeyPickerScreen":
                picker = app.screen
                break
        if picker is None:
            print("  ! key picker never opened; aborting workflow figure")
            return
        await pilot.press("slash")
        for ch in "LC":
            await pilot.press(ch)
        for _ in range(600):  # the first search walks the HDF5 tree (~3 s)
            if getattr(picker, "_search_rows", None):
                break
            await pilot.pause(0.1)
        else:
            print("  ! key search never returned results; aborting workflow figure")
            return
        await pilot.pause()
        await pilot.press("tab")
        await pilot.press("down")  # row 0 is the parent group; skip it
        await pilot.press("space")  # .../SGLC/time
        await pilot.press("down")
        await pilot.press("space")  # .../SGLC/value
        await pilot.pause()
        app.save_screenshot(str(FIG_DIR / "metadata-workflow-1.svg"))

        # -- panel 2: back in the form, format switched to CSV --------------
        await pilot.press("ctrl+s")
        for _ in range(100):
            await pilot.pause(0.05)
            if type(app.screen).__name__ == "BatchExtractDialog":
                break
        else:
            print("  ! extract form never resurfaced; aborting workflow figure")
            return
        from textual.widgets import Select

        app.screen.query_one("#fmt-select", Select).value = "csv"
        await pilot.pause()
        app.save_screenshot(str(FIG_DIR / "metadata-workflow-2.svg"))

        # -- run the extraction, land on the shared folder -------------------
        await pilot.press("ctrl+s")
        await app.workers.wait_for_complete()
        await pilot.pause()
        written = ipts_dir / f"{source.stem}_extracted.csv"
        if not written.is_file():
            print(f"  ! extraction did not produce {written}; aborting workflow figure")
            return

        # -- panel 3: the shared folder, cursor on the new CSV ---------------
        await pilot.press("tab")
        await pilot.pause()
        await app.workers.wait_for_complete()
        app.active_panel.move_cursor_to_path(written.resolve())
        await pilot.pause()
        app.save_screenshot(str(FIG_DIR / "metadata-workflow-3.svg"))

        # -- panel 4: 'l' plots it; headless, so it saves a PNG --------------
        os.environ["SANSDIR_CACHE_DIR"] = str(root / "plots")
        await pilot.press("l")
        await app.workers.wait_for_complete()
        await pilot.pause()

    for stem in ("metadata-workflow-1", "metadata-workflow-2", "metadata-workflow-3"):
        _svg_to_pdf(stem)

    # sansdir writes to $SANSDIR_CACHE_DIR/plots/<stamp>_<name>.png
    png_dir = root / "plots"
    pngs = sorted(png_dir.rglob("*.png")) if png_dir.is_dir() else []
    if not pngs:
        print("  ! 'l' did not produce a PNG; workflow figure is missing panel 4")
        return
    _tile_workflow_figure(pngs[-1])


def _tile_workflow_figure(plot_png: Path) -> None:
    """Assemble the four metadata-workflow panels into one labeled figure."""
    _tile_panels(
        "metadata-workflow",
        [
            (FIG_DIR / "metadata-workflow-1.pdf", "(a) M, then /LC: search + select keys"),
            (FIG_DIR / "metadata-workflow-2.pdf", "(b) Ctrl+S: output form, format = CSV"),
            (FIG_DIR / "metadata-workflow-3.pdf", "(c) the CSV lands in the other pane"),
            (plot_png, "(d) l: plot of the extracted table"),
        ],
    )


def _tile_panels(out_stem: str, panels: list[tuple[Path, str]]) -> None:
    """Tile captioned panels into ``FIG_DIR/<out_stem>.pdf`` (2 per row)."""
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt

    missing = [p for p, _ in panels if not p.is_file()]
    if missing:
        print(f"  ! missing panel source(s): {missing}; skipping tiled figure")
        return

    fig, axes = plt.subplots(2, 2, figsize=(13, 8.2))
    for ax, (path, caption) in zip(axes.ravel(), panels, strict=True):
        if path.suffix == ".pdf":
            # Rasterize the terminal-screenshot PDFs at a fixed DPI so all
            # four panels share one consistent resolution in the tile.
            import subprocess as _sp
            import tempfile

            with tempfile.TemporaryDirectory() as td:
                png = Path(td) / "panel.png"
                _sp.run(
                    [
                        "pdftoppm",
                        "-png",
                        "-r",
                        "220",
                        "-singlefile",
                        str(path),
                        str(png.with_suffix("")),
                    ],
                    check=True,
                    capture_output=True,
                )
                img = mpimg.imread(png)
        else:
            img = mpimg.imread(path)
        ax.imshow(img)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_xlabel(caption, fontsize=11)
    fig.tight_layout()
    out = FIG_DIR / f"{out_stem}.pdf"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {out.relative_to(REPO_ROOT)}")


async def _wait_for(pilot, predicate, *, tries: int = 600, delay: float = 0.1) -> bool:  # type: ignore[no-untyped-def]
    """Poll ``predicate`` between pilot pauses; True when it fires.

    Never ``await app.workers.wait_for_complete()`` while a modal is up:
    the command that opened the modal is itself a worker awaiting the
    dialog's answer, so that call deadlocks (learned the hard way).
    """
    for _ in range(tries):
        if predicate():
            return True
        await pilot.pause(delay)
    return False


async def _capture_usans_workflow() -> None:
    """Figure: the single-key USANS reduction flow, on real IPTS-37679 data.

    Cluster-only, like the metadata workflow above: it needs OnCat access,
    the IPTS-37679 autoreduce ARN files, and the ``usansred`` pixi
    environment, and silently no-ops when any of those are missing.

    Four panels, in keystroke order: ``r`` in an empty working folder
    offers to build the setup table; the start-run prompt takes 49434;
    the generated CSV lands under the cursor with its content previewed
    in the other pane; a second ``r`` reduces it and the other pane shows
    the reduced curves. The working folder is wiped and recreated on
    every run so the capture is reproducible.
    """
    from sansdir.app import SansdirApp
    from sansdir.core.history import CommandHistory

    ipts_shared = Path("/SNS/USANS/IPTS-37679/shared")
    if not (ipts_shared / "autoreduce").is_dir():
        print("  ! IPTS-37679/shared/autoreduce not reachable; skipping USANS figure")
        return
    work = ipts_shared / "cdo" / "report_demo"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    root = SCRATCH / "usans_workflow"
    root.mkdir(parents=True, exist_ok=True)
    app = SansdirApp(
        start_path=work,
        right_path=work,
        history=CommandHistory(path=root / "hist", load=False),
    )
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await pilot.pause()

        def modal_is(name: str) -> bool:
            return type(app.screen).__name__ == name

        def no_modal() -> bool:
            return len(app.screen_stack) == 1

        # -- panel 1: `r` with no table under the cursor: the offer ----------
        await pilot.press("r")
        if not await _wait_for(pilot, lambda: modal_is("ConfirmDialog")):
            print("  ! build-table offer never appeared; aborting USANS figure")
            return
        await pilot.pause()
        app.save_screenshot(str(FIG_DIR / "usans-workflow-1.svg"))

        # -- panel 2: accept; OnCat fetch, then the start-run prompt ---------
        await pilot.press("y")
        if not await _wait_for(pilot, lambda: modal_is("TextPromptDialog")):
            print("  ! start-run prompt never appeared; aborting USANS figure")
            return
        for ch in "49434":
            await pilot.press(ch)
        await pilot.pause()
        app.save_screenshot(str(FIG_DIR / "usans-workflow-2.svg"))

        # -- panel 3: table generated, previewed in the other pane -----------
        await pilot.press("enter")
        csv_path = work / "IPTS-37679_setup.csv"
        if not await _wait_for(pilot, lambda: no_modal() and csv_path.is_file()):
            print("  ! setup CSV was not generated; aborting USANS figure")
            return
        await pilot.pause()
        await pilot.pause()
        app.save_screenshot(str(FIG_DIR / "usans-workflow-3.svg"))

        # -- panel 4: `r` on the CSV -> output prompt -> reduce -> results ---
        await pilot.press("r")
        if not await _wait_for(pilot, lambda: modal_is("TextPromptDialog")):
            print("  ! output-dir prompt never appeared; aborting USANS figure")
            return
        await pilot.press("enter")  # accept <csv dir>/output
        # The engine reduces every block; give it up to ten minutes.
        if not await _wait_for(pilot, lambda: modal_is("ConfirmDialog"), tries=6000):
            print("  ! reduction never finished; aborting USANS figure")
            return
        await pilot.press("y")  # show the output directory in the other pane
        if not await _wait_for(pilot, no_modal):
            return
        await pilot.pause()
        app.save_screenshot(str(FIG_DIR / "usans-workflow-4.svg"))

    for stem in ("usans-workflow-1", "usans-workflow-2", "usans-workflow-3", "usans-workflow-4"):
        _svg_to_pdf(stem)
    _tile_panels(
        "usans-workflow",
        [
            (
                FIG_DIR / "usans-workflow-1.pdf",
                "(a) r in an empty folder: offer to build the table",
            ),
            (FIG_DIR / "usans-workflow-2.pdf", "(b) first run of the experiment: 49434"),
            (
                FIG_DIR / "usans-workflow-3.pdf",
                "(c) the generated CSV, previewed in the other pane",
            ),
            (
                FIG_DIR / "usans-workflow-4.pdf",
                "(d) r on the CSV: reduced curves in the other pane",
            ),
        ],
    )


def _make_plots() -> None:
    """Figures: a reduced I(q) curve and a raw detector heat map."""
    import matplotlib

    matplotlib.use("Agg")
    from sansdir.plot.ascii1d import make_iq_figure
    from sansdir.plot.hdf5_detector import make_detector_figure

    iq_source = REPO_ROOT / "tests" / "data" / "test_2o5m2o5a_Iq.dat"
    if iq_source.is_file():
        fig = make_iq_figure([iq_source])
        fig.savefig(FIG_DIR / "plot-iq.pdf", bbox_inches="tight")
        print(f"  -> {(FIG_DIR / 'plot-iq.pdf').relative_to(REPO_ROOT)}")

    nexus_source = REPO_ROOT / "tests" / "data" / "EQSANS_172749.nxs.h5"
    if nexus_source.is_file():
        fig = make_detector_figure(nexus_source)
        fig.savefig(FIG_DIR / "plot-detector.pdf", bbox_inches="tight")
        print(f"  -> {(FIG_DIR / 'plot-detector.pdf').relative_to(REPO_ROOT)}")


def main() -> int:
    # Force the headless plot path so no code here tries to open a window.
    os.environ["SANSDIR_HEADLESS"] = "1"
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    print("Capturing terminal screenshots ...")
    asyncio.run(_capture_panes())
    asyncio.run(_capture_hdf_and_help())
    for stem in ("tui-panes", "hdf-search", "help-overlay"):
        if (FIG_DIR / f"{stem}.svg").is_file():
            _svg_to_pdf(stem)

    print("Capturing metadata-extraction worked example (cluster-only) ...")
    asyncio.run(_capture_metadata_workflow())

    print("Capturing USANS reduction worked example (cluster-only) ...")
    asyncio.run(_capture_usans_workflow())

    print("Rendering plots ...")
    _make_plots()

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
