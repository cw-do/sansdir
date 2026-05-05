"""Built-in command registrations.

Two registration modes:

* **App-agnostic** (``app=None``): only commands that need no running app
  are registered. Used by tests, the LLM tool-schema export, and the CLI's
  ``--help`` path so importing the registry never drags Textual along.

* **App-bound** (``app=<SansdirApp>``): all Phase-1+ commands are
  registered; their handlers close over ``app`` to mutate panel state via
  the :class:`~sansdir.commands._protocols.AppProtocol` surface.

Per ``PLANNING.md`` §12.6, every key handler and every ``:`` line goes
through :meth:`CommandRegistry.dispatch` — handlers never bypass it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from sansdir.commands.registry import Command, CommandParam, CommandRegistry
from sansdir.core import fileops
from sansdir.core.filesystem import VALID_SORT_KEYS

if TYPE_CHECKING:
    from sansdir.commands._protocols import AppProtocol


# ---------------------------------------------------------------------------
# app-agnostic commands
# ---------------------------------------------------------------------------


def _make_app_quit(app: AppProtocol | None) -> Command:
    """``app.quit`` — exits the app when bound, returns sentinel otherwise.

    Returning a sentinel in the unbound form keeps the registry usable in
    tests that don't want a Textual instance running.
    """
    if app is None:

        def handler() -> str:
            return "quit"
    else:

        def handler() -> str:
            app.quit_app()
            return "quit"

    return Command(
        name="app.quit",
        description="Exit the sansdir application.",
        params=(),
        handler=handler,
        aliases=("quit", "q"),
        examples=(":quit", ":q"),
    )


# ---------------------------------------------------------------------------
# app-bound (Phase 1) commands
# ---------------------------------------------------------------------------


def _make_nav_cd(app: AppProtocol) -> Command:
    def handler(path: str) -> str:
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = app.active_panel.cwd / target
        target = target.resolve()
        if not target.is_dir():
            raise NotADirectoryError(target)
        app.active_panel.set_cwd(target)
        return str(target)

    return Command(
        name="nav.cd",
        description="Change the active pane's directory.",
        params=(CommandParam(name="path", type="path", description="Target directory."),),
        handler=handler,
        aliases=("cd",),
        examples=(":cd /SNS/EQSANS/IPTS-12345", ":cd .."),
    )


def _make_nav_up(app: AppProtocol) -> Command:
    def handler() -> str:
        cwd = app.active_panel.cwd
        parent = cwd.parent
        if parent != cwd:
            app.active_panel.set_cwd(parent)
        return str(app.active_panel.cwd)

    return Command(
        name="nav.up",
        description="Go up one directory in the active pane.",
        params=(),
        handler=handler,
    )


def _make_pane_activate(app: AppProtocol) -> Command:
    def handler(panel_id: str) -> str:
        app.set_active(panel_id)
        return panel_id

    return Command(
        name="pane.activate",
        description="Make the named pane (left/right/other) active.",
        params=(
            CommandParam(
                name="panel_id",
                type="enum",
                description="Which pane to activate.",
                choices=["left", "right", "other"],
            ),
        ),
        handler=handler,
    )


def _make_pane_swap(app: AppProtocol) -> Command:
    def handler() -> None:
        app.swap_panels()

    return Command(
        name="pane.swap",
        description="Swap the contents (cwd, cursor, tags) of the two panes.",
        params=(),
        handler=handler,
    )


def _make_pane_sync(app: AppProtocol) -> Command:
    def handler() -> str:
        target = app.active_panel.cwd
        app.inactive_panel.set_cwd(target)
        return str(target)

    return Command(
        name="pane.sync",
        description="Set the inactive pane's directory to match the active pane.",
        params=(),
        handler=handler,
    )


def _make_pane_toggle_max(app: AppProtocol) -> Command:
    def handler() -> None:
        app.toggle_max()

    return Command(
        name="pane.toggle_max",
        description="Toggle maximizing the active pane to full width.",
        params=(),
        handler=handler,
    )


def _make_view_toggle_hidden(app: AppProtocol) -> Command:
    def handler() -> bool:
        panel = app.active_panel
        panel.show_hidden = not panel.show_hidden
        panel.refresh_listing()
        return panel.show_hidden

    return Command(
        name="view.toggle_hidden",
        description="Show/hide dotfiles in the active pane.",
        params=(),
        handler=handler,
    )


def _make_view_set_filter(app: AppProtocol) -> Command:
    def handler(pattern: str = "") -> str:
        app.active_panel.filter_substring = pattern
        return pattern

    return Command(
        name="view.set_filter",
        description="Filter the active pane by substring (empty clears).",
        params=(
            CommandParam(
                name="pattern",
                type="string",
                description="Substring to filter by (empty to clear).",
                required=False,
                default="",
            ),
        ),
        handler=handler,
        aliases=("filter",),
    )


def _make_view_set_sort(app: AppProtocol) -> Command:
    def handler(key: str, reverse: bool = False) -> str:
        panel = app.active_panel
        panel.sort_key = key
        panel.sort_reverse = reverse
        panel.refresh_listing()
        return f"{key}{'(reversed)' if reverse else ''}"

    return Command(
        name="view.set_sort",
        description="Set the active pane's sort key.",
        params=(
            CommandParam(
                name="key",
                type="enum",
                description="Sort key.",
                choices=list(VALID_SORT_KEYS),
            ),
            CommandParam(
                name="reverse",
                type="bool",
                description="Reverse the sort order.",
                required=False,
                default=False,
            ),
        ),
        handler=handler,
    )


def _make_app_help(app: AppProtocol) -> Command:
    def handler() -> None:
        app.show_help()

    return Command(
        name="app.help",
        description="Show the help overlay listing all registered commands.",
        params=(),
        handler=handler,
        aliases=("help",),
    )


def _make_app_cmdline_open(app: AppProtocol) -> Command:
    def handler() -> None:
        app.focus_cmdline()

    return Command(
        name="app.cmdline_open",
        description="Focus the bottom command line so the next keys go there.",
        params=(),
        handler=handler,
    )


def _make_app_cmdline_prompt(app: AppProtocol) -> Command:
    def handler(text: str) -> None:
        app.cmdline_prompt(text)

    return Command(
        name="app.cmdline_prompt",
        description="Open the command line pre-filled with the given text.",
        params=(
            CommandParam(
                name="text",
                type="string",
                description="Initial value to place in the input.",
            ),
        ),
        handler=handler,
    )


def _make_tag_toggle(app: AppProtocol) -> Command:
    def handler(advance: bool = True) -> bool:
        panel = app.active_panel
        new_state = panel.toggle_tag()
        if advance:
            panel.move_cursor_down()
        return new_state

    return Command(
        name="tag.toggle",
        description="Toggle the tag on the cursor row of the active pane.",
        params=(
            CommandParam(
                name="advance",
                type="bool",
                description="Move cursor down after toggling.",
                required=False,
                default=True,
            ),
        ),
        handler=handler,
    )


def _make_tag_glob(app: AppProtocol) -> Command:
    def handler(pattern: str) -> int:
        return app.active_panel.tag_glob(pattern)

    return Command(
        name="tag.glob",
        description="Tag every visible entry in the active pane matching a glob.",
        params=(
            CommandParam(
                name="pattern",
                type="glob",
                description="Filename glob (e.g. '*Iq*.dat').",
            ),
        ),
        handler=handler,
        examples=("tag.glob *Iq*.dat", "tag.glob *.nxs.h5"),
    )


def _make_tag_untag_glob(app: AppProtocol) -> Command:
    def handler(pattern: str) -> int:
        return app.active_panel.untag_glob(pattern)

    return Command(
        name="tag.untag_glob",
        description="Remove tags from entries matching a glob.",
        params=(
            CommandParam(
                name="pattern",
                type="glob",
                description="Filename glob.",
            ),
        ),
        handler=handler,
    )


def _make_tag_clear(app: AppProtocol) -> Command:
    def handler() -> int:
        return app.active_panel.clear_tags()

    return Command(
        name="tag.clear",
        description="Clear every tag in the active pane.",
        params=(),
        handler=handler,
    )


# ---------------------------------------------------------------------------
# Pure-IO file commands (no UI). The LLM can call these directly with
# `confirm=False`-style explicit args; the F-key bindings go through the
# `ui.*_tagged` orchestration commands below, which add a confirm dialog.
# ---------------------------------------------------------------------------


def _make_file_copy(app: AppProtocol) -> Command:
    def handler(srcs: list[str], dst_dir: str) -> list[str]:
        out = fileops.copy_paths([Path(s) for s in srcs], Path(dst_dir))
        app.inactive_panel.refresh_listing()
        app.active_panel.refresh_listing()
        return [str(p) for p in out]

    return Command(
        name="file.copy",
        description="Copy files into a destination directory.",
        params=(
            CommandParam(name="srcs", type="files", description="Source paths."),
            CommandParam(name="dst_dir", type="path", description="Destination dir."),
        ),
        handler=handler,
        danger=True,
    )


def _make_file_move(app: AppProtocol) -> Command:
    def handler(srcs: list[str], dst_dir: str) -> list[str]:
        out = fileops.move_paths([Path(s) for s in srcs], Path(dst_dir))
        app.inactive_panel.refresh_listing()
        app.active_panel.refresh_listing()
        return [str(p) for p in out]

    return Command(
        name="file.move",
        description="Move files into a destination directory (or rename a single file).",
        params=(
            CommandParam(name="srcs", type="files", description="Source paths."),
            CommandParam(name="dst_dir", type="path", description="Destination dir or new name."),
        ),
        handler=handler,
        danger=True,
    )


def _make_file_delete(app: AppProtocol) -> Command:
    def handler(paths: list[str], trash: bool = True) -> list[str]:
        out = fileops.delete_paths([Path(p) for p in paths], trash=trash)
        app.active_panel.clear_tags()
        app.active_panel.refresh_listing()
        return [str(p) for p in out]

    return Command(
        name="file.delete",
        description="Delete (or trash) the given paths.",
        params=(
            CommandParam(name="paths", type="files", description="Paths to delete."),
            CommandParam(
                name="trash",
                type="bool",
                description="Use the OS trash bin (vs. unlink).",
                required=False,
                default=True,
            ),
        ),
        handler=handler,
        danger=True,
    )


def _make_file_mkdir(app: AppProtocol) -> Command:
    def handler(name: str) -> str:
        out = fileops.make_dir(app.active_panel.cwd, name)
        app.active_panel.refresh_listing()
        return str(out)

    return Command(
        name="file.mkdir",
        description="Create a directory in the active pane.",
        params=(CommandParam(name="name", type="string", description="New directory name."),),
        handler=handler,
        aliases=("mkdir",),
        examples=("mkdir new_data",),
    )


# ---------------------------------------------------------------------------
# UI orchestration — wraps a confirm dialog around the IO commands above.
# These are what F-key bindings target so destructive ops always confirm.
# ---------------------------------------------------------------------------


def _make_ui_copy_tagged(app: AppProtocol) -> Command:
    async def handler() -> int:
        srcs = app.active_panel.selection()
        dst = app.inactive_panel.cwd
        if not srcs:
            app.notify_user("nothing tagged or under cursor", severity="warning")
            return 0
        names = ", ".join(p.name for p in srcs[:5])
        more = f" (+{len(srcs) - 5} more)" if len(srcs) > 5 else ""
        ok = await app.confirm(f"Copy {names}{more} → {dst}?")
        if not ok:
            return 0
        try:
            fileops.copy_paths(srcs, dst)
        except (FileExistsError, OSError) as exc:
            app.notify_user(f"copy failed: {exc}", severity="error")
            return 0
        app.inactive_panel.refresh_listing()
        app.active_panel.refresh_listing()
        return len(srcs)

    return Command(
        name="ui.copy_tagged",
        description="Copy the active pane's selection (tags or cursor) to the inactive pane.",
        params=(),
        handler=handler,
    )


def _make_ui_move_tagged(app: AppProtocol) -> Command:
    async def handler() -> int:
        srcs = app.active_panel.selection()
        dst = app.inactive_panel.cwd
        if not srcs:
            app.notify_user("nothing tagged or under cursor", severity="warning")
            return 0
        names = ", ".join(p.name for p in srcs[:5])
        more = f" (+{len(srcs) - 5} more)" if len(srcs) > 5 else ""
        ok = await app.confirm(f"Move {names}{more} → {dst}?", danger=True)
        if not ok:
            return 0
        try:
            fileops.move_paths(srcs, dst)
        except (FileExistsError, OSError) as exc:
            app.notify_user(f"move failed: {exc}", severity="error")
            return 0
        app.active_panel.clear_tags()
        app.inactive_panel.refresh_listing()
        app.active_panel.refresh_listing()
        return len(srcs)

    return Command(
        name="ui.move_tagged",
        description="Move the active pane's selection to the inactive pane (with confirm).",
        params=(),
        handler=handler,
    )


def _make_app_browse_tree(app: AppProtocol) -> Command:
    async def handler(root: str = "/") -> str | None:
        from sansdir.app import SansdirApp as _RealApp

        if not isinstance(app, _RealApp):
            return None
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str | None] = loop.create_future()

        def _cb(value: str | None) -> None:
            if not fut.done():
                fut.set_result(value)

        from sansdir.ui.dialogs import DirectoryTreeDialog

        app.push_screen(DirectoryTreeDialog(root), _cb)
        result = await fut
        if result:
            target = Path(result).expanduser().resolve()
            if target.is_dir():
                app.active_panel.set_cwd(target)
        return result

    return Command(
        name="app.browse_tree",
        description="Open a directory tree browser; selected dir cds the active pane.",
        params=(
            CommandParam(
                name="root",
                type="path",
                description="Tree root.",
                required=False,
                default="/",
            ),
        ),
        handler=handler,
    )


def _make_view_file(app: AppProtocol) -> Command:
    def handler(path: str) -> None:
        from sansdir.ui.dialogs import FileViewer

        target = Path(path).expanduser().resolve()
        if not target.is_file():
            app.notify_user(f"not a file: {target}", severity="warning")
            return
        from sansdir.app import SansdirApp as _RealApp

        if isinstance(app, _RealApp):
            app.push_screen(FileViewer(target))

    return Command(
        name="view.file",
        description="Open the file under the cursor in a read-only modal pager.",
        params=(CommandParam(name="path", type="path", description="File to view."),),
        handler=handler,
        aliases=("view",),
    )


def _make_view_toggle_other_pane(app: AppProtocol) -> Command:
    def handler() -> bool:
        # If the inactive pane is already showing a viewer, F3 dismisses it.
        if app.is_other_pane_viewing():
            app.close_inline_viewer("right" if app.active_panel is _left_of(app) else "left")
            return False
        cur = app.active_panel.cursor_path
        if cur is None or not cur.is_file():
            app.notify_user("nothing under cursor to view", severity="warning")
            return False
        app.view_in_other_pane(cur)
        return True

    return Command(
        name="view.toggle_other_pane",
        description="Show the file under the cursor in the inactive pane (toggle).",
        params=(),
        handler=handler,
    )


def _left_of(app: AppProtocol):  # type: ignore[no-untyped-def]
    """Return whichever panel object the App calls 'left'.

    Used to identify which slot the inactive pane corresponds to. Lives as
    a tiny helper because the AppProtocol intentionally exposes only
    active/inactive, not left/right by name.
    """
    # By contract the implementation knows; we use object identity to
    # work it out without forcing every AppProtocol implementer to expose
    # left/right.
    return getattr(app, "_left", None) or app.active_panel


def _make_edit_file(app: AppProtocol) -> Command:
    def handler(path: str) -> int:
        target = Path(path).expanduser().resolve()
        if target.is_dir():
            raise IsADirectoryError(target)
        return app.edit_in_editor(target)

    return Command(
        name="edit.file",
        description="Edit the file under the cursor in $EDITOR.",
        params=(CommandParam(name="path", type="path", description="File to edit."),),
        handler=handler,
        aliases=("edit",),
        danger=True,
    )


def _make_ui_delete_tagged(app: AppProtocol) -> Command:
    async def handler() -> int:
        srcs = app.active_panel.selection()
        if not srcs:
            app.notify_user("nothing tagged or under cursor", severity="warning")
            return 0
        names = ", ".join(p.name for p in srcs[:5])
        more = f" (+{len(srcs) - 5} more)" if len(srcs) > 5 else ""
        ok = await app.confirm(
            f"Delete {names}{more}? (sent to trash if available)",
            danger=True,
        )
        if not ok:
            return 0
        removed = fileops.delete_paths(srcs)
        app.active_panel.clear_tags()
        app.active_panel.refresh_listing()
        app.notify_user(f"deleted {len(removed)} entries")
        return len(removed)

    return Command(
        name="ui.delete_tagged",
        description="Delete the active pane's selection (with confirm).",
        params=(),
        handler=handler,
    )


def _make_shell_run(app: AppProtocol) -> Command:
    def handler(cmd: str) -> int:
        return app.run_shell(cmd)

    return Command(
        name="shell.run",
        description="Run a shell command, suspending the TUI while it runs.",
        params=(
            CommandParam(
                name="cmd",
                type="string",
                description="Shell command line (e.g. 'ls -la /tmp').",
            ),
        ),
        handler=handler,
        aliases=("!",),
        examples=(":!ls -la", ":!echo hi"),
        danger=True,
    )


def _phase1_bound_commands(app: AppProtocol) -> list[Command]:
    return [
        _make_nav_cd(app),
        _make_nav_up(app),
        _make_pane_activate(app),
        _make_pane_swap(app),
        _make_pane_sync(app),
        _make_pane_toggle_max(app),
        _make_view_toggle_hidden(app),
        _make_view_set_sort(app),
        _make_view_set_filter(app),
        _make_app_help(app),
        _make_app_cmdline_open(app),
        _make_app_cmdline_prompt(app),
        _make_shell_run(app),
        _make_tag_toggle(app),
        _make_tag_glob(app),
        _make_tag_untag_glob(app),
        _make_tag_clear(app),
        _make_file_copy(app),
        _make_file_move(app),
        _make_file_delete(app),
        _make_file_mkdir(app),
        _make_ui_copy_tagged(app),
        _make_ui_move_tagged(app),
        _make_ui_delete_tagged(app),
        _make_view_file(app),
        _make_view_toggle_other_pane(app),
        _make_edit_file(app),
        _make_app_browse_tree(app),
    ]


def register_builtins(registry: CommandRegistry, app: AppProtocol | None = None) -> CommandRegistry:
    """Register built-in commands on ``registry``.

    Args:
        registry: The :class:`CommandRegistry` to mutate.
        app: When provided, app-bound Phase-1 commands are registered too.
            When ``None`` (default), only ``app.quit`` (sentinel form) is
            registered, which is what tests and the schema export use.

    Returns:
        The same ``registry``, for chaining.
    """
    registry.register(_make_app_quit(app))
    if app is not None:
        for cmd in _phase1_bound_commands(app):
            registry.register(cmd)
    return registry


def build_default_registry(app: AppProtocol | None = None) -> CommandRegistry:
    """Create a fresh registry pre-populated with all built-ins.

    Pass ``app`` to get the full Phase-1 surface bound to a running app;
    omit it for the app-agnostic surface used by tests and tool-schema
    export.
    """
    return register_builtins(CommandRegistry(), app=app)
