"""``FilePanel`` — a single MDIR-style file pane.

The widget is a thin presentation layer over :class:`textual.widgets.DataTable`.
It owns *only* its display state (cwd, cursor, sort, hidden-files toggle,
tag set, optional substring filter); all mutating actions are reached via
the command registry, never by callers poking attributes here directly.

Two identical instances of this widget make up the dual-pane layout
(``PLANNING.md`` §3).
"""

from __future__ import annotations

import contextlib
import fnmatch
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.coordinate import Coordinate
from textual.reactive import reactive
from textual.widgets import DataTable

from sansdir.core.filesystem import (
    VALID_SORT_KEYS,
    FileEntry,
    format_size,
    list_dir,
)

# A tiny palette for at-a-glance file kinds. Kept short on purpose:
# users came here for a file manager, not a Christmas tree.
_KIND_STYLES: tuple[tuple[str, str], ...] = (
    # SANS reduced data — separable green/magenta so 1D and 2D
    # outputs in the same dir don't bleed together.
    ("iqxqy", "magenta"),  # *Iqxqy*.dat
    ("iq", "green"),  # *Iq*.dat
    ("trans", "cyan"),  # *trans*.txt
    # Raw / processed NeXus stand out — they're the heaviest files
    # and the ones M / m / p act on.
    ("nxs", "bright_yellow"),
)


def _is_executable(path: Path) -> bool:
    """True for regular files with the user's exec bit set."""
    try:
        st = path.stat()
    except OSError:
        return False
    import stat as _stat

    if not _stat.S_ISREG(st.st_mode):
        return False
    return bool(st.st_mode & 0o111)


def _kind_style(entry: FileEntry) -> str:
    """Pick a Rich style for a file row based on extension / mode bits.

    Returns "" for plain files so the default terminal colour is
    used — keeps the panel readable instead of every row being
    coloured.
    """
    if entry.is_parent:
        return "dim"
    if entry.is_dir:
        return "bold blue"
    if entry.is_symlink:
        return "cyan"
    name_lower = entry.name.lower()
    for needle, style in _KIND_STYLES:
        if needle in name_lower:
            return style
    if _is_executable(entry.path):
        return "bold red"
    return ""


class FilePanel(DataTable):
    """A file/directory listing pane."""

    DEFAULT_CSS = """
    FilePanel {
        border: round $surface;
        height: 1fr;
        width: 1fr;
    }
    FilePanel:focus, FilePanel.-active {
        border: round $accent;
    }
    """

    # The cursor key bindings come from DataTable; we add j/k vim-style and
    # an Esc to clear an active filter (Phase 2 §"/" filter).
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("escape", "clear_filter", "Clear filter", show=False),
    ]

    cwd: reactive[Path] = reactive(Path.cwd, layout=True)
    show_hidden: reactive[bool] = reactive(False, layout=True)
    sort_key: reactive[str] = reactive("name", layout=True)
    sort_reverse: reactive[bool] = reactive(False, layout=True)
    filter_substring: reactive[str] = reactive("", layout=True)

    def __init__(
        self,
        cwd: Path | str,
        *,
        panel_id: str,
        name: str | None = None,
    ) -> None:
        super().__init__(
            id=panel_id,
            name=name,
            cursor_type="row",
            zebra_stripes=False,
            show_header=True,
            show_cursor=True,
        )
        self._entries: list[FileEntry] = []  # post-filter view shown to user
        self._all_entries: list[FileEntry] = []  # raw listing (pre-filter)
        self.tags: set[Path] = set()
        # Bypass reactive validation during __init__ — we'll refresh on mount.
        self.set_reactive(FilePanel.cwd, Path(cwd).expanduser().resolve())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self.add_columns("Name", "Size", "Modified")
        self.refresh_listing()

    # ------------------------------------------------------------------
    # Public API used by command handlers (AppProtocol surface)
    # ------------------------------------------------------------------

    @property
    def cursor_path(self) -> Path | None:
        if not self._entries:
            return None
        row = self.cursor_row
        if row < 0 or row >= len(self._entries):
            return None
        return self._entries[row].path

    @property
    def current_entry(self) -> FileEntry | None:
        if not self._entries:
            return None
        row = self.cursor_row
        if row < 0 or row >= len(self._entries):
            return None
        return self._entries[row]

    def set_cwd(self, new_cwd: Path) -> None:
        # Tags are per-pane *per-directory* (PLANNING.md §8); changing cwd
        # drops them so the user starts a new selection cleanly.
        self.tags.clear()
        self.filter_substring = ""
        self.cwd = Path(new_cwd).expanduser().resolve()
        # Reactive watcher fires refresh_listing.

    def refresh_listing(self) -> None:
        try:
            entries = list_dir(
                self.cwd,
                show_hidden=self.show_hidden,
                sort_key=self.sort_key if self.sort_key in VALID_SORT_KEYS else "name",
                reverse=self.sort_reverse,
            )
        except (PermissionError, FileNotFoundError, NotADirectoryError) as exc:
            entries = []
            if self.is_mounted:
                self.notify(f"{type(exc).__name__}: {exc}", severity="warning")
        self._all_entries = entries
        self._apply_filter()

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def toggle_tag(self, path: Path | None = None) -> bool:
        """Toggle tag on ``path`` (default: cursor row); return new state."""
        if path is None:
            entry = self.current_entry
            if entry is None or entry.is_parent:
                return False
            path = entry.path
        if any(e.path == path and e.is_parent for e in self._entries):
            return False
        if path in self.tags:
            self.tags.discard(path)
            new_state = False
        else:
            self.tags.add(path)
            new_state = True
        # Repaint only the affected row in place. ``_render_rows`` (the
        # previous implementation) called ``self.clear()`` which resets
        # the DataTable's scroll position to 0; ``move_cursor`` then
        # scrolled the cursor row into view by docking it at the
        # bottom of the visible window. The visible effect for the
        # user was: every Space press in a long file list snapped the
        # cursor to the bottom of the viewport, forcing them to
        # re-locate context. Updating cells in place keeps the
        # DataTable's existing scroll state intact and the cursor's
        # natural Up/Down scroll behaviour returns to normal.
        for i, e in enumerate(self._entries):
            if e.path == path:
                self._repaint_row(i)
                break
        return new_state

    def tag_glob(self, pattern: str) -> int:
        """Tag every visible entry whose name matches ``pattern``. Returns count."""
        n = 0
        affected: list[int] = []
        for i, entry in enumerate(self._entries):
            if entry.is_parent:
                continue
            if fnmatch.fnmatch(entry.name, pattern):
                if entry.path not in self.tags:
                    self.tags.add(entry.path)
                    affected.append(i)
                n += 1
        for i in affected:
            self._repaint_row(i)
        return n

    def untag_glob(self, pattern: str) -> int:
        """Untag every visible entry whose name matches ``pattern``."""
        n = 0
        affected: list[int] = []
        for i, entry in enumerate(self._entries):
            if entry.is_parent:
                continue
            if fnmatch.fnmatch(entry.name, pattern) and entry.path in self.tags:
                self.tags.discard(entry.path)
                n += 1
                affected.append(i)
        for i in affected:
            self._repaint_row(i)
        return n

    def clear_tags(self) -> int:
        """Drop every tag in this pane; returns the number cleared."""
        n = len(self.tags)
        if not n:
            return 0
        # Capture the rows that were tagged before we drop the set,
        # so we know which rows need a repaint.
        affected = [
            i for i, e in enumerate(self._entries) if e.path in self.tags
        ]
        self.tags.clear()
        for i in affected:
            self._repaint_row(i)
        return n

    def tagged_paths(self) -> list[Path]:
        """Sorted list of tagged paths still visible (i.e. still in cwd)."""
        visible = {e.path for e in self._all_entries}
        return sorted(p for p in self.tags if p in visible)

    def selection(self) -> list[Path]:
        """The op target list: tagged paths if any, else the cursor row.

        Most file ops follow this rule: act on the tag set when non-empty,
        otherwise treat the cursor row as a one-element selection (skipping
        the synthetic ``..``).
        """
        tagged = self.tagged_paths()
        if tagged:
            return tagged
        entry = self.current_entry
        if entry is None or entry.is_parent:
            return []
        return [entry.path]

    # ------------------------------------------------------------------
    # Cursor helpers (used by tag-then-advance behavior)
    # ------------------------------------------------------------------

    def move_cursor_down(self) -> None:
        if not self._entries:
            return
        row = min(self.cursor_row + 1, len(self._entries) - 1)
        self.move_cursor(row=row)

    # ------------------------------------------------------------------
    # Actions reachable via the panel's own BINDINGS
    # ------------------------------------------------------------------

    def action_clear_filter(self) -> None:
        if self.filter_substring:
            self.filter_substring = ""

    # ------------------------------------------------------------------
    # Reactive watchers
    # ------------------------------------------------------------------

    def watch_cwd(self, _old: Path, _new: Path) -> None:
        if self.is_mounted:
            self.refresh_listing()

    def watch_show_hidden(self, _old: bool, _new: bool) -> None:
        if self.is_mounted:
            self.refresh_listing()

    def watch_sort_key(self, _old: str, _new: str) -> None:
        if self.is_mounted:
            self.refresh_listing()

    def watch_sort_reverse(self, _old: bool, _new: bool) -> None:
        if self.is_mounted:
            self.refresh_listing()

    def watch_filter_substring(self, _old: str, _new: str) -> None:
        if self.is_mounted and self._all_entries:
            self._apply_filter()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        sub = self.filter_substring.strip().lower()
        if sub:
            self._entries = [e for e in self._all_entries if e.is_parent or sub in e.name.lower()]
        else:
            self._entries = list(self._all_entries)
        self._render_rows()

    def _render_rows(self, *, preserve_cursor: bool = False) -> None:
        prev_row = self.cursor_row if preserve_cursor else 0
        self.clear()
        for entry in self._entries:
            self.add_row(*self._format_row(entry))
        if self._entries:
            target = max(0, min(prev_row, len(self._entries) - 1))
            self.move_cursor(row=target)

    def _repaint_row(self, row_index: int) -> None:
        """Update the cells of a single row in place, no scroll reset.

        Calling ``DataTable.clear()`` (as ``_render_rows`` does) wipes
        the scroll offset; the subsequent ``move_cursor`` then has to
        scroll the cursor row back into view, which Textual does by
        docking it at the bottom of the visible window. For a single
        toggle-tag we just want the row's *style* to flip (yellow
        ``* prefix`` on / off) without touching anything else —
        ``update_cell_at`` does exactly that.
        """
        if not (0 <= row_index < len(self._entries)):
            return
        entry = self._entries[row_index]
        name_col, size_col, mtime_col = self._format_row(entry)
        # ``update_value=True`` forces a cell repaint even when the
        # underlying string compares equal (Rich Text values
        # compare strangely otherwise).
        with contextlib.suppress(Exception):
            self.update_cell_at(Coordinate(row_index, 0), name_col, update_width=False)
            self.update_cell_at(Coordinate(row_index, 1), size_col, update_width=False)
            self.update_cell_at(Coordinate(row_index, 2), mtime_col, update_width=False)

    def _format_row(self, entry: FileEntry) -> tuple[Text | str, str, str]:
        if entry.is_parent:
            name_text = ".."
        elif entry.is_dir:
            name_text = f"{entry.name}/"
        else:
            name_text = entry.name
        if entry.is_symlink:
            name_text = f"{name_text} @"
        if entry.path in self.tags:
            # Tag color always wins — keeps the "* prefix in yellow"
            # convention consistent regardless of underlying file kind.
            name_col: Text | str = Text(f"* {name_text}", style="bold yellow")
        else:
            style = _kind_style(entry)
            name_col = Text(name_text, style=style) if style else name_text
        size_col = "<DIR>" if entry.is_dir else format_size(entry.size)
        if entry.mtime > 0:
            mtime_col = datetime.fromtimestamp(entry.mtime).strftime("%Y-%m-%d %H:%M")
        else:
            mtime_col = "-"
        return name_col, size_col, mtime_col
