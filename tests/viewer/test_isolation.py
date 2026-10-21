"""The TUI must never load Qt (Phase 9.10.0).

Run in a fresh interpreter: by the time this test runs, other tests in
the same process may already have imported PySide6.
"""

from __future__ import annotations

import subprocess
import sys

TUI_AND_PURE_MODULES = [
    "sansdir.app",
    "sansdir.cli",
    "sansdir.commands.builtins",
    "sansdir.viewer",
    "sansdir.viewer.cube",
    "sansdir.viewer.geometry",
    "sansdir.viewer.colorscale",
    "sansdir.viewer.__main__",
]


def test_tui_and_pure_viewer_modules_import_no_qt() -> None:
    code = (
        "import importlib, sys\n"
        f"for m in {TUI_AND_PURE_MODULES!r}: importlib.import_module(m)\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('PySide6', 'pyqtgraph', 'shiboken6'))\n"
        "print(','.join(bad))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""
