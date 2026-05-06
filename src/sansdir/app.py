"""``SansdirApp`` — the Textual app shell.

Hosts two :class:`~sansdir.ui.panel.FilePanel` instances, one
:class:`~sansdir.ui.statusbar.StatusBar`, one
:class:`~sansdir.ui.command_input.CommandInput`, and routes every keystroke
through :meth:`~sansdir.commands.registry.CommandRegistry.dispatch` per the
keymap in :mod:`sansdir.ui.keys`. There is no business logic in this file
— :meth:`SansdirApp.on_key` is the only translation between Textual events
and registered commands (``PLANNING.md`` §12.6).

The ``:``-line at the bottom is always visible. ``:`` focuses it, ``Esc``
returns focus to the active pane, ``Enter`` parses + dispatches via
:func:`sansdir.commands.parser.parse_command_line`.
"""

from __future__ import annotations

import asyncio
import shlex
import subprocess
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input

from sansdir.commands.builtins import build_default_registry
from sansdir.commands.parser import ParseError, parse_command_line
from sansdir.commands.registry import CommandRegistry, UnknownCommandError
from sansdir.core.history import CommandHistory
from sansdir.ui.command_input import CommandInput, CommandLineRow
from sansdir.ui.help import HelpScreen
from sansdir.ui.key_hint_bar import KeyHintBar
from sansdir.ui.keys import KeyBinding, default_keymap
from sansdir.ui.pane_slot import PaneSlot
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
    #panes > PaneSlot {
        width: 1fr;
    }
    /* Maximize state: hide the inactive pane by giving it 0% width. */
    #panes.-max-left  > #slot-right { display: none; }
    #panes.-max-right > #slot-left  { display: none; }
    """

    def __init__(
        self,
        start_path: str | Path | None = None,
        *,
        right_path: str | Path | None = None,
        history: CommandHistory | None = None,
    ) -> None:
        super().__init__()
        start = Path(start_path).expanduser().resolve() if start_path else Path.cwd()
        right = Path(right_path).expanduser().resolve() if right_path else start
        self._start_left = start
        self._start_right = right
        self._left = FilePanel(self._start_left, panel_id="left")
        self._right = FilePanel(self._start_right, panel_id="right")
        self._left_slot = PaneSlot(self._left, panel_id="left")
        self._right_slot = PaneSlot(self._right, panel_id="right")
        self._panes: Horizontal = Horizontal(self._left_slot, self._right_slot, id="panes")
        self._statusbar = StatusBar()
        self._history = history if history is not None else CommandHistory()
        self.registry: CommandRegistry = build_default_registry(app=self)
        self.keymap: list[KeyBinding] = default_keymap()
        self._cmdline = CommandInput(registry=self.registry, history=self._history)
        self._cmdline_row = CommandLineRow(self._cmdline)
        self._hintbar = KeyHintBar(self.keymap)
        self._active_id: str = "left"
        self._max: bool = False

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            yield self._panes
            yield self._statusbar
            yield self._hintbar
            yield self._cmdline_row

    def on_mount(self) -> None:
        self._apply_active_class()
        self._refresh_status()
        self.set_focus(self.active_panel)

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

    def focus_cmdline(self) -> None:
        self.set_focus(self._cmdline)

    def cmdline_prompt(self, text: str) -> None:
        """Open the command line pre-filled with ``text``, cursor at end."""
        self._cmdline.value = text
        self._cmdline.cursor_position = len(text)
        self.set_focus(self._cmdline)

    async def confirm(self, message: str, *, danger: bool = False) -> bool:
        """Show a yes/no modal; return the user's choice.

        Uses an explicit Future + callback because :meth:`push_screen_wait`
        requires being inside a Textual worker, which our keymap-dispatch
        coroutines are not.
        """
        from sansdir.ui.dialogs import ConfirmDialog

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bool] = loop.create_future()

        def _on_dismiss(value: bool | None) -> None:
            if not fut.done():
                fut.set_result(bool(value))

        self.push_screen(ConfirmDialog(message, danger=danger), _on_dismiss)
        return await fut

    def notify_user(self, message: str, *, severity: str = "information") -> None:
        """Surface a message in the status notifier."""
        self.notify(message, severity=severity)  # type: ignore[arg-type]

    def edit_in_editor(self, path: Path) -> int:
        """Suspend the TUI and exec ``$EDITOR`` (or ``vi``) on ``path``."""
        import os as _os

        editor = _os.environ.get("EDITOR") or _os.environ.get("VISUAL") or "vi"
        cmd = f"{editor} {shlex.quote(str(path))}"
        return self.run_shell(cmd)

    # ------------------------------------------------------------------
    # Inline file viewer (Norton-style preview in the *other* pane)
    # ------------------------------------------------------------------

    def view_in_other_pane(self, path: Path) -> bool:
        """Show ``path`` in the inactive pane's slot. Returns False on binary."""
        slot = self._inactive_slot
        ok = slot.show_viewer(path)
        if not ok:
            slot.show_panel()
            self.notify_user(
                "binary or unreadable file — viewer dismissed",
                severity="warning",
            )
        # Keep focus on the active panel — the whole point is that the user
        # keeps navigating while the file content is shown next to them.
        self.set_focus(self.active_panel)
        return ok

    def close_inline_viewer(self, panel_id: str) -> None:
        """Restore the FilePanel in the named slot."""
        slot = self._left_slot if panel_id == "left" else self._right_slot
        slot.show_panel()
        self.set_focus(self.active_panel)

    def is_other_pane_viewing(self) -> bool:
        return self._inactive_slot.viewer_visible

    @property
    def _active_slot(self) -> PaneSlot:
        return self._left_slot if self._active_id == "left" else self._right_slot

    @property
    def _inactive_slot(self) -> PaneSlot:
        return self._right_slot if self._active_id == "left" else self._left_slot

    def run_shell(self, cmd_line: str) -> int:
        """Run ``cmd_line`` in a subshell, suspending the TUI while it runs.

        Returns the subprocess's exit code. Errors are surfaced via
        :meth:`App.notify`; a non-zero return is *not* treated as an
        exception so ``$?`` style failures land in the status bar like
        any other shell.
        """
        cmd_line = cmd_line.strip()
        if not cmd_line:
            return 0
        try:
            with self.suspend():
                result = subprocess.run(cmd_line, shell=True, check=False)
        except OSError as exc:
            self.notify(f"shell error: {exc}", severity="error")
            return -1
        if result.returncode != 0:
            self.notify(
                f"shell exited {result.returncode}: {cmd_line}",
                severity="warning",
            )
        return result.returncode

    # ------------------------------------------------------------------
    # Event routing — the *only* place keystrokes become commands.
    # ------------------------------------------------------------------

    async def on_key(self, event: events.Key) -> None:
        # If a modal (help, dialogs) is on top, let it handle keys.
        if self.screen is not self.screen_stack[0]:
            return
        # If the user is typing in the ``:``-input, hands off — the input's
        # own bindings handle Up/Down/Tab/Esc and normal characters.
        if self.focused is self._cmdline:
            return
        for kb in self.keymap:
            if event.key == kb.key:
                event.stop()
                event.prevent_default()
                self._dispatch(kb)
                return

    def _dispatch(self, kb: KeyBinding) -> None:
        """Run the handler inline (sync) or as a worker (async).

        Handlers that ``await`` on a modal (push_screen + callback Future)
        must run in a worker to avoid deadlocking against the App's event
        loop. **Sync** handlers, however, must run **inline** — otherwise
        side effects like ``set_focus(self._cmdline)`` (driven by the
        ``app.cmdline_open`` handler) don't take effect before Textual
        processes the user's *next* keystroke, and the keymap re-intercepts
        characters that should have gone into the input.
        """
        try:
            kwargs = kb.resolve(self)
        except Exception as exc:
            self.notify(f"resolver error for {kb.key}: {exc}", severity="error")
            return
        try:
            cmd = self.registry.get(kb.command)
        except UnknownCommandError:
            self.notify(f"unknown command: {kb.command}", severity="error")
            return
        if asyncio.iscoroutinefunction(cmd.handler):
            self.run_worker(
                self._dispatch_async(kb.command, kwargs),
                name=f"dispatch:{kb.command}",
                exclusive=False,
            )
        else:
            self._dispatch_sync(cmd, kwargs)

    def _dispatch_sync(self, cmd, kwargs: dict[str, object]) -> None:  # type: ignore[no-untyped-def]
        try:
            CommandRegistry._validate_kwargs(cmd, kwargs)
            cmd.handler(**kwargs)
        except (NotADirectoryError, FileNotFoundError, PermissionError) as exc:
            self.notify(f"{type(exc).__name__}: {exc}", severity="warning")
        except Exception as exc:
            self.notify(f"{cmd.name} failed: {exc}", severity="error")
        finally:
            self._refresh_status()

    async def _dispatch_async(self, name: str, kwargs: dict[str, object]) -> None:
        try:
            await self.registry.dispatch(name, **kwargs)
        except UnknownCommandError:
            self.notify(f"unknown command: {name}", severity="error")
        except (NotADirectoryError, FileNotFoundError, PermissionError) as exc:
            self.notify(f"{type(exc).__name__}: {exc}", severity="warning")
        except Exception as exc:
            self.notify(f"{name} failed: {exc}", severity="error")
        finally:
            self._refresh_status()

    # ------------------------------------------------------------------
    # ``:``-line submission
    # ------------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input is not self._cmdline:
            return
        text = event.value.strip()
        # Always clear the visible line and return focus, even on parse error.
        self._cmdline.value = ""
        self.set_focus(self.active_panel)
        if not text:
            return
        self._history.append(text)
        await self.run_command_line(text)

    async def run_command_line(self, text: str) -> None:
        """Parse a ``:``-line and dispatch it through the registry.

        Public so ``:!cmd`` macros, the LLM layer, and tests can drive the
        same code path the user does.
        """
        try:
            cmd, kwargs = parse_command_line(text, self.registry)
        except ParseError as exc:
            self.notify(f"parse error: {exc}", severity="error")
            return
        try:
            result = await self.registry.dispatch(cmd.name, **kwargs)
        except (NotADirectoryError, FileNotFoundError, PermissionError) as exc:
            self.notify(f"{type(exc).__name__}: {exc}", severity="warning")
            return
        except Exception as exc:
            self.notify(f"{cmd.name} failed: {exc}", severity="error")
            return
        finally:
            self._refresh_status()
        if isinstance(result, (int, float, bool)) and not isinstance(result, bool):
            self.notify(f"{cmd.name} → {result}", timeout=2)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apply_active_class(self) -> None:
        self._left.set_class(self._active_id == "left", "-active")
        self._right.set_class(self._active_id == "right", "-active")

    def _refresh_status(self) -> None:
        panel = self.active_panel
        try:
            count = len(panel._entries)
        except AttributeError:
            count = 0
        self._statusbar.update_for(panel.cwd, count)


def run_tui(start_path: str | Path | None = None) -> int:
    """Synchronous entry point used by ``cli.tui`` / ``python -m sansdir``."""
    app = SansdirApp(start_path=start_path)
    return asyncio.run(app.run_async()) or 0
