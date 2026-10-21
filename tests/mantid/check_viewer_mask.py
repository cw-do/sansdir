"""Manual check: do masks saved by the detector viewer mask the right detectors in drtsans?

Not collected by pytest (needs Mantid). Run it from the repo with the venv python::

    .venv/bin/python tests/mantid/check_viewer_mask.py [RAW_RUN.nxs.h5]

It builds a mask with every kind of viewer edit (shapes, brush, eraser hole,
tube toggle), saves it as ``.xml`` and ``.nxs`` exactly as the viewer does
(``viewer.masking.save_mask``; ``.nxs`` through Mantid), then re-runs itself
under ``drtsans --classic`` to apply each file with drtsans's own
``mask_utils.apply_mask`` to the loaded run, and compares the masked
detector IDs with the intended ones. Prints ``OK`` / ``MISMATCH`` per file.

Last run (2026-10-21, Mantid 6.16.1.2): both exact (2646 / 2646), and the
production ``IPTS-38269/shared/mask_4m.nxs`` exact too (7504 / 7504).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_RAW = REPO / "tests" / "data" / "EQSANS_172749.nxs.h5"


def prepare(workdir: Path, raw: Path) -> None:
    """Viewer side (sansdir venv): build the mask, save .xml + .nxs, record the IDs."""
    import numpy as np

    from sansdir.mask.core import Circle, Polygon, Rectangle
    from sansdir.viewer.geometry import detector_ids
    from sansdir.viewer.masking import MaskState, save_mask

    state = MaskState()
    state.add_shape(Circle(91, 132, 7))
    state.add_shape(Polygon(((140, 200), (180, 240), (170, 170))))
    state.add_shape(Rectangle(-0.5, -0.5, 191.5, 4.5))
    brush = np.zeros((256, 192), dtype=bool)
    brush[100:104, 20:60] = True
    state.paint(brush, masked=True)
    hole = np.zeros((256, 192), dtype=bool)
    hole[0:5, 90:95] = True
    state.paint(hole, masked=False)
    state.toggle_columns([146])
    expected = sorted(int(i) for i in detector_ids()[state.build()])
    os.environ.pop("SANSDIR_NO_MANTID", None)  # the real (Mantid) .nxs writer
    for suffix in (".xml", ".nxs"):
        save_mask(state, raw, "", workdir / f"viewer_mask{suffix}")
    (workdir / "expected.json").write_text(json.dumps(expected))


def check(workdir: Path, raw: Path) -> int:
    """Mantid side (under ``drtsans --classic``): apply each file the drtsans way."""
    from drtsans.mask_utils import apply_mask
    from mantid.simpleapi import LoadEventNexus, mtd

    expected = set(json.loads((workdir / "expected.json").read_text()))
    failures = 0
    for suffix in (".xml", ".nxs"):
        LoadEventNexus(Filename=str(raw), OutputWorkspace="run")
        apply_mask("run", mask=str(workdir / f"viewer_mask{suffix}"))
        ws = mtd["run"]
        info = ws.spectrumInfo()
        got = {
            ws.getDetector(i).getID()
            for i in range(ws.getNumberHistograms())
            if info.hasDetectors(i) and info.isMasked(i)
        }
        extra, missing = got - expected, expected - got
        ok = not extra and not missing
        failures += not ok
        print(
            f"{suffix}: {len(got)} masked, intended {len(expected)}, "
            f"extra {len(extra)}, missing {len(missing)} -> {'OK' if ok else 'MISMATCH'}"
        )
    return 1 if failures else 0


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--mantid":
        return check(Path(sys.argv[2]), Path(sys.argv[3]))
    raw = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RAW
    with tempfile.TemporaryDirectory(prefix="sansdir-mask-check-") as tmp:
        prepare(Path(tmp), raw)
        cmd = ["drtsans", "--classic", __file__, "--mantid", tmp, str(raw)]
        return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
