"""Structural typing for what command handlers need from the running app.

Defining these as :class:`typing.Protocol` instead of importing the real
:class:`~sansdir.app.SansdirApp` keeps the command layer testable without
spinning up Textual and prevents an import cycle (commands → builtins →
app → commands).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class PanelProtocol(Protocol):
    """The slice of :class:`~sansdir.ui.panel.FilePanel` that handlers touch."""

    cwd: Path
    show_hidden: bool
    sort_key: str
    sort_reverse: bool
    filter_substring: str
    tags: set[Path]

    @property
    def cursor_path(self) -> Path | None:
        """Absolute path under the cursor, or ``None`` for an empty pane."""

    def set_cwd(self, new_cwd: Path) -> None:
        """Change the panel's directory and refresh its listing."""

    def refresh_listing(self) -> None:
        """Re-read the current directory (after sort/hidden toggles)."""

    def toggle_tag(self, path: Path | None = None) -> bool: ...

    def tag_glob(self, pattern: str) -> int: ...

    def untag_glob(self, pattern: str) -> int: ...

    def clear_tags(self) -> int: ...

    def tagged_paths(self) -> list[Path]: ...

    def selection(self) -> list[Path]: ...

    def move_cursor_down(self) -> None: ...


class AppProtocol(Protocol):
    """The slice of :class:`~sansdir.app.SansdirApp` that handlers touch."""

    @property
    def active_panel(self) -> PanelProtocol: ...

    @property
    def inactive_panel(self) -> PanelProtocol: ...

    def set_active(self, panel_id: str) -> None:
        """``panel_id`` ∈ ``{"left", "right", "other"}``."""

    def swap_panels(self) -> None: ...

    def toggle_max(self) -> None: ...

    def show_help(self) -> None: ...

    def quit_app(self) -> None: ...

    def focus_cmdline(self) -> None: ...

    def cmdline_prompt(self, text: str) -> None: ...

    def run_shell(self, cmd_line: str) -> int: ...

    async def confirm(self, message: str, *, danger: bool = False) -> bool: ...

    def notify_user(self, message: str, *, severity: str = "information") -> None: ...

    def edit_in_editor(self, path: Path) -> int: ...

    def view_in_other_pane(self, path: Path) -> bool: ...

    def close_inline_viewer(self, panel_id: str) -> None: ...

    def is_other_pane_viewing(self) -> bool: ...

    def show_catalog_in_other_pane(self, ipts: str, files: list) -> None: ...  # type: ignore[type-arg]

    def toggle_other_pane_catalog(self) -> None: ...
