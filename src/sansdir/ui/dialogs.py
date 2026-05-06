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
