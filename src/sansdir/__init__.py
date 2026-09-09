"""sansdir — MDIR-style terminal file manager for SANS data."""

from __future__ import annotations

__version__ = "0.10.1"

# Kept here rather than read from importlib.metadata: an editable install can
# carry stale metadata (the shared dev venv reports 0.0.1), and the help
# overlay showing the wrong licence would be worse than not showing one. The
# LICENSE file remains authoritative; these strings must match it.
__license__ = "MIT"
__copyright__ = "Copyright (c) 2026 Changwoo Do, Oak Ridge National Laboratory"
__url__ = "https://github.com/cw-do/sansdir"

__all__ = ["__copyright__", "__license__", "__url__", "__version__"]
