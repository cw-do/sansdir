"""Standalone Mantid-side renderer.

This script is **executed in the Mantid python environment** by
:func:`sansdir.plot.hdf5_detector.load_via_mantid`. We subprocess
into Mantid because Mantid carries the EQSANS IDF (instrument
definition file) and therefore knows the correct
spectrum → detector mapping for every file format the reduction
pipeline emits — far cheaper than re-implementing that mapping in
sansdir for every flavour of processed output.

CLI::

    /path/to/mantid/python -m sansdir.plot._mantid_render \\
        <input.nxs> <output.npz>

Output is a numpy ``.npz`` archive with three arrays:

* ``image``   — ``(256, 192)`` float, ready for ``imshow`` with
  ``extent=(0.5, 192.5, 0.5, 256.5)`` and ``origin='lower'``.
* ``title``   — 0-d string array.
* ``source``  — 0-d string array, always ``"mantid"``.

The script is intentionally side-effect-free outside the output
path: it imports Mantid lazily, never writes to ``/tmp`` other than
the requested output, and exits non-zero with a Mantid traceback on
failure so the calling sansdir process can log it.
"""

from __future__ import annotations

import sys
from pathlib import Path

EQSANS_NTUBES: int = 192
EQSANS_NPIXELS_PER_TUBE: int = 256


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: mantid_render <input.nxs> <output.npz>", file=sys.stderr)
        return 2
    input_path = Path(args[0])
    output_path = Path(args[1])

    # Quiet Mantid's startup banner — we want a minimal stdout for
    # parsing in the parent.
    import os

    os.environ.setdefault("MANTID_NOTIFICATIONS_MUTED", "1")

    import numpy as np
    from mantid.simpleapi import LoadNexus

    ws = LoadNexus(Filename=str(input_path), OutputWorkspace="sansdir_mantid_load")

    # Per-spectrum total counts.
    y = ws.extractY()  # shape (n_spectra, n_bins)
    counts = y.sum(axis=1)

    # Per-spectrum 3-D detector position. EQSANS' banjo is curved in
    # z, so the *arc length* along z is the natural horizontal axis.
    # Mantid's positions are in metres in the instrument frame; we
    # don't care about the absolute scale — only the relative ordering
    # — so we just take the y, z components and build histogram bins.
    n = ws.getNumberHistograms()
    pos = np.zeros((n, 3), dtype=float)
    info = ws.detectorInfo()
    for i in range(n):
        # Use the spectrum's first detector index. SANS workspaces have
        # one detector per spectrum, so this is the canonical position.
        det_id = ws.getSpectrum(i).getDetectorIDs()[0]
        idx = info.indexOf(det_id)
        p = info.position(idx)
        pos[i] = (p.X(), p.Y(), p.Z())

    # Pick the two axes with the largest in-plane extent: that's the
    # detector face. EQSANS is curved in z (banjo) and flat in y.
    spans = pos.max(axis=0) - pos.min(axis=0)
    h_ax = int(np.argmax(spans))      # widest direction = "tube"
    v_ax = int(np.argsort(spans)[-2]) # second-widest = "pixel"
    if h_ax == v_ax:                   # fallback if positions degenerate
        h_ax, v_ax = 2, 1
    h_vals = pos[:, h_ax]
    v_vals = pos[:, v_ax]

    # EQSANS tubes are physically staggered front/back within each
    # bank. Two adjacent *electronic* tubes have slightly different
    # depth (the third axis), but in the unrolled logical detector
    # image they sit side-by-side. Sorting unique horizontal positions
    # and binning each detector into the *closest* logical tube
    # column collapses the front/back stagger into a clean 192-wide
    # grid — without this the histogram2d output shows alternating
    # empty / filled vertical stripes across the staggered region.
    pixel_edges = np.linspace(v_vals.min(), v_vals.max(), EQSANS_NPIXELS_PER_TUBE + 1)
    pixel_idx = np.clip(
        np.searchsorted(pixel_edges, v_vals, side="right") - 1,
        0,
        EQSANS_NPIXELS_PER_TUBE - 1,
    )
    sorted_h = np.argsort(h_vals)  # unroll the staggered tube positions
    tube_idx = np.empty(n, dtype=np.int64)
    tube_idx[sorted_h] = np.arange(n) * EQSANS_NTUBES // n
    image = np.zeros((EQSANS_NPIXELS_PER_TUBE, EQSANS_NTUBES), dtype=float)
    np.add.at(image, (pixel_idx, tube_idx), counts)

    title = ws.getTitle() or input_path.stem
    np.savez(output_path, image=image.astype(float), title=str(title), source="mantid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
