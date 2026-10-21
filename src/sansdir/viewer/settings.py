"""Viewer preferences kept between sessions: ``~/.config/sansdir/viewer.json`` (Qt-free).

Deliberately not ``QSettings``: its ini backend takes a ``QLockFile`` on
every sync, and on the NFS home directories of the analysis cluster that
lock got stuck while a colour-bar handle was being dragged (one sync per
mouse move), freezing the window (2026-10-21). Here a save is one small
file written next to the target and renamed over it — atomic, no lock —
and a failed write is logged, never raised. The window also only saves
once the changes settle, not per event.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from sansdir.viewer.colorscale import COLORMAPS, ScaleState

logger = logging.getLogger(__name__)

SETTINGS_NAME = "viewer.json"


def default_path() -> Path:
    """``$XDG_CONFIG_HOME/sansdir/viewer.json``, else ``~/.config/sansdir/viewer.json``."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "sansdir" / SETTINGS_NAME


def load_scale(path: Path) -> ScaleState:
    """The remembered colour scale; defaults for anything missing, unreadable or bad."""
    state = ScaleState()
    try:
        data = json.loads(path.read_text(encoding="utf-8")).get("scale", {})
    except (OSError, ValueError, AttributeError):
        return state
    if not isinstance(data, dict):
        return state
    if isinstance(data.get("log"), bool):
        state.log = data["log"]
    if isinstance(data.get("locked"), bool):
        state.locked = data["locked"]
    if data.get("cmap") in COLORMAPS:
        state.cmap = data["cmap"]
    try:
        lo, hi = data.get("percentiles", state.percentiles)
        state.set_percentiles(float(lo), float(hi))
        state.set_limits(float(data.get("vmin", state.vmin)), float(data.get("vmax", state.vmax)))
    except (TypeError, ValueError):
        pass
    return state


def save_scale(path: Path, state: ScaleState) -> bool:
    """Write the colour scale atomically. Returns False (and logs) if it could not."""
    payload: dict[str, Any] = {
        "scale": {
            "log": state.log,
            "locked": state.locked,
            "cmap": state.cmap,
            "percentiles": list(state.percentiles),
            "vmin": state.vmin,
            "vmax": state.vmax,
        }
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    except OSError as exc:
        logger.warning("could not save viewer settings to %s: %s", path, exc)
        return False
    return True


__all__ = ["SETTINGS_NAME", "default_path", "load_scale", "save_scale"]
