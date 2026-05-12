"""Display detection + matplotlib backend selection.

Two display modes:

* **Interactive** (display present, ``$SANSDIR_HEADLESS`` not set) —
  :func:`spawn_plot_window` runs ``python -m sansdir.plot.window`` in a
  separate process. The subprocess owns its own matplotlib GUI event
  loop so the figure window is fully responsive and the TUI never
  shares a thread with Qt/Tk. The TUI process itself never imports
  matplotlib in this mode.

* **Headless** — :func:`save_figure_to_png` writes a PNG to
  ``~/.cache/sansdir/plots/`` for callers that have already built a
  Figure inline.

This split was forced by an early bug: ``plt.show(block=False)`` from
inside Textual opened a window with nothing in it and a dead close
button, because there was no event loop pumping matplotlib events. A
subprocess sidesteps the conflict entirely.
"""

from __future__ import annotations

import datetime as _dt
import os
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sansdir.core.history import default_history_path

if TYPE_CHECKING:
    from matplotlib.figure import Figure


HEADLESS_ENV: str = "SANSDIR_HEADLESS"
DEFAULT_INTERACTIVE_PRIORITY: tuple[str, ...] = ("QtAgg", "TkAgg", "GTK4Agg")


@dataclass(frozen=True, slots=True)
class BackendInfo:
    """Outcome of a plot dispatch (interactive subprocess or headless PNG)."""

    name: str
    interactive: bool
    reason: str
    pid: int | None = None  # set when we spawned a window subprocess


# Module-level cache used only by the headless save path; subprocesses
# pick their own backend independently.
_headless_initialised: bool = False


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def has_display() -> bool:
    """Return True iff there's a display server available to host a window."""
    if os.environ.get(HEADLESS_ENV):
        return False
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def plot_cache_dir() -> Path:
    """``~/.cache/sansdir/plots`` (honours ``$SANSDIR_CACHE_DIR``)."""
    return default_history_path().parent / "plots"


# ---------------------------------------------------------------------------
# Interactive: spawn a separate process for each window
# ---------------------------------------------------------------------------


def spawn_plot_window(
    kind: str,
    paths: Iterable[Path],
    *,
    xscale: str | None = None,
    yscale: str | None = None,
    errorbars: bool = True,
    title: str | None = None,
    cmap: str | None = None,
    log_intensity: bool = True,
    colorbar_mode: str | None = None,
    log_dir: Path | None = None,
) -> BackendInfo:
    """Launch a detached ``python -m sansdir.plot.window`` for the given files.

    The subprocess writes its stdout/stderr into the plot cache dir so a
    user can ``cat`` it after a misbehaving plot. We do **not** wait for
    the subprocess — closing the window triggers its own exit.

    The 2D-only kwargs (``cmap``, ``log_intensity``, ``colorbar_mode``) are
    silently ignored by the subprocess for 1D plots.
    """
    log_dir = log_dir or plot_cache_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    log_path = log_dir / f"{stamp}_{kind}_window.log"

    argv = [sys.executable, "-m", "sansdir.plot.window", kind]
    argv.extend(str(p) for p in paths)
    if xscale:
        argv.extend(["--xscale", xscale])
    if yscale:
        argv.extend(["--yscale", yscale])
    if not errorbars:
        argv.append("--no-errorbars")
    if title:
        argv.extend(["--title", title])
    if cmap:
        argv.extend(["--cmap", cmap])
    # Log-intensity is the SANS default; pass an explicit flag in
    # either direction so the subprocess doesn't have to assume.
    argv.append("--log-intensity" if log_intensity else "--no-log-intensity")
    if colorbar_mode:
        argv.extend(["--colorbar-mode", colorbar_mode])

    log_fh = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        argv,
        stdout=log_fh,
        stderr=log_fh,
        # Detach so closing the TUI doesn't kill the figure window.
        start_new_session=True,
        close_fds=True,
    )
    return BackendInfo(
        name="subprocess",
        interactive=True,
        reason=f"window subprocess (pid {proc.pid}); log: {log_path}",
        pid=proc.pid,
    )


# ---------------------------------------------------------------------------
# Headless: save a Figure to PNG
# ---------------------------------------------------------------------------


def init_headless_backend() -> BackendInfo:
    """Force matplotlib into Agg mode (idempotent). Called by the headless path."""
    global _headless_initialised
    import matplotlib

    if not _headless_initialised:
        matplotlib.use("Agg", force=True)
        _headless_initialised = True
    return BackendInfo(
        name="Agg",
        interactive=False,
        reason="headless: SANSDIR_HEADLESS set"
        if os.environ.get(HEADLESS_ENV)
        else "no $DISPLAY / $WAYLAND_DISPLAY",
    )


def save_figure_to_png(fig: Figure, *, title: str = "plot") -> tuple[Path, BackendInfo]:
    """Write ``fig`` to a timestamped PNG; return the path and backend info."""
    info = init_headless_backend()
    import matplotlib.pyplot as plt

    out_dir = plot_cache_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_title = "".join(c if c.isalnum() or c in "._-" else "_" for c in title) or "plot"
    stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    out_path = out_dir / f"{stamp}_{safe_title}.png"
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out_path, info


# ---------------------------------------------------------------------------
# Compatibility shims kept for tests that still call the old names
# ---------------------------------------------------------------------------


def init_backend(priority: tuple[str, ...] | None = None) -> BackendInfo:
    """Back-compat: callers that ask for "the" backend get the headless one.

    The old single-init flow is gone — interactive plots run in a
    subprocess that picks its own backend. This shim exists so unit
    tests that only care about the headless decision still pass.
    """
    del priority  # ignored
    if has_display():
        return BackendInfo(
            name="subprocess",
            interactive=True,
            reason="window subprocess (per-plot)",
        )
    return init_headless_backend()


def show_or_save(fig: Figure, *, title: str = "plot") -> tuple[Path | None, BackendInfo]:
    """Back-compat for callers built before the subprocess split."""
    return save_figure_to_png(fig, title=title)


def reset_backend_cache() -> None:
    """Clear the cached :class:`BackendInfo` (tests only)."""
    global _headless_initialised
    _headless_initialised = False


def close_all() -> None:
    """Best-effort ``plt.close('all')`` for app shutdown — tolerates absence.

    Subprocess windows aren't ours to close (they manage their own GUI
    loop) — this only cleans up any in-process figures the headless save
    path may have left around.
    """
    import contextlib

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    with contextlib.suppress(Exception):
        plt.close("all")


# Suppress unused-import warning for the Any re-export check in mypy.
_ = Any
