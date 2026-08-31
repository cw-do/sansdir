"""Reduced USANS curves must land on the 1D I(q) plotter.

``reduceUSANS`` writes comma-separated ``q,I,E`` with a trailing delimiter,
under names whose sample part is arbitrary user text — including text that
could contain "trans" and mis-route the file to the transmission plotter.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sansdir.plot.ascii1d import read_iq
from sansdir.plot.detect import KIND_IQ, KIND_TRANSMISSION, detect_kind

# One real line shape from a UN_*_det_1_lb.txt: comma-separated, trailing comma.
_REDUCED_BODY = (
    "1e-06,19505001.35187176,11349603.325531611,\n"
    "1.0722672220103232e-06,18487622.96270287,10618464.703526597,\n"
    "1.149756995397736e-06,17396721.463615477,9834490.440495022,\n"
    "1.2328467394420666e-06,16226983.543702096,8993863.025239164,\n"
)


@pytest.mark.parametrize(
    "name",
    [
        "UN_S0-20C_det_1.txt",
        "UN_S0-20C_det_1_lb.txt",
        "UN_S0-20C_det_1_unscaled.txt",
        "UN_S0-20C_det_1_background_subtracted.txt",
        "UN_emptyBanjo-restart_det_1_lb.txt",
    ],
)
def test_reduced_usans_output_is_classified_as_iq(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_text(_REDUCED_BODY, encoding="utf-8")
    assert detect_kind(path).kind == KIND_IQ


def test_a_sample_named_trans_still_routes_to_iq(tmp_path: Path) -> None:
    """Filename-based USANS detection must beat the "trans" substring rule."""
    path = tmp_path / "UN_transferrin_det_1_lb.txt"
    path.write_text(_REDUCED_BODY, encoding="utf-8")
    assert detect_kind(path).kind == KIND_IQ


def test_ordinary_transmission_files_are_untouched(tmp_path: Path) -> None:
    path = tmp_path / "EQSANS_trans.txt"
    path.write_text("1.0 0.9 0.01\n2.0 0.8 0.01\n", encoding="utf-8")
    assert detect_kind(path).kind == KIND_TRANSMISSION


def test_reduced_curve_parses_into_q_i_sigma(tmp_path: Path) -> None:
    path = tmp_path / "UN_S0-20C_det_1_lb.txt"
    path.write_text(_REDUCED_BODY, encoding="utf-8")
    data = read_iq(path)
    assert data.q.size == 4
    assert data.has_errors
    assert data.q[0] == pytest.approx(1e-06)
    assert data.intensity[0] == pytest.approx(19505001.35187176)
