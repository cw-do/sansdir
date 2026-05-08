"""Top-level mask-creation API used by the CLI and the registry command.

Single function — :func:`create_mask` — takes the source NeXus file,
a list of shapes (typically parsed from CLI flags or a
``--shapes-json`` file), the output destination, and a format string.
Writes the chosen format plus the ``mask_log.json`` companion. No
matplotlib involvement; the GUI lives in :mod:`sansdir.mask.gui`.

The shape-string parser lives here too (``--rect 10,10,20,20`` etc.)
so it can be reused by both the CLI and any future programmatic
caller.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sansdir.mask.core import (
    Circle,
    Ellipse,
    MaskBuilder,
    Polygon,
    Rectangle,
    Shape,
    shape_from_dict,
)
from sansdir.mask.detector import SourceMeta, load_detector_image
from sansdir.mask.writers import (
    log_path_for,
    stats_for,
    write_log,
    write_npy,
    write_nxs,
    write_xml,
)

Format = Literal["xml", "nxs", "npy"]
_FMT_TO_SUFFIX: dict[str, str] = {"xml": ".xml", "nxs": ".nxs", "npy": ".npy"}


@dataclass(frozen=True, slots=True)
class MaskResult:
    """What :func:`create_mask` returns to the caller."""

    output_path: Path
    log_path: Path
    n_masked: int
    n_total: int


def create_mask(
    source: Path | str,
    shapes: Sequence[Shape],
    output: Path | str | None = None,
    *,
    fmt: Format | str = "nxs",
    inverse: bool = False,
) -> MaskResult:
    """Build a mask from ``shapes`` against ``source`` and write it out.

    ``output`` defaults to ``<source-stem>_mask.<ext>`` next to
    ``source`` so the user gets something predictable when they
    forget to pass ``--output``.
    """
    if fmt not in _FMT_TO_SUFFIX:
        raise ValueError(f"unknown format: {fmt!r} (pick xml/nxs/npy)")
    src = Path(source)
    _image, meta = load_detector_image(src)
    builder = MaskBuilder(meta.detector_shape, inverse=inverse)
    for s in shapes:
        builder.add(s)
    mask = builder.build()
    out = _resolve_output(src, output, fmt)
    if fmt == "xml":
        write_xml(out, mask, meta)
    elif fmt == "nxs":
        write_nxs(out, mask, meta)
    else:  # npy
        write_npy(out, mask, meta)
    log = write_log(out, meta, builder, stats_for(mask))
    return MaskResult(
        output_path=out,
        log_path=log,
        n_masked=int(mask.sum()),
        n_total=int(mask.size),
    )


def _resolve_output(source: Path, output: Path | str | None, fmt: str) -> Path:
    if output is not None:
        return Path(output)
    return source.with_name(f"{source.stem}_mask{_FMT_TO_SUFFIX[fmt]}")


# ---------------------------------------------------------------------------
# CLI / TUI shape-string parsing
# ---------------------------------------------------------------------------


def parse_rect(spec: str) -> Rectangle:
    """``"x0,y0,x1,y1"`` → :class:`Rectangle`."""
    x0, y0, x1, y1 = _parse_floats(spec, 4, "--rect")
    return Rectangle(x0, y0, x1, y1)


def parse_ellipse(spec: str) -> Ellipse:
    """``"xc,yc,rx,ry"`` → :class:`Ellipse`."""
    xc, yc, rx, ry = _parse_floats(spec, 4, "--ellipse")
    return Ellipse(xc, yc, rx, ry)


def parse_circle(spec: str) -> Circle:
    """``"xc,yc,r"`` → :class:`Circle`."""
    xc, yc, r = _parse_floats(spec, 3, "--circle")
    return Circle(xc, yc, r)


def parse_polygon(spec: str) -> Polygon:
    """``"x1,y1,x2,y2,..."`` (≥3 vertices) → :class:`Polygon`."""
    flat = _parse_floats(spec, None, "--polygon")
    if len(flat) % 2 != 0:
        raise ValueError("--polygon: need an even count of coordinates")
    if len(flat) // 2 < 3:
        raise ValueError("--polygon: need at least 3 vertices")
    pairs = tuple((flat[i], flat[i + 1]) for i in range(0, len(flat), 2))
    return Polygon(pairs)


def shapes_from_json(path: Path | str) -> tuple[list[Shape], bool]:
    """Read a ``mask_log.json`` (or compatible) and return ``(shapes, inverse)``."""
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    shapes = [shape_from_dict(d) for d in data.get("shapes", [])]
    return shapes, bool(data.get("inverse", False))


def _parse_floats(spec: str, n: int | None, label: str) -> list[float]:
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    try:
        nums = [float(p) for p in parts]
    except ValueError as exc:
        raise ValueError(f"{label}: not a comma-separated number list") from exc
    if n is not None and len(nums) != n:
        raise ValueError(f"{label}: expected {n} numbers, got {len(nums)}")
    return nums


__all__ = [
    "MaskResult",
    "create_mask",
    "log_path_for",
    "parse_circle",
    "parse_ellipse",
    "parse_polygon",
    "parse_rect",
    "shapes_from_json",
]


# Reassure the type-checker: SourceMeta is the documented return type
# of load_detector_image; bring it into the public namespace for
# downstream callers (CLI / tests) that import via this module.
__all__.append("SourceMeta")
SourceMeta  # noqa: B018 — re-export
