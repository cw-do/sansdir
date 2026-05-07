"""Key → command map.

The keymap is intentionally a plain data structure. Each :class:`KeyBinding`
names a registered command and an optional ``args_resolver`` that turns the
running app's state into the kwargs the command expects. The Textual app
walks this list and forwards each binding to
:meth:`~sansdir.commands.registry.CommandRegistry.dispatch` — there is no
inline business logic in any key handler. See ``PLANNING.md`` §12.6.

Tests verify that every binding's ``command`` exists in a fully-bound
registry, so a typo here fails CI rather than at runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sansdir.commands._protocols import AppProtocol

ArgsResolver = Callable[[AppProtocol], dict[str, Any]]


@dataclass(frozen=True)
class KeyBinding:
    """One keystroke routed to one registered command.

    Attributes:
        key: Textual key string (``"tab"``, ``"ctrl+u"``, ``"f10"``, ...).
        command: Name of a registered :class:`~sansdir.commands.registry.Command`.
        description: One-line label shown in help and the status hint bar.
        args_resolver: Optional callable mapping the running app to ``**kwargs``
            for :meth:`CommandRegistry.dispatch`. ``None`` means dispatch with
            no arguments.
        show_in_help: Hide internal/duplicate bindings from the help overlay.
    """

    key: str
    command: str
    description: str
    args_resolver: ArgsResolver | None = None
    show_in_help: bool = True

    def resolve(self, app: AppProtocol) -> dict[str, Any]:
        """Compute the kwargs to pass to :meth:`dispatch` for this app state."""
        if self.args_resolver is None:
            return {}
        return self.args_resolver(app)


# ---------------------------------------------------------------------------
# Resolvers — kept as small named functions (not lambdas) so tracebacks and
# the help overlay show meaningful names.
# ---------------------------------------------------------------------------


def _activate_other(_app: AppProtocol) -> dict[str, Any]:
    return {"panel_id": "other"}


def _cd_to_cursor(app: AppProtocol) -> dict[str, Any]:
    cursor = app.active_panel.cursor_path
    if cursor is None:
        # No selection — fall back to a no-op cd to current cwd. The handler
        # will resolve and refresh, which mirrors how mc treats an empty pane.
        return {"path": str(app.active_panel.cwd)}
    return {"path": str(cursor)}


def _sort_name(_app: AppProtocol) -> dict[str, Any]:
    return {"key": "name"}


def _sort_mtime(_app: AppProtocol) -> dict[str, Any]:
    return {"key": "mtime"}


def _sort_size(_app: AppProtocol) -> dict[str, Any]:
    return {"key": "size"}


def _sort_ext(_app: AppProtocol) -> dict[str, Any]:
    return {"key": "ext"}


def _prompt_tag_glob(_app: AppProtocol) -> dict[str, Any]:
    return {"text": "tag.glob "}


def _prompt_untag_glob(_app: AppProtocol) -> dict[str, Any]:
    return {"text": "tag.untag_glob "}


def _prompt_mkdir(_app: AppProtocol) -> dict[str, Any]:
    return {"text": "mkdir "}


def _prompt_jump(_app: AppProtocol) -> dict[str, Any]:
    return {"text": "cd "}


def _filter_open(_app: AppProtocol) -> dict[str, Any]:
    return {"text": "filter "}


def _prompt_ipts(_app: AppProtocol) -> dict[str, Any]:
    return {"text": "ipts "}


def _file_under_cursor(app: AppProtocol) -> dict[str, Any]:
    cur = app.active_panel.cursor_path
    return {"path": str(cur) if cur is not None else str(app.active_panel.cwd)}


def _hdf_under_cursor(app: AppProtocol) -> dict[str, Any]:
    cur = app.active_panel.cursor_path
    return {"path": str(cur) if cur is not None else ""}


# ---------------------------------------------------------------------------
# Default keymap (Phase 1 surface)
# ---------------------------------------------------------------------------


def default_keymap() -> list[KeyBinding]:
    """The Phase-1 navigation keymap.

    Phases 2+ extend this list (selection, copy/move, plot, …) — each
    addition is a new binding that names an already-registered command.
    """
    return [
        # Pane focus / layout
        KeyBinding("tab", "pane.activate", "Switch active pane", _activate_other),
        KeyBinding("ctrl+u", "pane.swap", "Swap left and right panes"),
        KeyBinding("equals_sign", "pane.sync", "Sync inactive pane to active path"),
        # The literal ``=`` key reaches Textual as the named "equals_sign" key
        # on most terminals, but some emit "=" directly — we register both.
        KeyBinding("=", "pane.sync", "Sync inactive pane to active path", show_in_help=False),
        KeyBinding("ctrl+o", "pane.toggle_max", "Maximize / restore active pane"),
        # Navigation
        KeyBinding(
            "enter",
            "ui.activate_cursor",
            "Open dir / image under cursor",
        ),
        KeyBinding("backspace", "nav.up", "Go up one directory"),
        # Tagging (Phase 2)
        KeyBinding("space", "tag.toggle", "Tag/untag current row"),
        KeyBinding("plus", "app.cmdline_prompt", "Tag by glob", _prompt_tag_glob),
        KeyBinding("+", "app.cmdline_prompt", "Tag by glob", _prompt_tag_glob, show_in_help=False),
        KeyBinding(
            "asterisk",
            "app.cmdline_prompt",
            "Tag by glob",
            _prompt_tag_glob,
            show_in_help=False,
        ),
        KeyBinding(
            "*",
            "app.cmdline_prompt",
            "Tag by glob",
            _prompt_tag_glob,
            show_in_help=False,
        ),
        KeyBinding("minus", "app.cmdline_prompt", "Untag by glob", _prompt_untag_glob),
        KeyBinding(
            "-",
            "app.cmdline_prompt",
            "Untag by glob",
            _prompt_untag_glob,
            show_in_help=False,
        ),
        KeyBinding("u", "tag.clear", "Untag all"),
        # View
        KeyBinding("h", "view.toggle_hidden", "Toggle hidden files"),
        KeyBinding("s", "view.set_sort", "Sort by name", _sort_name, show_in_help=False),
        KeyBinding("1", "view.set_sort", "Sort by name", _sort_name),
        KeyBinding("2", "view.set_sort", "Sort by mtime", _sort_mtime),
        KeyBinding("3", "view.set_sort", "Sort by size", _sort_size),
        KeyBinding("4", "view.set_sort", "Sort by extension", _sort_ext),
        # View / edit (Phase 2)
        KeyBinding("f3", "view.toggle_other_pane", "View in other pane"),
        KeyBinding("f4", "edit.file", "Edit file ($EDITOR)", _file_under_cursor),
        # Archive / mail (Phase 3)
        KeyBinding("z", "ui.zip_tagged", "Zip tagged"),
        KeyBinding("e", "ui.mail_tagged", "Email tagged"),
        # File ops (Phase 2)
        KeyBinding("f5", "ui.copy_tagged", "Copy tagged → other pane"),
        KeyBinding("f6", "ui.move_tagged", "Move tagged → other pane"),
        KeyBinding("f7", "app.cmdline_prompt", "Make directory", _prompt_mkdir),
        KeyBinding("f8", "ui.delete_tagged", "Delete tagged"),
        KeyBinding("delete", "ui.delete_tagged", "Delete tagged", show_in_help=False),
        # Jump (Phase 2)
        KeyBinding("g", "app.cmdline_prompt", "Jump to path", _prompt_jump),
        KeyBinding("G", "app.browse_tree", "Browse filesystem tree"),
        # OnCat IPTS search (Phase 4)
        KeyBinding("i", "oncat.search", "OnCat IPTS search"),
        KeyBinding("f2", "pane.toggle_catalog", "Toggle catalog/list (other pane)"),
        # Plotting (Phase 5/6/7)
        KeyBinding("p", "ui.plot_auto", "Plot selection (Iq / trans / 2D / NeXus)"),
        KeyBinding("l", "ui.plot_generic", "Plot selection (linear-linear, headered tables)"),
        # NeXus tree (Phase 7) + batch extract (Phase 8)
        KeyBinding("m", "hdf.show_keys", "HDF5 metadata tree", _hdf_under_cursor),
        KeyBinding("M", "ui.batch_extract", "Batch extract metadata → table"),
        # Filter (Phase 2)
        KeyBinding("slash", "app.cmdline_prompt", "Filter active pane", _filter_open),
        KeyBinding(
            "/",
            "app.cmdline_prompt",
            "Filter active pane",
            _filter_open,
            show_in_help=False,
        ),
        # App
        KeyBinding("colon", "app.cmdline_open", "Open command line"),
        KeyBinding(":", "app.cmdline_open", "Open command line", show_in_help=False),
        KeyBinding("question_mark", "app.help", "Help overlay"),
        KeyBinding("?", "app.help", "Help overlay", show_in_help=False),
        KeyBinding("q", "app.quit", "Quit"),
        KeyBinding("f10", "app.quit", "Quit", show_in_help=False),
    ]
