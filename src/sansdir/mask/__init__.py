"""Interactive detector-mask creation (Phase 9.6).

The whole package is pure Python — no Mantid runtime imports — so it
runs on any cluster account that can already read the source ``.nxs.h5``
file. The output formats (Mantid SaveMask XML, Mantid Processed NeXus,
plain ``.npy``) are loadable downstream by Mantid / drtsans / your own
code.

Submodules:

* :mod:`sansdir.mask.core`     — shape ABC + MaskBuilder
* :mod:`sansdir.mask.detector` — heatmap loader + SourceMeta
* :mod:`sansdir.mask.writers`  — XML / NeXus / npy / log writers

The TUI integration lives in :mod:`sansdir.commands.builtins` (the
``mask.create`` registry command + ``ui.mask`` keybinding handler).
"""

from __future__ import annotations
