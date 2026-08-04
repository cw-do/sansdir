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

    print("Rendering plots ...")
    _make_plots()

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
