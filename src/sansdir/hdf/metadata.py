"""Extract scalar / time-averaged values from NeXus DASlogs entries.

Used by:

* the ``m`` keypress (single-key preview in the tree dialog),
* the Phase 8 batch metadata extractor (``M`` → TSV/CSV).

DASlogs entries on SNS NeXus files come in two shapes:

* **Time series** — a group with ``value`` (1D array of samples) and
  ``time`` (matching axis). Scalar reduction is the mean.
* **Single value** — a group with just ``value`` (0-D or 1-element).

Either way :func:`extract_value` returns one Python scalar.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import h5py


@dataclass(frozen=True, slots=True)
class ExtractedValue:
    """Result of :func:`extract_value`."""

    key: str
    value: Any
    units: str
    is_scalar: bool
    n_points: int  # number of samples backing the value (1 for true scalars)


def extract_value(file: h5py.File, key: str) -> ExtractedValue:
    """Read ``key`` from ``file`` and reduce to a single value.

    Supported input shapes (in priority order):

    * ``key`` is a scalar dataset → return the value.
    * ``key`` is a 1-element dataset → return ``arr[0]``.
    * ``key`` is a 1D dataset → return ``mean(arr)``.
    * ``key`` is a *group* with a ``value`` member (typical DASlogs
      shape) → recurse into ``key/value``.
    """
    import h5py
    import numpy as np

    if key not in file:
        raise KeyError(f"key not found: {key}")
    obj = file[key]
    if isinstance(obj, h5py.Group):
        if "value" in obj:
            return extract_value(file, f"{key.rstrip('/')}/value")
        raise ValueError(f"group {key!r} has no 'value' member")
    assert isinstance(obj, h5py.Dataset)

    units = ""
    raw_units = obj.attrs.get("units", "")
    if isinstance(raw_units, bytes):
        raw_units = raw_units.decode("utf-8", errors="replace")
    if raw_units:
        units = str(raw_units)

    arr = obj[()]
    if obj.shape == ():
        scalar = arr.item() if hasattr(arr, "item") else arr
        if isinstance(scalar, bytes):
            scalar = scalar.decode("utf-8", errors="replace")
        return ExtractedValue(key=key, value=scalar, units=units, is_scalar=True, n_points=1)
    flat = np.asarray(arr).ravel()
    n = int(flat.size)
    if n == 0:
        return ExtractedValue(key=key, value=None, units=units, is_scalar=False, n_points=0)
    if n == 1:
        v = flat[0]
        if isinstance(v, bytes):
            v = v.decode("utf-8", errors="replace")
        else:
            v = v.item() if hasattr(v, "item") else v
        return ExtractedValue(key=key, value=v, units=units, is_scalar=True, n_points=1)
    # Numeric time series → mean. Strings → first entry.
    if np.issubdtype(flat.dtype, np.number):
        return ExtractedValue(
            key=key, value=float(flat.mean()), units=units, is_scalar=False, n_points=n
        )
    first = flat[0]
    if isinstance(first, bytes):
        first = first.decode("utf-8", errors="replace")
    return ExtractedValue(key=key, value=first, units=units, is_scalar=False, n_points=n)


def extract_value_from_path(path: Path, key: str) -> ExtractedValue:
    """One-shot helper that opens ``path`` and reads ``key`` in one call."""
    from sansdir.hdf.reader import open_nexus

    with open_nexus(path) as fh:
        return extract_value(fh, key)
