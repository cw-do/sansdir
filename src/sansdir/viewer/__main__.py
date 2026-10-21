"""``python -m sansdir.viewer [FILE] [--mask M] [--output OUT]`` — open the detector viewer.

Exit codes: 0 closed, 3 closed after saving a mask, 2 the viewer extra is
missing (or a bad argument).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sansdir.viewer.cube import DEFAULT_NBINS
from sansdir.viewer.masking import MASK_TOOLS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sansdir.viewer",
        description="Fast EQSANS raw detector viewer (TOF slicing, hover readout, masks).",
    )
    parser.add_argument("path", nargs="?", type=Path, help="raw or processed NeXus file")
    parser.add_argument(
        "--nbins", type=int, default=DEFAULT_NBINS, help="fine TOF bins (default %(default)s)"
    )
    parser.add_argument(
        "--mask", type=Path, help="load this mask (mask_log.json / .xml / .nxs / .npy) at start"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="default path for Save mask (default: <file-stem>_mask.nxs next to FILE)",
    )
    parser.add_argument(
        "--tool", choices=MASK_TOOLS, default="pan", help="mask tool active at start"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="neither read nor write ~/.cache/sansdir/viewer",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="delete everything in ~/.cache/sansdir/viewer and exit",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="print load milestones to stderr and exit once the full run is on screen",
    )
    args = parser.parse_args(argv)
    if args.clear_cache:  # no Qt needed
        from sansdir.viewer.cache import CubeCache, describe

        cache = CubeCache.default()
        runs, size = cache.clear()
        print(f"removed {describe(runs, size)} from {cache.directory}")
        return 0
    try:
        from sansdir.viewer.qt.main_window import run
    except ImportError as exc:
        print(
            f"the detector viewer needs PySide6 + pyqtgraph ({exc}).\n"
            "install them with:  pip install 'sansdir[viewer]'",
            file=sys.stderr,
        )
        return 2
    return run(
        args.path,
        nbins=args.nbins,
        use_cache=not args.no_cache,
        benchmark=args.benchmark,
        mask=args.mask,
        output=args.output,
        tool=args.tool,
    )


if __name__ == "__main__":
    raise SystemExit(main())
