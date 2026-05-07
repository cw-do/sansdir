"""Image viewer — pop a static image into a matplotlib window.

Used by the ``Enter``-on-image flow: the file panel's smart-Enter
handler routes ``*.png`` / ``*.jpg`` / ``*.svg`` etc. here so the
image opens in its own GUI window (interactive matplotlib backend,
same subprocess pattern as the data plotters).

Why matplotlib over ``xdg-open`` / ``display``: the analysis cluster
runs through SSH where ``xdg-open`` doesn't reliably reach a viewer,
and ImageMagick's ``display`` is often missing. matplotlib is
already a hard dependency, the backend probe in
:mod:`sansdir.plot.backend` already gracefully degrades to a PNG
copy when there's no display, and using it keeps every "open this in
a window" flow identical (close-on-q, headless fallback, etc.).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from sansdir.plot.backend import (
    BackendInfo,
    has_display,
    save_figure_to_png,
    spawn_plot_window,
)

if TYPE_CHECKING:
    from matplotlib.figure import Figure

# Extensions matplotlib's ``imread`` can handle out of the box. PDF /
# SVG aren't here because matplotlib won't read them as raster; for
# vector formats we'd want an external viewer.
IMAGE_EXTS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff"}
)


def is_image(path: Path) -> bool:
    """True iff ``path``'s extension is in :data:`IMAGE_EXTS` (case-insensitive)."""
    return path.suffix.lower() in IMAGE_EXTS


def make_image_figure(path: Path) -> Figure:
    """Return a matplotlib figure displaying ``path`` via ``imshow``."""
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt

    img = mpimg.imread(path)
    fig, ax = plt.subplots(layout="constrained")
    ax.imshow(img)
    ax.set_axis_off()
    ax.set_title(Path(path).name, fontsize=10)
    return fig


def plot_image(
    paths: Iterable[Path],
) -> tuple[Path | None, BackendInfo]:
    """Open ``paths`` in matplotlib windows. Returns the first PNG path
    (when headless) for symmetry with the other plotters."""
    path_list = [Path(p) for p in paths]
    if not path_list:
        raise ValueError("plot_image: at least one file required")
    if has_display():
        # One subprocess per image so each closes independently. We
        # reuse the existing plot-window CLI's ``image`` kind.
        info = BackendInfo(name="subprocess", interactive=True, reason="display present")
        for p in path_list:
            info = spawn_plot_window("image", [p])
        return None, info
    fig = make_image_figure(path_list[0])
    return save_figure_to_png(fig, title=f"{path_list[0].stem}_image")
