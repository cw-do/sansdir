"""Safe NeXus / HDF5 reader.

Thin wrapper around :mod:`h5py` for the common operations sansdir
needs: opening files in single-writer / multiple-reader (SWMR) mode,
walking the hierarchy, resolving keys with optional leading slashes,
and producing one-line previews of dataset contents for the tree
dialog.

Errors from h5py (corrupt files, missing keys, locked files when the
DAQ is still writing) are wrapped in :class:`HdfError` with a clean
message so the UI can show them in the status bar without leaking a
traceback.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import h5py


class HdfError(RuntimeError):
    """Wraps an h5py / OSError so the UI can surface a clean message."""


# ---------------------------------------------------------------------------
# Open
# ---------------------------------------------------------------------------


@contextmanager
def open_nexus(path: Path) -> Iterator[h5py.File]:
    """Open ``path`` read-only with SWMR enabled.

    SWMR (Single-Writer Multiple-Reader) lets us read live files the
    DAQ is currently writing without blocking the writer. h5py raises
    on every read error path; we wrap those in :class:`HdfError`.
    """
    import h5py

    try:
        f = h5py.File(path, "r", swmr=True)
    except OSError as exc:
        # ``swmr=True`` is rejected on files written without SWMR support;
        # fall back to a plain read.
        try:
            f = h5py.File(path, "r")
        except OSError as exc2:
            raise HdfError(f"could not open {path}: {exc2}") from exc
        else:
            del exc  # only used in except chain when we can't recover
    try:
        yield f
    finally:
        f.close()


# ---------------------------------------------------------------------------
# Walking / preview
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HdfNode:
    """One row in the tree dialog."""

    path: str  # e.g. "/entry/DASlogs/temperature/value"
    kind: str  # "group" | "dataset"
    dtype: str = ""
    shape: tuple[int, ...] = ()
    units: str = ""
    preview: str = ""


def walk_tree(file: h5py.File, root: str = "/", max_depth: int | None = None) -> list[HdfNode]:
    """Flatten the HDF5 hierarchy into a depth-ordered list of nodes.

    The tree dialog uses this to populate its top-level rows; nested
    groups expand on demand by re-calling with a deeper ``root``.
    ``max_depth=1`` returns just direct children — handy for lazy
    expansion.
    """
    import h5py

    nodes: list[HdfNode] = []
    target = file[root] if root in ("/", "") or root in file else None
    if target is None:
        return nodes

    def _depth(name: str) -> int:
        return name.count("/")

    base_depth = _depth(target.name)

    def _visit(name: str, obj: Any) -> None:
        if max_depth is not None and (_depth(name) - base_depth) > max_depth:
            return
        full = name if name.startswith("/") else f"{target.name.rstrip('/')}/{name}"
        if isinstance(obj, h5py.Group):
            nodes.append(HdfNode(path=full, kind="group"))
        elif isinstance(obj, h5py.Dataset):
            nodes.append(_describe_dataset(full, obj))

    target.visititems(_visit)
    return nodes


def list_children(file: h5py.File, group_path: str) -> list[HdfNode]:
    """Direct children of ``group_path`` (one level deep)."""
    import h5py

    if group_path not in file:
        return []
    grp = file[group_path]
    if not isinstance(grp, h5py.Group):
        return []
    out: list[HdfNode] = []
    for name in grp:
        full = f"{group_path.rstrip('/')}/{name}" if group_path != "/" else f"/{name}"
        obj = grp[name]
        if isinstance(obj, h5py.Group):
            out.append(HdfNode(path=full, kind="group"))
        elif isinstance(obj, h5py.Dataset):
            out.append(_describe_dataset(full, obj))
    return out


def _describe_dataset(path: str, ds: h5py.Dataset) -> HdfNode:
    """Build an :class:`HdfNode` for ``ds`` with a one-line value preview."""
    units_attr = ds.attrs.get("units", "")
    if isinstance(units_attr, bytes):
        units_attr = units_attr.decode("utf-8", errors="replace")
    return HdfNode(
        path=path,
        kind="dataset",
        dtype=str(ds.dtype),
        shape=tuple(ds.shape),
        units=str(units_attr) if units_attr is not None else "",
        preview=preview_value(ds),
    )


def preview_value(ds: h5py.Dataset, *, max_chars: int = 80) -> str:
    """One-line preview of ``ds``: scalar, short array head, or shape note."""
    try:
        if ds.shape == ():
            value = ds[()]
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            return _truncate(repr(value), max_chars)
        if ds.size == 0:
            return "(empty)"
        if ds.size <= 8:
            return _truncate(str(list(ds[()].ravel())), max_chars)
        head = list(ds[()].ravel()[:5])
        return _truncate(f"{head}... shape={ds.shape}", max_chars)
    except (OSError, ValueError, TypeError) as exc:
        return f"<error reading: {type(exc).__name__}>"


def _truncate(s: str, max_chars: int) -> str:
    return s if len(s) <= max_chars else s[: max_chars - 1] + "…"


# ---------------------------------------------------------------------------
# Convenience: open + read in one go
# ---------------------------------------------------------------------------


def read_dataset(path: Path, key: str) -> Any:
    """One-shot read of a single key from a NeXus file.

    Used by :mod:`sansdir.hdf.metadata` for the simple "give me the
    value at this path" use case; tests don't have to wire the
    contextmanager themselves.
    """
    with open_nexus(path) as fh:
        if key not in fh:
            raise HdfError(f"{path}: key not found: {key}")
        return fh[key][()]
