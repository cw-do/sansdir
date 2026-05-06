"""Zip and tar.gz creation.

Pure IO. Refuses to overwrite existing archives. Each successful
operation appends a one-line entry to ``~/.cache/sansdir/history.log``
via :func:`sansdir.core.fileops._log` so the audit trail is unified.
"""

from __future__ import annotations

import tarfile
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path

from sansdir.core.fileops import _log

ProgressCB = Callable[[int, int], None]  # (current_index, total_count)


def _resolve_srcs(srcs: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    for p in srcs:
        path = Path(p).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        out.append(path)
    if not out:
        raise ValueError("no source paths provided")
    return out


# ---------------------------------------------------------------------------
# Zip
# ---------------------------------------------------------------------------


def make_zip(
    srcs: Iterable[Path],
    out_path: Path,
    *,
    on_progress: ProgressCB | None = None,
    base_dir: Path | None = None,
) -> Path:
    """Create a zip archive at ``out_path`` containing every ``src`` (and
    every file under ``src`` if it's a directory).

    Args:
        srcs: Files and/or directories to include.
        out_path: Target archive path. Must not exist.
        on_progress: Optional ``(current, total)`` callback fired once per
            top-level source (not per file inside a directory).
        base_dir: Base directory used to compute archive arcnames. Defaults
            to the common parent of ``srcs`` so archived paths look natural
            (``data/a.txt`` instead of ``/abs/path/data/a.txt``).

    Returns:
        ``out_path`` (resolved).

    Raises:
        FileExistsError: ``out_path`` already exists.
        FileNotFoundError: any ``src`` is missing.
        ValueError: empty ``srcs``.
    """
    src_list = _resolve_srcs(srcs)
    out_path = Path(out_path).expanduser().resolve()
    if out_path.exists():
        raise FileExistsError(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if base_dir is None:
        base_dir = _common_parent(src_list)

    total = len(src_list)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, src in enumerate(src_list):
            _add_to_zip(zf, src, base_dir)
            if on_progress is not None:
                on_progress(i + 1, total)
    _log("zip", src_list, out_path)
    return out_path


def _add_to_zip(zf: zipfile.ZipFile, src: Path, base_dir: Path) -> None:
    if src.is_dir():
        for file in sorted(src.rglob("*")):
            if file.is_file():
                arcname = file.relative_to(base_dir).as_posix()
                zf.write(file, arcname)
    else:
        arcname = src.relative_to(base_dir).as_posix()
        zf.write(src, arcname)


# ---------------------------------------------------------------------------
# Tar.gz
# ---------------------------------------------------------------------------


def make_tar_gz(
    srcs: Iterable[Path],
    out_path: Path,
    *,
    on_progress: ProgressCB | None = None,
    base_dir: Path | None = None,
) -> Path:
    """Create a gzip-compressed tar archive. Same semantics as :func:`make_zip`."""
    src_list = _resolve_srcs(srcs)
    out_path = Path(out_path).expanduser().resolve()
    if out_path.exists():
        raise FileExistsError(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if base_dir is None:
        base_dir = _common_parent(src_list)

    total = len(src_list)
    with tarfile.open(out_path, "w:gz") as tf:
        for i, src in enumerate(src_list):
            arcname = src.relative_to(base_dir).as_posix()
            tf.add(src, arcname=arcname, recursive=True)
            if on_progress is not None:
                on_progress(i + 1, total)
    _log("tar.gz", src_list, out_path)
    return out_path


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _common_parent(paths: list[Path]) -> Path:
    """Deepest directory that's a parent of every path in ``paths``."""
    if len(paths) == 1:
        return paths[0].parent
    parts_lists = [list(p.parts) for p in paths]
    common: list[str] = []
    for parts in zip(*parts_lists, strict=False):
        if all(p == parts[0] for p in parts):
            common.append(parts[0])
        else:
            break
    if not common:
        # Should be unreachable on POSIX (every absolute path starts with "/").
        return paths[0].parent
    candidate = Path(*common)
    return candidate if candidate.is_dir() else candidate.parent
