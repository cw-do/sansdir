"""The TUI must never load Qt (Phase 9.10.0).

Run in a fresh interpreter: by the time this test runs, other tests in
the same process may already have imported PySide6.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TUI_AND_PURE_MODULES = [
    "sansdir.app",
    "sansdir.cli",
    "sansdir.commands.builtins",
    "sansdir.viewer",
    "sansdir.viewer.cube",
    "sansdir.viewer.geometry",
    "sansdir.viewer.colorscale",
    "sansdir.viewer.tofrange",
    "sansdir.viewer.masking",
    "sansdir.viewer.settings",
    "sansdir.viewer.export",
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


def test_clear_cache_cli_imports_no_qt(tmp_path: Path) -> None:
    code = (
        "import sys\n"
        "from sansdir.viewer.__main__ import main\n"
        "assert main(['--clear-cache']) == 0\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('PySide6', 'pyqtgraph'))\n"
        "print('QT:' + ','.join(bad))\n"
    )
    env = {**os.environ, "SANSDIR_CACHE_DIR": str(tmp_path)}
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, env=env
    )
    assert out.stdout.strip().endswith("QT:")
    assert "removed 0 runs, 0 B" in out.stdout
