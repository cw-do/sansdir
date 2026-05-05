"""``SansdirApp`` — the Textual app shell.

Hosts two :class:`~sansdir.ui.panel.FilePanel` instances, one
:class:`~sansdir.ui.statusbar.StatusBar`, and routes every keystroke through
:meth:`~sansdir.commands.registry.CommandRegistry.dispatch` per the keymap
in :mod:`sansdir.ui.keys`. There is no business logic in this file — the
event handler at :meth:`SansdirApp.on_key` is the only translation between
Textual events and registered commands (``PLANNING.md`` §12.6).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical

from sansdir.commands.builtins import build_default_registry
from sansdir.commands.registry import CommandRegistry, UnknownCommandError
from sansdir.ui.help import HelpScreen
from sansdir.ui.keys import KeyBinding, default_keymap
from sansdir.ui.panel import FilePanel
from sansdir.ui.statusbar import StatusBar


class SansdirApp(App[int]):
    """The dual-pane MDIR-style file manager."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #panes {
        height: 1fr;
    }
    #panes > FilePanel {
        width: 1fr;
    }
    /* Maximize state: hide the inactive pane by giving it 0% width. */
    #panes.-max-left  > #right { display: none; }
    #panes.-max-right > #left  { display: none; }
    """

    def __init__(
        self,
        start_path: str | Path | None = None,
        *,
        right_path: str | Path | None = None,
    ) -> None:
        super().__init__()
        start = Path(start_path).expanduser().resolve() if start_path else Path.cwd()
        right = Path(right_path).expanduser().resolve() if right_path else start
        self._start_left = start
        self._start_right = right
        self._left = FilePanel(self._start_left, panel_id="left")
        self._right = FilePanel(self._start_right, panel_id="right")
        self._panes: Horizontal = Horizontal(self._left, self._right, id="panes")
        self._statusbar = StatusBar()
        self._active_id: str = "left"
        self._max: bool = False
        # Registry built lazily in on_mount so the FakeApp tests never spin
        # up a real Textual instance.
        self.registry: CommandRegistry = build_default_registry(app=self)
        self.keymap: list[KeyBinding] = default_keymap()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            yield self._panes
            yield self._statusbar

    def on_mount(self) -> None:
        self._apply_active_class()
        self._refresh_status()

    # ------------------------------------------------------------------
    # AppProtocol surface (used by command handlers in commands/builtins.py)
    # ------------------------------------------------------------------

    @property
    def active_panel(self) -> FilePanel:
        return self._left if self._active_id == "left" else self._right

    @property
    def inactive_panel(self) -> FilePanel:
        return self._right if self._active_id == "left" else self._left

    def set_active(self, panel_id: str) -> None:
        if panel_id == "other":
            panel_id = "right" if self._active_id == "left" else "left"
        if panel_id not in ("left", "right"):
            raise ValueError(f"unknown panel_id {panel_id!r}")
        self._active_id = panel_id
        self._apply_active_class()
        self.set_focus(self.active_panel)
        self._refresh_status()

    def swap_panels(self) -> None:
        # Swap cwds (cheaper and more semantically MDIR-like than swapping
        # the widget instances themselves).
        l_cwd = self._left.cwd
        r_cwd = self._right.cwd
        self._left.set_cwd(r_cwd)
        self._right.set_cwd(l_cwd)
        self._refresh_status()

    def toggle_max(self) -> None:
        self._max = not self._max
        self._panes.set_class(self._max and self._active_id == "left", "-max-left")
        self._panes.set_class(self._max and self._active_id == "right", "-max-right")

    def show_help(self) -> None:
        self.push_screen(HelpScreen(self.registry, self.keymap))

    def quit_app(self) -> None:
        self.exit(0)

    # ------------------------------------------------------------------
    # Event routing — the *only* place keystrokes become commands.
    # ------------------------------------------------------------------

    async def on_key(self, event: events.Key) -> None:
        # If the help overlay (or any modal) is on top, let it handle keys.
        if self.screen is not self.screen_stack[0]:
            return
        for kb in self.keymap:
            if event.key == kb.key:
                event.stop()
                event.prevent_default()
                await self._dispatch(kb)
                return

    async def _dispatch(self, kb: KeyBinding) -> None:
        try:
            kwargs = kb.resolve(self)
        except Exception as exc:
            self.notify(f"resolver error for {kb.key}: {exc}", severity="error")
            return
        try:
            await self.registry.dispatch(kb.command, **kwargs)
        except UnknownCommandError:
            self.notify(f"unknown command: {kb.command}", severity="error")
        except (NotADirectoryError, FileNotFoundError, PermissionError) as exc:
            self.notify(f"{type(exc).__name__}: {exc}", severity="warning")
        except Exception as exc:
            self.notify(f"{kb.command} failed: {exc}", severity="error")
        finally:
            self._refresh_status()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apply_active_class(self) -> None:
        self._left.set_class(self._active_id == "left", "-active")
        self._right.set_class(self._active_id == "right", "-active")

    def _refresh_status(self) -> None:
        panel = self.active_panel
        # ``len(panel._entries)`` is private; expose count via len(rows) instead.
        try:
            count = len(panel._entries)
        except AttributeError:
            count = 0
        self._statusbar.update_for(panel.cwd, count)


def run_tui(start_path: str | Path | None = None) -> int:
    """Synchronous entry point used by ``cli.tui`` / ``python -m sansdir``."""
    app = SansdirApp(start_path=start_path)
    return asyncio.run(app.run_async()) or 0
