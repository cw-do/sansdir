"""Display ↔ detector ID ↔ Mantid naming (Phase 9.10.1).

The expected names in ``MANTID_NAMES`` were read from Mantid itself
(``LoadEmptyInstrument(InstrumentName="EQ-SANS")`` →
``getDetector(id).getFullName()``) on 2026-10-21. They pin the one
non-obvious fact: Mantid's bank numbers are *not* the raw file's
``bank<N>_events`` numbers.
"""

from __future__ import annotations

import numpy as np
import pytest

from sansdir.mask.banktube import col_to_bank_tube
from sansdir.plot.hdf5_detector import _reorder_tubes
from sansdir.viewer.geometry import (
    NCOLS,
    NPIX,
    NROWS,
    bank_columns,
    detector_ids,
    info_for_detid,
    pixel_info,
    to_flat,
    to_image,
)

# detid → (panel, Mantid bank, tube, pixel, DAS bank)
MANTID_NAMES = {
    0: ("front", 1, 1, 1, 1),
    1: ("front", 1, 1, 2, 1),
    255: ("front", 1, 1, 256, 1),
    256: ("front", 1, 2, 1, 1),
    1023: ("front", 1, 4, 256, 1),
    1024: ("back", 25, 1, 1, 2),
    2048: ("front", 2, 1, 1, 3),
    3072: ("back", 26, 1, 1, 4),
    14466: ("front", 8, 1, 131, 15),
    49151: ("back", 48, 4, 256, 48),
}


def test_detector_ids_is_a_permutation() -> None:
    ids = detector_ids()
    assert ids.shape == (NROWS, NCOLS)
    assert np.array_equal(np.sort(ids.ravel()), np.arange(NPIX))


def test_to_image_matches_heatmap_reorder() -> None:
    values = np.arange(NPIX) * 3 + 1
    assert np.array_equal(to_image(values), _reorder_tubes(values))
    assert np.array_equal(to_flat(to_image(values)), values)


@pytest.mark.parametrize(("detid", "expected"), sorted(MANTID_NAMES.items()))
def test_names_match_mantid(detid: int, expected: tuple[str, int, int, int, int]) -> None:
    info = info_for_detid(detid)
    assert (info.panel, info.bank, info.tube, info.pixel, info.das_bank) == expected


def test_pixel_info_round_trips_every_detector() -> None:
    for detid in range(0, NPIX, 97):
        info = info_for_detid(detid)
        assert pixel_info(info.x + 0.5, info.y + 0.5) == info
        assert detector_ids()[info.y, info.x] == detid


def test_pixel1_is_the_bottom_row() -> None:
    for col in (0, 1, 100, 191):
        assert pixel_info(col + 0.5, 0.5).pixel == 1  # type: ignore[union-attr]
        assert pixel_info(col + 0.5, NROWS - 0.5).pixel == NROWS  # type: ignore[union-attr]


@pytest.mark.parametrize(("x", "y"), [(-0.01, 5), (NCOLS, 5), (5, NROWS), (5, -1)])
def test_off_detector_is_none(x: float, y: float) -> None:
    assert pixel_info(x, y) is None


def test_bank_columns_tile_the_detector() -> None:
    seen: list[int] = []
    for bank in range(1, 49):
        cols = bank_columns(bank)
        assert len(cols) == 4
        for c in cols:
            info = pixel_info(c + 0.5, 10.5)
            assert info is not None and info.bank == bank
        seen += cols
    assert sorted(seen) == list(range(NCOLS))


def test_das_bank_agrees_with_banktube() -> None:
    """banktube's 0-based "bank" is the DAS block; its tube is 0-based."""
    for col in range(NCOLS):
        info = pixel_info(col + 0.5, 0.5)
        assert info is not None
        assert col_to_bank_tube(col) == (info.das_bank - 1, info.tube - 1)


def test_out_of_range_inputs_raise() -> None:
    with pytest.raises(ValueError):
        info_for_detid(NPIX)
    with pytest.raises(ValueError):
        bank_columns(0)
