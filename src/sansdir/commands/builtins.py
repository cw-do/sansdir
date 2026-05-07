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
import time
from pathlib import Path
from typing import TYPE_CHECKING

from sansdir.commands.registry import Command, CommandParam, CommandRegistry
from sansdir.core import archive, fileops, mailer
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


def _make_ui_set_theme(app: AppProtocol) -> Command:
    """``:theme <name>`` — switch Textual theme at runtime.

    Acceptable names come from ``app.available_themes`` (Textual ships
    monokai, nord, dracula, gruvbox, catppuccin-mocha, tokyo-night,
    rose-pine, solarized-{dark,light}, ansi-{dark,light}, plus the
    built-in textual-{dark,light}). Unknown names notify with the list.
    """

    def handler(name: str = "") -> str:
        from sansdir.app import SansdirApp as _RealApp

        if not isinstance(app, _RealApp):
            return ""  # pragma: no cover
        if not name:
            app.notify_user(
                "themes: " + ", ".join(sorted(app.available_themes)),
            )
            return ""
        if name not in app.available_themes:
            app.notify_user(
                f"unknown theme {name!r}. try: "
                + ", ".join(sorted(app.available_themes)),
                severity="warning",
            )
            return ""
        app.theme = name
        app.notify_user(f"theme: {name}")
        return name

    return Command(
        name="ui.set_theme",
        description="Switch Textual theme (no arg lists available).",
        params=(
            CommandParam(
                name="name",
                type="string",
                description="Theme name (blank to list).",
                required=False,
                default="",
            ),
        ),
        handler=handler,
        aliases=("theme",),
    )


def _make_view_set_filter(app: AppProtocol) -> Command:
    def handler(pattern: str = "") -> str:
        # If the active slot currently displays the run catalog, filter
        # *that* table; otherwise fall back to the file panel. Both
        # surfaces expose the same ``filter_substring`` attribute, so
        # the rest of the system (status bar, ``:filter`` cmdline, …)
        # doesn't need to care which is which.
        slot = getattr(app, "_active_slot", None)
        if slot is not None and slot.catalog_visible:
            slot.catalog.filter_substring = pattern
        else:
            app.active_panel.filter_substring = pattern
        return pattern

    return Command(
        name="view.set_filter",
        description="Filter the active pane (or catalog) by substring (empty clears).",
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


def _make_oncat_search(app: AppProtocol) -> Command:
    async def handler(keyword: str = "", instrument: str = "") -> None:
        from sansdir.app import SansdirApp as _RealApp
        from sansdir.config import load_config
        from sansdir.core.oncat import OnCatClient, OnCatError
        from sansdir.ui.dialogs import ConfirmDialog
        from sansdir.ui.oncat_browser import OnCatBrowserScreen

        if not isinstance(app, _RealApp):
            return None  # pragma: no cover
        cfg = load_config()
        instr = instrument or cfg.oncat.default_instrument

        async def _push_modal(screen) -> object:  # type: ignore[no-untyped-def]
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[object] = loop.create_future()

            def _cb(value: object) -> None:
                if not fut.done():
                    fut.set_result(value)

            app.push_screen(screen, _cb)
            return await fut

        try:
            async with OnCatClient(cfg.oncat) as client:
                # Pull the full instrument listing once — the browser
                # filters client-side via its own `/` input.
                experiments = await client.list_experiments(instrument=instr)
                initial_keyword = keyword or ""
                if not experiments:
                    app.notify_user(
                        f"OnCat: no experiments registered for {instr}",
                        severity="warning",
                    )
                    return None
                chosen = await _push_modal(OnCatBrowserScreen(experiments, keyword=initial_keyword))
                if chosen is None:
                    return None
                # `chosen` is a sansdir.core.oncat.Experiment.
                ipts_root = chosen.cluster_path()  # type: ignore[attr-defined]
                # Most users want the per-experiment ``shared/`` folder
                # (notebooks, reduced data, scripts) — not the root,
                # which mainly holds raw nexus / images. Drop into
                # ``shared`` when it exists, otherwise the root.
                shared_dir = ipts_root / "shared"
                target = shared_dir if shared_dir.is_dir() else ipts_root
                ok = await _push_modal(
                    ConfirmDialog(
                        f"Go to {target}\nand load the run catalog in the other pane?",
                        title=f"OnCat — {chosen.ipts}",  # type: ignore[attr-defined]
                    )
                )
                if not ok:
                    return None
                if not target.is_dir():
                    app.notify_user(
                        f"OnCat: {target} doesn't exist on this host",
                        severity="warning",
                    )
                    # Still try to load the catalog from OnCat even if the
                    # local mirror is missing.
                else:
                    app.active_panel.set_cwd(target)
                # Fetch and show the run catalog in the inactive pane.
                files = await client.list_datafiles(
                    chosen.ipts,  # type: ignore[attr-defined]
                    instrument=instr,
                )
                app.show_catalog_in_other_pane(  # type: ignore[attr-defined]
                    chosen.ipts,  # type: ignore[attr-defined]
                    files,
                    instrument=instr,
                    facility=chosen.facility,  # type: ignore[attr-defined]
                )
        except OnCatError as exc:
            app.notify_user(f"OnCat: {exc}", severity="error")
            return None
        return None

    return Command(
        name="oncat.search",
        description="Browse OnCat experiments; Enter cds + loads the run catalog.",
        params=(
            CommandParam(
                name="keyword",
                type="string",
                description="Initial substring filter for the browser.",
                required=False,
                default="",
            ),
            CommandParam(
                name="instrument",
                type="string",
                description="Instrument (defaults to [oncat].default_instrument).",
                required=False,
                default="",
            ),
        ),
        handler=handler,
        aliases=("ipts",),
        examples=("ipts bio-membrane", "ipts 12345"),
    )


def _make_plot_iq(app: AppProtocol) -> Command:
    def handler(paths: list[str]) -> str:
        from sansdir.plot.ascii1d import plot_iq

        png, info = plot_iq([Path(p) for p in paths])
        return _plot_user_message(png, info, paths)

    return Command(
        name="plot.iq",
        description="Plot one or more 2/3/4-col I(q) ASCII files (overlay).",
        params=(CommandParam(name="paths", type="files", description="File(s) to plot."),),
        handler=handler,
    )


def _make_plot_generic(app: AppProtocol) -> Command:
    def handler(paths: list[str]) -> str:
        from sansdir.plot.generic import plot_generic

        png, info = plot_generic([Path(p) for p in paths])
        return _plot_user_message(png, info, paths)

    return Command(
        name="plot.generic",
        description="Linear-linear plot of any tabular file (CSV/TSV/whitespace).",
        params=(CommandParam(name="paths", type="files", description="File(s) to plot."),),
        handler=handler,
        aliases=("plot.linear", "lplot"),
    )


def _make_plot_image(app: AppProtocol) -> Command:
    def handler(paths: list[str]) -> str:
        from sansdir.plot.image import plot_image

        png, info = plot_image([Path(p) for p in paths])
        return _plot_user_message(png, info, paths)

    return Command(
        name="plot.image",
        description="Open one or more image files (PNG / JPG / GIF / TIFF) in matplotlib.",
        params=(CommandParam(name="paths", type="files", description="Image file(s)."),),
        handler=handler,
        aliases=("image", "view.image"),
    )


def _make_ui_activate_cursor(app: AppProtocol) -> Command:
    """``Enter`` smart-dispatch: dir → cd, image → plot, else → cd (errors).

    The classic file-manager Enter only had to mean "cd into the
    folder under the cursor" — but with images on disk the natural
    expectation is "open it". We branch by path kind:

    * directory → :command:`nav.cd`
    * known image extension → :command:`plot.image`
    * anything else → :command:`nav.cd` (which raises a clean
      :class:`NotADirectoryError`, surfaced as a status notify)
    """

    async def handler() -> str | None:
        from sansdir.plot.image import is_image

        cur = app.active_panel.cursor_path
        if cur is None:
            # Mirror nav.cd's empty-pane behaviour.
            return await app.registry.dispatch(  # type: ignore[attr-defined]
                "nav.cd", path=str(app.active_panel.cwd)
            )
        target = Path(cur)
        if target.is_dir():
            return await app.registry.dispatch(  # type: ignore[attr-defined]
                "nav.cd", path=str(target)
            )
        if is_image(target):
            return await app.registry.dispatch(  # type: ignore[attr-defined]
                "plot.image", paths=[str(target)]
            )
        # Fall back so the user gets the existing "not a directory"
        # notification rather than a silent no-op.
        return await app.registry.dispatch(  # type: ignore[attr-defined]
            "nav.cd", path=str(target)
        )

    return Command(
        name="ui.activate_cursor",
        description="Smart Enter: cd into a directory, open an image, …",
        params=(),
        handler=handler,
    )


def _make_ui_plot_generic(app: AppProtocol) -> Command:
    """``l`` keystroke: linear-linear plot of the active selection."""

    def handler() -> str | None:
        srcs = app.active_panel.selection()
        if not srcs:
            app.notify_user("nothing tagged or under cursor", severity="warning")
            return None
        # Drop any directories that snuck in via tags.
        files = [p for p in srcs if p.is_file()]
        if not files:
            app.notify_user("no files in selection", severity="warning")
            return None
        from sansdir.plot.generic import plot_generic

        png, info = plot_generic(files)
        return _plot_user_message(png, info, [str(p) for p in files])

    return Command(
        name="ui.plot_generic",
        description="Linear-linear plot of the active selection (column-headered tables).",
        params=(),
        handler=handler,
    )


def _make_plot_transmission(app: AppProtocol) -> Command:
    def handler(paths: list[str]) -> str:
        from sansdir.plot.ascii1d import plot_transmission

        png, info = plot_transmission([Path(p) for p in paths])
        return _plot_user_message(png, info, paths)

    return Command(
        name="plot.transmission",
        description="Plot transmission curves T(λ) — linear axes, λ in Å.",
        params=(CommandParam(name="paths", type="files", description="File(s) to plot."),),
        handler=handler,
    )


def _plot_user_message(png: Path | None, info, paths: list[str]) -> str:  # type: ignore[no-untyped-def]
    """Return a user-facing summary; the dispatcher routes it to notify_user."""
    if png is None:
        return f"plot opened ({info.name})"
    return f"plot saved → {png}"


def _make_plot_iqxqy(app: AppProtocol) -> Command:
    def handler(paths: list[str]) -> str:
        from sansdir.plot.backend import has_display, save_figure_to_png, spawn_plot_window
        from sansdir.plot.tile import make_iqxqy_figure, make_tile_figure

        path_list = [Path(p) for p in paths]
        if not path_list:
            raise ValueError("plot.iqxqy: at least one file required")
        if has_display():
            info = spawn_plot_window("iqxqy", path_list)
            return f"plot opened ({info.name})"
        # Headless: build inline + save PNG.
        if len(path_list) == 1:
            fig = make_iqxqy_figure(path_list[0])
            title = path_list[0].stem
        else:
            fig = make_tile_figure(path_list)
            title = f"tile_{len(path_list)}files"
        png, _info = save_figure_to_png(fig, title=title)
        return f"plot saved → {png}"

    return Command(
        name="plot.iqxqy",
        description="Plot 4/6-col Iqxqy ASCII files (single pcolormesh or tile).",
        params=(CommandParam(name="paths", type="files", description="File(s) to plot."),),
        handler=handler,
    )


def _make_ui_plot_auto(app: AppProtocol) -> Command:
    """Dispatch a plot for the active selection based on detected file kind."""

    def handler() -> str | None:
        from sansdir.plot import ascii1d, detect
        from sansdir.plot.backend import has_display, save_figure_to_png, spawn_plot_window
        from sansdir.plot.hdf5_detector import make_detector_figure
        from sansdir.plot.tile import make_iqxqy_figure, make_tile_figure

        srcs = app.active_panel.selection()
        if not srcs:
            app.notify_user("nothing tagged or under cursor", severity="warning")
            return None
        # Bucket by kind so a mixed selection still does the right thing.
        iq: list[Path] = []
        trans: list[Path] = []
        iqxqy: list[Path] = []
        nexus: list[Path] = []
        unknown: list[tuple[Path, str]] = []
        for p in srcs:
            d = detect.detect_kind(p)
            if d.kind == detect.KIND_TRANSMISSION:
                trans.append(p)
            elif d.kind == detect.KIND_IQ:
                iq.append(p)
            elif d.kind == detect.KIND_IQXQY:
                iqxqy.append(p)
            elif d.kind == detect.KIND_NEXUS:
                nexus.append(p)
            else:
                unknown.append((p, d.kind))

        # Tell the user *what* is about to be plotted, including filenames,
        # so a stale-tags surprise (cursor on a transmission file but old
        # Iq tags still active) is obvious before any window appears.
        bucket_summary: list[str] = []
        for label, files in (
            ("Iq", iq),
            ("transmission", trans),
            ("Iqxqy", iqxqy),
            ("NeXus", nexus),
        ):
            if files:
                sample = ", ".join(p.name for p in files[:3]) + (
                    f" (+{len(files) - 3} more)" if len(files) > 3 else ""
                )
                bucket_summary.append(f"{len(files)} {label} [{sample}]")
        if bucket_summary:
            app.notify_user("plotting " + " · ".join(bucket_summary))
        if unknown:
            details = ", ".join(f"{p.name} [{kind}]" for p, kind in unknown[:5])
            app.notify_user(
                f"skipping (unsupported): {details}",
                severity="warning",
            )
        if not (iq or trans or iqxqy or nexus):
            return None

        result_msgs: list[str] = []
        if iq:
            png, info = ascii1d.plot_iq(iq)
            result_msgs.append(_plot_user_message(png, info, [str(p) for p in iq]))
        if trans:
            png, info = ascii1d.plot_transmission(trans)
            result_msgs.append(_plot_user_message(png, info, [str(p) for p in trans]))
        if iqxqy:
            if has_display():
                info = spawn_plot_window("iqxqy", iqxqy)
                result_msgs.append(f"Iqxqy plot opened ({info.name})")
            else:
                # Headless: build inline + save PNG.
                if len(iqxqy) == 1:
                    fig = make_iqxqy_figure(iqxqy[0])
                    title = iqxqy[0].stem
                else:
                    fig = make_tile_figure(iqxqy)
                    title = f"tile_{len(iqxqy)}files"
                png, info = save_figure_to_png(fig, title=title)
                result_msgs.append(f"Iqxqy plot saved → {png}")
        if nexus:
            if has_display():
                # One subprocess per file — different files don't share
                # a colour scale meaningfully (different total counts).
                for p in nexus:
                    spawn_plot_window("nexus", [p])
                result_msgs.append(f"NeXus plot opened ({len(nexus)} window(s))")
            else:
                for p in nexus:
                    fig = make_detector_figure(p)
                    png, _info = save_figure_to_png(fig, title=f"{p.stem}_detector")
                    result_msgs.append(f"NeXus plot saved → {png}")
        return " · ".join(result_msgs) or None

    return Command(
        name="ui.plot_auto",
        description="Plot the active selection; routes Iq / transmission / Iqxqy by file kind.",
        params=(),
        handler=handler,
    )


def _make_hdf_show_keys(app: AppProtocol) -> Command:
    def handler(path: str) -> None:
        from sansdir.app import SansdirApp as _RealApp
        from sansdir.ui.hdf_tree import HdfTreeScreen

        target = Path(path).expanduser().resolve()
        if not target.is_file():
            app.notify_user(f"not a file: {target}", severity="warning")
            return
        if not isinstance(app, _RealApp):
            return  # pragma: no cover
        app.push_screen(HdfTreeScreen(target))

    return Command(
        name="hdf.show_keys",
        description="Open an HDF5 / NeXus file in a tree-browser modal.",
        params=(CommandParam(name="path", type="path", description="Path to *.nxs.h5"),),
        handler=handler,
        aliases=("hdf",),
    )


def _make_plot_detector_sum(app: AppProtocol) -> Command:
    def handler(paths: list[str]) -> str:
        # Headless path only — interactive runs through the subprocess
        # via spawn_plot_window("nexus", ...).
        from sansdir.plot.backend import has_display, save_figure_to_png, spawn_plot_window
        from sansdir.plot.hdf5_detector import make_detector_figure

        path_list = [Path(p) for p in paths]
        if not path_list:
            raise ValueError("plot.detector_sum: at least one file required")
        if has_display():
            # One subprocess per file — multi-file detector tiling lives
            # inside a single make_detector_figure call but only handles
            # one file at a time today; a Phase 8 batch view would
            # collate runs.
            for p in path_list:
                spawn_plot_window("nexus", [p])
            return f"opened {len(path_list)} window(s)"
        msgs: list[str] = []
        for p in path_list:
            fig = make_detector_figure(p)
            png, _ = save_figure_to_png(fig, title=f"{p.stem}_detector")
            msgs.append(str(png))
        return " · ".join(msgs)

    return Command(
        name="plot.detector_sum",
        description="Render NeXus detector banks as 2D heatmaps (one window per file).",
        params=(CommandParam(name="paths", type="files", description="*.nxs.h5 file(s)."),),
        handler=handler,
    )


def _make_hdf_batch_extract(app: AppProtocol) -> Command:
    def handler(
        paths: list[str],
        keys: str | list[str],
        out: str = "",
        fmt: str = "tsv",
        with_stats: bool = False,
    ) -> str:
        from sansdir.hdf.batch import extract_to_file

        # ``keys`` arrives as a comma-separated string from the cmdline
        # but as a list when called programmatically (the M dialog
        # handler passes a list). Normalise to list.
        if isinstance(keys, str):
            key_list = [k.strip() for k in keys.split(",") if k.strip()]
        else:
            key_list = list(keys)
        if not paths:
            raise ValueError("hdf.batch_extract: at least one file required")
        if not key_list:
            raise ValueError("hdf.batch_extract: at least one key required")
        if fmt not in ("tsv", "csv", "columns"):
            raise ValueError(f"hdf.batch_extract: unknown fmt {fmt!r}")
        # ``out`` is a string param so the cmdline can pass it; treat
        # the empty string as "use the default timestamped path".
        out_path = Path(out).expanduser() if out else None
        if out_path is not None and not out_path.is_absolute():
            out_path = app.active_panel.cwd / out_path
        written = extract_to_file(
            files=[Path(p) for p in paths],
            keys=key_list,
            out_path=out_path,
            fmt=fmt,  # type: ignore[arg-type]
            with_stats=with_stats,
        )
        if isinstance(written, list):
            # Per-file mode: one output per input.
            app.notify_user(
                f"wrote {len(written)} per-file table(s) "
                f"(first: {written[0].name})"
                if written
                else "no files written"
            )
            return ", ".join(str(p) for p in written)
        app.notify_user(f"wrote {len(paths)} row(s) → {written}")
        return str(written)

    return Command(
        name="hdf.batch_extract",
        description="Extract DASlogs values from many NeXus files into a TSV/CSV/columns file.",
        params=(
            CommandParam(name="paths", type="files", description="*.nxs.h5 files."),
            CommandParam(
                name="keys",
                type="string",
                description=(
                    "Comma-separated HDF5 key paths (e.g. /entry/DASlogs/temperature/value)."
                ),
            ),
            CommandParam(
                name="out",
                type="path",
                description="Output file. Empty → ./extracted_<timestamp>.<ext>.",
                required=False,
                default="",
            ),
            CommandParam(
                name="fmt",
                type="string",
                description="Output format: tsv | csv | columns.",
                required=False,
                default="tsv",
            ),
            CommandParam(
                name="with_stats",
                type="bool",
                description="Add <key>_stdev and <key>_n columns.",
                required=False,
                default=False,
            ),
        ),
        handler=handler,
        aliases=("extract",),
    )


def _make_ui_batch_extract(app: AppProtocol) -> Command:
    """``M`` keystroke: open the BatchExtractDialog for the active selection.

    Two entry points:

    * From a file pane (the keystroke fires with no args): we resolve
      the user's tags / cursor selection to ``*.nxs.h5`` paths.
    * From the catalog pane (the catalog binding fires with explicit
      ``paths=[...]``): we honour the supplied list verbatim, since
      the catalog has already resolved IPTS run numbers to cluster
      NeXus paths on its end.
    """

    async def handler(paths: list[str] | None = None) -> str | None:
        from sansdir.app import SansdirApp as _RealApp
        from sansdir.hdf.batch import (
            extract_many,
            extract_per_file,
            write_table,
        )
        from sansdir.ui.dialogs import BatchExtractDialog

        if not isinstance(app, _RealApp):
            return None  # pragma: no cover
        if paths is not None:
            nexus_files = [Path(p) for p in paths]
        else:
            srcs = app.active_panel.selection()
            nexus_files = [
                p
                for p in srcs
                if p.is_file()
                and (p.name.endswith(".nxs.h5") or p.suffix.lower() == ".nxs")
            ]
        if not nexus_files:
            app.notify_user(
                "no NeXus files selected — tag *.nxs.h5 / *.nxs files first",
                severity="warning",
            )
            return None
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict | None] = loop.create_future()

        def _cb(value: dict | None) -> None:
            if not fut.done():
                fut.set_result(value)

        # Pass the write dir up-front so the dialog can show it next
        # to the Output field — the same value the dispatcher uses to
        # resolve relative paths a few lines down.
        app.push_screen(
            BatchExtractDialog(nexus_files, write_dir=app.inactive_panel.cwd),
            _cb,
        )
        data = await fut
        if not data:
            return None
        # MDIR semantic: write to *the other pane* by default. The
        # active source might be a read-only IPTS folder (raw data) or
        # the OnCat catalog (which has no real cwd at all), so anchoring
        # the output to the inactive pane's cwd avoids permission errors
        # and matches users' "copy/move from active → inactive" muscle
        # memory.
        write_dir = app.inactive_panel.cwd
        keys = data["keys"]
        fmt = data.get("fmt", "tsv")
        mode = data.get("mode", "per_file")
        with_stats = bool(data.get("with_stats", False))
        out_value = (data.get("out") or "").strip()
        # Per-file mode requires ``<filename>`` somewhere in the path so
        # each input gets its own output. We inject it into the basename
        # if missing so users can type ``my_extract.csv`` and still get
        # one CSV per run (rather than the cross-run summary table).
        if mode == "per_file":
            if not out_value:
                out_value = "<filename>_extracted." + (
                    "csv" if fmt == "csv" else "tsv" if fmt == "tsv" else "txt"
                )
            elif "<filename>" not in out_value:
                p = Path(out_value)
                stem_name = f"<filename>_{p.name}"
                out_value = (
                    str(p.parent / stem_name) if str(p.parent) not in (".", "") else stem_name
                )
                app.notify_user(
                    f"per-file mode: writing to '{out_value}' (auto-prepended <filename>_)",
                )
        if out_value:
            p = Path(out_value).expanduser()
            out_path: Path = p if p.is_absolute() else write_dir / p
        else:
            # Summary mode with empty output → timestamped table in the
            # writable pane.
            ext = {"tsv": "tsv", "csv": "csv", "columns": "txt"}[fmt]
            stamp = time.strftime("%Y%m%d-%H%M%S")
            out_path = write_dir / f"extracted_{stamp}.{ext}"
        try:
            if mode == "per_file":
                written_paths = extract_per_file(
                    nexus_files, keys, out_path, fmt=fmt  # type: ignore[arg-type]
                )
                if not written_paths:
                    app.notify_user("no files written", severity="warning")
                    return None
                app.notify_user(
                    f"wrote {len(written_paths)} per-file table(s) "
                    f"(first: {written_paths[0].name})"
                )
                return ", ".join(str(p) for p in written_paths)
            # Summary mode: one row per file with means.
            rows = extract_many(nexus_files, keys)
            written = write_table(
                rows, keys, out_path, fmt=fmt, with_stats=with_stats  # type: ignore[arg-type]
            )
        except (OSError, ValueError) as exc:
            app.notify_user(f"extract failed: {exc}", severity="error")
            return None
        app.notify_user(f"wrote {len(nexus_files)} row(s) → {written}")
        return str(written)

    return Command(
        name="ui.batch_extract",
        description="Open the metadata-extraction dialog for the active selection.",
        params=(
            CommandParam(
                name="paths",
                type="files",
                description=(
                    "Explicit *.nxs.h5 list (catalog pane uses this); "
                    "blank → fall back to the active file pane's selection."
                ),
                required=False,
                default=None,
            ),
        ),
        handler=handler,
    )


def _make_pane_toggle_catalog(app: AppProtocol) -> Command:
    def handler() -> None:
        app.toggle_other_pane_catalog()

    return Command(
        name="pane.toggle_catalog",
        description="Flip the inactive pane between filelist and run catalog.",
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


def _make_archive_zip(app: AppProtocol) -> Command:
    def handler(srcs: list[str], out_path: str) -> str:
        out = archive.make_zip([Path(s) for s in srcs], Path(out_path))
        app.inactive_panel.refresh_listing()
        app.active_panel.refresh_listing()
        return str(out)

    return Command(
        name="archive.zip",
        description="Create a zip archive containing the given paths.",
        params=(
            CommandParam(name="srcs", type="files", description="Files/dirs to include."),
            CommandParam(name="out_path", type="path", description="Output .zip path."),
        ),
        handler=handler,
        examples=("archive.zip a.txt b.txt /tmp/out.zip",),
    )


def _make_archive_tar_gz(app: AppProtocol) -> Command:
    def handler(srcs: list[str], out_path: str) -> str:
        out = archive.make_tar_gz([Path(s) for s in srcs], Path(out_path))
        app.inactive_panel.refresh_listing()
        app.active_panel.refresh_listing()
        return str(out)

    return Command(
        name="archive.tar_gz",
        description="Create a gzip-compressed tar archive.",
        params=(
            CommandParam(name="srcs", type="files", description="Files/dirs to include."),
            CommandParam(name="out_path", type="path", description="Output .tar.gz path."),
        ),
        handler=handler,
        aliases=("tar",),
        examples=("tar a.txt b.txt /tmp/out.tar.gz",),
    )


def _make_mail_send(app: AppProtocol) -> Command:
    def handler(
        recipient: str,
        subject: str = "[sansdir] data",
        attachments: list[str] | None = None,
        body: str = "",
    ) -> int:
        from sansdir.config import load_config

        cfg = load_config()
        atts = [Path(a) for a in (attachments or [])]
        result = mailer.send_mail(
            recipient=recipient,
            subject=subject,
            attachments=atts,
            body=body,
            command=cfg.mail.command,
        )
        if result.ok:
            app.notify_user(f"sent {len(atts)} attachment(s) to {recipient}")
        else:
            stderr = (result.stderr or "").strip().splitlines()[:1]
            tail = stderr[0] if stderr else f"exit {result.returncode}"
            app.notify_user(f"mail failed: {tail}", severity="error")
        return result.returncode

    return Command(
        name="mail.send",
        description="Send mail via the configured mail/mutt command.",
        params=(
            CommandParam(name="recipient", type="string", description="To address."),
            CommandParam(
                name="subject",
                type="string",
                description="Subject line.",
                required=False,
                default="[sansdir] data",
            ),
            CommandParam(
                name="attachments",
                type="files",
                description="Files to attach.",
                required=False,
                default=[],
            ),
            CommandParam(
                name="body",
                type="string",
                description="Plain-text body (sent on stdin).",
                required=False,
                default="",
            ),
        ),
        handler=handler,
        danger=True,
    )


def _make_ui_zip_tagged(app: AppProtocol) -> Command:
    async def handler() -> str | None:
        from sansdir.app import SansdirApp as _RealApp
        from sansdir.ui.dialogs import TextPromptDialog

        srcs = app.active_panel.selection()
        if not srcs:
            app.notify_user("nothing tagged or under cursor", severity="warning")
            return None
        default_name = f"{app.active_panel.cwd.name or 'archive'}.zip"
        if not isinstance(app, _RealApp):
            return None  # pragma: no cover — only meaningful in real app
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str | None] = loop.create_future()

        def _cb(value: str | None) -> None:
            if not fut.done():
                fut.set_result(value)

        help_text = (
            "Examples:\n"
            "  filename.zip          → current folder\n"
            "  ../filename.zip       → parent folder\n"
            "  /abs/path/file.zip    → exactly there"
        )
        app.push_screen(
            TextPromptDialog(
                f"zip {len(srcs)} item(s):",
                default=default_name,
                title="Archive name",
                help_text=help_text,
            ),
            _cb,
        )
        name = await fut
        if not name:
            return None
        # Resolve the user's input as a filesystem path:
        # - absolute path → use as-is
        # - relative path (incl. ``..`` segments) → relative to *active* pane
        target = Path(name).expanduser()
        if not target.is_absolute():
            target = app.active_panel.cwd / target
        target = target.resolve()
        try:
            archive.make_zip(srcs, target)
        except (FileExistsError, OSError, ValueError) as exc:
            app.notify_user(f"zip failed: {exc}", severity="error")
            return None
        # Refresh whichever panes show the directory the zip landed in.
        for panel in (app.active_panel, app.inactive_panel):
            if target.parent == panel.cwd:
                panel.refresh_listing()
        app.notify_user(f"created {target}")
        return str(target)

    return Command(
        name="ui.zip_tagged",
        description="Prompt for an archive path and zip the active selection.",
        params=(),
        handler=handler,
    )


def _make_ui_mail_tagged(app: AppProtocol) -> Command:
    async def handler() -> int | None:
        from sansdir.app import SansdirApp as _RealApp
        from sansdir.config import load_config
        from sansdir.ui.dialogs import MailDialog

        srcs = app.active_panel.selection()
        if not srcs:
            app.notify_user("nothing tagged or under cursor", severity="warning")
            return None
        if not isinstance(app, _RealApp):
            return None  # pragma: no cover
        cfg = load_config()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict | None] = loop.create_future()

        def _cb(value: dict | None) -> None:
            if not fut.done():
                fut.set_result(value)

        summary = ", ".join(p.name for p in srcs[:5])
        if len(srcs) > 5:
            summary += f" (+{len(srcs) - 5} more)"
        app.push_screen(
            MailDialog(
                attachments_summary=summary,
                default_subject=cfg.mail.default_subject,
            ),
            _cb,
        )
        data = await fut
        if not data:
            return None
        try:
            result = mailer.send_mail(
                recipient=data["recipient"],
                subject=data["subject"] or cfg.mail.default_subject,
                attachments=srcs,
                body=data["body"],
                command=cfg.mail.command,
            )
        except (FileNotFoundError, RuntimeError) as exc:
            app.notify_user(f"mail failed: {exc}", severity="error")
            return None
        if result.ok:
            app.notify_user(f"sent {len(srcs)} attachment(s) to {data['recipient']}")
        else:
            tail = (result.stderr or f"exit {result.returncode}").strip().splitlines()[:1]
            app.notify_user(
                f"mail failed: {tail[0] if tail else 'unknown'}",
                severity="error",
            )
        return result.returncode

    return Command(
        name="ui.mail_tagged",
        description="Open the mail dialog and send the active selection as attachments.",
        params=(),
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
        from sansdir.app import SansdirApp as _RealApp

        # If *either* pane is showing a viewer, F3 dismisses that one —
        # users routinely Tab into the viewer pane to scroll, then hit
        # F3 (or Esc) to close from there. Without this branch, F3 from
        # the viewer pane would try to view its own (FilePanel-less)
        # cursor and warn.
        if isinstance(app, _RealApp):
            if app._active_slot.viewer_visible:
                app.close_inline_viewer(app._active_id)
                return False
            if app._inactive_slot.viewer_visible:
                other_id = "right" if app._active_id == "left" else "left"
                app.close_inline_viewer(other_id)
                return False
        elif app.is_other_pane_viewing():  # protocol-only fallback
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
        description="Show the file under the cursor in the other pane (toggle from either side).",
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
        failed = len(srcs) - len(removed)
        if failed:
            app.notify_user(
                f"deleted {len(removed)} of {len(srcs)} entries "
                f"({failed} failed — check permissions)",
                severity="warning",
            )
        else:
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
        _make_archive_zip(app),
        _make_archive_tar_gz(app),
        _make_mail_send(app),
        _make_ui_zip_tagged(app),
        _make_ui_mail_tagged(app),
        _make_view_file(app),
        _make_view_toggle_other_pane(app),
        _make_edit_file(app),
        _make_app_browse_tree(app),
        _make_oncat_search(app),
        _make_pane_toggle_catalog(app),
        _make_plot_iq(app),
        _make_plot_transmission(app),
        _make_plot_iqxqy(app),
        _make_plot_detector_sum(app),
        _make_plot_generic(app),
        _make_hdf_show_keys(app),
        _make_hdf_batch_extract(app),
        _make_ui_batch_extract(app),
        _make_ui_plot_auto(app),
        _make_ui_plot_generic(app),
        _make_plot_image(app),
        _make_ui_activate_cursor(app),
        _make_ui_set_theme(app),
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
