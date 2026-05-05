"""Reusable Textual modals.

For Phase 2 we need exactly one: a yes/no confirm dialog. Later phases
will add a destination-editor dialog (copy/move with editable target),
a directory tree picker, and a metadata extract picker.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Center, Vertical
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
        yes_label: str = "Yes",
        no_label: str = "No",
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
    """Single-line text prompt; returns the entered string, or ``None`` on cancel."""

    DEFAULT_CSS = """
    TextPromptDialog {
        align: center middle;
    }
    TextPromptDialog > Vertical {
        background: $surface;
        border: round $accent;
        padding: 1 2;
        width: 80%;
    }
    TextPromptDialog .title {
        text-style: bold;
        margin-bottom: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, message: str, *, default: str = "", title: str = "Prompt") -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._default = default

    def compose(self) -> ComposeResult:
        from textual.widgets import Input

        with Vertical():
            yield Label(self._title, classes="title")
            yield Static(self._message)
            yield Input(value=self._default, id="prompt-input", select_on_focus=False)

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
