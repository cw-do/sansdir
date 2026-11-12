"""Tests for sansdir.plot.ascii2d + tile (2D Iqxqy plotting)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sansdir.plot import ascii2d, backend, tile


@pytest.fixture(autouse=True)
def headless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv(backend.HEADLESS_ENV, "1")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    backend.reset_backend_cache()


def _write_iqxqy(path: Path, nx: int = 5, ny: int = 4, *, cols: int = 4) -> None:
    """Write a regular Iqxqy grid with optional sigma_I + dqx/dqy columns."""
    qx_vals = np.linspace(-0.1, 0.1, nx)
    qy_vals = np.linspace(-0.08, 0.08, ny)
    rows = ["# qx qy I sigI" + (" dqx dqy" if cols == 6 else "")]
    for iy, qy in enumerate(qy_vals):
        for ix, qx in enumerate(qx_vals):
            intensity = 1.0 + ix + 10 * iy
            line = [f"{qx:.4e}", f"{qy:.4e}", f"{intensity:.4e}", f"{intensity * 0.05:.4e}"]
            if cols == 6:
                line.extend(["1.0e-3", "1.0e-3"])
            rows.append("\t".join(line))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# read_iqxqy
# ---------------------------------------------------------------------------


def test_read_iqxqy_4col(tmp_path: Path) -> None:
    f = tmp_path / "Iqxqy.dat"
    _write_iqxqy(f, nx=5, ny=4, cols=4)
    ds = ascii2d.read_iqxqy(f)
    assert ds.shape == (4, 5)  # (ny, nx)
    assert ds.qx.shape == (5,)
    assert ds.qy.shape == (4,)
    assert ds.sigma_i is not None
    # First cell at (qx=qx[0], qy=qy[0]) should be intensity 1.0 (ix=0, iy=0).
    assert ds.intensity[0, 0] == pytest.approx(1.0)
    assert ds.intensity[3, 4] == pytest.approx(1.0 + 4 + 10 * 3)


def test_read_iqxqy_6col_drops_dq(tmp_path: Path) -> None:
    f = tmp_path / "Iqxqy.dat"
    _write_iqxqy(f, cols=6)
    ds = ascii2d.read_iqxqy(f)
    assert ds.shape == (4, 5)


def test_read_iqxqy_sparse_grid_fills_nan(tmp_path: Path) -> None:
    """Real SANS files mask the beam-stop region — missing cells stay NaN.

    Regression: read_iqxqy used to raise GridError on any unfilled cell,
    which rejected almost every real Iqxqy.dat from the cluster. Now we
    just leave NaN there and let pcolormesh render it as a soft grey.
    """
    f = tmp_path / "scatter.dat"
    f.write_text(
        "# qx qy I sigI\n0.0 0.0 1.0 0.1\n0.05 0.0 1.5 0.1\n0.1 0.05 2.0 0.1\n",
        encoding="utf-8",
    )
    ds = ascii2d.read_iqxqy(f)
    assert ds.shape == (2, 3)  # 2 unique qy x 3 unique qx
    assert ds.intensity[0, 0] == pytest.approx(1.0)
    assert ds.intensity[0, 1] == pytest.approx(1.5)
    assert ds.intensity[1, 2] == pytest.approx(2.0)
    # The other 3 cells weren't supplied → NaN, not a hard failure.
    assert np.isnan(ds.intensity[0, 2])
    assert np.isnan(ds.intensity[1, 0])
    assert np.isnan(ds.intensity[1, 1])


def test_read_iqxqy_real_grid_with_masked_centre(tmp_path: Path) -> None:
    """Regular grid with a masked square in the middle — most cells filled."""
    f = tmp_path / "Iqxqy.dat"
    rows = ["# qx qy I sigI"]
    qx_vals = np.linspace(-0.1, 0.1, 5)
    qy_vals = np.linspace(-0.08, 0.08, 4)
    for iy, qy in enumerate(qy_vals):
        for ix, qx in enumerate(qx_vals):
            # Skip the centre 2x2 region as if it were masked by the beam stop.
            if 1 <= ix <= 2 and 1 <= iy <= 2:
                continue
            rows.append(f"{qx:.4e}\t{qy:.4e}\t{ix + 10 * iy + 1.0}\t0.1")
    f.write_text("\n".join(rows) + "\n", encoding="utf-8")
    ds = ascii2d.read_iqxqy(f)
    assert ds.shape == (4, 5)
    nan_count = int(np.isnan(ds.intensity).sum())
    assert nan_count == 4  # the masked 2x2 block


def test_read_iqxqy_rejects_wrong_columns(tmp_path: Path) -> None:
    f = tmp_path / "x.dat"
    f.write_text("# only three\n1.0 2.0 3.0\n4.0 5.0 6.0\n", encoding="utf-8")
    with pytest.raises(ascii2d.GridError, match="4 or 6 columns"):
        ascii2d.read_iqxqy(f)


# ---------------------------------------------------------------------------
# Single 2D plot
# ---------------------------------------------------------------------------


def test_make_iqxqy_figure_returns_figure_with_pcolormesh(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    f = tmp_path / "Iqxqy.dat"
    _write_iqxqy(f)
    fig = tile.make_iqxqy_figure(f)
    # One axes + one colorbar axes = two axes total.
    assert len(fig.axes) == 2
    # The first axes carries our pcolormesh as a QuadMesh collection.
    main = fig.axes[0]
    assert any(c.__class__.__name__ == "QuadMesh" for c in main.collections)
    assert "qx" in main.get_xlabel().lower() or "q_x" in main.get_xlabel()
    plt.close(fig)


def test_make_iqxqy_figure_log_intensity(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    f = tmp_path / "Iqxqy.dat"
    _write_iqxqy(f)
    fig = tile.make_iqxqy_figure(f, log_intensity=True)
    main = fig.axes[0]
    pcm = next(c for c in main.collections if c.__class__.__name__ == "QuadMesh")
    assert isinstance(pcm.norm, LogNorm)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Tile mode (multi-2D)
# ---------------------------------------------------------------------------


def test_tile_one_file_falls_through_to_single(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    f = tmp_path / "Iqxqy.dat"
    _write_iqxqy(f)
    fig = tile.make_tile_figure([f])
    # Same shape as single Iqxqy: 1 main + 1 colorbar.
    assert len(fig.axes) == 2
    plt.close(fig)


def _count_data_tiles(fig) -> int:  # type: ignore[no-untyped-def]
    """Count axes that render an Iqxqy tile (vs. colorbar / spare cells).

    Data tiles in :func:`make_tile_figure` set ``box_aspect == 1`` so
    they stay square; colorbars and the off-axes spare cells don't.
    Filtering on that flag distinguishes them cleanly.
    """
    return sum(1 for ax in fig.axes if ax.get_box_aspect() == 1)


def test_tile_four_files_uses_4wide_with_shared_colorbar(tmp_path: Path) -> None:
    """eqsanstools-style: 4 columns x ceil(N/4) rows + dedicated cbar column."""
    import matplotlib.pyplot as plt

    files = []
    for i in range(4):
        f = tmp_path / f"Iqxqy_{i}.dat"
        _write_iqxqy(f)
        files.append(f)
    fig = tile.make_tile_figure(files, colorbar_mode="shared")
    assert _count_data_tiles(fig) == 4
    plt.close(fig)


def test_tile_four_files_independent_colorbars(tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    files = []
    for i in range(4):
        f = tmp_path / f"Iqxqy_{i}.dat"
        _write_iqxqy(f)
        files.append(f)
    fig = tile.make_tile_figure(files, colorbar_mode="independent")
    # 4 data subplots, each with its own colorbar.
    assert _count_data_tiles(fig) == 4
    plt.close(fig)


def test_tile_five_files_wraps_into_two_rows(tmp_path: Path) -> None:
    """5 files with TILE_NCOLS=4 → 2 rows; spare cells in row 2 are off."""
    import matplotlib.pyplot as plt

    files = []
    for i in range(5):
        f = tmp_path / f"Iqxqy_{i}.dat"
        _write_iqxqy(f)
        files.append(f)
    fig = tile.make_tile_figure(files)
    assert _count_data_tiles(fig) == 5
    plt.close(fig)


def test_tile_natural_sort_orders_files(tmp_path: Path) -> None:
    """run2 must come before run10 when files are sorted naturally."""
    files = [
        tmp_path / f"run{i}_Iqxqy.dat"
        for i in (10, 1, 2)  # alphabetical would put run10 between run1 and run2
    ]
    for f in files:
        _write_iqxqy(f)
    sorted_paths = sorted(files, key=tile._natural_key)
    assert [p.name for p in sorted_paths] == [
        "run1_Iqxqy.dat",
        "run2_Iqxqy.dat",
        "run10_Iqxqy.dat",
    ]


def test_tile_rejects_empty_paths() -> None:
    with pytest.raises(ValueError, match="at least one file"):
        tile.make_tile_figure([])


def _min_tile_size(fig) -> tuple[float, float]:  # type: ignore[no-untyped-def]
    """Smallest square-tile width/height as a fraction of the figure."""
    fig.canvas.draw()
    squares = [ax for ax in fig.axes if ax.get_box_aspect() == 1]
    w = min(ax.get_position().width for ax in squares)
    h = min(ax.get_position().height for ax in squares)
    return w, h


def _tile_overlay_texts(fig) -> list[str]:  # type: ignore[no-untyped-def]
    """Text drawn inside the square data tiles (filenames or indices)."""
    return [t.get_text() for ax in fig.axes if ax.get_box_aspect() == 1 for t in ax.texts]


def test_short_names_are_shown_in_tiles_without_a_legend(tmp_path: Path) -> None:
    """Names that fit the tile are drawn inside it; no name-key legend."""
    import matplotlib.pyplot as plt

    files = []
    for i in range(6):
        f = tmp_path / f"run{i}_Iqxqy.dat"
        _write_iqxqy(f)
        files.append(f)
    fig = tile.make_tile_figure(files)
    overlays = _tile_overlay_texts(fig)
    assert "run0_Iqxqy.dat" in overlays  # full filename, in-tile
    assert fig.legends == []  # no legend needed
    plt.close(fig)


def test_clean_common_suffix_trims_to_separator() -> None:
    """The hoisted suffix is a whole-token tail, never a mid-token cut."""
    names = [f"EQSANS_scan_run{i:03d}_Iqxqy.dat" for i in range(6)]
    assert tile._clean_common_suffix(names) == "_Iqxqy.dat"
    # No separator in the shared tail → nothing worth hoisting.
    assert tile._clean_common_suffix(["aabc", "zzbc"]) == ""
    # Single file has no "shared" suffix.
    assert tile._clean_common_suffix(["only_Iqxqy.dat"]) == ""


def test_long_names_hoist_shared_suffix_to_footer(tmp_path: Path) -> None:
    """Names past the length cap drop their shared suffix; it moves to a footer."""
    import matplotlib.pyplot as plt

    files = []
    for i in range(6):
        # >60 chars so the suffix hoist triggers.
        name = f"EQSANS_2024B_experiment_porasil_temperature_scan_run{i:03d}_Iqxqy.dat"
        assert len(name) > tile.SUFFIX_HOIST_OVER
        f = tmp_path / name
        _write_iqxqy(f)
        files.append(f)

    fig = tile.make_tile_figure(files)
    overlays = _tile_overlay_texts(fig)
    # In-tile labels have the shared tail stripped ...
    assert all(t.endswith("run000") or "_run" in t for t in overlays[:1])
    assert not any(t.endswith("_Iqxqy.dat") for t in overlays)
    # ... and it appears once in a footer note.
    assert len(fig.legends) == 1
    footer = [t.get_text() for t in fig.legends[0].get_texts()]
    assert footer == ["shared suffix:  _Iqxqy.dat"]
    plt.close(fig)


@pytest.mark.skipif(
    not tile.NUMBERED_FALLBACK,
    reason="numbered-tile fallback is temporarily disabled (NUMBERED_FALLBACK=False)",
)
def test_long_names_switch_to_numbered_tiles_with_a_name_key(tmp_path: Path) -> None:
    """When names overflow the tile, tiles are numbered and a legend maps them.

    The full filenames must appear verbatim in the legend — never
    truncated — and the in-tile overlays become the running indices.
    """
    import matplotlib.pyplot as plt

    files = []
    long_names = []
    for i in range(6):
        name = f"EQSANS_2024B_experiment_porasil_temperature_scan_run{i:03d}_Iqxqy.dat"
        f = tmp_path / name
        _write_iqxqy(f)
        files.append(f)
        long_names.append(name)

    fig = tile.make_tile_figure(files)
    overlays = _tile_overlay_texts(fig)
    assert overlays == ["1", "2", "3", "4", "5", "6"]

    assert len(fig.legends) == 1
    legend_texts = [t.get_text() for t in fig.legends[0].get_texts()]
    for idx, name in enumerate(long_names, start=1):
        assert f"{idx}: {name}" in legend_texts  # full name, not truncated
    plt.close(fig)


def test_tile_size_is_independent_of_filename_length(tmp_path: Path) -> None:
    """A long filename must not shrink the tiles (regression).

    Panel labels are excluded from constrained_layout; otherwise a long
    centred name overflows the square tile and the layout engine
    collapses every panel. Tiles must come out the same size whether
    names are short (shown in-tile) or long (numbered + legend).
    """
    import matplotlib.pyplot as plt

    short, long = [], []
    for i in range(6):
        s = tmp_path / f"r{i}.dat"
        _write_iqxqy(s)
        short.append(s)
        long_f = tmp_path / f"EQSANS_2024B_experiment_porasil_scan_run{i:03d}_Iqxqy.dat"
        _write_iqxqy(long_f)
        long.append(long_f)

    fig_s = tile.make_tile_figure(short)
    fig_l = tile.make_tile_figure(long)
    sw, sh = _min_tile_size(fig_s)
    lw, lh = _min_tile_size(fig_l)
    plt.close(fig_s)
    plt.close(fig_l)
    assert lw == pytest.approx(sw, rel=0.02)
    assert lh == pytest.approx(sh, rel=0.02)


# ---------------------------------------------------------------------------
# Detector kind (Phase 5 detect.py — the iqxqy branch)
# ---------------------------------------------------------------------------


def test_detect_kind_iqxqy_for_real_grid(tmp_path: Path) -> None:
    """A real 4-col regular Iqxqy grid (repeating qx) is detected as iqxqy."""
    from sansdir.plot import detect

    f = tmp_path / "Iqxqy.dat"
    _write_iqxqy(f, nx=5, ny=4)
    d = detect.detect_kind(f)
    assert d.kind == detect.KIND_IQXQY


def test_plot_iqxqy_command_exposes_colorbar_mode(tmp_path: Path) -> None:
    """The toggle the report documents must be a real, discoverable parameter."""
    from sansdir.commands.builtins import build_default_registry
    from tests.test_phase1_commands import FakeApp, FakePanel

    app = FakeApp(left=FakePanel(cwd=tmp_path), right=FakePanel(cwd=tmp_path))
    cmd = build_default_registry(app=app).get("plot.iqxqy")
    param = {p.name: p for p in cmd.params}["colorbar_mode"]
    assert param.choices == ["shared", "independent"]
    assert not param.required


# ---------------------------------------------------------------------------
# `:plot.iqxqy colorbar_mode=…` from the command line (user report 2026-11-12)
# ---------------------------------------------------------------------------


def _tui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, list[tuple]]:
    from sansdir.app import SansdirApp
    from sansdir.core.history import CommandHistory

    data = tmp_path / "data"
    data.mkdir()
    for t in (20, 30, 40):
        _write_iqxqy(data / f"S_{t}C_conf1_Iqxqy.dat")
    (data / "notes.txt").write_text("x")
    other = tmp_path / "other"
    other.mkdir()
    opened: list[tuple] = []

    def fake_spawn(kind, paths, **kwargs):  # type: ignore[no-untyped-def]
        opened.append((kind, [Path(p).name for p in paths], kwargs.get("colorbar_mode")))
        return backend.BackendInfo(name="QtAgg", interactive=True, reason="test")

    monkeypatch.setattr(backend, "has_display", lambda: True)
    monkeypatch.setattr(backend, "spawn_plot_window", fake_spawn)
    monkeypatch.chdir(other)  # the TUI's own cwd is NOT where the files are
    app = SansdirApp(
        start_path=data,
        right_path=other,
        history=CommandHistory(path=tmp_path / "hist", load=False),
    )
    return app, opened


async def _type(pilot, text: str) -> None:  # type: ignore[no-untyped-def]
    await pilot.press(":")
    for ch in text:
        await pilot.press(ch if ch != " " else "space")
    await pilot.press("enter")
    await pilot.pause(0.2)


async def test_colorbar_mode_applies_to_the_tagged_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, opened = _tui(tmp_path, monkeypatch)
    async with app.run_test() as pilot:  # type: ignore[attr-defined]
        await pilot.pause()
        app.active_panel.tag_glob("*Iqxqy.dat")  # type: ignore[attr-defined]
        await _type(pilot, "plot.iqxqy colorbar_mode=independent")
        await pilot.press("q")
    assert opened == [
        (
            "iqxqy",
            ["S_20C_conf1_Iqxqy.dat", "S_30C_conf1_Iqxqy.dat", "S_40C_conf1_Iqxqy.dat"],
            "independent",
        )
    ]


async def test_typed_glob_is_relative_to_the_active_pane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, opened = _tui(tmp_path, monkeypatch)
    async with app.run_test() as pilot:  # type: ignore[attr-defined]
        await pilot.pause()
        await _type(pilot, "plot.iqxqy S_*0C_conf1_Iqxqy.dat colorbar_mode=shared")
        await pilot.press("q")
    assert len(opened) == 1 and len(opened[0][1]) == 3 and opened[0][2] == "shared"


async def test_nothing_to_plot_says_what_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, opened = _tui(tmp_path, monkeypatch)
    notes: list[str] = []
    async with app.run_test() as pilot:  # type: ignore[attr-defined]
        await pilot.pause()
        original = app.notify_user  # type: ignore[attr-defined]

        def record(message: str, **kwargs):  # type: ignore[no-untyped-def]
            notes.append(message)
            return original(message, **kwargs)

        app.notify_user = record  # type: ignore[attr-defined]
        app.active_panel.move_cursor(row=0)  # type: ignore[attr-defined]  # ".."
        await _type(pilot, "plot.iqxqy colorbar_mode=independent")
        await pilot.press("q")
    assert opened == []
    assert any("tag the I(qx,qy) files" in n for n in notes)
