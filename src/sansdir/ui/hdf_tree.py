"""``HdfTreeScreen`` — modal browser of an HDF5 file.

Used by the ``m`` keypress on a ``*.nxs.h5`` file. Renders the
hierarchy as a Textual :class:`Tree` (lazy expansion — ``visititems``
on a 350 MB EQSANS file would be ~15 s and 50 k entries, far too much
to inflate eagerly), with a side panel showing the selected leaf's
path / dtype / shape / units / value preview.

``/`` switches to keyword search: the full key list is walked once in
a worker thread, then filtered by case-insensitive substring — the
same flow as the batch-extract picker (``M``), minus the selection
markers, since this screen is read-only.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static, Tree

from sansdir.hdf.reader import HdfError, HdfNode, list_children, open_nexus, walk_tree

GROUP_MARKER: str = "__sansdir_lazy__"

#: Cap on rendered search hits — a raw NeXus file has ~50 k keys and a
#: one-letter query would otherwise stall the DataTable for seconds.
MAX_SEARCH_RESULTS: int = 500


class HdfTreeScreen(ModalScreen[None]):
    """Browse an HDF5 file in a modal tree + detail pane."""

    DEFAULT_CSS = """
    HdfTreeScreen {
        align: center middle;
    }
    HdfTreeScreen > Vertical {
        background: $surface;
        border: round $accent;
        padding: 1 2;
        width: 95%;
        height: 90%;
    }
    HdfTreeScreen .title {
        text-style: bold;
        margin-bottom: 1;
    }
    HdfTreeScreen Horizontal {
        height: 1fr;
    }
    HdfTreeScreen #hdf-search {
        height: 3;
        margin-bottom: 1;
    }
    HdfTreeScreen Tree {
        width: 60%;
        height: 1fr;
    }
    HdfTreeScreen #hdf-search-results {
        width: 75%;
        height: 1fr;
        display: none;
    }
    HdfTreeScreen.-searching #hdf-tree {
        display: none;
    }
    HdfTreeScreen.-searching #hdf-search-results {
        display: block;
    }
    HdfTreeScreen .detail {
        width: 40%;
        height: 1fr;
        padding: 0 1;
        background: $boost;
    }
    /* Full DASlogs paths run ~55 chars; at 40% the shape column falls off
       the right edge. Search mode has no tree, so borrow the width. */
    HdfTreeScreen.-searching .detail {
        width: 25%;
    }
    HdfTreeScreen .hint {
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("q", "dismiss", "Close", show=False),
    ]

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        # Flat key list for search — walked once, lazily, on the first
        # query (the full walk of a raw NeXus file is seconds, and most
        # users never search).
        self._all_nodes: list[HdfNode] | None = None
        self._search_rows: list[HdfNode] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"HDF5 tree · {self._path.name}", classes="title")
            yield Input(
                placeholder="search keys (substring; clear or Esc to return to tree)",
                id="hdf-search",
            )
            with Horizontal():
                yield Tree[HdfNode](label=str(self._path), id="hdf-tree")
                yield DataTable(id="hdf-search-results", cursor_type="row", show_header=True)
                with VerticalScroll(classes="detail"):
                    yield Static("(select a leaf)", id="hdf-detail")
            yield Static(
                "[dim]↑/↓ navigate · → expand · / search · q/Esc close[/dim]",
                classes="hint",
                id="hdf-hint",
            )

    def on_mount(self) -> None:
        tree = self.query_one("#hdf-tree", Tree)
        tree.show_root = True
        tree.root.expand()
        self.query_one("#hdf-search-results", DataTable).add_columns("key", "shape")
        try:
            self._populate(tree.root, "/")
        except HdfError as exc:
            self.app.notify(f"HDF5: {exc}", severity="error")
            self.dismiss(None)
            return
        tree.focus()

    # ------------------------------------------------------------------
    # Lazy expansion
    # ------------------------------------------------------------------

    def _populate(self, node, group_path: str) -> None:  # type: ignore[no-untyped-def]
        """List the direct children of ``group_path`` under ``node``."""
        try:
            with open_nexus(self._path) as fh:
                children = list_children(fh, group_path)
        except HdfError as exc:
            node.add_leaf(f"<error: {exc}>")
            return
        for child in children:
            label = self._label_for(child)
            if child.kind == "group":
                child_node = node.add(label, data=child, expand=False)
                # Add a placeholder so the disclosure caret renders; we
                # populate on expansion.
                child_node.add(GROUP_MARKER, data=None)
            else:
                node.add_leaf(label, data=child)

    @staticmethod
    def _label_for(node: HdfNode) -> str:
        name = node.path.rsplit("/", 1)[-1] or "/"
        if node.kind == "group":
            return name + "/"
        shape = "x".join(str(d) for d in node.shape) or "scalar"
        return f"{name}  [{node.dtype}, {shape}]"

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:  # type: ignore[type-arg]
        node = event.node
        # Skip if we've already populated (children include real data).
        if node.children and any(c.data is not None for c in node.children):
            return
        # Drop placeholder children, then populate from disk.
        node.remove_children()
        data = node.data
        if isinstance(data, HdfNode) and data.kind == "group":
            self._populate(node, data.path)

    # ------------------------------------------------------------------
    # Detail pane
    # ------------------------------------------------------------------

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:  # type: ignore[type-arg]
        data = event.node.data
        with contextlib.suppress(Exception):
            self.query_one("#hdf-detail", Static).update(self._detail_text(data))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "hdf-search-results":
            return
        idx = event.cursor_row
        if 0 <= idx < len(self._search_rows):
            with contextlib.suppress(Exception):
                self.query_one("#hdf-detail", Static).update(
                    self._detail_text(self._search_rows[idx])
                )

    def _detail_text(self, node: HdfNode | None) -> str:
        if node is None:
            return "(select a leaf)"
        if node.kind == "group":
            return f"[b]{node.path}[/]\ngroup"
        units = f" {node.units}" if node.units else ""
        shape = "x".join(str(d) for d in node.shape) if node.shape else "scalar"
        return f"[b]{node.path}[/]\ndtype: {node.dtype}\nshape: {shape}{units}\n\n{node.preview}"

    # ------------------------------------------------------------------
    # Keyword search
    # ------------------------------------------------------------------

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        """``/`` opens search; ↑/↓ drive the hit list without leaving it."""
        focused = self.focused
        if event.key == "slash" and not isinstance(focused, Input):
            self.query_one("#hdf-search", Input).focus()
            event.stop()
            event.prevent_default()
            return
        # Arrowing from inside the input walks the results, so the detail
        # pane updates as the user scans matches — no Tab dance.
        if isinstance(focused, Input) and event.key in ("up", "down") and self._search_rows:
            table = self.query_one("#hdf-search-results", DataTable)
            delta = -1 if event.key == "up" else 1
            row = max(0, min(len(self._search_rows) - 1, table.cursor_row + delta))
            table.move_cursor(row=row)
            event.stop()
            event.prevent_default()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "hdf-search":
            return
        query = event.value.strip().lower()
        if not query:
            self._exit_search()
            return
        if self._all_nodes is None:
            self.run_worker(self._walk_then_filter(query), exclusive=True, name="hdf-key-search")
        else:
            self._show_results(query)

    async def _walk_then_filter(self, query: str) -> None:
        """Walk the file off the UI thread, then apply the live query."""

        def _walk() -> list[HdfNode]:
            with open_nexus(self._path) as fh:
                return walk_tree(fh)

        try:
            self._all_nodes = await asyncio.to_thread(_walk)
        except HdfError as exc:
            self.app.notify(f"HDF5: {exc}", severity="error")
            return
        # The user may have typed more while the walk ran — re-read.
        current = self.query_one("#hdf-search", Input).value.strip().lower()
        if current:
            self._show_results(current)

    def _show_results(self, query: str) -> None:
        if self._all_nodes is None:
            return
        matches = [n for n in self._all_nodes if query in n.path.lower()]
        total = len(matches)
        if total > MAX_SEARCH_RESULTS:
            matches = matches[:MAX_SEARCH_RESULTS]
        self._search_rows = matches
        table = self.query_one("#hdf-search-results", DataTable)
        table.clear()
        for node in matches:
            shape = "x".join(str(d) for d in node.shape) or (
                "group" if node.kind == "group" else "scalar"
            )
            table.add_row(node.path, shape)
        self.add_class("-searching")
        if total <= MAX_SEARCH_RESULTS:
            shown = f"{total} match(es)"
        else:
            shown = f"{MAX_SEARCH_RESULTS} of {total} match(es) — narrow the query to see the rest"
        self.query_one("#hdf-hint", Static).update(
            f"[dim]{shown} · ↑/↓ scan · Esc back to tree · q close[/dim]"
        )
        if matches:
            table.move_cursor(row=0)
        else:
            self.query_one("#hdf-detail", Static).update("(no match)")

    def _exit_search(self) -> None:
        """Leave search mode, keeping the walked cache for next time."""
        self._search_rows = []
        self.remove_class("-searching")
        self.query_one("#hdf-hint", Static).update(
            "[dim]↑/↓ navigate · → expand · / search · q/Esc close[/dim]"
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_dismiss(self, result: None = None) -> None:  # type: ignore[override]
        # Esc backs out of search first — closing the whole modal on the
        # first Esc would throw away the query the user just typed.
        search = self.query_one("#hdf-search", Input)
        if search.value:
            search.value = ""
            self._exit_search()
            self.query_one("#hdf-tree", Tree).focus()
            return
        self.dismiss(None)
