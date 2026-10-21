"""Figure / data / TOF-stack export (Phase 9.10.4; Qt-free, matplotlib Agg)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from sansdir.viewer.colorscale import ScaleState
from sansdir.viewer.cube import TofCube, load_cube
from sansdir.viewer.export import (
    ExportCancelledError,
    ImageInfo,
    export_data,
    export_figure,
    export_stack_npy,
    export_stack_pngs,
    figure_for,
    stack_ranges,
    tof_stack,
)
from tests.viewer.test_cube import _events, _write_raw

MAGIC = {".png": b"\x89PNG", ".pdf": b"%PDF", ".svg": b"<?xml"}


@pytest.fixture(scope="module")
def cube(tmp_path_factory: pytest.TempPathFactory) -> TofCube:
    raw = _write_raw(tmp_path_factory.mktemp("raw") / "EQSANS_4242.nxs.h5", _events(per_bank=4000))
    return load_cube(raw, nbins=50)


@pytest.fixture
def mask() -> np.ndarray:
    m = np.zeros((256, 192), dtype=bool)
    m[:10, :] = True
    return m


def _scale(image: np.ndarray, *, log: bool = True) -> ScaleState:
    state = ScaleState(log=log)
    state.limits_for(image)
    return state


def test_image_info_describes_the_slice(cube: TofCube) -> None:
    info = ImageInfo.for_cube(cube, 10, 20)
    assert info.label == "EQSANS run 4242 — synthetic run"
    assert info.tof_text.startswith("TOF ") and f"bins 10-19 of {cube.nbins}" in info.tof_text
    assert info.tof_us == (pytest.approx(cube.tof_edges[10]), pytest.approx(cube.tof_edges[20]))
    assert ImageInfo.for_cube(cube, 0, cube.nbins).tof_text.startswith("all TOF")


def test_figure_has_title_axes_and_count_colour_bar(cube: TofCube, mask: np.ndarray) -> None:
    image = cube.image(10, 20)
    fig = figure_for(image, ImageInfo.for_cube(cube, 10, 20), _scale(image), mask=mask)
    ax, bar_ax = fig.axes
    assert "EQSANS run 4242" in ax.get_title() and "bins 10-19" in ax.get_title()
    assert ax.get_xlabel().startswith("x") and bar_ax.get_ylabel() == "counts per pixel"
    assert any(t.get_text() == "grey: masked" for t in ax.texts)
    fig.canvas.draw()
    labels = [t.get_text() for t in bar_ax.get_yticklabels() if t.get_text()]
    assert labels and not any("times" in t or "^" in t for t in labels)  # 1, 10, 1k…


@pytest.mark.parametrize("suffix", [".png", ".pdf", ".svg"])
def test_export_figure_formats(cube: TofCube, tmp_path: Path, suffix: str) -> None:
    image = cube.image()
    out = export_figure(
        tmp_path / f"f{suffix}", image, ImageInfo.for_cube(cube, 0, 50), _scale(image)
    )
    assert out.read_bytes().startswith(MAGIC[suffix])


def test_linear_and_preview_figures(cube: TofCube, tmp_path: Path) -> None:
    image = cube.image()
    info = ImageInfo(source=cube.path, tof_text="all TOF", preview=True)
    fig = figure_for(image, info, _scale(image, log=False))
    assert "preview estimate" in fig.axes[0].get_title()
    assert fig.axes[0].get_title().startswith("EQSANS_4242.nxs.h5")  # no run number


def test_export_figure_rejects_other_formats(cube: TofCube, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="figure"):
        export_figure(tmp_path / "f.jpg", cube.image(), ImageInfo(source=cube.path), ScaleState())


def test_export_data_npy_with_sidecar(cube: TofCube, tmp_path: Path, mask: np.ndarray) -> None:
    image = cube.image(5, 9)
    out = export_data(tmp_path / "img.npy", image, ImageInfo.for_cube(cube, 5, 9), mask=mask)
    data = np.load(out)
    assert data.shape == (256, 192) and np.isnan(data[:10]).all()
    np.testing.assert_array_equal(data[10:], image[10:])
    meta = json.loads(out.with_suffix(".json").read_text())
    assert meta["mask_applied"] and meta["masked_pixels"] == 10 * 192
    assert meta["run_number"] == "4242" and meta["shape"] == [256, 192]


def test_export_data_txt_with_header(cube: TofCube, tmp_path: Path) -> None:
    image = cube.image(5, 9)
    out = export_data(tmp_path / "img.txt", image, ImageInfo.for_cube(cube, 5, 9))
    header = [line for line in out.read_text().splitlines() if line.startswith("#")]
    text = "\n".join(header)
    assert "run: 4242" in text and "mask applied: no" in text and "row 0 = bottom" in text
    np.testing.assert_array_equal(np.loadtxt(out), image)


def test_export_data_rejects_other_formats(cube: TofCube, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="image data"):
        export_data(tmp_path / "x.csv", cube.image(), ImageInfo(source=cube.path))


# -- TOF stacks ----------------------------------------------------------------------


def test_stack_ranges_cover_the_run() -> None:
    assert stack_ranges(10, 4) == [(0, 4), (4, 8), (8, 10)]
    assert stack_ranges(10, 20) == [(0, 10)]
    assert stack_ranges(3, 0) == [(0, 1), (1, 2), (2, 3)]


def test_tof_stack_slices_add_up_to_the_total(cube: TofCube, mask: np.ndarray) -> None:
    stack, ranges = tof_stack(cube, 7)
    assert stack.shape == (len(ranges), 256, 192) and stack.dtype == np.float32
    np.testing.assert_allclose(stack.sum(axis=0), cube.image())
    blanked, _ = tof_stack(cube, 7, mask=mask)
    assert np.isnan(blanked[:, :10]).all()


def test_tof_stack_can_be_cancelled(cube: TofCube) -> None:
    seen: list[int] = []

    def progress(done: int, total: int) -> bool:
        seen.append(done)
        return done < 2

    with pytest.raises(ExportCancelledError):
        tof_stack(cube, 5, progress=progress)
    assert seen == [0, 1, 2]


def test_tof_stack_needs_tof(cube: TofCube) -> None:
    flat = TofCube(cube.path, "", "", "processed", cube.cum[[0, -1]], None)
    with pytest.raises(ValueError, match="no TOF"):
        tof_stack(flat, 5)


def test_export_stack_npy(cube: TofCube, tmp_path: Path) -> None:
    out = export_stack_npy(tmp_path / "stack.npy", cube, 20)
    assert np.load(out).shape == (3, 256, 192)
    meta = json.loads(out.with_suffix(".json").read_text())
    assert meta["width_bins"] == 20 and [s["bins"] for s in meta["slices"]] == [
        [0, 20],
        [20, 40],
        [40, cube.nbins],  # the last slice is what is left
    ]
    assert meta["slices"][0]["tof_us"][1] == pytest.approx(cube.tof_edges[20])


def test_export_stack_pngs(cube: TofCube, tmp_path: Path) -> None:
    scale = _scale(cube.image())
    before = dict(scale.__dict__)
    paths = export_stack_pngs(tmp_path / "frames", cube, 20, scale, prefix="run4242")
    assert [p.name for p in paths] == [f"run4242_tof{k:03d}.png" for k in range(3)]
    assert all(p.read_bytes().startswith(MAGIC[".png"]) for p in paths)
    assert scale.__dict__ == before  # the viewer's own scale is not touched
