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

    @property
    def cursor_path(self) -> Path | None:
        """Absolute path under the cursor, or ``None`` for an empty pane."""

    def set_cwd(self, new_cwd: Path) -> None:
        """Change the panel's directory and refresh its listing."""

    def refresh_listing(self) -> None:
        """Re-read the current directory (after sort/hidden toggles)."""


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
