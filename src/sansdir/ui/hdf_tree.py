"""``HdfTreeScreen`` — modal browser of an HDF5 file.

Used by the ``m`` keypress on a ``*.nxs.h5`` file. Renders the
hierarchy as a Textual :class:`Tree` (lazy expansion — ``visititems``
on a 350 MB EQSANS file would be ~15 s and 50 k entries, far too much
to inflate eagerly), with a side panel showing the selected leaf's
path / dtype / shape / units / value preview.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static, Tree

from sansdir.hdf.reader import HdfError, HdfNode, list_children, open_nexus

GROUP_MARKER: str = "__sansdir_lazy__"


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
    HdfTreeScreen Tree {
        width: 60%;
        height: 1fr;
    }
    HdfTreeScreen .detail {
        width: 40%;
        height: 1fr;
        padding: 0 1;
        background: $boost;
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

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"HDF5 tree · {self._path.name}", classes="title")
            with Horizontal():
                yield Tree[HdfNode](label=str(self._path), id="hdf-tree")
                with VerticalScroll(classes="detail"):
                    yield Static("(select a leaf)", id="hdf-detail")
            yield Static(
                "[dim]↑/↓ navigate · → expand · Enter preview · q/Esc close[/dim]",
                classes="hint",
            )

    def on_mount(self) -> None:
        tree = self.query_one("#hdf-tree", Tree)
        tree.show_root = True
        tree.root.expand()
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

    def _detail_text(self, node: HdfNode | None) -> str:
        if node is None:
            return "(select a leaf)"
        if node.kind == "group":
            return f"[b]{node.path}[/]\ngroup"
        units = f" {node.units}" if node.units else ""
        shape = "x".join(str(d) for d in node.shape) if node.shape else "scalar"
        return f"[b]{node.path}[/]\ndtype: {node.dtype}\nshape: {shape}{units}\n\n{node.preview}"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_dismiss(self, result: None = None) -> None:  # type: ignore[override]
        self.dismiss(None)
