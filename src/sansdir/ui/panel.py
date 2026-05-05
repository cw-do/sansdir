"""``FilePanel`` — a single MDIR-style file pane.

The widget is a thin presentation layer over :class:`textual.widgets.DataTable`.
It owns *only* its display state (cwd, cursor, sort, hidden-files toggle);
all mutating actions are reached via the command registry, never by callers
poking attributes here directly.

Two identical instances of this widget make up the dual-pane layout
(``PLANNING.md`` §3).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import ClassVar

from textual.binding import Binding, BindingType
from textual.reactive import reactive
from textual.widgets import DataTable

from sansdir.core.filesystem import (
    VALID_SORT_KEYS,
    FileEntry,
    format_size,
    list_dir,
)


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

    # The cursor key bindings come from DataTable; we add j/k vim-style here.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    cwd: reactive[Path] = reactive(Path.cwd, layout=True)
    show_hidden: reactive[bool] = reactive(False, layout=True)
    sort_key: reactive[str] = reactive("name", layout=True)
    sort_reverse: reactive[bool] = reactive(False, layout=True)

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
        self._entries: list[FileEntry] = []
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
            # Surface errors via the app notifier when mounted.
            if self.is_mounted:
                self.notify(f"{type(exc).__name__}: {exc}", severity="warning")
        self._entries = entries
        self._render_rows()

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

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_rows(self) -> None:
        self.clear()
        for entry in self._entries:
            self.add_row(*self._format_row(entry))
        if self._entries:
            self.move_cursor(row=0)

    @staticmethod
    def _format_row(entry: FileEntry) -> tuple[str, str, str]:
        if entry.is_parent:
            name_col = ".."
        elif entry.is_dir:
            name_col = f"{entry.name}/"
        else:
            name_col = entry.name
        if entry.is_symlink:
            name_col = f"{name_col} @"
        size_col = "<DIR>" if entry.is_dir else format_size(entry.size)
        if entry.mtime > 0:
            mtime_col = datetime.fromtimestamp(entry.mtime).strftime("%Y-%m-%d %H:%M")
        else:
            mtime_col = "-"
        return name_col, size_col, mtime_col
