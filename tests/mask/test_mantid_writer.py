"""Tests for the Mantid-backed mask writer (Phase 9.8).

The unit tests use ``unittest.mock.patch`` to stub the
``subprocess.run`` call so they exercise the orchestration logic
without needing Mantid installed. The end-to-end test at the
bottom only runs when ``drtsans`` is on PATH (typically the
cluster); on CI without it, the test is skipped.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np
import pytest

from sansdir.mask.core import MaskBuilder, Rectangle
from sansdir.mask.detector import SourceMeta
from sansdir.mask.mantid_writer import (
    MantidUnavailableError,
    MantidWriterError,
    is_drtsans_available,
    write_nxs_via_mantid,
)


def _meta(detector_shape=(10, 10), source_path: Path | None = None) -> SourceMeta:  # type: ignore[no-untyped-def]
    return SourceMeta(
        source_path=source_path or Path("/SNS/EQSANS/IPTS-12345/nexus/EQSANS_181166.nxs.h5"),
        instrument_name="EQ-SANS",
        detector_shape=detector_shape,
        pixel_ids=np.arange(detector_shape[0] * detector_shape[1], dtype=np.int64),
        run_number="181166",
    )


# ---------------------------------------------------------------------------
# Availability detection
# ---------------------------------------------------------------------------


class TestIsDrtsansAvailable:
    def test_with_real_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda _name: "/bin/drtsans")
        assert is_drtsans_available() is True

    def test_with_no_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        assert is_drtsans_available() is False

    def test_custom_executable_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = {}

        def fake_which(name):  # type: ignore[no-untyped-def]
            captured["asked"] = name
            return None

        monkeypatch.setattr(shutil, "which", fake_which)
        is_drtsans_available("my-mantid-wrapper")
        assert captured["asked"] == "my-mantid-wrapper"


# ---------------------------------------------------------------------------
# write_nxs_via_mantid — orchestration via mocked subprocess
# ---------------------------------------------------------------------------


class TestWriteNxsViaMantidOrchestration:
    """Pin the cmdline shape + tempfile handling without needing Mantid."""

    def test_raises_when_drtsans_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        mask = np.zeros((10, 10), dtype=np.uint8)
        with pytest.raises(MantidUnavailableError, match="not on PATH"):
            write_nxs_via_mantid(tmp_path / "out.nxs", mask, _meta())

    def test_passes_masked_detector_ids_to_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The config JSON passed to drtsans contains the right detector
        IDs and output path — that's the actual contract the Mantid
        driver script consumes."""
        monkeypatch.setattr(shutil, "which", lambda _name: "/bin/drtsans")

        # Build a mask with 4 specific pixels masked.
        meta = _meta(detector_shape=(10, 10))
        builder = MaskBuilder(meta.detector_shape)
        builder.add(Rectangle(2, 2, 3, 3))  # 4 cells: (2,2)(2,3)(3,2)(3,3)
        mask = builder.build()
        out_path = tmp_path / "result.nxs"

        captured: list[dict] = []

        def fake_run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
            # cmd is [drtsans_exec, --classic, driver_path, config_path]
            assert cmd[0] == "drtsans"
            assert cmd[1] == "--classic"
            with open(cmd[3]) as f:
                captured.append(json.load(f))
            # Simulate Mantid writing the output file.
            out_path.write_bytes(b"FAKE NEXUS")
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = write_nxs_via_mantid(out_path, mask, meta)
        assert result == out_path.resolve()
        assert len(captured) == 1
        cfg = captured[0]
        # Source path round-trips verbatim.
        assert cfg["source"] == str(meta.source_path)
        assert cfg["output"] == str(out_path.resolve())
        # 4-cell rectangle → 4 detector IDs. With identity pixel_ids
        # the IDs are the flat row-major indices: (2,2)→22, (2,3)→23,
        # (3,2)→32, (3,3)→33.
        assert sorted(cfg["detector_ids"]) == [22, 23, 32, 33]

    def test_raises_writer_error_on_nonzero_return(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(shutil, "which", lambda _name: "/bin/drtsans")

        def fake_run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
            return subprocess.CompletedProcess(
                cmd, returncode=2, stdout="", stderr="some Mantid crash"
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(MantidWriterError, match="rc=2") as exc_info:
            write_nxs_via_mantid(
                tmp_path / "out.nxs", np.zeros((10, 10), dtype=np.uint8), _meta()
            )
        assert "some Mantid crash" in str(exc_info.value)

    def test_raises_writer_error_when_output_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """rc=0 but no output file means the driver script went wrong
        silently — still a failure."""
        monkeypatch.setattr(shutil, "which", lambda _name: "/bin/drtsans")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 0, "ok", ""),
        )
        with pytest.raises(MantidWriterError, match="not written"):
            write_nxs_via_mantid(
                tmp_path / "out.nxs", np.zeros((10, 10), dtype=np.uint8), _meta()
            )

    def test_raises_writer_error_on_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(shutil, "which", lambda _name: "/bin/drtsans")

        def fake_run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
            raise subprocess.TimeoutExpired(cmd, 1.0)

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(MantidWriterError, match="timed out"):
            write_nxs_via_mantid(
                tmp_path / "out.nxs",
                np.zeros((10, 10), dtype=np.uint8),
                _meta(),
                timeout=1.0,
            )

    def test_tempfiles_cleaned_up_on_success_and_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both the config JSON and the driver script tempfiles must
        be unlinked regardless of success/failure — otherwise a long
        editor session leaks ``/tmp`` files."""
        monkeypatch.setattr(shutil, "which", lambda _name: "/bin/drtsans")
        captured_paths: list[str] = []

        def fake_run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
            captured_paths.extend(cmd[2:4])
            return subprocess.CompletedProcess(cmd, 2, "", "crash")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(MantidWriterError):
            write_nxs_via_mantid(
                tmp_path / "out.nxs", np.zeros((10, 10), dtype=np.uint8), _meta()
            )
        # Both temp paths gone after the call returned (via finally).
        for p in captured_paths:
            assert not Path(p).exists(), f"tempfile leaked: {p}"


# ---------------------------------------------------------------------------
# writers.write_nxs dispatcher — Mantid-first with legacy fallback
# ---------------------------------------------------------------------------


class TestWriteNxsDispatcher:
    """Pin the behaviour of the public ``write_nxs`` wrapper."""

    def test_uses_legacy_when_env_var_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # conftest sets this globally; reaffirm explicitly here.
        monkeypatch.setenv("SANSDIR_NO_MANTID", "1")
        # Patch out the Mantid writer so we'd see it if called.
        with patch(
            "sansdir.mask.mantid_writer.write_nxs_via_mantid"
        ) as mantid_call:
            from sansdir.mask.writers import write_nxs

            out = write_nxs(
                tmp_path / "out.nxs", np.zeros((10, 10), dtype=np.uint8), _meta()
            )
        assert mantid_call.call_count == 0
        # Legacy writer produced a real h5 file.
        with h5py.File(out, "r") as f:
            assert "mantid_workspace_1/event_workspace/indices" in f

    def test_uses_legacy_when_prefer_mantid_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SANSDIR_NO_MANTID", raising=False)
        with patch(
            "sansdir.mask.mantid_writer.write_nxs_via_mantid"
        ) as mantid_call:
            from sansdir.mask.writers import write_nxs

            write_nxs(
                tmp_path / "out.nxs",
                np.zeros((10, 10), dtype=np.uint8),
                _meta(),
                prefer_mantid=False,
            )
        assert mantid_call.call_count == 0

    def test_falls_back_when_mantid_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SANSDIR_NO_MANTID", raising=False)
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        from sansdir.mask.writers import write_nxs

        # Should silently fall back without raising.
        out = write_nxs(
            tmp_path / "out.nxs", np.zeros((10, 10), dtype=np.uint8), _meta()
        )
        with h5py.File(out, "r") as f:
            assert "mantid_workspace_1/event_workspace/indices" in f

    def test_propagates_mantid_writer_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When drtsans is found but the subprocess fails, the error
        must propagate — legacy fallback would silently produce a
        mask file drtsans won't honour, which is the exact bug this
        whole module exists to avoid."""
        monkeypatch.delenv("SANSDIR_NO_MANTID", raising=False)
        monkeypatch.setattr(shutil, "which", lambda _name: "/bin/drtsans")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, **_kw: subprocess.CompletedProcess(
                cmd, 1, "", "boom"
            ),
        )
        from sansdir.mask.writers import write_nxs

        with pytest.raises(MantidWriterError, match="rc=1"):
            write_nxs(
                tmp_path / "out.nxs",
                np.zeros((10, 10), dtype=np.uint8),
                _meta(),
            )


# ---------------------------------------------------------------------------
# End-to-end against real Mantid (cluster-only)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not is_drtsans_available(),
    reason="drtsans not on PATH — Mantid integration test skipped",
)
def test_e2e_writer_produces_drtsans_compatible_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The end-to-end test that catches regressions in the contract
    with drtsans. Only runs on hosts where drtsans is installed.

    Pins:
      * ``instrument_parameter_map`` is present and non-empty
      * It contains ``detID:<N>;bool;masked;1`` entries
      * The count of masked entries matches our mask's masked-pixel
        count exactly
      * ``event_workspace/indices`` shows the same count of zero-event
        spectra (Mantid drops events on masked detectors)
    """
    monkeypatch.delenv("SANSDIR_NO_MANTID", raising=False)
    # Use the user's actual IPTS-36811 mask log as the source —
    # it's the smallest real reproducible we have. If the file is
    # missing (e.g. running off-cluster) skip.
    log_path = Path(
        "/SNS/EQSANS/IPTS-36811/shared/mask4m.mask_log.json"
    )
    if not log_path.exists():
        pytest.skip(f"reference mask log {log_path} not present")
    builder = MaskBuilder.from_log(log_path)
    mask = builder.build()
    with open(log_path) as f:
        log_data = json.load(f)
    source = Path(log_data["source_nxs"])
    if not source.exists():
        pytest.skip(f"source nexus {source} not present")
    from sansdir.mask.detector import load_detector_image

    _, meta = load_detector_image(source)
    out_path = tmp_path / "e2e_mask.nxs"
    result = write_nxs_via_mantid(out_path, mask, meta, timeout=240.0)
    assert result == out_path.resolve()
    assert out_path.exists()

    expected_masked = int(mask.sum())
    with h5py.File(out_path, "r") as fh:
        ipm = fh["mantid_workspace_1/instrument/instrument_parameter_map/data"][()]
        text = ipm[0].decode() if hasattr(ipm[0], "decode") else ipm[0]
        n_masked_in_map = text.count(";bool;masked;1")
        assert n_masked_in_map == expected_masked, (
            f"instrument_parameter_map has {n_masked_in_map} masked entries, "
            f"expected {expected_masked}"
        )
        indices = fh["mantid_workspace_1/event_workspace/indices"][()]
        zero_evt_spectra = int((np.diff(indices) == 0).sum())
        assert zero_evt_spectra == expected_masked, (
            f"event_workspace shows {zero_evt_spectra} zero-event spectra, "
            f"expected {expected_masked} (one per masked detector)"
        )
