"""Standalone matplotlib viewer subprocess.

Spawned by sansdir's TUI to display plots in their own GUI process so the
matplotlib event loop is fully independent of Textual's. This is the only
reliable way to get a *responsive* matplotlib window from a TUI app —
calling ``plt.show(block=False)`` from inside Textual leaves the window
unable to paint or close because there's nothing pumping its event loop.

Usage::

    python -m sansdir.plot.window iq /path/to/a.dat /path/to/b.dat
    python -m sansdir.plot.window transmission /path/to/trans.txt

Options match the kwargs of :func:`sansdir.plot.ascii1d.make_iq_figure` /
:func:`make_transmission_figure`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_BACKEND_PRIORITY: tuple[str, ...] = ("QtAgg", "TkAgg", "GTK4Agg")


def _pick_interactive_backend() -> str:
    import matplotlib

    for candidate in DEFAULT_BACKEND_PRIORITY:
        try:
            matplotlib.use(candidate, force=True)
            import matplotlib.pyplot

            return candidate
        except (ImportError, ValueError, RuntimeError):
            continue
    raise RuntimeError(
        f"no interactive matplotlib backend available (tried {list(DEFAULT_BACKEND_PRIORITY)})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sansdir.plot.window")
    parser.add_argument("kind", choices=("iq", "transmission"))
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--xscale", default=None)
    parser.add_argument("--yscale", default=None)
    parser.add_argument(
        "--no-errorbars",
        dest="errorbars",
        action="store_false",
        default=True,
    )
    parser.add_argument("--title", default=None)
    args = parser.parse_args(argv)

    backend = _pick_interactive_backend()
    print(f"sansdir.plot.window: backend={backend}", file=sys.stderr)

    import matplotlib.pyplot as plt

    from sansdir.plot import ascii1d

    kwargs: dict = {"errorbars": args.errorbars, "title": args.title}
    if args.xscale:
        kwargs["xscale"] = args.xscale
    if args.yscale:
        kwargs["yscale"] = args.yscale

    if args.kind == "iq":
        ascii1d.make_iq_figure(args.files, **kwargs)
    else:
        ascii1d.make_transmission_figure(args.files, **kwargs)

    # Blocking show — this subprocess owns its own GUI event loop, so the
    # window is fully responsive and closes normally.
    plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
