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
from typing import ClassVar

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.dom import DOMNode
from textual.widgets import Input

from sansdir.commands.builtins import build_default_registry
from sansdir.commands.parser import ParseError, parse_command_line
from sansdir.commands.registry import CommandRegistry, UnknownCommandError
from sansdir.config import load_config
from sansdir.core.history import CommandHistory
from sansdir.core.instrument import mode_for_instrument, normalise_instrument, resolve_instrument
from sansdir.ui.command_input import CommandInput, CommandLineRow
from sansdir.ui.help import HelpScreen
from sansdir.ui.key_hint_bar import KeyHintBar
from sansdir.ui.keys import KeyBinding, default_keymap
from sansdir.ui.pane_slot import PaneSlot
from sansdir.ui.panel import FilePanel
from sansdir.ui.pathbar import PathBar
from sansdir.ui.statusbar import StatusBar
from sansdir.ui.titlebar import TitleBar


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
        self._pathbar = PathBar(self._left, self._right)
        self._statusbar = StatusBar()
        self._history = history if history is not None else CommandHistory()
        self.registry: CommandRegistry = build_default_registry(app=self)
        self._cfg = load_config()
        # Instrument mode: a launch path under /SNS/USANS (or any path
        # containing "usans") auto-selects USANS; otherwise the configured
        # default, falling back to [oncat].default_instrument — which is
        # exactly what every pre-USANS session did.
        self._instrument: str = resolve_instrument(
            (self._start_left, self._start_right),
            configured=self._cfg.instrument.default,
            fallback=self._cfg.oncat.default_instrument,
            auto_detect=self._cfg.instrument.auto_detect,
        )
        # Build the keymap, then apply [keys] overrides from config so
        # power users can rebind without forking the source.
        self.keymap: list[KeyBinding] = _apply_keymap_overrides(
            default_keymap(mode=self.instrument_mode), self._cfg.keys.overrides, self.registry
        )
        self._cmdline = CommandInput(registry=self.registry, history=self._history)
        self._cmdline_row = CommandLineRow(self._cmdline)
        self._hintbar = KeyHintBar(self.keymap, mode=self.instrument_mode)
        self._titlebar = TitleBar(self._instrument)
        self._active_id: str = "left"
        self._max: bool = False
        # Set while pick_file_in_other_pane() is awaiting a choice; on_key
        # routes Enter/Esc to it and suppresses the rest of the keymap.
        self._pick_future: asyncio.Future[Path | None] | None = None

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            yield self._titlebar
            yield self._pathbar
            yield self._panes
            yield self._statusbar
            yield self._hintbar
            yield self._cmdline_row

    def on_mount(self) -> None:
        # Apply the configured theme. Unknown names fall back to the
        # built-in default with a notify so a typo never blocks startup.
        try:
            self.theme = self._cfg.ui.theme
        except Exception as exc:
            self.notify(
                f"theme '{self._cfg.ui.theme}' not available ({exc}); "
                "using default. Try one of: " + ", ".join(sorted(self.available_themes)),
                severity="warning",
            )
        self._apply_active_class()
        self._refresh_status()
        self.set_focus(self.active_panel)

    # ------------------------------------------------------------------
    # AppProtocol surface (used by command handlers in commands/builtins.py)
    # ------------------------------------------------------------------

    # ---- instrument mode ---------------------------------------------

    @property
    def instrument(self) -> str:
        """Instrument this session targets — drives OnCat and catalog columns."""
        return self._instrument

    @property
    def instrument_mode(self) -> str:
        """``"SANS"`` or ``"USANS"``; see :mod:`sansdir.core.instrument`."""
        return mode_for_instrument(self._instrument)

    def set_instrument(self, name: str) -> str:
        """Switch instrument, rebuilding anything the mode changes.

        The keymap and hint bar are rebuilt because USANS adds ``r``; the
        catalog is re-rendered because USANS uses different columns. The
        registry is *not* rebuilt — every command stays registered in both
        modes so ``:usans reduce`` works even if someone forgot to switch.

        Returns:
            The normalised instrument name now in effect.
        """
        previous_mode = self.instrument_mode
        self._instrument = normalise_instrument(name)
        if self.instrument_mode != previous_mode:
            self.keymap = _apply_keymap_overrides(
                default_keymap(mode=self.instrument_mode),
                self._cfg.keys.overrides,
                self.registry,
            )
            self._hintbar.set_keymap(self.keymap, mode=self.instrument_mode)
        self._titlebar.set_instrument(self._instrument)
        # Re-render the catalog so its columns follow the new mode.
        catalog = self._right_slot.catalog
        if self._right_slot.has_catalog:
            catalog.set_instrument(self._instrument)
        self._refresh_status()
        return self._instrument

    def loaded_catalog(self) -> tuple[str, list] | None:  # type: ignore[type-arg]
        """``(ipts, runs)`` for the loaded run catalog, or ``None``.

        Reads the *unfiltered* run list: a ``/`` filter narrows what the
        user is looking at, not what a generated reduction table should
        cover.
        """
        right = self._right_slot
        if not right.has_catalog:
            return None
        return right.catalog.ipts, right.catalog.all_files

    @property
    def active_panel(self) -> FilePanel:
        return self._left if self._active_id == "left" else self._right

    @property
    def inactive_panel(self) -> FilePanel:
        return self._right if self._active_id == "left" else self._left

    @property
    def working_panel(self) -> FilePanel:
        """The pane whose cwd the user is actually working in.

        Normally the active pane. But when the active slot is showing the
        **run catalog**, its underlying FilePanel's cwd is incidental —
        the catalog covers it, and the directory the user navigated to
        lives in the *other* pane (``i`` cds the active pane into
        ``<IPTS>/shared`` and loads the catalog opposite it). Commands
        that write a file "here" should follow the user's eye, not the
        hidden panel behind the table.
        """
        if self._active_slot.catalog_visible:
            return self.inactive_panel
        return self.active_panel

    def focus_active_surface(self) -> None:
        """Focus the right widget in the active slot.

        Each PaneSlot can show one of three things — file panel, run
        catalog, or inline viewer — and only the visible widget is
        focusable. We dispatch to the matching focus target so that
        Tab and similar key paths land users on something useful.
        """
        slot = self._active_slot
        if slot.catalog_visible:
            self.set_focus(slot.catalog.table)
        elif slot.viewer_visible:
            self.set_focus(slot.viewer)
        else:
            self.set_focus(self.active_panel)

    def set_active(self, panel_id: str) -> None:
        if panel_id == "other":
            panel_id = "right" if self._active_id == "left" else "left"
        if panel_id not in ("left", "right"):
            raise ValueError(f"unknown panel_id {panel_id!r}")
        self._active_id = panel_id
        self._apply_active_class()
        # Pick a focus target based on the new active slot's mode —
        # the wrapping container isn't focusable on its own.
        target_slot = self._left_slot if panel_id == "left" else self._right_slot
        if target_slot.catalog_visible:
            self.set_focus(target_slot.catalog.table)
        elif target_slot.viewer_visible:
            self.set_focus(target_slot.viewer)
        else:
            self.set_focus(self.active_panel)
        self._refresh_status()

    def _sync_active_id(self, panel_id: str) -> None:
        """Update ``_active_id`` without moving focus.

        Companion to :meth:`set_active`. Used by the focus watcher so
        a mouse click that lands inside a slot drags the active
        marker (border, status bar, keymap target) along with it,
        without re-firing ``set_focus`` and risking a focus loop.
        """
        if panel_id == self._active_id or panel_id not in ("left", "right"):
            return
        self._active_id = panel_id
        self._apply_active_class()
        self._refresh_status()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """Keep ``_active_id`` in sync with whatever Textual focuses.

        Textual auto-focuses the widget under a mouse click, but our
        keymap dispatches to ``self.active_panel`` based on
        ``_active_id``. Without this hook, clicking the other pane
        moved focus visually but left every keystroke targeting the
        previous pane — a confusing split-state.
        """
        widget = event.widget
        # Modals (help, dialogs, picker) own their own focus; ignore.
        if self.screen is not self.screen_stack[0]:
            return
        node: DOMNode | None = widget
        while node is not None:
            if node is self._left_slot:
                self._sync_active_id("left")
                return
            if node is self._right_slot:
                self._sync_active_id("right")
                return
            node = node.parent

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
        # Best-effort: close any matplotlib figures the user opened during
        # the session so they don't outlive the TUI process.
        try:
            from sansdir.plot.backend import close_all

            close_all()
        except ImportError:
            pass
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

    async def pick_file_in_other_pane(
        self,
        message: str,
        *,
        title: str = "Select a file",
        help_text: str = "",
        start_dir: Path | None = None,
    ) -> Path | None:
        """Ask a question in this pane; let the user answer in the other one.

        A modal would cover the very file list the user has to read. Instead
        the question goes into the active slot and the *opposite* pane becomes
        active, so arrows, ``/`` filtering and ``Backspace`` all work exactly
        as they normally do while choosing. ``Enter`` picks the file under the
        cursor, ``Esc`` declines.

        Args:
            message: The question. Rich markup allowed.
            title: Heading above it.
            help_text: Extra guidance under the question.
            start_dir: Directory to show the picking pane in; defaults to
                wherever that pane already is.

        Returns:
            The chosen file, or ``None`` if the user pressed ``Esc``.
        """
        if self._pick_future is not None:
            self.notify_user("already waiting for a file selection", severity="warning")
            return None

        asking_id = self._active_id
        picking_id = "right" if asking_id == "left" else "left"
        asking_slot = self._left_slot if asking_id == "left" else self._right_slot
        picking_slot = self._right_slot if asking_id == "left" else self._left_slot
        picking_panel = self._right if asking_id == "left" else self._left

        # Remember what the picking pane was showing so we can put it back.
        restore_mode = picking_slot.mode
        restore_cwd = picking_panel.cwd
        asking_slot.show_prompt(title, message, help_text)
        picking_slot.show_panel()
        if start_dir is not None and Path(start_dir).is_dir():
            picking_panel.set_cwd(Path(start_dir))
        self.set_active(picking_id)

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Path | None] = loop.create_future()
        self._pick_future = fut
        try:
            chosen = await fut
        finally:
            self._pick_future = None
            asking_slot.show_panel()
            if restore_mode == "catalog" and picking_slot.has_catalog:
                picking_slot.show_catalog(
                    picking_slot.catalog.ipts,
                    picking_slot.catalog.all_files,
                    instrument=picking_slot.catalog.instrument,
                    facility=picking_slot.catalog.facility,
                )
            elif start_dir is not None:
                picking_panel.set_cwd(restore_cwd)
            self.set_active(asking_id)
        return chosen

    def _resolve_pick(self, value: Path | None) -> None:
        """Complete an in-flight :meth:`pick_file_in_other_pane`."""
        fut = self._pick_future
        if fut is not None and not fut.done():
            fut.set_result(value)

    def revalidate_panes(self) -> None:
        """Bring both slots back in step with the filesystem.

        Called after anything that can delete or move files. Two states it
        repairs: a pane sitting inside a directory that no longer exists
        (re-anchored to the nearest surviving ancestor by
        :meth:`FilePanel.refresh_listing`), and an inline viewer still
        showing a deleted file.
        """
        for slot in (self._left_slot, self._right_slot):
            slot.revalidate()
        self._left.refresh_listing()
        self._right.refresh_listing()

    def show_catalog_in_other_pane(
        self,
        ipts: str,
        files: list,  # type: ignore[type-arg]
        *,
        instrument: str = "",
        facility: str = "SNS",
    ) -> None:
        """Mount the OnCat run catalog. Always opens on the *right* slot.

        We deliberately don't honour "inactive" or "active" — putting
        the catalog on a fixed side keeps the mental model simple
        (right is "where IPTS data lives", left is "where I work"). If
        the user pressed ``i`` from the right pane it still lands on
        the right pane; the right slot's underlying FilePanel was cd'd
        into ``IPTS/shared`` by the caller, so F2 to hide reveals that
        directory.
        """
        self._right_slot.show_catalog(
            ipts, files, instrument=instrument or self.instrument, facility=facility
        )
        # Keep focus on whatever the user was doing — this is the
        # MDIR-style "load it on the side, you keep navigating" flow.
        self.focus_active_surface()
        self._refresh_status()

    def toggle_other_pane_catalog(self) -> None:
        """F2 — show/hide the run catalog on the right pane.

        The catalog always lives on the right (per
        :meth:`show_catalog_in_other_pane`), so F2 is a simple toggle.
        Loading via the user's last ``i`` is replayed when the right
        slot has been emptied via F2 but still remembers a catalog.
        """
        right = self._right_slot
        if not right.has_catalog and not right.catalog_visible:
            self.notify_user(
                "no run catalog loaded yet — press `i` to pick an IPTS first",
                severity="warning",
            )
            return
        if right.catalog_visible:
            # Hide → reveal the right FilePanel underneath.
            right.show_panel()
            # If the user was focused on the catalog, send focus to
            # the right pane's now-visible file list. Otherwise leave
            # focus where it was so the active-pane workflow stays
            # uninterrupted.
            if self._active_id == "right":
                self.set_focus(self._right)
            else:
                self.focus_active_surface()
        else:
            # Preserve the instrument/facility the catalog was loaded with —
            # re-showing with the defaults would silently relabel a USANS
            # catalog as EQSANS and break its raw-file paths.
            right.show_catalog(
                right.catalog.ipts,
                right.catalog.all_files,
                instrument=right.catalog.instrument,
                facility=right.catalog.facility,
            )
            if self._active_id == "right":
                # User explicitly Tab'd to the right pane before F2;
                # focus the catalog table so Up/Down work right away.
                self.set_focus(right.catalog.table)
            else:
                self.focus_active_surface()
        self._refresh_status()

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
        # A pick_file_in_other_pane() is waiting for an answer. Enter chooses,
        # Esc declines, and a short allowlist keeps navigating; everything
        # else is swallowed so `q` cannot quit and `d`/`r` cannot re-enter a
        # command out from under the pending one.
        if self._pick_future is not None:
            self._on_key_while_picking(event)
            return
        # CatalogTable owns its own ``p`` / ``Enter`` (plot raw run),
        # ``m`` (HDF5 tree for the cursor's run), ``M`` (batch-extract
        # the selection), ``K`` (mask editor), ``space`` (tag run) and
        # ``u`` (clear tags). For every other key (Tab, q, :, ?,
        # F-keys, …) we still want the App's keymap to fire normally —
        # and a blanket "skip-when-focused-binds-anything" check would
        # also kill Enter on a FilePanel, where DataTable's row-select
        # binding shouldn't block ``nav.cd``.
        if event.key in ("p", "enter", "m", "M", "K", "space", "u") and _is_catalog_table(
            self.focused
        ):
            return
        # Inline viewer owns ``q`` / ``escape`` (close-from-the-viewer).
        # Without this branch the App's ``q`` keymap entry would quit
        # the whole app instead.
        if event.key in ("q", "escape") and _is_inline_viewer(self.focused):
            return
        for kb in self.keymap:
            if event.key == kb.key:
                event.stop()
                event.prevent_default()
                self._dispatch(kb)
                return

    # Keys that still reach the keymap while a file pick is in flight: pure
    # navigation and filtering of the pane the user is choosing in.
    _PICK_ALLOWED: ClassVar[frozenset[str]] = frozenset(
        {"backspace", "slash", "/", "h", "1", "2", "3", "4", "g", "G"}
    )

    def _on_key_while_picking(self, event: events.Key) -> None:
        """Route a keystroke while :meth:`pick_file_in_other_pane` is awaiting."""
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self._resolve_pick(None)
            return
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            cursor = self.active_panel.cursor_path
            if cursor is None or not cursor.is_file():
                self.notify_user(
                    "that is not a file — pick one, or Esc to skip", severity="warning"
                )
                return
            self._resolve_pick(cursor)
            return
        if event.key in self._PICK_ALLOWED:
            for kb in self.keymap:
                if event.key == kb.key:
                    event.stop()
                    event.prevent_default()
                    self._dispatch(kb)
                    return
            return
        # Arrows / j / k / page keys are the DataTable's own bindings; let
        # them through untouched. Anything else is swallowed.
        if event.key not in ("up", "down", "j", "k", "pageup", "pagedown", "home", "end"):
            event.stop()
            event.prevent_default()

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
        self.focus_active_surface()
        if not text:
            return
        self._history.append(text)
        # Run command-line dispatch as a worker for the same reason the
        # keymap path does: async handlers (e.g. ones that show a modal)
        # would otherwise deadlock against the App event loop.
        self.run_worker(
            self.run_command_line(text),
            name=f"cmdline:{text[:32]}",
            exclusive=False,
        )

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
        # Mirror the active marker in the path bar so the user can
        # tell at a glance which pane's cwd the keymap targets.
        self._pathbar.set_active(self._active_id)

    def _refresh_status(self) -> None:
        panel = self.active_panel
        try:
            count = len(panel._entries)
        except AttributeError:
            count = 0
        # Catalog summary lives in the middle of the status bar — it's
        # a "ready / not ready" indicator the user can glance at to see
        # whether F2 / M from the catalog will do anything useful.
        right = self._right_slot
        catalog_summary = ""
        if right.has_catalog:
            ipts = right.catalog.ipts
            n = len(right.catalog.all_files)
            tagged = len(right.catalog.tagged_runs)
            visible = "visible" if right.catalog_visible else "loaded"
            tail = f" · {tagged} tagged" if tagged else ""
            catalog_summary = f"catalog {visible}: {ipts} ({n} runs{tail})"
        self._statusbar.update_for(
            count,
            filter_substring=panel.filter_substring,
            tag_count=len(panel.tags),
            catalog_summary=catalog_summary,
        )


def _apply_keymap_overrides(
    base: list[KeyBinding],
    overrides: dict[str, str],
    registry: CommandRegistry,
) -> list[KeyBinding]:
    """Apply ``[keys]`` config to ``base`` and return the merged keymap.

    Each override entry has the form ``key = "command.name"``. Existing
    keymap entries with the same ``key`` are replaced; entries pointing
    at unknown commands are dropped (the *default* binding is kept so
    the user isn't left with a dead key). New ``key``s are appended.
    Resolver functions don't survive override (the user's command name
    drives args from the cursor / selection rather than via a static
    resolver), so most rebindings are zero-arg style commands.
    """
    if not overrides:
        return base
    by_key = {kb.key: kb for kb in base}
    for key, command in overrides.items():
        try:
            registry.get(command)
        except KeyError:
            # Unknown command name — leave the default binding alone.
            continue
        by_key[key] = KeyBinding(
            key=key,
            command=command,
            description=f"(custom) {command}",
        )
    return list(by_key.values())


def _is_catalog_table(widget) -> bool:  # type: ignore[no-untyped-def]
    """True iff ``widget`` is a :class:`CatalogTable` (or subclass).

    Imported lazily so the catalog module isn't pulled in by
    everything that touches ``app.py`` (keeps the cold-start budget
    intact).
    """
    if widget is None:
        return False
    try:
        from sansdir.ui.run_catalog import CatalogTable
    except ImportError:  # pragma: no cover
        return False
    return isinstance(widget, CatalogTable)


def _is_inline_viewer(widget) -> bool:  # type: ignore[no-untyped-def]
    """True iff ``widget`` is an :class:`InlineFileViewer` (or subclass)."""
    if widget is None:
        return False
    try:
        from sansdir.ui.inline_viewer import InlineFileViewer
    except ImportError:  # pragma: no cover
        return False
    return isinstance(widget, InlineFileViewer)


def run_tui(start_path: str | Path | None = None) -> int:
    """Synchronous entry point used by ``cli.tui`` / ``python -m sansdir``."""
    app = SansdirApp(start_path=start_path)
    return asyncio.run(app.run_async()) or 0
