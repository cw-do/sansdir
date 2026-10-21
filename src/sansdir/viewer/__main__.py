"""``python -m sansdir.viewer [FILE]`` — open the detector viewer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sansdir.viewer.cube import DEFAULT_NBINS


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
        "--benchmark",
        action="store_true",
        help="print load milestones to stderr and exit once the full run is on screen",
    )
    args = parser.parse_args(argv)
    try:
        from sansdir.viewer.qt.main_window import run
    except ImportError as exc:
        print(
            f"the detector viewer needs PySide6 + pyqtgraph ({exc}).\n"
            "install them with:  pip install 'sansdir[viewer]'",
            file=sys.stderr,
        )
        return 2
    return run(args.path, nbins=args.nbins, benchmark=args.benchmark)


if __name__ == "__main__":
    raise SystemExit(main())
