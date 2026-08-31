"""USANS reduction support — pure, UI-free helpers plus the engine runner.

Nothing in this subpackage imports ``textual``, ``httpx``, ``scipy``,
``pandas`` or ``mantid``: the grouping / reconciliation / table code is
plain stdlib so it can be unit-tested offline and driven equally from the
TUI, the ``sansdir usans`` CLI, or (later) the LLM layer.

The reduction *math* is deliberately not here — sansdir shells out to the
instrument team's installed ``reduceUSANS`` console script
(``neutrons/usansred``). See :mod:`sansdir.usans.runner`.

Typical flow::

    from sansdir.usans.catalog import build_catalog, write_outputs
    from sansdir.usans.runner import reduce_csv

    cat = build_catalog("IPTS-37679", runs, start_run=49434)
    write_outputs(cat, "IPTS-37679_setup.csv", "IPTS-37679_NOTE.md")
    # ... user reviews the CSV with F4 ...
    reduce_csv("IPTS-37679_setup.csv", data_dir=..., output_dir="output")
"""

from __future__ import annotations

__all__ = ["catalog", "grouping", "reconcile", "runner", "table"]
