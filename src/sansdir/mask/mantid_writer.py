"""Mantid-backed mask writer — produces drtsans-compatible NeXus output.

Why this module exists
----------------------

The pure-numpy writer in :mod:`sansdir.mask.writers` produces a file
that *looks* like a Mantid event workspace at the group-structure
level (``mantid_workspace_1/event_workspace/...``) and round-trips
through sansdir's own plot loader (``p`` keystroke). But the file
is missing ``instrument/instrument_parameter_map`` — the Mantid
serialised parameter map where per-detector ``isMasked()`` flags
live — so when drtsans's reduction loads it and calls
``MaskDetectors(Workspace=run, MaskedWorkspace=loaded_mask)``,
no detectors are flagged and the mask silently has no effect.

This module bridges that gap by spawning Mantid (via the cluster's
``drtsans --classic`` pixi wrapper) as a subprocess just for the
write step. The flow is:

    1. sansdir computes the masked detector-IDs (pure numpy).
    2. We write a tiny JSON config + a stand-alone Mantid driver
       script to two tempfiles.
    3. ``drtsans --classic <driver> <config>`` runs
       ``Load → MaskDetectors → SaveNexus`` against the original
       source NeXus.
    4. The resulting file is the same shape Mantid produces from a
       hand-masked workspace — ``instrument_parameter_map`` carries
       7000+ ``detID:N;bool;masked;1`` entries that drtsans then
       consumes correctly.

The rest of the sansdir package stays free of Mantid imports —
this is a subprocess call, not a Python import.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from sansdir.mask.detector import SourceMeta
from sansdir.mask.writers import _masked_detector_ids

logger = logging.getLogger(__name__)


class MantidUnavailableError(RuntimeError):
    """``drtsans`` (or the configured Mantid wrapper) isn't on PATH."""


class MantidWriterError(RuntimeError):
    """``drtsans`` was found but the write subprocess failed."""


# The stand-alone Mantid driver. Runs under ``drtsans --classic``,
# reads its config from argv[1], and does the bare minimum needed
# to emit a drtsans-compatible mask file. Kept as a string template
# (not a packaged .py file) so we can write it to a tempfile and
# clean up afterwards — also keeps the import graph clean: nothing
# in the sansdir tree ever imports ``mantid``.
_MANTID_DRIVER_SCRIPT = '''\
"""sansdir mask writer — runs under Mantid via ``drtsans --classic``.

Not meant to be human-edited. argv[1] is a JSON config emitted by
:mod:`sansdir.mask.mantid_writer`.
"""
import json
import sys

with open(sys.argv[1]) as f:
    cfg = json.load(f)

from mantid.simpleapi import Load, MaskDetectors, SaveNexus

ws = Load(Filename=cfg["source"], OutputWorkspace="sansdir_mask_src")
if cfg["detector_ids"]:
    MaskDetectors(Workspace=ws, DetectorList=cfg["detector_ids"])
SaveNexus(InputWorkspace=ws, Filename=cfg["output"])
print(
    f"sansdir-mantid: masked {len(cfg['detector_ids'])} detector(s) "
    f"-> {cfg['output']}",
    flush=True,
)
'''


def is_drtsans_available(executable: str = "drtsans") -> bool:
    """Return True if the named Mantid wrapper is on ``$PATH``.

    The cluster's wrapper is a pixi-env launcher at ``/bin/drtsans``
    that runs python inside the ``sans`` env with Mantid 6.15+
    available. Locally, users can install their own wrapper script
    under the same name (or override via the
    ``write_nxs_via_mantid(executable=...)`` kwarg).
    """
    return shutil.which(executable) is not None


def write_nxs_via_mantid(
    output_path: Path | str,
    mask: np.ndarray,
    source_meta: SourceMeta,
    *,
    executable: str = "drtsans",
    timeout: float = 300.0,
) -> Path:
    """Write a drtsans-compatible Mantid NeXus mask file.

    Args:
        output_path: where to write the .nxs.
        mask: ``(n_rows, n_cols)`` uint8 array (1 = masked).
        source_meta: ties the mask back to the source NeXus Mantid
            will Load. ``source_meta.source_path`` must exist and be
            something Mantid's ``Load`` algorithm understands (raw
            event-mode .nxs.h5 or Mantid-processed .nxs both work).
        executable: name of the Mantid wrapper on PATH. Default
            ``drtsans`` (the cluster's pixi launcher).
        timeout: subprocess wall-clock budget in seconds. The
            Load + SaveNexus pair runs ~5-15 s on a typical
            ~50 MB EQSANS file, so the 300 s default has comfortable
            headroom even on slow GPFS days.

    Returns:
        ``Path(output_path).resolve()`` on success.

    Raises:
        MantidUnavailableError: ``executable`` isn't on PATH —
            caller should fall back to the legacy pure-numpy writer.
        MantidWriterError: subprocess exited non-zero or finished
            without producing the output file; the message carries
            the tail of stderr / stdout for diagnosis.
    """
    if not is_drtsans_available(executable):
        raise MantidUnavailableError(
            f"{executable!r} not on PATH — install Mantid or fall back "
            f"to the legacy sansdir writer"
        )
    out = Path(output_path).resolve()
    det_ids = _masked_detector_ids(mask, source_meta).tolist()

    # Both files clean up in the finally block regardless of outcome
    # — useful because Mantid stderr can be useful diagnostic if the
    # subprocess crashed in the script body.
    cfg_fd, cfg_path = tempfile.mkstemp(suffix=".json", prefix="sansdir-mask-cfg-")
    drv_fd, drv_path = tempfile.mkstemp(suffix=".py", prefix="sansdir-mask-driver-")
    try:
        with open(cfg_fd, "w") as f:
            json.dump(
                {
                    "source": str(source_meta.source_path),
                    "detector_ids": det_ids,
                    "output": str(out),
                },
                f,
            )
        with open(drv_fd, "w") as f:
            f.write(_MANTID_DRIVER_SCRIPT)
        cmd = [executable, "--classic", drv_path, cfg_path]
        logger.info("invoking %s for %d masked detectors -> %s", cmd[0], len(det_ids), out)
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise MantidWriterError(
                f"drtsans timed out after {timeout}s while writing {out}; "
                "increase the timeout or check the source file size"
            ) from exc
        if res.returncode != 0:
            stderr_tail = "\n".join(res.stderr.splitlines()[-12:])
            stdout_tail = "\n".join(res.stdout.splitlines()[-6:])
            raise MantidWriterError(
                f"drtsans failed (rc={res.returncode}):\n"
                f"--- stderr (tail) ---\n{stderr_tail}\n"
                f"--- stdout (tail) ---\n{stdout_tail}"
            )
        if not out.exists():
            raise MantidWriterError(
                f"drtsans returned 0 but {out} was not written;\n"
                f"stdout tail: {res.stdout[-300:]}"
            )
    finally:
        Path(cfg_path).unlink(missing_ok=True)
        Path(drv_path).unlink(missing_ok=True)
    return out


__all__ = [
    "MantidUnavailableError",
    "MantidWriterError",
    "is_drtsans_available",
    "write_nxs_via_mantid",
]
