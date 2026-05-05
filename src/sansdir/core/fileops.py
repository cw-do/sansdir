"""Filesystem mutation primitives — pure IO, no UI.

The functions here are the only place where the app modifies the filesystem.
Every destructive op writes a one-line entry to
``~/.cache/sansdir/history.log`` (configurable via ``$SANSDIR_CACHE_DIR``)
so a user can audit what sansdir did to their files (PLANNING.md §8).
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
from collections.abc import Iterable
from pathlib import Path

from sansdir.core.history import default_history_path


def history_log_path() -> Path:
    """``~/.cache/sansdir/history.log`` (or under ``$SANSDIR_CACHE_DIR``)."""
    return default_history_path().parent / "history.log"


def _log(action: str, paths: Iterable[Path], dest: Path | None = None) -> None:
    """Append a one-line audit record. Failures are intentionally silent."""
    try:
        log = history_log_path()
        log.parent.mkdir(parents=True, exist_ok=True)
        ts = _dt.datetime.now().isoformat(timespec="seconds")
        srcs = " ".join(str(p) for p in paths)
        line = f"{ts} {action} {srcs}"
        if dest is not None:
            line += f" -> {dest}"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# mkdir
# ---------------------------------------------------------------------------


def make_dir(parent: Path, name: str) -> Path:
    """Create ``parent / name``; raise if it already exists.

    ``name`` may contain ``/`` to create nested dirs in one call. The
    refusal-to-overwrite is intentional (see ``CLAUDE.md`` §10).
    """
    if not name or name in (".", ".."):
        raise ValueError(f"invalid directory name: {name!r}")
    target = (parent / name).resolve()
    if not str(target).startswith(str(parent.resolve())):
        # Block traversal attempts like `../etc/passwd`. The user can still
        # `:cd ..` and create there explicitly; this only constrains the
        # one-call form.
        raise ValueError(f"refusing to create outside parent: {target}")
    target.mkdir(parents=True, exist_ok=False)
    _log("mkdir", [target])
    return target


# ---------------------------------------------------------------------------
# copy / move
# ---------------------------------------------------------------------------


def copy_paths(srcs: Iterable[Path], dst_dir: Path) -> list[Path]:
    """Copy each ``src`` into ``dst_dir``; return the list of new paths.

    Files use :func:`shutil.copy2` (preserves metadata); directories use
    :func:`shutil.copytree`. Raises :class:`FileExistsError` if any
    destination already exists — the caller is expected to confirm with
    the user before retrying with a different ``dst_dir``.
    """
    src_list = [Path(s) for s in srcs]
    dst_dir = Path(dst_dir).expanduser().resolve()
    if not dst_dir.is_dir():
        raise NotADirectoryError(dst_dir)
    out: list[Path] = []
    for src in src_list:
        target = dst_dir / src.name
        if target.exists():
            raise FileExistsError(target)
        if src.is_dir():
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)
        out.append(target)
    _log("copy", src_list, dst_dir)
    return out


def move_paths(srcs: Iterable[Path], dst_dir: Path) -> list[Path]:
    """Move each ``src`` into ``dst_dir`` (or rename single src to a path).

    If ``dst_dir`` is *not* an existing directory and ``srcs`` contains a
    single entry, it is treated as a rename target (the inactive pane's cwd
    handling lives in the keymap, not here). Otherwise, files are moved
    into ``dst_dir`` preserving their basenames.
    """
    src_list = [Path(s) for s in srcs]
    dst = Path(dst_dir).expanduser().resolve()
    if not dst.exists() and len(src_list) == 1:
        # Rename form: dst is the new full path.
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_list[0]), str(dst))
        _log("rename", src_list, dst)
        return [dst]
    if not dst.is_dir():
        raise NotADirectoryError(dst)
    out: list[Path] = []
    for src in src_list:
        target = dst / src.name
        if target.exists():
            raise FileExistsError(target)
        shutil.move(str(src), str(target))
        out.append(target)
    _log("move", src_list, dst)
    return out


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def delete_paths(paths: Iterable[Path], *, trash: bool = True) -> list[Path]:
    """Delete each path. Uses ``send2trash`` when available and ``trash=True``.

    Returns the list of paths actually removed (deletes that raised are
    skipped and logged separately).
    """
    path_list = [Path(p) for p in paths]
    removed: list[Path] = []
    use_trash = trash
    if use_trash:
        try:
            from send2trash import send2trash
        except ImportError:
            use_trash = False

    for p in path_list:
        try:
            if use_trash:
                send2trash(os.fspath(p))  # type: ignore[name-defined]
            elif p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
            removed.append(p)
        except OSError:
            _log("delete-failed", [p])
            continue
    if removed:
        _log("trash" if use_trash else "delete", removed)
    return removed
