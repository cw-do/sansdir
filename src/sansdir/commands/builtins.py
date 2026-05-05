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

from pathlib import Path
from typing import TYPE_CHECKING

from sansdir.commands.registry import Command, CommandParam, CommandRegistry
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
        _make_app_help(app),
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
