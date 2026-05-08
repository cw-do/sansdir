"""Interactive matplotlib mask editor (Phase 9.6.4).

Runs in its own matplotlib subprocess (the same pattern as the
plot-window helpers in :mod:`sansdir.plot.window`), so the TUI stays
responsive while the editor is up. The TUI launches us via
``python -m sansdir.mask.gui <source.nxs.h5> [--output …] [--format …]``;
the user draws shapes, presses **Save**, and the chosen writer
dumps the file plus its ``mask_log.json`` companion.

Architecture
------------

The state-bearing logic lives in :class:`MaskController`, which holds
the :class:`MaskBuilder` and a list of matplotlib patches mirroring
each added shape. The controller never imports any matplotlib-only
modules at the top, so unit tests can drive it with a ``MagicMock``
figure / axes — no ``$DISPLAY`` required.

The GUI bits — selectors, buttons, the figure layout — are wired in
:func:`run_editor`. Tests cover the controller; the rendered widget
graph is left to manual verification (per
``CLAUDE.md`` §11 "real plots, not text-art plots": we don't snapshot
GUI windows).

Out of scope (Phase 9.6 goal: cover the common 90 % of real-world
masking workflows; deeper edits land later):

* Resize handles for already-placed shapes (delete + redraw works).
* Boolean ops between shapes (the union covers the typical
  beam-stop-plus-corner-mask flow).
* Real-time mask preview during drag (final fill renders on commit).
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np

from sansdir.mask.api import Format, _resolve_output
from sansdir.mask.core import (
    Circle,
    Ellipse,
    MaskBuilder,
    Polygon,
    Rectangle,
    Shape,
)
from sansdir.mask.detector import load_detector_image
from sansdir.mask.writers import stats_for, write_log, write_nxs, write_xml

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.patches import Patch

    from sansdir.mask.detector import SourceMeta


# Modes the controller can be in. Drives which selector is armed and
# which patch class wraps the next user gesture.
Mode = Literal["rectangle", "ellipse", "circle", "polygon", "edit"]


# ---------------------------------------------------------------------------
# Controller — testable without matplotlib
# ---------------------------------------------------------------------------


class MaskController:
    """Mediates between the :class:`MaskBuilder` and the matplotlib axes.

    Each gesture (``add_rectangle``, ``add_ellipse``, …) appends a
    :class:`Shape` to the builder and a matching :class:`~matplotlib.patches.Patch`
    to the axes — wrapped in a parallel list so :meth:`undo` and
    :meth:`clear` can drop both sides in lockstep.

    The class only touches matplotlib through the ``ax`` argument, so
    a ``MagicMock`` axes is a valid argument for unit tests. The
    real GUI calls into this class from the selector callbacks in
    :func:`run_editor`.
    """

    def __init__(
        self,
        ax: Axes,
        builder: MaskBuilder,
        *,
        patch_face_color: str = "red",
        patch_edge_color: str = "white",
        patch_alpha: float = 0.35,
    ) -> None:
        self.ax = ax
        self.builder = builder
        self._patches: list[Patch] = []
        self._face = patch_face_color
        self._edge = patch_edge_color
        self._alpha = patch_alpha
        self.mode: Mode = "rectangle"

    # ------------------------------------------------------------------
    # Mode management
    # ------------------------------------------------------------------

    def set_mode(self, mode: Mode) -> None:
        if mode not in ("rectangle", "ellipse", "circle", "polygon", "edit"):
            raise ValueError(f"unknown mode: {mode!r}")
        self.mode = mode

    # ------------------------------------------------------------------
    # Shape additions — selectors call these from their on-release callbacks
    # ------------------------------------------------------------------

    def add_rectangle(self, x0: float, y0: float, x1: float, y1: float) -> Rectangle:
        from matplotlib.patches import Rectangle as MplRect

        shape = Rectangle(x0, y0, x1, y1)
        x_lo, x_hi = sorted((x0, x1))
        y_lo, y_hi = sorted((y0, y1))
        patch = MplRect(
            (x_lo, y_lo),
            x_hi - x_lo,
            y_hi - y_lo,
            facecolor=self._face,
            edgecolor=self._edge,
            alpha=self._alpha,
            linewidth=1.0,
            zorder=10,
        )
        return self._add(shape, patch)

    def add_ellipse(
        self, xc: float, yc: float, rx: float, ry: float
    ) -> Ellipse:
        from matplotlib.patches import Ellipse as MplEllipse

        shape = Ellipse(xc, yc, rx, ry)
        patch = MplEllipse(
            (xc, yc),
            width=2 * rx,
            height=2 * ry,
            facecolor=self._face,
            edgecolor=self._edge,
            alpha=self._alpha,
            linewidth=1.0,
            zorder=10,
        )
        return self._add(shape, patch)

    def add_circle(self, xc: float, yc: float, r: float) -> Circle:
        # A circle is just an ellipse with rx == ry; reuse the patch.
        from matplotlib.patches import Circle as MplCircle

        shape = Circle(xc, yc, r)
        patch = MplCircle(
            (xc, yc),
            radius=r,
            facecolor=self._face,
            edgecolor=self._edge,
            alpha=self._alpha,
            linewidth=1.0,
            zorder=10,
        )
        return self._add(shape, patch)

    def add_polygon(self, vertices: list[tuple[float, float]]) -> Polygon:
        from matplotlib.patches import Polygon as MplPoly

        if len(vertices) < 3:
            raise ValueError("polygon needs ≥ 3 vertices")
        shape = Polygon(tuple((float(x), float(y)) for x, y in vertices))
        patch = MplPoly(
            list(vertices),
            closed=True,
            facecolor=self._face,
            edgecolor=self._edge,
            alpha=self._alpha,
            linewidth=1.0,
            zorder=10,
        )
        return self._add(shape, patch)

    def _add(self, shape: Shape, patch: Patch) -> Shape:
        self.builder.add(shape)
        self.ax.add_patch(patch)
        self._patches.append(patch)
        return shape

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def undo(self) -> Shape | None:
        """Remove the most recently added shape; return it (or None)."""
        if not self.builder.shapes:
            return None
        return self.delete(len(self.builder.shapes) - 1)

    def clear(self) -> None:
        import contextlib

        for patch in self._patches:
            with contextlib.suppress(Exception):
                patch.remove()
        self._patches.clear()
        self.builder.clear()

    def delete(self, index: int) -> Shape | None:
        """Remove the shape at ``index`` from the builder and the axes."""
        import contextlib

        if not (0 <= index < len(self.builder.shapes)):
            return None
        shape = self.builder.shapes.pop(index)
        patch = self._patches.pop(index)
        with contextlib.suppress(Exception):
            patch.remove()
        return shape

    def index_of_patch(self, patch: Patch) -> int | None:
        """Return the index of ``patch`` in ``self._patches`` or ``None``."""
        for i, p in enumerate(self._patches):
            if p is patch:
                return i
        return None

    @property
    def patches(self) -> list[Patch]:
        """Read-only view of the overlay patches, indexed parallel to shapes."""
        return list(self._patches)

    def translate(self, index: int, dx: float, dy: float) -> Shape | None:
        """Translate the shape and patch at ``index`` by ``(dx, dy)``.

        Replaces the immutable :class:`Shape` instance with a new one
        carrying shifted coords, and nudges the matplotlib patch via
        its native API so the visual matches without a redraw.
        Returns the new shape (or ``None`` if ``index`` is invalid).
        """
        from matplotlib.patches import (
            Circle as MplCircle,
        )
        from matplotlib.patches import (
            Ellipse as MplEllipse,
        )
        from matplotlib.patches import (
            Polygon as MplPolygon,
        )
        from matplotlib.patches import (
            Rectangle as MplRectangle,
        )

        if not (0 <= index < len(self.builder.shapes)):
            return None
        shape = self.builder.shapes[index]
        patch = self._patches[index]
        if isinstance(shape, Rectangle):
            new_shape: Shape = Rectangle(
                shape.x0 + dx, shape.y0 + dy, shape.x1 + dx, shape.y1 + dy
            )
            if isinstance(patch, MplRectangle):
                patch.set_xy((patch.get_x() + dx, patch.get_y() + dy))
        elif isinstance(shape, Circle):
            new_shape = Circle(shape.xc + dx, shape.yc + dy, shape.r)
            if isinstance(patch, MplCircle):
                patch.center = (patch.center[0] + dx, patch.center[1] + dy)
        elif isinstance(shape, Ellipse):
            new_shape = Ellipse(
                shape.xc + dx, shape.yc + dy, shape.rx, shape.ry
            )
            if isinstance(patch, MplEllipse):
                patch.center = (patch.center[0] + dx, patch.center[1] + dy)
        elif isinstance(shape, Polygon):
            new_shape = Polygon(
                tuple((x + dx, y + dy) for x, y in shape.vertices)
            )
            if isinstance(patch, MplPolygon):
                xy = patch.get_xy()
                xy = xy + np.array([dx, dy])
                patch.set_xy(xy)
        else:  # pragma: no cover — exhaustive over current Shape subclasses
            return shape
        self.builder.shapes[index] = new_shape
        return new_shape

    def toggle_inverse(self) -> bool:
        self.builder.inverse = not self.builder.inverse
        return self.builder.inverse

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def save(
        self,
        meta: SourceMeta,
        output_path: Path,
        fmt: Format,
    ) -> tuple[Path, Path, dict]:  # type: ignore[type-arg]
        """Build + write the chosen format. Returns ``(out, log_path, stats)``."""
        mask = self.builder.build()
        if fmt == "xml":
            write_xml(output_path, mask, meta)
        elif fmt == "nxs":
            write_nxs(output_path, mask, meta)
        elif fmt == "npy":
            from sansdir.mask.writers import write_npy

            write_npy(output_path, mask, meta)
        else:
            raise ValueError(f"unknown format: {fmt!r}")
        stats = stats_for(mask)
        log = write_log(output_path, meta, self.builder, stats)
        return output_path, log, stats


# ---------------------------------------------------------------------------
# matplotlib runner
# ---------------------------------------------------------------------------


def run_editor(
    source_path: Path | str,
    output_path: Path | str | None = None,
    fmt: str = "nxs",
) -> int:
    """Open the editor, block until the user quits / saves.

    Returns ``0`` on a successful save, ``1`` on cancel/exit-without-save.
    The TUI subprocess pattern doesn't care which — we only spawn and
    forget — but the CLI exit code is informative for shell users.
    """
    import matplotlib

    # Lazy backend pick (interactive only — no headless fallback for
    # the editor; if there's no display, the TUI's K handler points
    # the user at the CLI form instead).
    if matplotlib.get_backend().lower() == "agg":
        matplotlib.use("QtAgg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm
    from matplotlib.widgets import (
        Button,
        EllipseSelector,
        RectangleSelector,
    )

    from sansdir.mask.banktube import (
        EQSANS_NPIXELS_PER_TUBE as _BANKTUBE_NPIX,
    )
    from sansdir.mask.banktube import (
        EQSANS_NTUBES as _BANKTUBE_NTUBES,
    )
    from sansdir.mask.banktube import (
        col_to_bank_tube,
        cols_to_runs,
        parse_spec,
    )

    src = Path(source_path)
    image, meta = load_detector_image(src)
    out_path = Path(_resolve_output(src, output_path, fmt))

    # Disable toolbar key bindings that collide with the mode shortcuts.
    plt.rcParams["keymap.home"] = []
    plt.rcParams["keymap.back"] = []
    plt.rcParams["keymap.forward"] = []
    plt.rcParams["keymap.pan"] = []
    plt.rcParams["keymap.zoom"] = []
    plt.rcParams["keymap.save"] = []
    plt.rcParams["keymap.fullscreen"] = []
    plt.rcParams["keymap.grid"] = []

    fig, ax = plt.subplots(figsize=(10, 8))
    # Reserve more bottom space — the new "Mask spec" row sits below
    # the button bar.
    fig.subplots_adjust(left=0.08, right=0.98, top=0.94, bottom=0.22)
    fig.canvas.manager.set_window_title(f"sansdir mask editor · {src.name}")

    log_data = np.where(image > 0, image, np.nan)
    vmin = max(float(np.nanmin(log_data)) if np.isfinite(log_data).any() else 1.0, 1.0)
    vmax = float(np.nanmax(log_data)) if np.isfinite(log_data).any() else 1.0
    if vmax <= vmin:
        vmax = vmin + 1.0
    ax.imshow(
        log_data,
        cmap="viridis",
        norm=LogNorm(vmin=vmin, vmax=vmax),
        origin="lower",
        # Cell aspect compensates for the EQSANS detector's physical
        # tube_pitch / pixel_pitch ratio (~5.2mm / ~3.9mm ≈ 1.33).
        # Tuned by eye on real EQSANS heatmaps — circles read as
        # circles at this setting. Drop closer to 1.0 for instruments
        # where the cells are nearer to square.
        aspect=1.0 / 1.3,
        extent=(0.5, image.shape[1] + 0.5, 0.5, image.shape[0] + 0.5),
    )
    # Add a generous margin around the detector so the user can drag
    # selectors from outside the heatmap (much easier than landing the
    # first click on column 0 / row 0). The MaskBuilder still clips
    # everything to ``detector_shape`` at rasterise time, so shapes
    # extending beyond the detector are silently truncated.
    margin_x = max(image.shape[1] * 0.05, 8)
    margin_y = max(image.shape[0] * 0.05, 8)
    ax.set_xlim(-margin_x, image.shape[1] + margin_x)
    ax.set_ylim(-margin_y, image.shape[0] + margin_y)
    # Visible detector boundary so users see where the mask actually applies.
    from matplotlib.patches import Rectangle as _BoundaryRect

    boundary = _BoundaryRect(
        (0.5, 0.5),
        image.shape[1],
        image.shape[0],
        fill=False,
        edgecolor="white",
        linewidth=0.5,
        linestyle=":",
        alpha=0.5,
        zorder=5,
    )
    ax.add_patch(boundary)
    ax.set_xlabel("Tube")
    ax.set_ylabel("Pixel")

    # ---- Cursor readout: tube/pixel/bank/tube_in_bank --------------
    # The matplotlib status bar gets a richer line than just "x=… y=…".
    # Only EQSANS-shaped detectors (192 cols x 256 px) get the bank
    # decoration; other shapes fall back to plain coords so this code
    # doesn't lie about non-EQSANS layouts.
    is_eqsans = (
        image.shape[1] == _BANKTUBE_NTUBES
        and image.shape[0] == _BANKTUBE_NPIX
    )

    def format_coord(x: float, y: float) -> str:
        col = int(np.floor(x + 0.5)) - 1  # extent shifts by 0.5
        row = int(np.floor(y + 0.5)) - 1
        if not (0 <= col < image.shape[1] and 0 <= row < image.shape[0]):
            return f"tube={x:.1f} pixel={y:.1f}"
        counts = float(image[row, col])
        base = f"tube={col} pixel={row} counts={counts:g}"
        if not is_eqsans:
            return base
        try:
            bank, tib = col_to_bank_tube(col)
        except ValueError:
            return base
        return f"{base}  ·  bank={bank} tube_in_bank={tib}"

    ax.format_coord = format_coord  # type: ignore[assignment]
    title = f"{src.name}  →  {out_path.name}"
    ax.set_title(title)

    builder = MaskBuilder(image.shape)
    controller = MaskController(ax, builder)

    # Selectors are held as references (else they drop) and toggled
    # by mode.
    selectors: dict[str, object] = {}
    status_text = ax.text(
        0.5,
        -0.12,
        "mode: rectangle  ·  shapes: 0",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=10,
    )

    def update_status() -> None:
        n = len(builder.shapes)
        inv = " · INVERSE" if builder.inverse else ""
        status_text.set_text(f"mode: {controller.mode}  ·  shapes: {n}{inv}")
        fig.canvas.draw_idle()

    # Map each user-facing mode to which underlying selector should
    # be active. Edit mode uses no selector. Circle and Polygon are
    # deliberately not in the GUI menu (cell aspect makes circles
    # mis-render under a rubber-band; polygons are rare in practice
    # and the bank/tube spec covers the strip-mask case better).
    # Both Shapes and the ``--circle`` / ``--polygon`` CLI flags are
    # kept; only the GUI affordance is gone.
    mode_to_selector_key: dict[str, str | None] = {
        "rectangle": "rectangle",
        "ellipse": "ellipse",
        "edit": None,
    }

    def _activate(mode: Mode) -> None:
        # Disable all selectors then enable the matching one. Selectors
        # need to be alive (held in ``selectors`` dict) for callbacks
        # to fire; we just toggle ``set_active``.
        #
        # Deduplicate by ``id``: circle/ellipse share the same selector
        # so a naive per-key loop would set it active then immediately
        # inactive (or vice versa).
        controller.set_mode(mode)
        target_key = mode_to_selector_key.get(mode)
        seen: set[int] = set()
        for k, sel in selectors.items():
            if id(sel) in seen:
                continue
            seen.add(id(sel))
            if hasattr(sel, "set_active"):
                sel.set_active(k == target_key)
        update_status()

    # ---- Selectors ---------------------------------------------------

    def on_rect_select(eclick, erelease) -> None:  # type: ignore[no-untyped-def]
        x0, y0 = eclick.xdata, eclick.ydata
        x1, y1 = erelease.xdata, erelease.ydata
        if None in (x0, y0, x1, y1):
            return
        controller.add_rectangle(x0, y0, x1, y1)
        update_status()

    def on_ellipse_select(eclick, erelease) -> None:  # type: ignore[no-untyped-def]
        x0, y0 = eclick.xdata, eclick.ydata
        x1, y1 = erelease.xdata, erelease.ydata
        if None in (x0, y0, x1, y1):
            return
        xc = (x0 + x1) / 2
        yc = (y0 + y1) / 2
        rx = abs(x1 - x0) / 2
        ry = abs(y1 - y0) / 2
        if rx <= 0 or ry <= 0:
            return
        controller.add_ellipse(xc, yc, rx, ry)
        update_status()

    selectors["rectangle"] = RectangleSelector(
        ax,
        on_rect_select,
        useblit=True,
        button=[1],
        minspanx=1,
        minspany=1,
        spancoords="data",
        interactive=False,
    )
    selectors["ellipse"] = EllipseSelector(
        ax,
        on_ellipse_select,
        useblit=True,
        button=[1],
        minspanx=1,
        minspany=1,
        spancoords="data",
        interactive=False,
    )

    _activate("rectangle")

    # ---- Buttons -----------------------------------------------------

    def make_button(label: str, x: float, w: float, callback) -> Button:  # type: ignore[no-untyped-def]
        ax_btn = fig.add_axes((x, 0.02, w, 0.05))
        btn = Button(ax_btn, label)
        btn.on_clicked(callback)
        return btn

    def cb_rect(_event) -> None:  # type: ignore[no-untyped-def]
        _activate("rectangle")

    def cb_ellipse(_event) -> None:  # type: ignore[no-untyped-def]
        _activate("ellipse")

    def cb_edit(_event) -> None:  # type: ignore[no-untyped-def]
        _activate("edit")

    def cb_undo(_event) -> None:  # type: ignore[no-untyped-def]
        controller.undo()
        update_status()

    def cb_clear(_event) -> None:  # type: ignore[no-untyped-def]
        controller.clear()
        update_status()

    def cb_invert(_event) -> None:  # type: ignore[no-untyped-def]
        controller.toggle_inverse()
        update_status()

    save_state: dict[str, object] = {"saved": False, "out": out_path, "fmt": fmt}

    def _ask_save_path(default: Path) -> Path | None:
        """Show a Save-As dialog and return the chosen path (or ``None``).

        Tk's ``asksaveasfilename`` is in stdlib and works alongside
        the QtAgg backend the editor runs on. We hide the Tk root so
        only the file dialog itself is visible. Returning ``None``
        means the user pressed Cancel.
        """
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            # tkinter missing on the cluster Python: fall back to the
            # legacy in-place save with whatever path was last set.
            return default
        root = tk.Tk()
        root.withdraw()
        try:
            chosen = filedialog.asksaveasfilename(
                parent=root,
                title="Save mask file",
                initialdir=str(default.parent),
                initialfile=default.name,
                defaultextension=".nxs",
                filetypes=[("NeXus mask", "*.nxs"), ("All files", "*.*")],
            )
        finally:
            root.destroy()
        if not chosen:
            return None
        return Path(chosen)

    def _do_save() -> None:
        # Always save as .nxs — the only format users actually want
        # from the GUI. The CLI still supports xml / npy.
        default = Path(save_state["out"]).with_suffix(".nxs")  # type: ignore[arg-type]
        chosen = _ask_save_path(default)
        if chosen is None:
            ax.set_title("save cancelled")
            fig.canvas.draw_idle()
            return
        try:
            controller.save(meta, chosen, "nxs")
        except Exception as exc:
            ax.set_title(f"save failed: {exc}")
            fig.canvas.draw_idle()
            return
        save_state["saved"] = True
        save_state["out"] = chosen
        ax.set_title(f"saved: {chosen}")
        fig.canvas.draw_idle()

    def cb_save(_event) -> None:  # type: ignore[no-untyped-def]
        _do_save()

    def cb_quit(_event) -> None:  # type: ignore[no-untyped-def]
        plt.close(fig)

    # Tight horizontal layout — 8 buttons fit across the figure with
    # no gaps. Circle and Polygon are intentionally absent (see
    # ``mode_to_selector_key``); Ellipse + the bank/tube spec input
    # cover the workflows users actually need.
    btn_rect = make_button("Rect (r)", 0.02, 0.10, cb_rect)
    btn_ell = make_button("Ellipse (e)", 0.13, 0.10, cb_ellipse)
    btn_edit = make_button("Edit (v)", 0.24, 0.10, cb_edit)
    btn_undo = make_button("Undo (z)", 0.35, 0.10, cb_undo)
    btn_clear = make_button("Clear", 0.46, 0.08, cb_clear)
    btn_invert = make_button("Invert (i)", 0.55, 0.10, cb_invert)
    btn_save = make_button("Save... (s)", 0.66, 0.13, cb_save)
    btn_quit = make_button("Quit (Esc)", 0.80, 0.10, cb_quit)

    # ---- Mask-by-bank/tube spec --------------------------------------
    # A button + Tk askstring dialog instead of an inline TextBox:
    # matplotlib's TextBox calls ``draw_idle()`` on every keystroke,
    # which on a 256x192 LogNorm imshow lands as visible per-character
    # lag. Tk's askstring runs in its own (fast) widget and fires a
    # single rebuild on submit. The status text below the button bar
    # shows the most recent spec's outcome.
    spec_status_ax = fig.add_axes((0.20, 0.09, 0.78, 0.04))
    spec_status_ax.axis("off")
    spec_status_text = spec_status_ax.text(
        0.0, 0.5,
        "Mask spec — click [Mask Spec... (k)] or press k  "
        "(e.g. b3, t50, b5-7 t10-15)",
        transform=spec_status_ax.transAxes,
        ha="left", va="center", fontsize=9, color="#888",
    )

    def _ask_mask_spec() -> str | None:
        """Open a Tk simpledialog for a bank/tube spec.

        Returns the entered string (possibly empty), or ``None`` if
        the user cancelled or Tk isn't available on this Python.
        """
        try:
            import tkinter as tk
            from tkinter import simpledialog
        except ImportError:
            return None
        root = tk.Tk()
        root.withdraw()
        try:
            return simpledialog.askstring(
                title="Mask spec",
                prompt="Bank / tube spec\n(e.g. b3, t50, b5-7 t10-15):",
                parent=root,
            )
        finally:
            root.destroy()

    def _apply_mask_spec(text: str) -> None:
        text = text.strip()
        if not text:
            return
        try:
            cols = parse_spec(text)
        except ValueError as exc:
            spec_status_text.set_text(f"spec err: {exc}")
            spec_status_text.set_color("#c00")
            fig.canvas.draw_idle()
            return
        if not cols:
            spec_status_text.set_text(f"(no columns matched in {text!r})")
            spec_status_text.set_color("#888")
            fig.canvas.draw_idle()
            return
        # Drop columns that lie outside the loaded detector — a
        # synthetic test fixture might have a smaller shape than the
        # real EQSANS layout.
        cols = [c for c in cols if 0 <= c < image.shape[1]]
        n_added = 0
        for lo, hi in cols_to_runs(cols):
            controller.add_rectangle(lo, 0, hi, image.shape[0] - 1)
            # The default ``add_rectangle`` patch uses width = hi-lo,
            # which is **zero** for a single-tube spec like ``t130``
            # (and is half a cell off otherwise — imshow's extent
            # shifts cells by 0.5). Override the just-added patch
            # with cell-aligned geometry so the masked tube reads as
            # a solid coloured strip on the heatmap. The Shape itself
            # is unchanged, so the rasterised mask is identical.
            patch = controller.patches[-1]
            patch.set_xy((lo + 0.5, 0.5))
            patch.set_width(hi - lo + 1)
            patch.set_height(image.shape[0])
            n_added += 1
        spec_status_text.set_text(
            f"+{n_added} rect{'s' if n_added != 1 else ''}, "
            f"{len(cols)} cols  ({text!r})"
        )
        spec_status_text.set_color("#080")
        update_status()

    def cb_mask_spec(_event) -> None:  # type: ignore[no-untyped-def]
        text = _ask_mask_spec()
        if text is None:  # cancelled or Tk unavailable
            return
        _apply_mask_spec(text)

    btn_spec_ax = fig.add_axes((0.02, 0.09, 0.16, 0.04))
    btn_spec = Button(btn_spec_ax, "Mask Spec... (k)")
    btn_spec.on_clicked(cb_mask_spec)

    # Hold refs so GC doesn't collect the widgets.
    fig._sansdir_buttons = [  # type: ignore[attr-defined]
        btn_rect, btn_ell, btn_edit, btn_undo,
        btn_clear, btn_invert, btn_save, btn_quit,
        btn_spec,
    ]

    # ---- Keyboard shortcuts -----------------------------------------

    # ---- Edit mode: select / move / delete existing shapes -----------
    #
    # When ``mode == "edit"`` the drawing selectors are inactive; mouse
    # clicks instead grab whichever overlay patch sits under the
    # cursor. A selected patch is highlighted with a thicker yellow
    # edge. Drag = translate (the underlying Shape is rebuilt with
    # shifted coords on each motion event so the saved mask matches
    # what's on screen). ``Delete`` removes the selected shape.
    edit_state: dict[str, object] = {
        "selected_index": None,
        "drag_origin": None,    # (x, y) where the drag started
        "saved_edge": None,     # original edgecolor / lw to restore
        "saved_lw": None,
        "drag_bg": None,        # cached static background for blit-fast drags
    }

    def _highlight(idx: int | None) -> None:
        """Switch which patch shows the selected-edge styling."""
        prev = edit_state.get("selected_index")
        if prev is not None and prev != idx:
            patches = controller.patches
            if 0 <= prev < len(patches):
                patches[prev].set_edgecolor(edit_state.get("saved_edge"))
                patches[prev].set_linewidth(edit_state.get("saved_lw") or 1.0)
        if idx is not None:
            patches = controller.patches
            if 0 <= idx < len(patches):
                p = patches[idx]
                edit_state["saved_edge"] = p.get_edgecolor()
                edit_state["saved_lw"] = p.get_linewidth()
                p.set_edgecolor("yellow")
                p.set_linewidth(2.0)
        edit_state["selected_index"] = idx
        fig.canvas.draw_idle()

    def on_mouse_press(event) -> None:  # type: ignore[no-untyped-def]
        if controller.mode != "edit":
            return
        if event.inaxes is not ax or event.xdata is None or event.ydata is None:
            return
        # Find the topmost patch under the cursor (last in z-order).
        hit_idx: int | None = None
        for i in range(len(controller.patches) - 1, -1, -1):
            patch = controller.patches[i]
            contains, _ = patch.contains(event)
            if contains:
                hit_idx = i
                break
        _highlight(hit_idx)
        if hit_idx is not None:
            edit_state["drag_origin"] = (event.xdata, event.ydata)
            # Set up blit-fast drags: mark the moving patch
            # ``animated`` so it's excluded from the canvas's full
            # render, do one synchronous draw to flush the rest, then
            # snapshot the canvas. Each subsequent motion event
            # restores that snapshot and re-renders only the moving
            # patch — orders of magnitude cheaper than ``draw_idle()``
            # on a 256x192 LogNorm imshow.
            try:
                moving = controller.patches[hit_idx]
                moving.set_animated(True)
                fig.canvas.draw()
                edit_state["drag_bg"] = fig.canvas.copy_from_bbox(ax.bbox)
            except Exception:
                # Some non-Agg backends don't support copy_from_bbox;
                # fall back to the slow draw_idle() path silently.
                edit_state["drag_bg"] = None
        else:
            edit_state["drag_origin"] = None

    def on_mouse_motion(event) -> None:  # type: ignore[no-untyped-def]
        if controller.mode != "edit":
            return
        origin = edit_state.get("drag_origin")
        idx = edit_state.get("selected_index")
        if origin is None or idx is None:
            return
        if event.inaxes is not ax or event.xdata is None or event.ydata is None:
            return
        ox, oy = origin  # type: ignore[misc]
        dx = event.xdata - ox
        dy = event.ydata - oy
        if dx == 0 and dy == 0:
            return
        controller.translate(idx, dx, dy)  # type: ignore[arg-type]
        edit_state["drag_origin"] = (event.xdata, event.ydata)
        bg = edit_state.get("drag_bg")
        if bg is not None:
            fig.canvas.restore_region(bg)  # type: ignore[arg-type]
            ax.draw_artist(controller.patches[idx])  # type: ignore[arg-type]
            fig.canvas.blit(ax.bbox)
        else:
            fig.canvas.draw_idle()

    def on_mouse_release(_event) -> None:  # type: ignore[no-untyped-def]
        idx = edit_state.get("selected_index")
        if idx is not None and edit_state.get("drag_bg") is not None:
            with contextlib.suppress(Exception):
                controller.patches[idx].set_animated(False)  # type: ignore[arg-type]
            # One final full redraw to fold the patch back into the
            # normal layer (otherwise the next zoom / resize could
            # render without it).
            fig.canvas.draw_idle()
        edit_state["drag_origin"] = None
        edit_state["drag_bg"] = None

    fig.canvas.mpl_connect("button_press_event", on_mouse_press)
    fig.canvas.mpl_connect("motion_notify_event", on_mouse_motion)
    fig.canvas.mpl_connect("button_release_event", on_mouse_release)

    def on_key(event) -> None:  # type: ignore[no-untyped-def]
        k = (event.key or "").lower()
        if k == "r":
            _activate("rectangle")
            _highlight(None)
        elif k == "e":
            _activate("ellipse")
            _highlight(None)
        elif k == "v":
            _activate("edit")
        elif k == "z":
            # Plain undo — drop the most recently added shape.
            controller.undo()
            _highlight(None)
            update_status()
        elif k == "delete":
            # In edit mode, delete the *selected* shape; otherwise
            # fall back to undo so the keystroke is never a no-op.
            sel = edit_state.get("selected_index")
            if controller.mode == "edit" and sel is not None:
                controller.delete(int(sel))  # type: ignore[arg-type]
                edit_state["selected_index"] = None
            else:
                controller.undo()
            update_status()
        elif k == "i":
            controller.toggle_inverse()
            update_status()
        elif k == "s":
            _do_save()
        elif k == "k":
            text = _ask_mask_spec()
            if text is not None:
                _apply_mask_spec(text)
        elif k == "escape":
            plt.close(fig)

    fig.canvas.mpl_connect("key_press_event", on_key)

    plt.show()
    return 0 if save_state["saved"] else 1


# ---------------------------------------------------------------------------
# CLI entry point — `python -m sansdir.mask.gui ...`
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sansdir.mask.gui",
        description="Interactive matplotlib detector mask editor.",
    )
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Output file (default: <source-stem>_mask.<ext> next to source)",
    )
    parser.add_argument(
        "--format", "-f", choices=("xml", "nxs", "npy"), default="nxs",
        help="Default save format used by the keyboard shortcut and the "
             "Save button (Save .xml / .nxs explicitly override).",
    )
    args = parser.parse_args(argv)
    return run_editor(args.source, args.output, args.format)


if __name__ == "__main__":
    sys.exit(main())
