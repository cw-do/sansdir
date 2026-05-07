"""Help overlay — auto-generated from the registry and keymap.

Press ``?`` (or run ``:help`` / ``app.help``) to open. The screen reads
the live :class:`~sansdir.commands.registry.CommandRegistry` and the
default keymap so it always reflects what the running build actually
exposes — no separate help-text file to drift out of sync.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from sansdir import __version__
from sansdir.commands.registry import CommandRegistry
from sansdir.ui.keys import KeyBinding


class HelpScreen(ModalScreen[None]):
    """Modal screen listing key bindings and the full command registry."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen > VerticalScroll {
        width: 90%;
        height: 90%;
        background: $surface;
        border: round $accent;
        padding: 1 2;
    }
    HelpScreen .title {
        text-style: bold;
        margin-bottom: 1;
    }
    HelpScreen .contact {
        color: $text-muted;
        margin-bottom: 1;
    }
    HelpScreen .section {
        text-style: bold;
        margin-top: 1;
    }
    HelpScreen DataTable {
        height: auto;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close", show=False),
        Binding("question_mark", "dismiss", "Close", show=False),
        Binding("?", "dismiss", "Close", show=False),
    ]

    def __init__(self, registry: CommandRegistry, keymap: list[KeyBinding]) -> None:
        super().__init__()
        self._registry = registry
        self._keymap = keymap

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(
                f"[b cyan]▣[/] [b orange1]SansDIR[/]  [dim]v{__version__}[/dim] — help",
                classes="title",
            )
            yield Static(
                "Contact: [b]Changwoo Do[/]  ·  doc1@ornl.gov",
                classes="contact",
            )

            yield Static("Key bindings", classes="section")
            keys_table: DataTable[str] = DataTable(show_header=True, cursor_type=None)
            keys_table.add_columns("Key", "Action", "Command")
            for kb in self._keymap:
                if not kb.show_in_help:
                    continue
                keys_table.add_row(kb.key, kb.description, kb.command)
            yield keys_table

            yield Static("Registered commands", classes="section")
            cmds_table: DataTable[str] = DataTable(show_header=True, cursor_type=None)
            cmds_table.add_columns("Command", "Description", "Aliases")
            for cmd in self._registry.all():
                aliases = ", ".join(cmd.aliases) if cmd.aliases else ""
                desc = cmd.description + ("  [DANGER]" if cmd.danger else "")
                cmds_table.add_row(cmd.name, desc, aliases)
            yield cmds_table

    def action_dismiss(self, result: None = None) -> None:  # type: ignore[override]
        self.dismiss(None)
