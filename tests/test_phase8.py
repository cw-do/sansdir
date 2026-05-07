"""Phase 8 end-to-end Pilot test for the M batch-extract dialog."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from sansdir.app import SansdirApp
from sansdir.core.history import CommandHistory


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))


def _write_nx(path: Path, *, temperature: float, duration: float, seed: int = 0) -> None:
    import h5py

    rng = np.random.default_rng(seed=seed)
    with h5py.File(path, "w") as fh:
        entry = fh.create_group("entry")
        entry.create_dataset("duration", data=np.float64(duration))
        daslogs = entry.create_group("DASlogs")
        for name, mean in (("temperature", temperature), ("shear", 1.0)):
            grp = daslogs.create_group(name)
            grp.create_dataset(
                "value",
                data=rng.normal(loc=mean, scale=0.05, size=10).astype("float64"),
            )
            grp.create_dataset("time", data=np.linspace(0.0, 600.0, 10))


def _scratch(tmp_path: Path) -> tuple[Path, Path]:
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    for i, (t, d) in enumerate([(298.0, 600.0), (300.0, 1200.0)], start=1):
        _write_nx(left / f"EQSANS_{i:03d}.nxs.h5", temperature=t, duration=d, seed=i)
    return left, right


def _real_app(tmp_path: Path) -> SansdirApp:
    left, right = _scratch(tmp_path)
    return SansdirApp(
        start_path=left,
        right_path=right,
        history=CommandHistory(path=tmp_path / "hist", load=False),
    )


def _find_screen(app, cls_name: str):  # type: ignore[no-untyped-def]
    """Return the topmost screen of ``cls_name`` on the stack, or None."""
    for screen in reversed(app.screen_stack):
        if type(screen).__name__ == cls_name:
            return screen
    return None


async def test_capital_m_opens_batch_extract_dialog(tmp_path: Path) -> None:
    """``M`` mounts the form and auto-pushes the full-screen key picker."""
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Tag both NeXus files via the * glob.
        await pilot.press("plus")
        await pilot.pause()
        for ch in "*.nxs.h5":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.active_panel.tags) == 2
        await pilot.press("M")
        await pilot.pause()
        # Form is mounted underneath; picker is the topmost modal.
        assert _find_screen(app, "BatchExtractDialog") is not None
        assert _find_screen(app, "HdfKeyPickerScreen") is not None
        # Esc on the picker dismisses it, leaving the form for editing.
        await pilot.press("escape")
        await pilot.pause()
        assert _find_screen(app, "HdfKeyPickerScreen") is None
        assert _find_screen(app, "BatchExtractDialog") is not None
        # Esc on the form dismisses it — no file written.
        await pilot.press("escape")
        await pilot.pause()
        assert not any(p.name.startswith("extracted_") for p in tmp_path.iterdir())
        await pilot.press("q")


async def test_dialog_dispatches_extract_and_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full flow: M → picker dismiss with keys → form submit → TSV exists."""
    app = _real_app(tmp_path)
    out_path = tmp_path / "out.tsv"
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("plus")
        await pilot.pause()
        for ch in "*.nxs.h5":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("M")
        await pilot.pause()
        # Picker is on top; dismiss it with the same list it would
        # produce after the user space-toggled both keys.
        picker = _find_screen(app, "HdfKeyPickerScreen")
        assert picker is not None
        picker.dismiss(["/entry/DASlogs/temperature/value", "/entry/duration"])
        await pilot.pause()
        form = _find_screen(app, "BatchExtractDialog")
        assert form is not None
        # Verify the picker's result was merged into the form's input.
        from textual.widgets import Input

        assert "/entry/duration" in form.query_one("#keys-input", Input).value
        # Submit the form with an explicit payload (Pilot can't easily
        # drive the Select widget; submit() reads from the Input).
        # Submit in summary mode (so the test writes to a fixed path
        # without `<filename>` injection). Per-file mode is exercised
        # by ``test_dialog_per_file_mode_writes_one_csv_per_input``.
        form.dismiss(
            {
                "keys": ["/entry/DASlogs/temperature/value", "/entry/duration"],
                "out": str(out_path),
                "fmt": "tsv",
                "mode": "summary",
                "with_stats": False,
            }
        )
        await pilot.pause()
        for _ in range(20):
            if out_path.exists():
                break
            await pilot.pause()
        assert out_path.exists(), "extract did not write the summary output"
        with out_path.open(newline="") as fh:
            rows = list(csv.reader(fh, delimiter="\t"))
        assert rows[0] == ["filename", "temperature", "duration"]
        assert len(rows) == 3  # header + two files
        await pilot.press("q")


async def test_dialog_per_file_mode_writes_one_csv_per_input(tmp_path: Path) -> None:
    """Default per-file mode: each input file produces its own CSV."""
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("plus")
        await pilot.pause()
        for ch in "*.nxs.h5":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("M")
        await pilot.pause()
        picker = _find_screen(app, "HdfKeyPickerScreen")
        assert picker is not None
        picker.dismiss(
            ["/entry/DASlogs/temperature/time", "/entry/DASlogs/temperature/value"]
        )
        await pilot.pause()
        form = _find_screen(app, "BatchExtractDialog")
        assert form is not None
        # Submit with a non-templated output — per-file mode must
        # auto-prepend <filename>_ so we still get one CSV per input.
        form.dismiss(
            {
                "keys": [
                    "/entry/DASlogs/temperature/time",
                    "/entry/DASlogs/temperature/value",
                ],
                "out": "temp.csv",
                "fmt": "csv",
                "mode": "per_file",
                "with_stats": False,
            }
        )
        # Output lands in the *inactive* pane's cwd (the right scratch
        # dir), with `<filename>_` auto-prepended.
        right_dir = tmp_path / "R"
        for _ in range(20):
            if any(p.name.endswith("_temp.csv") for p in right_dir.iterdir()):
                break
            await pilot.pause()
        outputs = sorted(p for p in right_dir.iterdir() if p.name.endswith("_temp.csv"))
        assert len(outputs) == 2
        assert {p.name for p in outputs} == {
            "EQSANS_001_temp.csv",
            "EQSANS_002_temp.csv",
        }
        # Each file holds the *full* 10-sample arrays, no filename column.
        with outputs[0].open(newline="") as fh:
            rows = list(csv.reader(fh))
        assert rows[0] == ["time", "temperature"]
        assert len(rows) == 11  # header + 10 samples
        await pilot.press("q")


async def test_picker_space_toggles_selection(tmp_path: Path) -> None:
    """Inside the picker: Space on a dataset leaf toggles it in the result list."""
    from textual.widgets import Tree

    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("plus")
        await pilot.pause()
        for ch in "*.nxs.h5":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("M")
        await pilot.pause()
        picker = _find_screen(app, "HdfKeyPickerScreen")
        assert picker is not None
        tree = picker.query_one("#picker-tree", Tree)
        entry = next(c for c in tree.root.children if "entry" in str(c.label))
        tree.select_node(entry)
        await pilot.pause()
        entry.expand()
        await pilot.pause()
        duration = next(c for c in entry.children if "duration" in str(c.label))
        tree.select_node(duration)
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert "/entry/duration" in picker._selected
        await pilot.press("space")
        await pilot.pause()
        assert "/entry/duration" not in picker._selected
        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.press("q")


async def test_catalog_capital_m_defaults_to_cursor_run_when_untagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catalog ``M`` with no tags → only the cursor row's run is extracted.

    Mirrors the file-pane convention (no tags = act on cursor). Use
    ``Space`` to tag multiple runs first; that path is exercised by
    ``test_catalog_space_tags_run_and_capital_m_uses_tags``.
    """
    from sansdir.core.oncat import Datafile

    # Two synthetic NeXus files we can put at the conventional path.
    fake_root = tmp_path / "FAKE"
    nx_dir = fake_root / "EQSANS" / "IPTS-99999" / "nexus"
    nx_dir.mkdir(parents=True)
    runs: list[Datafile] = []
    for i in range(2):
        run_n = 100 + i
        p = nx_dir / f"EQSANS_{run_n}.nxs.h5"
        _write_nx(p, temperature=298.0 + i, duration=600.0, seed=i)
        runs.append(
            Datafile(
                run_number=run_n,
                title=f"sample {i}",
                start_time="",
                duration_s=600,
                detector_distance_mm=2500.0,
                wavelength_a=2.5,
                total_counts=1000,
            )
        )
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Inject the catalog directly — bypassing OnCat keeps this
        # test focused on the M binding's path resolution.
        slot = app._inactive_slot
        slot.show_catalog("IPTS-99999", runs, instrument="EQSANS", facility=str(fake_root)[1:])
        await pilot.pause()
        # Raw path resolution prefixes ``/`` to the facility — strip
        # the leading slash from our tmp_path-derived facility so the
        # resolver lands on tmp_path/FAKE/EQSANS/IPTS-99999/nexus/...
        assert slot.catalog.raw_nexus_path(100).exists()
        # Tab into the catalog so M reaches the CatalogTable.
        await pilot.press("tab")
        await pilot.pause()
        assert app._active_slot is slot
        await pilot.press("M")
        await pilot.pause()
        form = _find_screen(app, "BatchExtractDialog")
        assert form is not None
        # No tags → just the cursor row (run 100 in this fixture, since
        # ``show_catalog`` resets the cursor to row 0).
        assert [p.name for p in form._files] == ["EQSANS_100.nxs.h5"]
        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.press("q")


async def test_catalog_space_tags_run_and_capital_m_uses_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catalog Space tags the cursor row; M then operates on tagged runs only."""
    from sansdir.core.oncat import Datafile

    fake_root = tmp_path / "FAKE"
    nx_dir = fake_root / "EQSANS" / "IPTS-99999" / "nexus"
    nx_dir.mkdir(parents=True)
    runs: list[Datafile] = []
    for i in range(3):
        run_n = 100 + i
        p = nx_dir / f"EQSANS_{run_n}.nxs.h5"
        _write_nx(p, temperature=298.0 + i, duration=600.0, seed=i)
        runs.append(
            Datafile(
                run_number=run_n,
                title=f"sample {i}",
                start_time="",
                duration_s=600,
                detector_distance_mm=2500.0,
                wavelength_a=2.5,
                total_counts=1000,
            )
        )
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        slot = app._inactive_slot
        slot.show_catalog("IPTS-99999", runs, instrument="EQSANS", facility=str(fake_root)[1:])
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        # Tag run 100 (cursor on row 0) and run 102 (cursor on row 2).
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("space")
        await pilot.pause()
        assert slot.catalog.tagged_runs == {100, 102}
        # The catalog had no leakage into the file pane's tag set —
        # that was the original bug.
        assert app.active_panel.tags == set() or len(app.active_panel.tags) == 0
        # M should now operate on the tagged runs only (2, not 3).
        await pilot.press("M")
        await pilot.pause()
        form = _find_screen(app, "BatchExtractDialog")
        assert form is not None
        assert {p.name for p in form._files} == {
            "EQSANS_100.nxs.h5",
            "EQSANS_102.nxs.h5",
        }
        await pilot.press("escape")
        await pilot.press("escape")
        # `u` clears catalog tags.
        await pilot.press("u")
        await pilot.pause()
        assert slot.catalog.tagged_runs == set()
        await pilot.press("q")


async def test_capital_m_with_no_nexus_selection_notifies(tmp_path: Path) -> None:
    """If no .nxs.h5 is selected, M warns instead of opening the dialog."""
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    (left / "a.dat").write_text("aa", encoding="utf-8")
    app = SansdirApp(
        start_path=left,
        right_path=right,
        history=CommandHistory(path=tmp_path / "hist", load=False),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("M")
        await pilot.pause()
        # No modal pushed.
        assert not any(type(s).__name__ == "BatchExtractDialog" for s in app.screen_stack)
        await pilot.press("q")
