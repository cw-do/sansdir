"""Qt front end of the viewer — the only package allowed to import Qt.

Never import this from the TUI process; it is loaded by
``python -m sansdir.viewer`` only.
"""

from __future__ import annotations
