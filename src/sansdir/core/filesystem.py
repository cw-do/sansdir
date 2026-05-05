"""Directory listing, sorting, and a small immutable :class:`FileEntry` model.

The functions here are the single source of truth for "what's in a directory"
across the TUI, the CLI, and the LLM layer. They never block on network and
are cheap enough (sub-100 ms on 1000-entry dirs per ``PLANNING.md`` §10) to
be called on the UI thread for typical SANS directories.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

SortKey = str  # "name" | "mtime" | "size" | "ext"

VALID_SORT_KEYS: tuple[SortKey, ...] = ("name", "mtime", "size", "ext")


@dataclass(frozen=True, slots=True)
class FileEntry:
    """One row in a :class:`~sansdir.ui.panel.FilePanel`.

    Attributes:
        path: Absolute path to the entry.
        name: Display name (``..`` for the parent shortcut).
        is_dir: True if the entry is a directory (or a symlink that resolves
            to one).
        is_symlink: True if the entry itself is a symlink.
        size: Byte count for files; 0 for directories.
        mtime: POSIX modification timestamp, or 0.0 if unavailable.
    """

    path: Path
    name: str
    is_dir: bool
    is_symlink: bool
    size: int
    mtime: float

    @property
    def is_parent(self) -> bool:
        """True for the synthetic ``..`` row."""
        return self.name == ".."

    @property
    def extension(self) -> str:
        """Lowercased extension without the leading dot, or ``""`` for dirs."""
        if self.is_dir:
            return ""
        # Treat compound suffixes like ``.nxs.h5`` as a single extension so
        # NeXus files sort together rather than scattering under ``.h5``.
        suffixes = "".join(self.path.suffixes).lower()
        return suffixes.lstrip(".")


def _stat_entry(p: Path, name: str | None = None) -> FileEntry:
    """Build a :class:`FileEntry` from ``p`` without raising on broken symlinks."""
    display_name = name if name is not None else p.name
    try:
        st = p.stat()
        size = st.st_size
        mtime = st.st_mtime
        # ``Path.is_dir`` follows symlinks; we use it after a successful stat
        # so a broken link doesn't blow up the listing.
        is_dir = p.is_dir()
    except OSError:
        size = 0
        mtime = 0.0
        is_dir = False
    return FileEntry(
        path=p,
        name=display_name,
        is_dir=is_dir,
        is_symlink=p.is_symlink(),
        size=size,
        mtime=mtime,
    )


def list_dir(
    path: str | os.PathLike[str],
    *,
    show_hidden: bool = False,
    sort_key: SortKey = "name",
    reverse: bool = False,
    include_parent: bool = True,
) -> list[FileEntry]:
    """Return the entries of ``path``, sorted.

    Args:
        path: Directory to list. Resolved to absolute via :meth:`Path.resolve`.
        show_hidden: Include entries starting with ``.``.
        sort_key: One of :data:`VALID_SORT_KEYS`.
        reverse: Reverse the chosen sort.
        include_parent: Prepend a ``..`` synthetic entry when ``path`` has
            a parent (suppressed at the filesystem root).

    Raises:
        ValueError: ``sort_key`` is not in :data:`VALID_SORT_KEYS`.
        FileNotFoundError / PermissionError / NotADirectoryError: passed
            through from :func:`os.scandir`.
    """
    if sort_key not in VALID_SORT_KEYS:
        raise ValueError(f"unknown sort_key {sort_key!r} (valid: {VALID_SORT_KEYS})")

    base = Path(path).expanduser().resolve()

    # ``os.scandir`` is the fastest portable directory walker; it returns
    # ``DirEntry`` objects whose ``stat`` is cached, halving the syscalls
    # vs. iterating ``Path.iterdir`` and stat'ing each one ourselves.
    entries: list[FileEntry] = []
    with os.scandir(base) as it:
        for de in it:
            if not show_hidden and de.name.startswith("."):
                continue
            entries.append(_stat_entry(Path(de.path)))

    entries = sort_entries(entries, sort_key=sort_key, reverse=reverse)

    if include_parent and base.parent != base:
        parent = _stat_entry(base.parent, name="..")
        # Parent is always pinned at the top regardless of sort/reverse.
        entries.insert(0, parent)

    return entries


def sort_entries(
    entries: Iterable[FileEntry],
    *,
    sort_key: SortKey = "name",
    reverse: bool = False,
) -> list[FileEntry]:
    """Sort ``entries`` by ``sort_key``, with directories grouped first."""
    if sort_key not in VALID_SORT_KEYS:
        raise ValueError(f"unknown sort_key {sort_key!r} (valid: {VALID_SORT_KEYS})")

    if sort_key == "name":
        key = lambda e: e.name.lower()  # noqa: E731
    elif sort_key == "mtime":
        key = lambda e: e.mtime  # noqa: E731
    elif sort_key == "size":
        key = lambda e: e.size  # noqa: E731
    else:  # "ext"
        key = lambda e: (e.extension, e.name.lower())  # noqa: E731

    # Two-pass sort: directories first (alphabetical within each group),
    # files second by the requested key. Mirrors MDIR / mc behavior.
    dirs = sorted((e for e in entries if e.is_dir and not e.is_parent), key=key, reverse=reverse)
    files = sorted((e for e in entries if not e.is_dir), key=key, reverse=reverse)
    parent = [e for e in entries if e.is_parent]
    return parent + dirs + files


def cycle_sort_key(current: SortKey) -> SortKey:
    """Return the next sort key in :data:`VALID_SORT_KEYS`, wrapping around."""
    if current not in VALID_SORT_KEYS:
        raise ValueError(f"unknown sort_key {current!r} (valid: {VALID_SORT_KEYS})")
    idx = VALID_SORT_KEYS.index(current)
    return VALID_SORT_KEYS[(idx + 1) % len(VALID_SORT_KEYS)]


def free_disk_bytes(path: str | os.PathLike[str]) -> int:
    """Return free bytes on the filesystem containing ``path``.

    Returns 0 on platforms or paths where ``shutil.disk_usage`` raises.
    """
    import shutil

    try:
        return shutil.disk_usage(os.fspath(path)).free
    except OSError:
        return 0


def format_size(n: int) -> str:
    """Human-readable size like ``"12.3 KB"``. Uses 1024-based units."""
    if n < 0:
        return "-"
    if n < 1024:
        return f"{n} B"
    units = ("KB", "MB", "GB", "TB", "PB")
    value = float(n)
    for unit in units:
        value /= 1024
        if value < 1024:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} EB"
