"""Display detection + matplotlib backend selection.

The first plot call detects whether we have a usable display server and
picks an interactive matplotlib backend (``QtAgg`` → ``TkAgg`` →
``GTK4Agg``). When no display is available — or when ``$SANSDIR_HEADLESS``
is set — we fall back to ``Agg`` and write a PNG under
``~/.cache/sansdir/plots/`` so the user has *something* to look at.

The chosen backend is cached for the process lifetime; the TUI cannot
swap backends mid-session because matplotlib doesn't support it cleanly.
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sansdir.core.history import default_history_path

if TYPE_CHECKING:
    from matplotlib.figure import Figure


HEADLESS_ENV: str = "SANSDIR_HEADLESS"
DEFAULT_INTERACTIVE_PRIORITY: tuple[str, ...] = ("QtAgg", "TkAgg", "GTK4Agg")


@dataclass(frozen=True, slots=True)
class BackendInfo:
    """Outcome of :func:`init_backend`."""

    name: str  # the matplotlib backend that was activated
    interactive: bool  # True if a display was found and an interactive backend works
    reason: str  # human-readable note for the status bar


_chosen: BackendInfo | None = None


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
# Initialisation
# ---------------------------------------------------------------------------


def init_backend(priority: tuple[str, ...] = DEFAULT_INTERACTIVE_PRIORITY) -> BackendInfo:
    """Pick (and remember) the matplotlib backend to use this session.

    Calling this more than once is cheap: the first call decides; later
    calls return the cached :class:`BackendInfo`.
    """
    global _chosen
    if _chosen is not None:
        return _chosen
    import matplotlib

    if not has_display():
        matplotlib.use("Agg", force=True)
        _chosen = BackendInfo(
            name="Agg",
            interactive=False,
            reason=(
                "headless: SANSDIR_HEADLESS set"
                if os.environ.get(HEADLESS_ENV)
                else "no $DISPLAY / $WAYLAND_DISPLAY"
            ),
        )
        return _chosen
    for candidate in priority:
        try:
            matplotlib.use(candidate, force=True)
            # Lazy-import pyplot here so a failed `use()` doesn't leave it
            # half-initialised on a broken backend.
            import matplotlib.pyplot as _plt  # noqa: F401
        except (ImportError, ValueError):
            continue
        _chosen = BackendInfo(name=candidate, interactive=True, reason=f"interactive ({candidate})")
        return _chosen
    # All candidates failed — fall back to Agg so plots still produce PNGs.
    matplotlib.use("Agg", force=True)
    _chosen = BackendInfo(
        name="Agg",
        interactive=False,
        reason=f"no interactive backend available; tried {list(priority)}",
    )
    return _chosen


def reset_backend_cache() -> None:
    """Clear the cached :class:`BackendInfo` (tests only)."""
    global _chosen
    _chosen = None


# ---------------------------------------------------------------------------
# Show / save
# ---------------------------------------------------------------------------


def show_or_save(fig: Figure, *, title: str = "plot") -> tuple[Path | None, BackendInfo]:
    """Display ``fig`` interactively, or save it to PNG in headless mode.

    Returns ``(png_path or None, BackendInfo)``. ``png_path`` is ``None``
    when an interactive window was opened.
    """
    info = init_backend()
    import matplotlib.pyplot as plt

    if info.interactive:
        # Non-blocking so the TUI keeps processing input. The user closes
        # the window themselves; ``plt.close("all")`` runs at app shutdown.
        plt.show(block=False)
        plt.pause(0.001)  # nudge the GUI loop to actually paint
        return None, info

    out_dir = plot_cache_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_title = "".join(c if c.isalnum() or c in "._-" else "_" for c in title) or "plot"
    stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    out_path = out_dir / f"{stamp}_{safe_title}.png"
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out_path, info


def close_all() -> None:
    """Best-effort ``plt.close('all')`` for app shutdown — tolerates absence."""
    import contextlib

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    with contextlib.suppress(Exception):
        plt.close("all")
