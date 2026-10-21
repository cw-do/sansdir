"""The viewer's mask: editable shapes + painted cells + invert, with undo/redo (Qt-free).

::

    mask = (union(shapes) | painted_on) & ~painted_off
    mask = ~mask if inverted

``1 = masked`` throughout (Mantid's convention, as in :mod:`sansdir.mask.core`).
Shapes are :mod:`sansdir.mask.core` shapes in its pixel space, where cell
``(col, row)`` is centred on the integer point ``(col, row)``. The viewer
draws cell ``(col, row)`` over ``[col, col+1) x [row, row+1)``, so
:data:`VIEW_OFFSET` converts between the two.

The painted layers hold brush / eraser strokes, tube and bank clicks,
threshold results and masks loaded from ``.xml`` / ``.nxs`` / ``.npy``.
They are saved as one :class:`~sansdir.mask.core.PixelSet` after the
shapes, so ``mask_log.json`` replays exactly with
``sansdir mask --shapes-json``.

Undo/redo keep whole snapshots: the state is two 49k-cell bool layers and a
few shapes, so a snapshot is ~100 kB.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sansdir.hdf.reader import HdfError, open_nexus
from sansdir.mask.core import MaskBuilder, PixelSet, Shape, text_to_indices
from sansdir.viewer.geometry import NCOLS, NPIX, NROWS, detector_ids, to_image

DETECTOR_SHAPE: tuple[int, int] = (NROWS, NCOLS)
# Mask-editor tools (the viewer's toolbar, ``--tool``); "pan" = no tool.
MASK_TOOLS: tuple[str, ...] = (
    "pan",
    "rect",
    "ellipse",
    "circle",
    "polygon",
    "brush",
    "eraser",
    "tube",
)
VIEW_OFFSET: float = 0.5  # view coordinate = shape coordinate + 0.5
MAX_UNDO: int = 200
MASK_SUFFIXES: tuple[str, ...] = (".json", ".xml", ".nxs", ".h5", ".npy")
SAVE_FORMATS: dict[str, str] = {".nxs": "nxs", ".xml": "xml", ".npy": "npy"}
_MASKED_FLAG = re.compile(r"detID:(\d+);bool;masked;1")
_PARAMETER_MAP = "mantid_workspace_1/instrument/instrument_parameter_map/data"
_EVENT_INDICES = "mantid_workspace_1/event_workspace/indices"
_HIST_VALUES = "mantid_workspace_1/workspace/values"


@dataclass(frozen=True)
class _Snapshot:
    shapes: tuple[Shape, ...]
    on: np.ndarray
    off: np.ndarray
    inverted: bool


class MaskState:
    """What the mask editor edits. Every mutator records an undo step unless
    ``record=False`` (used while a drag is in progress, after one
    :meth:`checkpoint` at its start)."""

    def __init__(self) -> None:
        self.shapes: list[Shape] = []
        self.on = np.zeros(DETECTOR_SHAPE, dtype=bool)
        self.off = np.zeros(DETECTOR_SHAPE, dtype=bool)
        self.inverted = False
        self._undo: list[_Snapshot] = []
        self._redo: list[_Snapshot] = []
        self._version = 0
        self._saved_version = 0

    # -- result --------------------------------------------------------------

    def build(self) -> np.ndarray:
        """``(256, 192)`` bool, True = masked."""
        out: np.ndarray = self.on.copy()
        for shape in self.shapes:
            out |= shape.rasterise(DETECTOR_SHAPE)
        out &= ~self.off
        if self.inverted:
            out = ~out
        return out

    def to_builder(self) -> MaskBuilder:
        """Shapes, then the painted layers as one ``PixelSet``: builds the same mask."""
        builder = MaskBuilder(DETECTOR_SHAPE, inverse=self.inverted)
        for shape in self.shapes:
            builder.add(shape)
        if self.on.any() or self.off.any():
            builder.add(PixelSet.from_cells(self.on, self.off))
        return builder

    @property
    def is_empty(self) -> bool:
        return not (self.shapes or self.on.any() or self.off.any() or self.inverted)

    @property
    def modified(self) -> bool:
        """Changed since the last :meth:`mark_saved` (or since creation)."""
        return self._version != self._saved_version

    def mark_saved(self) -> None:
        self._saved_version = self._version

    # -- undo / redo -----------------------------------------------------------

    def checkpoint(self) -> None:
        """Record the current state as one undo step (call before a change)."""
        self._undo.append(self._snapshot())
        del self._undo[:-MAX_UNDO]
        self._redo.clear()
        self._version += 1

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        return True

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def _snapshot(self) -> _Snapshot:
        return _Snapshot(tuple(self.shapes), self.on.copy(), self.off.copy(), self.inverted)

    def _restore(self, snap: _Snapshot) -> None:
        self.shapes = list(snap.shapes)
        self.on = snap.on.copy()
        self.off = snap.off.copy()
        self.inverted = snap.inverted
        self._version += 1

    def _change(self, record: bool) -> None:
        if record:
            self.checkpoint()
        else:
            self._version += 1

    # -- edits -----------------------------------------------------------------

    def add_shape(self, shape: Shape, *, record: bool = True) -> int:
        self._change(record)
        self.shapes.append(shape)
        return len(self.shapes) - 1

    def set_shape(self, index: int, shape: Shape, *, record: bool = True) -> None:
        self._change(record)
        self.shapes[index] = shape

    def remove_shape(self, index: int, *, record: bool = True) -> Shape:
        self._change(record)
        return self.shapes.pop(index)

    def paint(self, cells: np.ndarray, *, masked: bool, record: bool = True) -> None:
        """Brush (``masked=True``) or erase ``cells``.

        The eraser beats shapes: an erased cell inside a rectangle is unmasked.
        """
        cells = np.asarray(cells, dtype=bool)
        self._change(record)
        if masked:
            self.on |= cells
            self.off &= ~cells
        else:
            self.off |= cells
            self.on &= ~cells

    def toggle_columns(self, cols: list[int], *, record: bool = True) -> bool:
        """Tube / bank click: mask the columns, or unmask them if all already are.

        Returns True when they end up masked.
        """
        cells = np.zeros(DETECTOR_SHAPE, dtype=bool)
        cells[:, cols] = True
        masked = not bool(self.build()[cells].all())
        self.paint(cells, masked=masked, record=record)
        return masked

    def threshold(
        self,
        image: np.ndarray,
        *,
        low: float | None = None,
        high: float | None = None,
        record: bool = True,
    ) -> int:
        """Mask dead (``counts <= low``) and/or hot (``counts >= high``) cells.

        Returns how many cells were newly masked.
        """
        cells = threshold_cells(image, low=low, high=high)
        before = self.build()
        self.paint(cells, masked=True, record=record)
        return int(np.count_nonzero(self.build() & ~before))

    def set_inverted(self, inverted: bool, *, record: bool = True) -> None:
        self._change(record)
        self.inverted = inverted

    def clear(self, *, record: bool = True) -> None:
        self._change(record)
        self.shapes.clear()
        self.on[:] = False
        self.off[:] = False
        self.inverted = False

    def load(self, loaded: MaskBuilder | np.ndarray, *, record: bool = True) -> None:
        """Add a loaded mask: a builder's shapes stay editable; cells are painted on.

        A builder's ``inverse`` flag is taken over only when this state is
        empty; merging into an existing mask never flips it.
        """
        empty = self.is_empty
        self._change(record)
        if isinstance(loaded, np.ndarray):
            self.on |= loaded.astype(bool)
            self.off &= ~loaded.astype(bool)
            return
        if loaded.detector_shape != DETECTOR_SHAPE:
            raise ValueError(
                f"mask is for a {loaded.detector_shape} detector, not EQSANS {DETECTOR_SHAPE}"
            )
        for shape in loaded.shapes:
            if isinstance(shape, PixelSet):
                on = shape.rasterise(DETECTOR_SHAPE)
                off = shape.unmasked(DETECTOR_SHAPE)
                self.on = (self.on | on) & ~off
                self.off = (self.off | off) & ~on
            else:
                self.shapes.append(shape)
        if empty:
            self.inverted = loaded.inverse


def threshold_cells(
    image: np.ndarray, *, low: float | None = None, high: float | None = None
) -> np.ndarray:
    """Cells with ``counts <= low`` or ``counts >= high`` (either bound optional)."""
    image = np.asarray(image)
    cells = np.zeros(image.shape, dtype=bool)
    if low is not None:
        cells |= image <= low
    if high is not None:
        cells |= image >= high
    return cells


def brush_cells(x: float, y: float, radius: float) -> np.ndarray:
    """Cells whose centres lie within ``radius`` cells of view point ``(x, y)``.

    ``radius`` 0 is the single cell under the point.
    """
    cells = np.zeros(DETECTOR_SHAPE, dtype=bool)
    if radius <= 0:
        col, row = int(np.floor(x)), int(np.floor(y))
        if 0 <= col < NCOLS and 0 <= row < NROWS:
            cells[row, col] = True
        return cells
    cols = np.arange(NCOLS)[None, :] + VIEW_OFFSET
    rows = np.arange(NROWS)[:, None] + VIEW_OFFSET
    inside: np.ndarray = (cols - x) ** 2 + (rows - y) ** 2 <= radius * radius
    return inside


def cells_for_detids(ids: np.ndarray) -> np.ndarray:
    """Detector IDs → ``(256, 192)`` bool cells. IDs outside the detector are ignored."""
    ids = np.asarray(ids, dtype=np.int64)
    flat = np.zeros(NPIX, dtype=bool)
    flat[ids[(ids >= 0) & (ids < NPIX)]] = True
    return to_image(flat)


# -- reading mask files ----------------------------------------------------------


def read_mask_file(path: Path | str) -> MaskBuilder | np.ndarray:
    """Read a mask for :meth:`MaskState.load`.

    * ``*.json`` (``mask_log.json``): a :class:`MaskBuilder` — shapes stay editable.
    * ``*.xml`` (Mantid ``SaveMask``), ``*.nxs`` / ``*.h5`` (Mantid mask
      workspace, or sansdir's legacy writer), ``*.npy``: ``(256, 192)`` bool cells.

    Raises ``ValueError`` (or ``OSError``) with a readable message.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        return MaskBuilder.from_dict(json.loads(path.read_text(encoding="utf-8")))
    if suffix == ".xml":
        return _read_xml(path)
    if suffix in (".nxs", ".h5"):
        return _read_nxs(path)
    if suffix == ".npy":
        return _read_npy(path)
    raise ValueError(f"{path.name}: not a mask file ({', '.join(MASK_SUFFIXES)})")


def _read_xml(path: Path) -> np.ndarray:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"{path.name}: not valid XML ({exc})") from exc
    texts = [el.text or "" for el in root.iter("detids")]
    if not texts:
        raise ValueError(f"{path.name}: no <detids> element (not a Mantid mask file?)")
    ids = [text_to_indices(t) for t in texts]
    return cells_for_detids(np.concatenate(ids))


def _read_nxs(path: Path) -> np.ndarray:
    """Masked flags from ``instrument_parameter_map`` (what Mantid and drtsans use).

    Files without flags are accepted only in the legacy-writer encoding (one
    event per unmasked detector, none per masked one): event data is not a mask.
    """
    try:
        with open_nexus(path) as fh:
            if _PARAMETER_MAP in fh:
                raw = fh[_PARAMETER_MAP][()]
                text = (raw[0] if np.ndim(raw) else raw).decode("utf-8", "replace")
                ids = np.array([int(m) for m in _MASKED_FLAG.findall(text)], dtype=np.int64)
                if ids.size:
                    return cells_for_detids(ids)
            counts = None
            if _EVENT_INDICES in fh:
                counts = np.diff(np.asarray(fh[_EVENT_INDICES][()], dtype=np.int64))
            elif _HIST_VALUES in fh:
                counts = np.asarray(fh[_HIST_VALUES][()]).reshape(-1)
    except HdfError as exc:
        raise ValueError(f"{path.name}: {exc}") from exc
    if counts is not None and counts.size == NPIX and set(np.unique(counts)) <= {0, 1}:
        return cells_for_detids(np.flatnonzero(counts == 0))
    raise ValueError(f"{path.name}: no masked detectors flagged in this NeXus file")


def _read_npy(path: Path) -> np.ndarray:
    data: np.ndarray = np.load(path, allow_pickle=False)
    if data.shape == DETECTOR_SHAPE:
        return data.astype(bool)
    if data.shape == (NPIX,):
        return cells_for_detids(np.flatnonzero(data))
    raise ValueError(f"{path.name}: array shape {data.shape}, expected {DETECTOR_SHAPE}")


# -- saving -------------------------------------------------------------------------


@dataclass(frozen=True)
class SavedMask:
    path: Path
    log_path: Path
    n_masked: int


def default_output(source: Path, directory: Path | None = None) -> Path:
    """``<source-stem>_mask.nxs`` (as ``sansdir mask`` and the old editor name it)."""
    return (directory or source.parent) / f"{source.stem}_mask.nxs"


def save_mask(state: MaskState, source: Path, run_number: str, output: Path) -> SavedMask:
    """Write ``output`` (format from its suffix) plus its ``mask_log.json``.

    ``.nxs`` goes through Mantid when ``drtsans`` is installed (8-15 s), so
    call this off the UI thread.
    """
    from sansdir.mask.detector import SourceMeta
    from sansdir.mask.writers import stats_for, write_log, write_npy, write_nxs, write_xml

    fmt = SAVE_FORMATS.get(output.suffix.lower())
    if fmt is None:
        raise ValueError(f"{output.name}: save as {', '.join(SAVE_FORMATS)}")
    builder = state.to_builder()
    mask = builder.build()
    meta = SourceMeta(
        source_path=source.resolve(),
        instrument_name="EQSANS",
        detector_shape=DETECTOR_SHAPE,
        pixel_ids=detector_ids().reshape(-1),
        run_number=run_number,
    )
    if fmt == "nxs":
        write_nxs(output, mask, meta)
    elif fmt == "xml":
        write_xml(output, mask, meta)
    else:
        write_npy(output, mask, meta)
    log = write_log(output, meta, builder, stats_for(mask))
    return SavedMask(output, log, int(mask.sum()))


__all__ = [
    "DETECTOR_SHAPE",
    "MASK_SUFFIXES",
    "MASK_TOOLS",
    "SAVE_FORMATS",
    "VIEW_OFFSET",
    "MaskState",
    "SavedMask",
    "brush_cells",
    "cells_for_detids",
    "default_output",
    "read_mask_file",
    "save_mask",
    "threshold_cells",
]
