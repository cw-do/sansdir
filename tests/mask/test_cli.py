"""CLI integration tests for ``sansdir mask`` (Phase 9.6.5)."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
from click.testing import CliRunner

from sansdir.cli import main
from sansdir.mask.detector import (
    UnsupportedFileLayoutError,
    load_detector_image,
)
from sansdir.plot.hdf5_detector import EQSANS_NBANKS, EQSANS_NPIXELS_TOTAL


def _write_synthetic_eqsans(path: Path) -> None:
    rng = np.random.default_rng(seed=11)
    with h5py.File(path, "w") as fh:
        fh.create_dataset("entry/run_number", data=np.bytes_("0042"))
        fh.create_dataset("entry/title", data=np.bytes_("synthetic"))
        fh.create_dataset(
            "entry/instrument/name", data=np.bytes_("EQ-SANS")
        )
        chunk = EQSANS_NPIXELS_TOTAL // EQSANS_NBANKS
        for b in range(1, EQSANS_NBANKS + 1):
            lo = (b - 1) * chunk
            hi = lo + chunk
            ids = rng.integers(low=lo, high=hi, size=8)
            fh.create_dataset(f"entry/bank{b}_events/event_id", data=ids)


# ---------------------------------------------------------------------------
# CLI behaviour
# ---------------------------------------------------------------------------


def test_cli_requires_at_least_one_shape(tmp_path: Path) -> None:
    src = tmp_path / "EQSANS.nxs.h5"
    _write_synthetic_eqsans(src)
    runner = CliRunner()
    result = runner.invoke(main, ["mask", str(src)])
    assert result.exit_code != 0
    assert "no shapes" in result.output


def test_cli_writes_nxs_with_default_output(tmp_path: Path) -> None:
    src = tmp_path / "EQSANS.nxs.h5"
    _write_synthetic_eqsans(src)
    runner = CliRunner()
    result = runner.invoke(main, ["mask", str(src), "--rect", "10,10,20,20"])
    assert result.exit_code == 0, result.output
    out = src.with_name(f"{src.stem}_mask.nxs")
    assert out.exists()
    assert out.with_suffix(".mask_log.json").exists() or \
        Path(str(out).replace(".nxs", ".mask_log.json")).exists()


def test_cli_writes_xml(tmp_path: Path) -> None:
    src = tmp_path / "EQSANS.nxs.h5"
    _write_synthetic_eqsans(src)
    out = tmp_path / "mask.xml"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "mask", str(src),
            "--circle", "96,128,5",
            "--format", "xml",
            "--output", str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "<detector-masking>" in text
    assert "<detids>" in text


def test_cli_inverse_flag_inverts_mask(tmp_path: Path) -> None:
    """`--inverse` produces the complement count vs the same shapes alone."""
    src = tmp_path / "EQSANS.nxs.h5"
    _write_synthetic_eqsans(src)
    runner = CliRunner()
    out_a = tmp_path / "normal.nxs"
    out_b = tmp_path / "inverse.nxs"
    runner.invoke(
        main,
        ["mask", str(src), "--rect", "10,10,20,20", "--output", str(out_a)],
    )
    runner.invoke(
        main,
        [
            "mask", str(src), "--rect", "10,10,20,20",
            "--inverse", "--output", str(out_b),
        ],
    )
    with h5py.File(out_a, "r") as f:
        n_normal = int(np.diff(f["mantid_workspace_1/event_workspace/indices"][()]).sum())
    with h5py.File(out_b, "r") as f:
        n_inverse = int(np.diff(f["mantid_workspace_1/event_workspace/indices"][()]).sum())
    # Total pixels = sum_normal + sum_inverse.
    assert n_normal + n_inverse == EQSANS_NPIXELS_TOTAL


def test_cli_replay_via_shapes_json(tmp_path: Path) -> None:
    """A round-trip via ``--shapes-json`` produces the same masked count."""
    src = tmp_path / "EQSANS.nxs.h5"
    _write_synthetic_eqsans(src)
    runner = CliRunner()
    first = tmp_path / "first.nxs"
    runner.invoke(
        main,
        [
            "mask", str(src), "--rect", "5,5,12,12",
            "--circle", "96,128,7", "--output", str(first),
        ],
    )
    log = first.with_name(first.stem + ".mask_log.json")
    assert log.exists()
    second = tmp_path / "replay.nxs"
    runner.invoke(
        main,
        [
            "mask", str(src), "--shapes-json", str(log),
            "--output", str(second),
        ],
    )
    with h5py.File(first, "r") as f:
        a = int(np.diff(f["mantid_workspace_1/event_workspace/indices"][()]).sum())
    with h5py.File(second, "r") as f:
        b = int(np.diff(f["mantid_workspace_1/event_workspace/indices"][()]).sum())
    assert a == b


def test_cli_polygon_shape(tmp_path: Path) -> None:
    src = tmp_path / "EQSANS.nxs.h5"
    _write_synthetic_eqsans(src)
    runner = CliRunner()
    out = tmp_path / "poly.npy"
    result = runner.invoke(
        main,
        [
            "mask", str(src),
            "--polygon", "10,10,30,10,30,30",
            "--format", "npy",
            "--output", str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    arr = np.load(out)
    assert arr.dtype == np.uint8
    assert arr.sum() > 0


def test_cli_npy_format(tmp_path: Path) -> None:
    src = tmp_path / "EQSANS.nxs.h5"
    _write_synthetic_eqsans(src)
    runner = CliRunner()
    out = tmp_path / "x.npy"
    result = runner.invoke(
        main,
        ["mask", str(src), "--rect", "0,0,5,5", "--format", "npy", "--output", str(out)],
    )
    assert result.exit_code == 0, result.output
    arr = np.load(out)
    # 6x6 inclusive rectangle = 36 cells.
    assert arr.sum() == 36


def test_cli_rejects_bad_shape_string(tmp_path: Path) -> None:
    src = tmp_path / "EQSANS.nxs.h5"
    _write_synthetic_eqsans(src)
    runner = CliRunner()
    result = runner.invoke(main, ["mask", str(src), "--circle", "1,2"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# End-to-end: detector loader on the synthetic fixture
# ---------------------------------------------------------------------------


def test_loader_smoke(tmp_path: Path) -> None:
    src = tmp_path / "EQSANS.nxs.h5"
    _write_synthetic_eqsans(src)
    image, meta = load_detector_image(src)
    assert image.shape == meta.detector_shape
    assert meta.run_number == "0042"
    assert meta.instrument_name == "EQ-SANS"


def test_unsupported_layout_error_class_present() -> None:
    """The class is exported for callers that want to catch it directly."""
    assert UnsupportedFileLayoutError is not None
