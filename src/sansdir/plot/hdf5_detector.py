"""Detector-counts heatmaps for EQSANS NeXus files.

Two loaders, picked automatically by inspecting the file's structure:

* :func:`load_eqsans_raw` — for raw event-mode files (the default DAS
  output ``EQSANS_<run>.nxs.h5``). Mirrors
  ``/SNS/EQSANS/shared/script/eqsanstools/EQSANS_raw_2D.py``: bincount
  the ``event_id`` of each ``/entry/bank<N>_events`` group into a
  ``256x192`` array, then reorder tubes [0,4,1,5,2,6,3,7] to match the
  physical detector layout.

* :func:`load_processed` — for files written by Mantid / drtsans
  (``mantid_workspace_1/workspace/values``). Same final shape, no
  reorder needed.

Both produce one ``(256, 192)`` array — pixel rows x tube columns —
which we render with ``imshow`` (LogNorm, viridis, "Tube" / "Pixel"
axis labels). This is a *single* detector image, not a per-bank tile,
because the 48 banks are physically one detector.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from sansdir.hdf.reader import HdfError, open_nexus

if TYPE_CHECKING:
    from matplotlib.figure import Figure


# EQSANS detector geometry — 48 banks of 8 tubes x 256 pixels each, in
# 24 columns of 8 tubes, total 192 tubes x 256 pixels per tube.
EQSANS_NPIXELS_PER_TUBE: int = 256
EQSANS_NTUBES: int = 192
EQSANS_NPIXELS_TOTAL: int = EQSANS_NPIXELS_PER_TUBE * EQSANS_NTUBES
EQSANS_NBANKS: int = 48
EQSANS_TUBE_REORDER: tuple[int, ...] = (0, 4, 1, 5, 2, 6, 3, 7)


@dataclass(frozen=True, slots=True)
class DetectorImage:
    """Final 2D image we hand to matplotlib."""

    image: np.ndarray  # shape (npixels, ntubes), rows = pixel index, cols = tube
    run_number: str
    title: str
    source: str  # "raw" | "processed" | "fallback"


# ---------------------------------------------------------------------------
# Raw loader (event mode) — mirrors EQSANS_raw_2D.py
# ---------------------------------------------------------------------------


def load_eqsans_raw(path: Path) -> DetectorImage:
    """Build the ``(256, 192)`` detector image from raw event-mode NeXus.

    Replicates the logic in
    ``/SNS/EQSANS/shared/script/eqsanstools/EQSANS_raw_2D.py``.
    """
    bc = np.zeros(EQSANS_NPIXELS_TOTAL, dtype=np.int64)
    with open_nexus(path) as fh:
        if "entry/bank1_events" not in fh:
            raise HdfError(f"{path}: no /entry/bank<N>_events groups (not raw EQSANS)")
        run_number = _scalar(fh, "entry/run_number")
        title = _scalar(fh, "entry/title")
        for b in range(1, EQSANS_NBANKS + 1):
            key = f"entry/bank{b}_events/event_id"
            if key not in fh:
                continue
            ids = np.asarray(fh[key][()], dtype=np.int64)
            if ids.size:
                bc += np.bincount(ids, minlength=EQSANS_NPIXELS_TOTAL)[:EQSANS_NPIXELS_TOTAL]
    image = _reorder_tubes(bc)
    return DetectorImage(image=image, run_number=run_number, title=title, source="raw")


def _reorder_tubes(bincounts: np.ndarray) -> np.ndarray:
    """Map a flat 49152-pixel bincount to a ``(256, 192)`` detector image.

    The EQSANS detector layout interleaves tubes [0,4,1,5,2,6,3,7]
    within each 8-tube bank — without this reorder the image is sliced
    incorrectly. Math taken verbatim from EQSANS_raw_2D.py.
    """
    if bincounts.size != EQSANS_NPIXELS_TOTAL:
        raise ValueError(
            f"_reorder_tubes: expected {EQSANS_NPIXELS_TOTAL} cells, got {bincounts.size}"
        )
    data = bincounts.reshape(-1, 8, EQSANS_NPIXELS_PER_TUBE).T  # (256, 8, 24)
    reordered = data[:, list(EQSANS_TUBE_REORDER), :]  # interleave tubes
    final = reordered.transpose().reshape(-1, EQSANS_NPIXELS_PER_TUBE)  # (192, 256)
    return final.T  # (256, 192)


# ---------------------------------------------------------------------------
# Processed loader — Mantid / drtsans output
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Mantid-backed loader — uses the EQSANS IDF for correct geometry
# ---------------------------------------------------------------------------


# Common locations Mantid is installed at on the ORNL analysis cluster.
# We probe these in order before subprocessing the renderer; users can
# override via ``$SANSDIR_MANTID_PYTHON``.
_DEFAULT_MANTID_PYTHONS: tuple[str, ...] = (
    "/usr/local/pixi/mantid/.pixi/envs/default/bin/python",
    "/opt/Mantid/bin/python",
)


def _mantid_python() -> str | None:
    """Return a Mantid python interpreter path, or ``None`` if absent."""
    import os
    import shutil

    env = os.environ.get("SANSDIR_MANTID_PYTHON")
    if env and Path(env).exists():
        return env
    for cand in _DEFAULT_MANTID_PYTHONS:
        if Path(cand).exists():
            return cand
    # Last resort: `mantidpython` on PATH (older Mantid installs).
    found = shutil.which("mantidpython")
    return found


def load_via_mantid(path: Path, *, mantid_python: str | None = None) -> DetectorImage:
    """Load a NeXus / processed file by subprocessing the EQSANS Mantid env.

    Mantid carries the official EQSANS IDF, so it knows the
    spectrum → physical-position mapping for every output flavour
    (Workspace2D, EventWorkspace, drtsans-reduced, …). We bin those
    physical positions onto the canonical 256-pixel x 192-tube grid
    (with the staggered front/back tubes collapsed by sorting their
    horizontal positions), so the rendered image matches what the
    user would see in MantidWorkbench's instrument view.

    Raises :class:`HdfError` if no Mantid interpreter is reachable
    (the caller falls back to :func:`load_processed`).
    """
    import subprocess
    import tempfile

    py = mantid_python or _mantid_python()
    if py is None:
        raise HdfError(
            "Mantid python not found; set $SANSDIR_MANTID_PYTHON or "
            "install Mantid at one of: " + ", ".join(_DEFAULT_MANTID_PYTHONS)
        )
    # Resolve the renderer's path relative to this module so we don't
    # rely on the Mantid env having sansdir installed.
    renderer = Path(__file__).with_name("_mantid_render.py")
    with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as tmp:
        out_npz = Path(tmp.name)
    try:
        proc = subprocess.run(
            [py, str(renderer), str(path), str(out_npz)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
            raise HdfError(
                f"{path}: Mantid load failed (exit {proc.returncode})\n"
                + "\n".join(tail)
            )
        data = np.load(out_npz, allow_pickle=False)
        image = np.asarray(data["image"])
        title = str(data["title"])
    finally:
        import contextlib

        with contextlib.suppress(OSError):
            out_npz.unlink()
    return DetectorImage(image=image, run_number="", title=title, source="processed")


def load_processed(path: Path) -> DetectorImage:
    """Pure-numpy/h5py loader for Mantid / drtsans processed files.

    Two payload kinds, picked from the file structure:

    * Histogram workspace at ``mantid_workspace_1/workspace/values``
      — supports ``(49152,)``, ``(49152, n_bins)`` (drtsans
      wavelength-banded output, summed across bins), and the
      transposed ``(n_bins, 49152)`` layout.
    * Event workspace at
      ``mantid_workspace_1/event_workspace/indices`` — masks /
      event-mode artefacts; per-spectrum count = ``diff(indices)``.

    Once we have one number per spectrum, we apply the same
    ``[0, 4, 1, 5, 2, 6, 3, 7]`` tube-reorder that
    :func:`load_eqsans_raw` uses for raw event-mode files. This is
    the EQSANS detector-ID encoding: 24 bank-pairs x 8 staggered
    tubes x 256 pixels, where the 8 tubes alternate physical
    front/back. Both raw event_ids and Mantid spectrum indices use
    this encoding (Mantid loads the same IDF), so the same recipe
    matches MantidWorkbench's instrument view.
    """
    with open_nexus(path) as fh:
        title = _scalar(fh, "mantid_workspace_1/title", default="")
        if "mantid_workspace_1/workspace/values" in fh:
            raw = np.asarray(fh["mantid_workspace_1/workspace/values"][()])
            counts = _reduce_to_detector_pixels(raw)
            if counts is None:
                raise HdfError(
                    f"{path}: workspace/values shape {raw.shape} "
                    f"({raw.size} elements) can't be reduced to "
                    f"{EQSANS_NPIXELS_TOTAL} detector pixels"
                )
        elif "mantid_workspace_1/event_workspace/indices" in fh:
            indices = np.asarray(
                fh["mantid_workspace_1/event_workspace/indices"][()],
                dtype=np.int64,
            )
            if indices.size != EQSANS_NPIXELS_TOTAL + 1:
                raise HdfError(
                    f"{path}: event_workspace/indices length {indices.size} "
                    f"!= {EQSANS_NPIXELS_TOTAL + 1} (n_pixels + 1)"
                )
            counts = np.diff(indices).astype(float)
        else:
            raise HdfError(
                f"{path}: no /mantid_workspace_1/workspace/values nor "
                "event_workspace/indices (not a processed EQSANS file)"
            )
    # ``_reorder_tubes`` already returns (256, 192); no extra .T needed.
    image = _reorder_tubes(counts)
    return DetectorImage(image=image, run_number="", title=title, source="processed")


def _reduce_to_detector_pixels(raw: np.ndarray) -> np.ndarray | None:
    """Squeeze ``raw`` down to a flat ``EQSANS_NPIXELS_TOTAL`` array."""
    if raw.size == EQSANS_NPIXELS_TOTAL:
        return np.asarray(raw).reshape(-1).astype(float)
    if raw.ndim == 2 and raw.shape[0] == EQSANS_NPIXELS_TOTAL:
        return raw.sum(axis=1).astype(float)
    if raw.ndim == 2 and raw.shape[1] == EQSANS_NPIXELS_TOTAL:
        return raw.sum(axis=0).astype(float)
    return None


# ---------------------------------------------------------------------------
# Auto-dispatch
# ---------------------------------------------------------------------------


def load_detector_image(path: Path) -> DetectorImage:
    """Try the raw loader, then the processed loader.

    Both paths are pure numpy / h5py — no Mantid subprocess, fast
    enough for interactive viewing. The processed loader recovers
    the EQSANS detector geometry from the IDF positions Mantid wrote
    into the file, so the rendered image matches what
    MantidWorkbench's instrument view shows.

    Raises :class:`HdfError` if neither shape is present.
    """
    try:
        return load_eqsans_raw(path)
    except HdfError as raw_err:
        try:
            return load_processed(path)
        except HdfError as proc_err:
            raise HdfError(
                f"{path}: not a recognised EQSANS NeXus shape\n"
                f"  raw: {raw_err}\n  processed: {proc_err}"
            ) from raw_err


# ---------------------------------------------------------------------------
# Reduced Iqxy loader — Mantid 2D I(qx, qy) workspaces (e.g. *_Iqxy.nxs)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IqxyImage:
    """Reduced 2D ``I(qx, qy)`` data extracted from a Mantid workspace."""

    values: np.ndarray  # (n_qy, n_qx) — Mantid layout (spectrum x bin)
    qx_edges: np.ndarray  # length n_qx + 1
    qy_edges: np.ndarray  # length n_qy + 1
    title: str


def load_iqxy_reduced(path: Path) -> IqxyImage:
    """Load a Mantid-style reduced 2D ``I(qx, qy)`` workspace.

    Convention (matches Mantid's NeXus Workspace2D layout):

    * ``mantid_workspace_1/workspace/values`` is ``(n_spectra, n_bins)``
      with the second axis varying fastest.
    * ``axis1`` is the bin-edge axis (``n_bins + 1`` values) — qx.
    * ``axis2`` is the spectrum axis. For Iqxy it carries qy bin edges
      (``n_spectra + 1`` values). For a 1D workspace it would just be
      ``n_spectra`` integers — those files raise :class:`HdfError`
      from this loader and fall through to the 1D plotters elsewhere.
    """
    with open_nexus(path) as fh:
        if "mantid_workspace_1/workspace/values" not in fh:
            raise HdfError(
                f"{path}: no /mantid_workspace_1/workspace/values "
                "(not a Mantid-shaped processed file)"
            )
        ws = fh["mantid_workspace_1/workspace"]
        values = np.asarray(ws["values"][()])
        if values.ndim != 2:
            raise HdfError(
                f"{path}: workspace/values is {values.shape}; "
                "Iqxy expects 2D (n_spectra, n_bins)"
            )
        axis1 = np.asarray(ws["axis1"][()]) if "axis1" in ws else None
        axis2 = np.asarray(ws["axis2"][()]) if "axis2" in ws else None
        if (
            axis1 is None
            or axis2 is None
            or axis1.size != values.shape[1] + 1
            or axis2.size != values.shape[0] + 1
        ):
            raise HdfError(
                f"{path}: axis1 / axis2 don't look like bin-edge arrays "
                f"(values {values.shape}, axis1 {axis1.shape if axis1 is not None else None}, "
                f"axis2 {axis2.shape if axis2 is not None else None})"
            )
        title = _scalar(fh, "mantid_workspace_1/title", default="")
    return IqxyImage(values=values, qx_edges=axis1, qy_edges=axis2, title=title)


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------


def make_detector_figure(path: Path, *, log_intensity: bool = True) -> Figure:
    """Render any supported NeXus / HDF5 file as a 2D figure.

    Auto-dispatches by inspecting the file:

    * Raw EQSANS event-mode (``/entry/bank<N>_events``) → bincount + tube
      reorder into a ``256x192`` detector image.
    * Mantid processed detector (``mantid_workspace_1/workspace/values``
      with 49152 elements) → reshape to the same ``256x192`` image.
    * Mantid reduced Iqxy (``values`` shape ``(n_spectra, n_bins)`` with
      bin-edge axes) → ``pcolormesh`` of ``I(qx, qy)`` with q axes.

    Initial layout uses a square plot box for detector images
    (``set_box_aspect(1)``) so they read symmetrically regardless of
    window size. Press ``a`` inside the figure to toggle to the
    physical data aspect; matplotlib's pan/zoom still works in either
    mode.
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    path = Path(path)
    try:
        img = load_detector_image(path)
    except HdfError as detector_err:
        # Fall through to Iqxy reduced — that's the other shape we
        # commonly see under ``*_Iqxy.nxs``.
        try:
            iqxy = load_iqxy_reduced(path)
        except HdfError as iqxy_err:
            raise HdfError(
                f"{path}: not a detector image or reduced Iqxy file\n"
                f"  detector: {detector_err}\n  iqxy: {iqxy_err}"
            ) from detector_err
        return _make_iqxy_figure_from_image(iqxy, log_intensity=log_intensity)
    data = img.image.astype(float)
    if log_intensity:
        data = np.where(data > 0, data, np.nan)
    fig, ax = plt.subplots(figsize=(7, 7), layout="constrained")
    cm = _cmap_with_bad("viridis")
    norm: LogNorm | None = None
    if log_intensity:
        finite = data[np.isfinite(data)]
        if finite.size:
            vmin = max(1.0, float(np.nanmin(finite)))
            vmax = float(np.nanmax(finite))
            if vmax <= vmin:
                vmax = vmin * 1.01
            norm = LogNorm(vmin=vmin, vmax=vmax)
    im = ax.imshow(
        data,
        norm=norm,
        cmap=cm,
        extent=(0.5, EQSANS_NTUBES + 0.5, 0.5, EQSANS_NPIXELS_PER_TUBE + 0.5),
        origin="lower",
        aspect="auto",
    )
    cb = fig.colorbar(im, ax=ax, shrink=0.95)
    cb.set_label("counts")
    ax.set_xlabel("Tube")
    ax.set_ylabel("Pixel")
    title = f"EQSANS_{img.run_number}" if img.run_number else "EQSANS"
    if img.title:
        title = f"{title} — {img.title}"
    ax.set_title(title, fontsize=10)
    # Square-by-default plot box. Set this *after* the colorbar attaches
    # to ``ax`` — fig.colorbar() resets box_aspect to None when it
    # divides the axes for the bar.
    ax.set_box_aspect(1)
    _wire_aspect_toggle(fig, ax)
    return fig


def _make_iqxy_figure_from_image(img: IqxyImage, *, log_intensity: bool) -> Figure:
    """``pcolormesh`` for a Mantid Iqxy workspace."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    fig, ax = plt.subplots(figsize=(7, 7), layout="constrained")
    cm = _cmap_with_bad("viridis")
    data = img.values.astype(float)
    if log_intensity:
        # Log color scale needs strictly-positive entries; mask zeros
        # and below to NaN so they render via the colormap's "bad"
        # color (a neutral grey from ``_cmap_with_bad``).
        data = np.where(data > 0, data, np.nan)
    norm: LogNorm | None = None
    if log_intensity:
        finite = data[np.isfinite(data)]
        if finite.size:
            vmin = max(np.nanmin(finite), 1e-12)
            vmax = float(np.nanmax(finite))
            if vmax <= vmin:
                vmax = vmin * 1.01
            norm = LogNorm(vmin=vmin, vmax=vmax)
    mesh = ax.pcolormesh(img.qx_edges, img.qy_edges, data, norm=norm, cmap=cm)
    cb = fig.colorbar(mesh, ax=ax, shrink=0.95)
    cb.set_label("I(qx, qy)")
    ax.set_xlabel(r"$q_x$ ($\mathrm{\AA}^{-1}$)")
    ax.set_ylabel(r"$q_y$ ($\mathrm{\AA}^{-1}$)")
    ax.set_aspect("equal", adjustable="box")
    title = img.title or "I(qx, qy)"
    ax.set_title(title, fontsize=10)
    return fig


def _wire_aspect_toggle(fig, ax) -> None:  # type: ignore[no-untyped-def]
    """Make ``a`` (inside the Axes) flip between square box and data aspect."""

    def _on_key(event):  # type: ignore[no-untyped-def]
        if event.key != "a" or event.inaxes is not ax:
            return
        if ax.get_box_aspect() is not None:
            ax.set_box_aspect(None)
            ax.set_aspect("equal", adjustable="box")
        else:
            ax.set_aspect("auto")
            ax.set_box_aspect(1)
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("key_press_event", _on_key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scalar(fh, key: str, *, default: str = "") -> str:  # type: ignore[no-untyped-def]
    """Read a scalar string-like dataset; tolerates ``[b'...']`` arrays."""
    if key not in fh:
        return default
    raw = fh[key][()]
    if isinstance(raw, np.ndarray) and raw.size:
        raw = raw.flat[0]
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _cmap_with_bad(name: str):  # type: ignore[no-untyped-def]
    import matplotlib as mpl

    cm = mpl.colormaps[name].copy()
    cm.set_bad("#bdbdbd")
    return cm
