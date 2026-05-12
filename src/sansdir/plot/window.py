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
    """Try each candidate backend until one *actually loads*, not just resolves.

    ``matplotlib.use("QtAgg")`` only sets the rcParam; the backend module
    isn't imported until a figure is created. So we have to call
    ``plt.figure()`` to provoke the real load — that's what surfaces a
    missing Qt binding before we waste time building data only to
    fail later inside :func:`make_iq_figure`.
    """
    import matplotlib

    errors: list[str] = []
    for candidate in DEFAULT_BACKEND_PRIORITY:
        try:
            matplotlib.use(candidate, force=True)
            import matplotlib.pyplot as plt

            fig = plt.figure()
            plt.close(fig)
            return candidate
        except (ImportError, ValueError, RuntimeError) as exc:
            errors.append(f"{candidate}: {type(exc).__name__}: {exc}")
            continue
    msg = "no interactive matplotlib backend available\n  " + "\n  ".join(errors)
    msg += (
        "\n\nFix one of:\n"
        '  - pip install "sansdir[qt]"           # installs PyQt5\n'
        "  - dnf install python3-tkinter         # system Tk (Linux)\n"
        "  - SANSDIR_HEADLESS=1 sansdir          # write PNGs instead"
    )
    raise RuntimeError(msg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sansdir.plot.window")
    parser.add_argument(
        "kind",
        choices=("iq", "transmission", "iqxqy", "nexus", "generic", "image"),
    )
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
    parser.add_argument("--cmap", default="viridis", help="matplotlib colormap (2D only)")
    # SANS intensity spans many decades, so log is the right default.
    # ``BooleanOptionalAction`` exposes both ``--log-intensity`` and
    # ``--no-log-intensity`` so power users can flip back to linear
    # when needed.
    parser.add_argument(
        "--log-intensity",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="log-scale the colormap (2D only); pass --no-log-intensity for linear",
    )
    parser.add_argument(
        "--colorbar-mode",
        choices=("shared", "independent"),
        default="shared",
        help="for tile mode: one shared bar or per-subplot bars",
    )
    args = parser.parse_args(argv)

    backend = _pick_interactive_backend()
    print(f"sansdir.plot.window: backend={backend}", file=sys.stderr)

    import matplotlib.pyplot as plt

    if args.kind == "iqxqy":
        from sansdir.plot import tile

        if len(args.files) == 1:
            tile.make_iqxqy_figure(
                args.files[0],
                cmap=args.cmap,
                log_intensity=args.log_intensity,
                title=args.title,
            )
        else:
            tile.make_tile_figure(
                args.files,
                cmap=args.cmap,
                colorbar_mode=args.colorbar_mode,
                log_intensity=args.log_intensity,
                title=args.title,
            )
    elif args.kind == "nexus":
        from sansdir.plot.hdf5_detector import make_detector_figure

        # One subprocess handles one NeXus file — the launcher fires N
        # subprocesses for N tagged files so each can be closed
        # independently. log_intensity is the SANS default; the
        # subprocess CLI doesn't expose a flag to flip it yet.
        make_detector_figure(args.files[0], log_intensity=True)
    elif args.kind == "generic":
        from sansdir.plot.generic import make_generic_figure

        make_generic_figure(args.files, title=args.title)
    elif args.kind == "image":
        from sansdir.plot.image import make_image_figure

        make_image_figure(args.files[0])
    else:
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

    # Blocking show — this subprocess owns its own GUI event loop.
    plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
