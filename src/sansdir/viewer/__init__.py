"""Fast raw-detector viewer + mask editor (Phase 9.10).

Spec: ``PLANNING-viewer.md``. The package splits in two:

* Qt-free modules — :mod:`sansdir.viewer.geometry` (display ↔ detector
  ID ↔ Mantid bank/tube/pixel), :mod:`sansdir.viewer.cube` (the
  cumulative TOF histogram), :mod:`sansdir.viewer.masking` (the mask
  model, mask files) and friends. Testable headlessly, importable from
  the TUI without cost.
* :mod:`sansdir.viewer.qt` — the **only** place PySide6 / pyqtgraph
  may be imported. It runs in the viewer subprocess
  (``python -m sansdir.viewer FILE``), never in the TUI process, so
  sansdir's cold start is unaffected. ``tests/viewer/test_isolation.py``
  pins that.
"""

from __future__ import annotations

# ``python -m sansdir.viewer`` exits with this after a mask was saved, so the
# TUI (``K`` / ``V``) knows to refresh its panes. 0 = closed without saving.
EXIT_SAVED: int = 3
