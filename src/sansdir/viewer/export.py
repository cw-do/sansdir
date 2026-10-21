"""Exporting what the viewer shows (Qt-free; figures through matplotlib ``Agg``).

* :func:`export_figure` — a publication figure (PNG / PDF / SVG): real axes,
  a colour bar in counts, run number, title and TOF range. Rendered
  off-screen with ``matplotlib.figure.Figure`` + the Agg canvas, never
  pyplot, so it cannot fight the viewer's Qt event loop.
* :func:`export_data` — the image as ``.npy`` (+ ``.json`` sidecar) or
  ``.txt`` with a ``#`` header: 256 rows (y, pixel along the tube, row 0 =
  bottom = Mantid ``pixel1``) x 192 columns (x, tube column).
* :func:`export_stack_npy` / :func:`export_stack_pngs` — every TOF slice at
  one width: one ``(nslice, 256, 192)`` array, or numbered figures.

Masked pixels can be blanked (NaN in data, grey in figures); every file
records whether they were. matplotlib is imported inside the functions, so
importing this module costs nothing at viewer start-up.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from sansdir.viewer import tofrange
from sansdir.viewer.colorscale import LOG_FLOOR, ScaleState, count_label
from sansdir.viewer.geometry import CELL_ASPECT, NCOLS, NROWS

if TYPE_CHECKING:
    from matplotlib.figure import Figure
    from matplotlib.ticker import Formatter

    from sansdir.viewer.cube import TofCube

FIGURE_FORMATS: tuple[str, ...] = (".png", ".pdf", ".svg")
DATA_FORMATS: tuple[str, ...] = (".npy", ".txt")
FIGURE_DPI = 200
MASKED_GREY = "#9a9a9a"
LAYOUT = (
    "256 rows = y, pixel along the tube (row 0 = bottom = Mantid pixel1); "
    "192 columns = x, tube column (sansdir.viewer.geometry maps cells to detector IDs)"
)

# progress(done, total) → True to keep going, False to cancel
StackProgress = Callable[[int, int], bool]


class ExportCancelledError(RuntimeError):
    """The stack export was cancelled part-way."""


@dataclass(frozen=True)
class ImageInfo:
    """Where an image came from — goes into titles, headers and sidecars."""

    source: Path
    run_number: str = ""
    title: str = ""
    tof_text: str = ""  # tofrange.describe(...)
    tof_us: tuple[float, float] | None = None  # TOF range in µs, None without TOF
    preview: bool = False  # counts are a scaled estimate

    @classmethod
    def for_cube(cls, cube: TofCube, a: int, b: int) -> ImageInfo:
        edges = cube.tof_edges
        a, b = tofrange.clamp(a, b, cube.nbins) if edges is not None else (0, 1)
        return cls(
            source=cube.path,
            run_number=cube.run_number,
            title=cube.title,
            tof_text=tofrange.describe(edges, a, b),
            tof_us=None if edges is None else (float(edges[a]), float(edges[b])),
            preview=cube.is_preview,
        )

    @property
    def label(self) -> str:
        """``EQSANS run 176669 — S-PMMA 1.3m 2.5a`` (or the file name)."""
        head = f"EQSANS run {self.run_number}" if self.run_number else self.source.name
        return f"{head} — {self.title}" if self.title else head

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "run_number": self.run_number,
            "title": self.title,
            "tof": self.tof_text,
            "tof_us": list(self.tof_us) if self.tof_us is not None else None,
            "preview_estimate": self.preview,
        }


def blank_masked(image: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    """Float copy of ``image`` with masked cells set to NaN."""
    out: np.ndarray = np.asarray(image, dtype=np.float64).copy()
    if mask is not None:
        out[mask.astype(bool)] = np.nan
    return out


# -- figures -------------------------------------------------------------------


def figure_for(
    image: np.ndarray,
    info: ImageInfo,
    scale: ScaleState,
    *,
    mask: np.ndarray | None = None,
) -> Figure:
    """The publication figure (not yet saved). ``mask`` cells are drawn grey."""
    from matplotlib import colormaps
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.colors import LogNorm, Normalize
    from matplotlib.figure import Figure

    data = np.ma.masked_invalid(blank_masked(image, mask))
    cmap = colormaps[scale.cmap].copy()
    cmap.set_bad(MASKED_GREY if mask is not None and mask.any() else "black")
    if scale.log:
        vmin = max(scale.vmin, LOG_FLOOR)
        norm: Normalize = LogNorm(vmin=vmin, vmax=max(scale.vmax, vmin * 10))
        data = np.ma.masked_less_equal(data, 0)  # zero counts: no colour in log
    else:
        norm = Normalize(vmin=scale.vmin, vmax=scale.vmax)

    fig = Figure(figsize=(6.4, 6.0), layout="constrained")
    FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    shown = ax.imshow(
        data,
        origin="lower",
        extent=(0, NCOLS, 0, NROWS),
        aspect=1.0 / CELL_ASPECT,  # cells are 5.5 mm wide, 4.09 mm tall
        cmap=cmap,
        norm=norm,
        interpolation="nearest",
    )
    ax.set_xlabel("x  (tube column)")
    ax.set_ylabel("y  (pixel along tube)")
    lines = [info.label]
    if info.tof_text:
        lines.append(info.tof_text + ("  ·  preview estimate" if info.preview else ""))
    ax.set_title("\n".join(lines), fontsize=10)
    bar = fig.colorbar(shown, ax=ax, shrink=0.9)
    bar.set_label("counts per pixel")
    if scale.log:  # 1, 10, 1k... as on the viewer's colour bar, not 6x10^3
        bar.ax.yaxis.set_major_formatter(_count_log_formatter())
        bar.ax.yaxis.set_minor_formatter(_count_log_formatter())
    if mask is not None and mask.any():
        ax.text(
            1.0, -0.09, "grey: masked", transform=ax.transAxes, ha="right", fontsize=8,
            color="#555",
        )  # fmt: skip
    return fig


def _count_log_formatter() -> Formatter:
    """matplotlib's log formatter (it picks which ticks get a label), in counts."""
    from matplotlib.ticker import LogFormatterSciNotation

    class CountLogFormatter(LogFormatterSciNotation):
        def __call__(self, x: float, pos: int | None = None) -> str:
            return count_label(x) if super().__call__(x, pos) else ""

    return CountLogFormatter(labelOnlyBase=False)


def export_figure(
    path: Path,
    image: np.ndarray,
    info: ImageInfo,
    scale: ScaleState,
    *,
    mask: np.ndarray | None = None,
) -> Path:
    """Save the figure; the format follows the suffix (``.png`` / ``.pdf`` / ``.svg``)."""
    if path.suffix.lower() not in FIGURE_FORMATS:
        raise ValueError(f"{path.name}: save a figure as {', '.join(FIGURE_FORMATS)}")
    fig = figure_for(image, info, scale, mask=mask)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=FIGURE_DPI, metadata=_figure_metadata(path, info))
    return path


def _figure_metadata(path: Path, info: ImageInfo) -> dict[str, str]:
    if path.suffix.lower() == ".png":
        return {"Title": info.label, "Description": info.tof_text, "Software": "sansdir"}
    if path.suffix.lower() == ".pdf":
        return {"Title": info.label, "Subject": info.tof_text, "Creator": "sansdir"}
    return {"Title": info.label}


# -- image data ----------------------------------------------------------------------


def export_data(
    path: Path, image: np.ndarray, info: ImageInfo, *, mask: np.ndarray | None = None
) -> Path:
    """``.npy`` (+ ``<name>.json``) or ``.txt`` with a header. ``mask`` cells → NaN."""
    suffix = path.suffix.lower()
    if suffix not in DATA_FORMATS:
        raise ValueError(f"{path.name}: save image data as {', '.join(DATA_FORMATS)}")
    data = blank_masked(image, mask)
    meta = _data_meta(info, mask)
    path.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".npy":
        np.save(path, data)
        path.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    else:
        header = "\n".join(f"{k}: {v}" for k, v in _header_lines(meta))
        np.savetxt(path, data, fmt="%.8g", header=header)
    return path


def _data_meta(info: ImageInfo, mask: np.ndarray | None) -> dict[str, Any]:
    n_masked = int(mask.sum()) if mask is not None else 0
    return {
        "format": "sansdir viewer detector image",
        **info.as_dict(),
        "units": "counts per pixel",
        "shape": [NROWS, NCOLS],
        "layout": LAYOUT,
        "mask_applied": bool(n_masked),
        "masked_pixels": n_masked,
        "masked_value": "nan" if n_masked else None,
    }


def _header_lines(meta: dict[str, Any]) -> list[tuple[str, Any]]:
    applied = f"yes, {meta['masked_pixels']} pixels set to nan" if meta["mask_applied"] else "no"
    return [
        ("EQSANS detector image", "sansdir viewer"),
        ("run", meta["run_number"] or "-"),
        ("title", meta["title"] or "-"),
        ("source", meta["source"]),
        ("range", meta["tof"] or "-"),
        ("units", "counts per pixel" + (" (preview estimate)" if meta["preview_estimate"] else "")),
        ("mask applied", applied),
        ("layout", meta["layout"]),
    ]


# -- TOF stacks -------------------------------------------------------------------------


def stack_ranges(nbins: int, width: int) -> list[tuple[int, int]]:
    """Consecutive ``[a, b)`` bin ranges of ``width`` covering the run (last may be shorter)."""
    width = max(1, int(width))
    return [(a, min(a + width, nbins)) for a in range(0, nbins, width)]


def tof_stack(
    cube: TofCube,
    width: int,
    *,
    mask: np.ndarray | None = None,
    progress: StackProgress | None = None,
) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """``(nslice, 256, 192)`` float32 counts, one slice per :func:`stack_ranges` range."""
    if not cube.has_tof:
        raise ValueError("this file has no TOF: there is no stack to export")
    ranges = stack_ranges(cube.nbins, width)
    stack = np.empty((len(ranges), NROWS, NCOLS), dtype=np.float32)
    for k, (a, b) in enumerate(ranges):
        if progress is not None and not progress(k, len(ranges)):
            raise ExportCancelledError("cancelled")
        stack[k] = blank_masked(cube.image(a, b), mask)
    return stack, ranges


def export_stack_npy(
    path: Path,
    cube: TofCube,
    width: int,
    *,
    mask: np.ndarray | None = None,
    progress: StackProgress | None = None,
) -> Path:
    """One ``.npy`` with every slice + a ``.json`` listing each slice's TOF range."""
    if path.suffix.lower() != ".npy":
        raise ValueError(f"{path.name}: a TOF stack is saved as .npy")
    stack, ranges = tof_stack(cube, width, mask=mask, progress=progress)
    edges = cube.tof_edges
    assert edges is not None
    meta = _data_meta(ImageInfo.for_cube(cube, 0, cube.nbins), mask)
    meta.update(
        format="sansdir viewer TOF stack",
        shape=list(stack.shape),
        width_bins=int(width),
        slices=[{"bins": [a, b], "tof_us": [float(edges[a]), float(edges[b])]} for a, b in ranges],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, stack)
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


def export_stack_pngs(
    directory: Path,
    cube: TofCube,
    width: int,
    scale: ScaleState,
    *,
    mask: np.ndarray | None = None,
    prefix: str | None = None,
    progress: StackProgress | None = None,
) -> list[Path]:
    """One figure per slice: ``<prefix>_000.png``… With ``scale.locked`` off each
    slice is auto-scaled, as in the viewer; locked, they share Min/Max."""
    if not cube.has_tof:
        raise ValueError("this file has no TOF: there is no stack to export")
    ranges = stack_ranges(cube.nbins, width)
    stem = prefix or (f"run{cube.run_number}" if cube.run_number else cube.path.stem)
    directory.mkdir(parents=True, exist_ok=True)
    state = ScaleState(**{**scale.__dict__})
    digits = max(3, len(str(len(ranges) - 1)))
    paths: list[Path] = []
    for k, (a, b) in enumerate(ranges):
        if progress is not None and not progress(k, len(ranges)):
            raise ExportCancelledError("cancelled")
        image = cube.image(a, b)
        state.limits_for(image, mask)
        out = directory / f"{stem}_tof{k:0{digits}d}.png"
        export_figure(out, image, ImageInfo.for_cube(cube, a, b), state, mask=mask)
        paths.append(out)
    return paths


__all__ = [
    "DATA_FORMATS",
    "FIGURE_FORMATS",
    "ExportCancelledError",
    "ImageInfo",
    "blank_masked",
    "export_data",
    "export_figure",
    "export_stack_npy",
    "export_stack_pngs",
    "figure_for",
    "stack_ranges",
    "tof_stack",
]
