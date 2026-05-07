"""SVG snapshot tests for the dialogs and the help overlay.

Uses ``pytest-textual-snapshot``: first run with ``--snapshot-update``
bakes in the SVG files under ``tests/__snapshots__/``; subsequent runs
fail when rendering changes. Re-bless intentionally with
``pytest --snapshot-update`` after a UI tweak.

We snapshot only dialogs with deterministic input. The HDF5 picker /
tree screens lazy-walk a file via worker threads, which is racy under
the snapshot driver — they're covered by the Pilot tests in
``test_phase8.py`` instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sansdir.commands.builtins import build_default_registry
from sansdir.ui.dialogs import (
    BatchExtractDialog,
    ConfirmDialog,
    MailDialog,
    TextPromptDialog,
)
from sansdir.ui.help import HelpScreen
from sansdir.ui.keys import default_keymap


class _DialogHarness(App[None]):
    """Minimal host that pushes a single screen on mount.

    Snapshot fixtures in ``pytest-textual-snapshot`` capture one frame
    after the app finishes mounting. This harness gives the dialogs a
    non-empty parent so the screenshot includes their normal centred
    layout against the surface background.
    """

    CSS: ClassVar[str] = "Screen { background: $surface; }"

    def __init__(self, screen) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self._target = screen

    def compose(self) -> ComposeResult:
        # A breadcrumb behind the modal so the screenshot includes
        # the surface backdrop the dialog overlays.
        yield Static("(snapshot harness)")

    def on_mount(self) -> None:
        self.push_screen(self._target)


# ---------------------------------------------------------------------------
# ConfirmDialog
# ---------------------------------------------------------------------------


def test_snapshot_confirm_dialog_default(snap_compare) -> None:  # type: ignore[no-untyped-def]
    app = _DialogHarness(ConfirmDialog("Delete 3 files?"))
    assert snap_compare(app, terminal_size=(80, 20))


def test_snapshot_confirm_dialog_danger(snap_compare) -> None:  # type: ignore[no-untyped-def]
    app = _DialogHarness(
        ConfirmDialog(
            "rm -rf /SNS/EQSANS/IPTS-12345/raw — really?",
            danger=True,
            yes_label="(Y)es, delete",
            no_label="(N)o, keep",
        )
    )
    assert snap_compare(app, terminal_size=(80, 20))


# ---------------------------------------------------------------------------
# TextPromptDialog
# ---------------------------------------------------------------------------


def test_snapshot_text_prompt_dialog(snap_compare) -> None:  # type: ignore[no-untyped-def]
    app = _DialogHarness(
        TextPromptDialog(
            "Archive name:",
            default="reduced.zip",
            title="Make zip",
            help_text=(
                "filename.zip → current folder\n"
                "../filename.zip → parent folder\n"
                "/abs/path.zip → absolute"
            ),
        )
    )
    assert snap_compare(app, terminal_size=(80, 20))


# ---------------------------------------------------------------------------
# MailDialog
# ---------------------------------------------------------------------------


def test_snapshot_mail_dialog(snap_compare) -> None:  # type: ignore[no-untyped-def]
    app = _DialogHarness(
        MailDialog(
            attachments_summary="EQSANS_001_Iq.dat, EQSANS_002_Iq.dat",
            default_subject="[sansdir] data",
            default_recipient="user@example.com",
        )
    )
    assert snap_compare(app, terminal_size=(90, 24))


# ---------------------------------------------------------------------------
# BatchExtractDialog (auto_browse off so the picker doesn't pop up)
# ---------------------------------------------------------------------------


def test_snapshot_batch_extract_dialog(snap_compare) -> None:  # type: ignore[no-untyped-def]
    # Stable, hard-coded paths so the snapshot SVG is deterministic
    # across machines and pytest tmp_path values. The dialog never
    # opens the files in ``auto_browse=False`` mode — it only
    # renders their count.
    fake_root = Path("/SNS/EQSANS/IPTS-12345/nexus")
    files = [fake_root / f"EQSANS_{i:03d}.nxs.h5" for i in (1, 2, 3)]
    app = _DialogHarness(
        BatchExtractDialog(
            files,
            auto_browse=False,
            write_dir=Path("/SNS/EQSANS/IPTS-12345/shared"),
        )
    )
    assert snap_compare(app, terminal_size=(100, 28))


# ---------------------------------------------------------------------------
# HelpScreen — full registry, real keymap
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="Help screen renders the full keymap; snapshot is too brittle to "
    "useful change. Pilot test test_help_overlay_opens_and_closes covers it."
)
def test_snapshot_help_screen(snap_compare) -> None:  # type: ignore[no-untyped-def]
    class _StubApp:
        def __getattr__(self, name):  # type: ignore[no-untyped-def]
            return lambda *a, **k: None

    registry = build_default_registry(app=_StubApp())  # type: ignore[arg-type]
    app = _DialogHarness(HelpScreen(registry, default_keymap()))
    assert snap_compare(app, terminal_size=(120, 40))
