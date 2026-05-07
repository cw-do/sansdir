"""Reusable Textual modals.

For Phase 2 we need exactly one: a yes/no confirm dialog. Later phases
will add a destination-editor dialog (copy/move with editable target),
a directory tree picker, and a metadata extract picker.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Center, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class ConfirmDialog(ModalScreen[bool]):
    """A yes/no modal. ``await app.push_screen_wait(ConfirmDialog(...))``."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }
    ConfirmDialog > Vertical {
        background: $surface;
        border: round $accent;
        padding: 1 2;
        width: auto;
        max-width: 80%;
        height: auto;
    }
    ConfirmDialog .title {
        text-style: bold;
        margin-bottom: 1;
    }
    ConfirmDialog .body {
        margin-bottom: 1;
    }
    ConfirmDialog .hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    ConfirmDialog Button {
        margin: 0 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "deny", "No", show=False),
        Binding("n", "deny", "No", show=False),
        Binding("y", "confirm", "Yes", show=False),
        Binding("enter", "confirm", "Yes", show=False),
    ]

    def __init__(
        self,
        message: str,
        *,
        title: str = "Confirm",
        yes_label: str = "(Y)es",
        no_label: str = "(N)o",
        danger: bool = False,
    ) -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._yes_label = yes_label
        self._no_label = no_label
        self._danger = danger

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._title, classes="title")
            yield Static(self._message, classes="body")
            yield Static(
                "[dim]Y/Enter to confirm · N/Esc to cancel[/dim]",
                classes="hint",
            )
            with Center():
                yield Button(
                    self._yes_label,
                    id="yes",
                    variant="error" if self._danger else "primary",
                )
                yield Button(self._no_label, id="no")

    def on_mount(self) -> None:
        # Default focus on "No" for destructive actions, "Yes" otherwise —
        # lowers the chance of an accidental Enter wiping data.
        target = "no" if self._danger else "yes"
        self.query_one(f"#{target}", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)


class TextPromptDialog(ModalScreen[str | None]):
    """Single-line text prompt; returns the entered string, or ``None`` on cancel.

    ``help_text`` (optional) renders below the input as muted multi-line text.
    Useful for showing concrete examples — see :func:`_make_ui_zip_tagged` for
    the path-resolution examples shown in the zip flow.
    """

    DEFAULT_CSS = """
    TextPromptDialog {
        align: center middle;
    }
    TextPromptDialog > Vertical {
        background: $surface;
        border: round $accent;
        padding: 1 2;
        width: 80%;
        height: auto;
    }
    TextPromptDialog .title {
        text-style: bold;
        margin-bottom: 1;
    }
    TextPromptDialog .help {
        color: $text-muted;
        margin-top: 1;
    }
    TextPromptDialog .hint {
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        message: str,
        *,
        default: str = "",
        title: str = "Prompt",
        help_text: str = "",
    ) -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._default = default
        self._help_text = help_text

    def compose(self) -> ComposeResult:
        from textual.widgets import Input

        with Vertical():
            yield Label(self._title, classes="title")
            yield Static(self._message)
            yield Input(value=self._default, id="prompt-input", select_on_focus=False)
            if self._help_text:
                yield Static(self._help_text, classes="help")
            yield Static(
                "[dim]Enter to submit · Esc to cancel[/dim]",
                classes="hint",
            )

    def on_mount(self) -> None:
        from textual.widgets import Input

        inp = self.query_one("#prompt-input", Input)
        inp.cursor_position = len(inp.value)
        inp.focus()

    def on_input_submitted(self, event) -> None:  # type: ignore[no-untyped-def]
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class FileViewer(ModalScreen[None]):
    """Read-only pager. Refuses to render binary files (offers a notify instead)."""

    DEFAULT_CSS = """
    FileViewer {
        align: center middle;
    }
    FileViewer > Vertical {
        background: $surface;
        border: round $accent;
        padding: 1 2;
        width: 90%;
        height: 90%;
    }
    FileViewer .title {
        text-style: bold;
        margin-bottom: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("q", "dismiss", "Close", show=False),
    ]

    MAX_BYTES: ClassVar[int] = 1_000_000  # 1 MB cap

    def __init__(self, path) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self._path = path
        self._content: str = ""

    def compose(self) -> ComposeResult:
        from textual.containers import VerticalScroll

        with Vertical():
            yield Static(f"view: {self._path}", classes="title")
            with VerticalScroll():
                yield Static(self._content, id="viewer-body")

    def on_mount(self) -> None:
        try:
            data = self._path.read_bytes()[: self.MAX_BYTES]
        except OSError as exc:
            self._content = f"<error: {exc}>"
            self.query_one("#viewer-body", Static).update(self._content)
            return
        # Heuristic: any NUL in the first 8 KB → call it binary.
        if b"\x00" in data[:8192]:
            self.app.notify("binary file — refusing to render in pager", severity="warning")
            self.dismiss(None)
            return
        try:
            self._content = data.decode("utf-8", errors="replace")
        except UnicodeDecodeError as exc:
            self._content = f"<decode error: {exc}>"
        self.query_one("#viewer-body", Static).update(self._content)

    def action_dismiss(self, result: None = None) -> None:  # type: ignore[override]
        self.dismiss(None)


class DirectoryTreeDialog(ModalScreen[str | None]):
    """Folder browser using Textual's :class:`DirectoryTree`.

    Returns the absolute path of the highlighted directory on Enter, or
    ``None`` on Escape.
    """

    DEFAULT_CSS = """
    DirectoryTreeDialog {
        align: center middle;
    }
    DirectoryTreeDialog > Vertical {
        background: $surface;
        border: round $accent;
        padding: 1 2;
        width: 80%;
        height: 80%;
    }
    DirectoryTreeDialog .title {
        text-style: bold;
        margin-bottom: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, root: str = "/", *, title: str = "Browse") -> None:
        super().__init__()
        self._root = root
        self._title = title

    def compose(self) -> ComposeResult:
        from textual.widgets import DirectoryTree

        with Vertical():
            yield Static(f"{self._title}  (Enter: cd here, Esc: cancel)", classes="title")
            tree = DirectoryTree(self._root, id="dt")
            yield tree

    def on_mount(self) -> None:
        from textual.widgets import DirectoryTree

        self.query_one("#dt", DirectoryTree).focus()

    def on_directory_tree_directory_selected(self, event) -> None:  # type: ignore[no-untyped-def]
        # User pressed Enter on a directory.
        self.dismiss(str(event.path))

    def action_cancel(self) -> None:
        self.dismiss(None)


class OnCatResultsDialog(ModalScreen[object]):
    """Browseable list of OnCat experiments. Enter returns the chosen one.

    The dialog itself does no I/O — the caller passes a pre-fetched list of
    :class:`~sansdir.core.oncat.Experiment` objects (so the modal can be
    unit-tested without network) and gets back either the selected
    Experiment or ``None`` on cancel.
    """

    DEFAULT_CSS = """
    OnCatResultsDialog {
        align: center middle;
    }
    OnCatResultsDialog > Vertical {
        background: $surface;
        border: round $accent;
        padding: 1 2;
        width: 90%;
        height: 80%;
    }
    OnCatResultsDialog .title {
        text-style: bold;
        margin-bottom: 1;
    }
    OnCatResultsDialog .hint {
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
    ]

    def __init__(self, experiments: list, *, keyword: str = "") -> None:  # type: ignore[type-arg]
        super().__init__()
        self._experiments = experiments
        self._keyword = keyword

    def compose(self) -> ComposeResult:
        from textual.widgets import DataTable

        title = (
            f"OnCat results for {self._keyword!r} — {len(self._experiments)} match(es)"
            if self._keyword
            else f"OnCat — {len(self._experiments)} experiment(s)"
        )
        with Vertical():
            yield Static(title, classes="title")
            table: DataTable = DataTable(id="oncat-table", cursor_type="row", show_header=True)
            table.add_columns("IPTS", "Title", "PI / Members", "Last activity")
            for e in self._experiments:
                table.add_row(
                    e.ipts,
                    e.title,
                    ", ".join(e.members) if e.members else "",
                    e.activity,
                )
            yield table
            yield Static(
                "[dim]Enter to cd into the IPTS · Esc / q to cancel[/dim]",
                classes="hint",
            )

    def on_mount(self) -> None:
        from textual.widgets import DataTable

        if self._experiments:
            self.query_one("#oncat-table", DataTable).focus()

    def on_data_table_row_selected(self, event) -> None:  # type: ignore[no-untyped-def]
        idx = event.cursor_row
        if 0 <= idx < len(self._experiments):
            self.dismiss(self._experiments[idx])
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class MailDialog(ModalScreen[dict | None]):
    """Recipient + subject + body modal.

    Returns ``{"recipient", "subject", "body"}`` on submit, or ``None`` on
    Esc / Ctrl+C. The list of attachments is computed by the caller from
    the active pane's selection — the dialog only collects the human
    inputs.
    """

    DEFAULT_CSS = """
    MailDialog {
        align: center middle;
    }
    MailDialog > Vertical {
        background: $surface;
        border: round $accent;
        padding: 1 2;
        width: 80%;
        height: auto;
    }
    MailDialog .title {
        text-style: bold;
        margin-bottom: 1;
    }
    MailDialog .field-label {
        color: $text-muted;
        margin-top: 1;
    }
    MailDialog .body-input {
        height: 8;
        border: round $surface;
    }
    MailDialog Center {
        margin-top: 1;
    }
    MailDialog Button {
        margin: 0 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+c", "cancel", "Cancel", show=False),
        Binding("ctrl+s", "submit", "Send", show=False),
    ]

    def __init__(
        self,
        *,
        attachments_summary: str = "",
        default_subject: str = "",
        default_recipient: str = "",
    ) -> None:
        super().__init__()
        self._summary = attachments_summary
        self._default_subject = default_subject
        self._default_recipient = default_recipient

    def compose(self) -> ComposeResult:
        from textual.widgets import Input, TextArea

        with Vertical():
            yield Static("Send mail", classes="title")
            if self._summary:
                yield Static(f"attachments: {self._summary}")
            yield Static("To:", classes="field-label")
            yield Input(
                value=self._default_recipient,
                placeholder="user@example.com",
                id="mail-to",
                select_on_focus=False,
            )
            yield Static("Subject:", classes="field-label")
            yield Input(
                value=self._default_subject,
                placeholder="subject",
                id="mail-subj",
                select_on_focus=False,
            )
            yield Static("Body:  (Ctrl+S to send, Esc to cancel)", classes="field-label")
            yield TextArea("", id="mail-body", classes="body-input")
            with Center():
                yield Button("Send", id="send", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        from textual.widgets import Input

        target = "mail-to" if not self._default_recipient else "mail-subj"
        self.query_one(f"#{target}", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send":
            self.action_submit()
        else:
            self.action_cancel()

    def action_submit(self) -> None:
        from textual.widgets import Input, TextArea

        recipient = self.query_one("#mail-to", Input).value.strip()
        subject = self.query_one("#mail-subj", Input).value.strip()
        body = self.query_one("#mail-body", TextArea).text
        if not recipient:
            self.app.notify("recipient is required", severity="warning")
            self.query_one("#mail-to", Input).focus()
            return
        self.dismiss({"recipient": recipient, "subject": subject, "body": body})

    def action_cancel(self) -> None:
        self.dismiss(None)


class HdfKeyPickerScreen(ModalScreen[list[str] | None]):
    """Full-screen tree picker for batch metadata keys.

    Lazy-expands the supplied HDF5 file (raw NeXus has 200+ DASlogs;
    eager walk would be both slow and unreadable). ``Space`` on a
    *dataset* leaf — or a group whose only meaningful payload is a
    ``value`` child (the SNS DASlogs convention) — toggles selection
    and prepends ``[*]`` to the label. ``Ctrl+S`` (or the **Done**
    button) returns the selected list; ``Esc`` cancels.

    Used as a sub-flow of :class:`BatchExtractDialog`.
    """

    DEFAULT_CSS = """
    HdfKeyPickerScreen {
        align: center middle;
    }
    HdfKeyPickerScreen > Vertical {
        background: $surface;
        border: round $accent;
        padding: 1 2;
        width: 95%;
        height: 95%;
    }
    HdfKeyPickerScreen .title {
        text-style: bold;
        margin-bottom: 1;
    }
    HdfKeyPickerScreen #search-input {
        height: 3;
        margin-bottom: 1;
    }
    HdfKeyPickerScreen Tree {
        height: 1fr;
    }
    HdfKeyPickerScreen #search-results {
        height: 1fr;
        display: none;
    }
    HdfKeyPickerScreen.-searching #picker-tree {
        display: none;
    }
    HdfKeyPickerScreen.-searching #search-results {
        display: block;
    }
    HdfKeyPickerScreen .meta {
        color: $accent;
        margin-top: 1;
    }
    HdfKeyPickerScreen .hint {
        color: $text-muted;
        margin-top: 1;
    }
    HdfKeyPickerScreen Button {
        margin: 0 1;
    }
    HdfKeyPickerScreen .button-row {
        height: auto;
        align-horizontal: center;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+s", "submit", "Done", show=False),
    ]

    _LAZY_MARKER: ClassVar[str] = "__sansdir_lazy__"

    def __init__(self, path, *, initial: list[str] | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self._path = path
        self._selected: list[str] = list(initial or [])
        # Lazy: populated on first search via a worker (the eager walk
        # of a 350 MB raw NeXus file takes a couple of seconds).
        self._all_nodes_cache: list | None = None  # type: ignore[type-arg]

    def compose(self) -> ComposeResult:
        from textual.widgets import DataTable, Input, Tree

        from sansdir.hdf.reader import HdfNode

        with Vertical():
            yield Static(f"Pick keys · {self._path.name}", classes="title")
            yield Static(
                "[b]Space[/]: toggle · [b]→[/]: expand · [b]↑/↓[/]: move · "
                "[b]/[/]: search · [b]Ctrl+S[/]: done · [b]Esc[/]: cancel",
                classes="hint",
            )
            yield Input(
                placeholder="search keys (substring; clear to return to tree)",
                id="search-input",
            )
            yield Tree[HdfNode](label=self._path.name, id="picker-tree")
            yield DataTable(
                id="search-results", cursor_type="row", show_header=True
            )
            yield Static("", id="picker-meta", classes="meta")
            with Horizontal(classes="button-row"):
                yield Button("Done (Ctrl+S)", id="done", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        from textual.widgets import DataTable, Tree

        from sansdir.hdf.reader import HdfNode

        tree: Tree[HdfNode] = self.query_one("#picker-tree", Tree)
        tree.show_root = True
        tree.root.expand()
        results = self.query_one("#search-results", DataTable)
        results.add_columns(" ", "key", "shape")
        try:
            self._populate(tree.root, "/")
        except Exception as exc:
            self.app.notify(f"HDF5: {exc}", severity="error")
            self.dismiss(None)
            return
        tree.focus()
        self._refresh_markers(tree.root)
        self._update_meta()

    # ------------------------------------------------------------------
    # Lazy expansion
    # ------------------------------------------------------------------

    def _populate(self, node, group_path: str) -> None:  # type: ignore[no-untyped-def]
        from sansdir.hdf.reader import list_children, open_nexus

        with open_nexus(self._path) as fh:
            children = list_children(fh, group_path)
        for child in children:
            label = self._label_for(child, marker=self._marker_for(child))
            if child.kind == "group":
                child_node = node.add(label, data=child, expand=False)
                child_node.add(self._LAZY_MARKER, data=None)
            else:
                node.add_leaf(label, data=child)

    def _marker_for(self, node) -> str:  # type: ignore[no-untyped-def]
        return "*" if self._effective_key(node) in self._selected else " "

    @staticmethod
    def _label_for(node, *, marker: str = " ") -> str:  # type: ignore[no-untyped-def]
        name = node.path.rsplit("/", 1)[-1] or "/"
        if node.kind == "group":
            return f"[{marker}] {name}/"
        shape = "x".join(str(d) for d in node.shape) or "scalar"
        return f"[{marker}] {name}  [{node.dtype}, {shape}]"

    def on_tree_node_expanded(self, event) -> None:  # type: ignore[no-untyped-def]
        from sansdir.hdf.reader import HdfNode

        node = event.node
        if node.children and any(c.data is not None for c in node.children):
            return
        node.remove_children()
        data = node.data
        if isinstance(data, HdfNode) and data.kind == "group":
            self._populate(node, data.path)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _effective_key(self, node) -> str | None:  # type: ignore[no-untyped-def]
        """Path the extractor reads for ``node`` — or None if unselectable."""
        from sansdir.hdf.reader import HdfNode

        if not isinstance(node, HdfNode):
            return None
        if node.kind == "dataset":
            return node.path
        if node.kind == "group" and self._group_has_value(node.path):
            return f"{node.path.rstrip('/')}/value"
        return None

    def _group_has_value(self, group_path: str) -> bool:
        from sansdir.hdf.reader import open_nexus

        try:
            with open_nexus(self._path) as fh:
                grp = fh[group_path.lstrip("/")]
                return hasattr(grp, "keys") and "value" in grp
        except Exception:
            return False

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        from textual.widgets import DataTable, Input, Tree

        tree = self.query_one("#picker-tree", Tree)
        results = self.query_one("#search-results", DataTable)
        # ``/`` from anywhere jumps to the search input; ``Esc`` from
        # the search input clears it (handled via Input's own keys).
        if event.key == "slash" and not isinstance(self.focused, Input):
            self.query_one("#search-input", Input).focus()
            event.stop()
            event.prevent_default()
            return
        if self.focused is tree and event.key == "space":
            self._toggle_cursor_node(tree)
            event.stop()
            event.prevent_default()
            return
        if self.focused is results and event.key == "space":
            self._toggle_search_row(results)
            event.stop()
            event.prevent_default()
            return

    def _toggle_cursor_node(self, tree) -> None:  # type: ignore[no-untyped-def]
        node = tree.cursor_node
        if node is None or node.data is None:
            return
        key = self._effective_key(node.data)
        if key is None:
            self.app.notify(
                f"{node.data.path}: not a dataset (and no /value child) — pick a leaf",
                severity="warning",
            )
            return
        if key in self._selected:
            self._selected.remove(key)
        else:
            self._selected.append(key)
        node.set_label(self._label_for(node.data, marker=self._marker_for(node.data)))
        self._update_meta()

    def _refresh_markers(self, root) -> None:  # type: ignore[no-untyped-def]
        for child in list(root.children):
            data = child.data
            if data is None:
                continue
            child.set_label(self._label_for(data, marker=self._marker_for(data)))
            if child.children:
                self._refresh_markers(child)

    def _update_meta(self) -> None:
        meta = self.query_one("#picker-meta", Static)
        if self._selected:
            preview = ", ".join(self._selected[:3])
            if len(self._selected) > 3:
                preview += f" (+{len(self._selected) - 3} more)"
            meta.update(f"selected: {len(self._selected)} key(s) — {preview}")
        else:
            meta.update("selected: 0 key(s)")

    # ------------------------------------------------------------------
    # Search mode
    # ------------------------------------------------------------------

    def on_input_changed(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.input.id != "search-input":
            return
        query = event.value.strip().lower()
        if not query:
            # Empty → back to tree mode.
            self.remove_class("-searching")
            return
        # Ensure the cache exists, then filter. The walk runs in a
        # worker so a 350 MB raw NeXus file doesn't freeze the UI.
        if self._all_nodes_cache is None:
            self.run_worker(
                self._populate_cache_then_filter(query),
                exclusive=True,
                name="key-search",
            )
        else:
            self._show_search_results(query)

    async def _populate_cache_then_filter(self, query: str) -> None:
        import asyncio

        from sansdir.hdf.reader import open_nexus, walk_tree

        def _walk() -> list:  # type: ignore[type-arg]
            with open_nexus(self._path) as fh:
                return walk_tree(fh)

        self._all_nodes_cache = await asyncio.to_thread(_walk)
        # Re-read the current input value — user may have typed more
        # while the walk was running, in which case ``query`` is stale.
        from textual.widgets import Input

        current = self.query_one("#search-input", Input).value.strip().lower()
        if current:
            self._show_search_results(current)

    def _show_search_results(self, query: str) -> None:
        from textual.widgets import DataTable

        if self._all_nodes_cache is None:
            return
        # Match against the path, case-insensitive substring.
        matches = [n for n in self._all_nodes_cache if query in n.path.lower()]
        # Cap to 500 to keep rendering snappy on huge files; user can
        # narrow further if they overshoot.
        if len(matches) > 500:
            matches = matches[:500]
        table = self.query_one("#search-results", DataTable)
        table.clear()
        # Save the matched nodes alongside row index so Space can
        # resolve the row → node without re-querying h5py.
        self._search_rows = matches
        for n in matches:
            marker = "*" if self._effective_key(n) in self._selected else " "
            shape = "x".join(str(d) for d in n.shape) or ("group" if n.kind == "group" else "scalar")
            table.add_row(marker, n.path, shape)
        self.add_class("-searching")
        if matches:
            table.move_cursor(row=0)

    def _toggle_search_row(self, table) -> None:  # type: ignore[no-untyped-def]
        rows = getattr(self, "_search_rows", None)
        if not rows:
            return
        idx = table.cursor_row
        if idx < 0 or idx >= len(rows):
            return
        node = rows[idx]
        key = self._effective_key(node)
        if key is None:
            self.app.notify(
                f"{node.path}: not a dataset (and no /value child) — pick a leaf",
                severity="warning",
            )
            return
        if key in self._selected:
            self._selected.remove(key)
            table.update_cell_at((idx, 0), " ")
        else:
            self._selected.append(key)
            table.update_cell_at((idx, 0), "*")
        # Also re-mark the tree if the matching node was already
        # populated — keeps both views consistent on the way out.
        self._update_meta()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "done":
            self.action_submit()
        else:
            self.action_cancel()

    def action_submit(self) -> None:
        self.dismiss(list(self._selected))

    def action_cancel(self) -> None:
        self.dismiss(None)


class BatchExtractDialog(ModalScreen[dict | None]):
    """Output form for the batch metadata extractor.

    The picker (:class:`HdfKeyPickerScreen`) is a separate full-screen
    modal pushed on first mount or via the **Browse keys** button — the
    HDF5 tree needs vertical room that an inline widget can't reasonably
    give it. The picker dismisses back to this dialog with the chosen
    paths merged into the comma-separated keys input, which the user can
    also edit by hand.
    """

    DEFAULT_CSS = """
    BatchExtractDialog {
        align: center middle;
    }
    BatchExtractDialog > Vertical {
        background: $surface;
        border: round $accent;
        padding: 1 2;
        width: 80%;
        height: auto;
        max-height: 90%;
    }
    BatchExtractDialog .title {
        text-style: bold;
        margin-bottom: 1;
    }
    BatchExtractDialog .field-label {
        color: $text-muted;
        margin-top: 1;
    }
    BatchExtractDialog .hint {
        color: $text-muted;
        margin-top: 1;
    }
    BatchExtractDialog Button {
        margin: 0 1;
    }
    BatchExtractDialog .button-row {
        height: auto;
        align-horizontal: center;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+c", "cancel", "Cancel", show=False),
        Binding("ctrl+s", "submit", "Submit", show=False),
        Binding("ctrl+b", "browse_keys", "Browse keys", show=False),
        Binding("ctrl+t", "toggle_stats", "Toggle stats", show=False),
    ]

    def __init__(
        self,
        files: list,  # type: ignore[type-arg]
        *,
        auto_browse: bool = True,
        write_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self._files = files
        self._with_stats: bool = False
        self._auto_browse: bool = auto_browse
        # Where the dispatcher will write relative paths to. Shown in
        # the dialog so the user can confirm before pressing Run.
        self._write_dir: Path | None = write_dir

    def compose(self) -> ComposeResult:
        from textual.widgets import Input, Select

        with Vertical():
            yield Static(
                f"Batch metadata extract · {len(self._files)} file(s)",
                classes="title",
            )
            yield Static(
                "Press [b]Ctrl+B[/] (or click [b]Browse keys[/]) to pick keys "
                "from the HDF5 tree, or type them comma-separated below.",
                classes="hint",
            )
            yield Static("Selected keys:", classes="field-label")
            yield Input(
                placeholder="/entry/DASlogs/temperature/value, /entry/duration",
                id="keys-input",
            )
            yield Static("Mode:", classes="field-label")
            yield Select(
                options=[
                    ("Per-file (one CSV per input, full arrays)", "per_file"),
                    ("Summary (one row per input, means)", "summary"),
                ],
                value="per_file",
                id="mode-select",
                allow_blank=False,
            )
            # ``write_dir`` comes from the dispatcher (= inactive
            # pane's cwd). Show it next to the Output label so the
            # user sees where relative paths will resolve before
            # hitting Run — saves a "wait, where did that go?"
            # round-trip.
            dest_text = (
                f"Output  [dim](relative paths → {self._write_dir})[/dim]"
                if self._write_dir is not None
                else "Output:"
            )
            yield Static(dest_text, classes="field-label")
            yield Input(
                # Per-file mode auto-injects ``<filename>_`` if missing,
                # so this default works for either mode.
                value="<filename>_extracted.csv",
                placeholder=(
                    "<filename>_temp.csv  (per-file mode auto-injects "
                    "<filename>_ if you forget it)"
                ),
                id="out-input",
            )
            yield Static("Format:", classes="field-label")
            yield Select(
                options=[("TSV", "tsv"), ("CSV", "csv"), ("Aligned columns", "columns")],
                value="tsv",
                id="fmt-select",
                allow_blank=False,
            )
            yield Static(
                "[dim](stats: off — Ctrl+T toggles _stdev/_n columns)[/dim]",
                id="stats-hint",
                classes="hint",
            )
            yield Static(
                "[dim]Ctrl+B: browse keys · Ctrl+T: stats · Ctrl+S: run · Esc: cancel[/dim]",
                classes="hint",
            )
            # ``Center`` is vertical-by-default in Textual, so three buttons
            # stack instead of sitting on one row. ``Horizontal`` with a
            # centered align-horizontal puts them side by side.
            with Horizontal(classes="button-row"):
                yield Button("Browse keys (Ctrl+B)", id="browse")
                yield Button("Run", id="submit", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        from textual.widgets import Input

        # Auto-launch the picker on first mount when the caller wants
        # it — most users don't already know the exact key paths and
        # the picker is the whole point. ``auto_browse=False`` lets
        # tests and headless callers see the bare form.
        if self._auto_browse and self._files:
            self.call_after_refresh(self.action_browse_keys)
            return
        self.query_one("#keys-input", Input).focus()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_browse_keys(self) -> None:
        from textual.widgets import Input

        if not self._files:
            self.app.notify("no NeXus file to browse", severity="warning")
            return
        inp = self.query_one("#keys-input", Input)
        initial = [k.strip() for k in inp.value.split(",") if k.strip()]

        def _on_picked(result: list[str] | None) -> None:
            if result is None:
                return  # Cancel — leave the existing input untouched.
            inp.value = ", ".join(result)

        self.app.push_screen(HdfKeyPickerScreen(self._files[0], initial=initial), _on_picked)

    def action_toggle_stats(self) -> None:
        self._with_stats = not self._with_stats
        hint = self.query_one("#stats-hint", Static)
        if self._with_stats:
            hint.update("[b yellow]stats: ON[/]   (Ctrl+T to toggle)")
        else:
            hint.update("[dim](stats: off — Ctrl+T toggles _stdev/_n columns)[/dim]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "browse":
            self.action_browse_keys()
        elif event.button.id == "submit":
            self.action_submit()
        else:
            self.action_cancel()

    def action_submit(self) -> None:
        from textual.widgets import Input, Select

        keys_raw = self.query_one("#keys-input", Input).value
        keys = [k.strip() for k in keys_raw.split(",") if k.strip()]
        if not keys:
            self.app.notify("at least one key required", severity="warning")
            self.query_one("#keys-input", Input).focus()
            return
        out = self.query_one("#out-input", Input).value.strip()
        fmt_widget = self.query_one("#fmt-select", Select)
        fmt = str(fmt_widget.value) if fmt_widget.value is not None else "tsv"
        mode_widget = self.query_one("#mode-select", Select)
        mode = str(mode_widget.value) if mode_widget.value is not None else "per_file"
        self.dismiss(
            {
                "keys": keys,
                "out": out,
                "fmt": fmt,
                "mode": mode,
                "with_stats": self._with_stats,
            }
        )

    def action_cancel(self) -> None:
        self.dismiss(None)
