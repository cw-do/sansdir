"""Tests for the EQSANS column ↔ bank/tube map and spec parser."""

from __future__ import annotations

import pytest

from sansdir.mask.banktube import (
    EQSANS_NBANKS,
    EQSANS_NTUBES,
    EQSANS_NTUBES_PER_BANK,
    bank_tube_to_col,
    col_to_bank_tube,
    cols_for_bank,
    cols_to_runs,
    parse_spec,
)


class TestColumnBankTubeRoundTrip:
    """The forward and inverse functions must be exact and total."""

    def test_round_trip_all_columns(self) -> None:
        for col in range(EQSANS_NTUBES):
            bank, tube = col_to_bank_tube(col)
            assert 0 <= bank < EQSANS_NBANKS
            assert 0 <= tube < EQSANS_NTUBES_PER_BANK
            assert bank_tube_to_col(bank, tube) == col

    def test_round_trip_all_bank_tubes(self) -> None:
        for bank in range(EQSANS_NBANKS):
            for tube in range(EQSANS_NTUBES_PER_BANK):
                col = bank_tube_to_col(bank, tube)
                assert col_to_bank_tube(col) == (bank, tube)

    def test_total_columns_covered_exactly_once(self) -> None:
        """Every column belongs to exactly one (bank, tube_in_bank)."""
        seen: set[int] = set()
        for bank in range(EQSANS_NBANKS):
            for tube in range(EQSANS_NTUBES_PER_BANK):
                col = bank_tube_to_col(bank, tube)
                assert col not in seen
                seen.add(col)
        assert len(seen) == EQSANS_NTUBES


class TestColToBankTubeKnownExamples:
    """Pin the staggered-front/back interleave at a few corners."""

    def test_zero_column_is_first_front_bank(self) -> None:
        assert col_to_bank_tube(0) == (0, 0)

    def test_first_column_is_first_back_bank(self) -> None:
        # The interleave is front,back,front,back,… within each group.
        assert col_to_bank_tube(1) == (1, 0)

    def test_second_column_is_second_tube_of_front_bank(self) -> None:
        assert col_to_bank_tube(2) == (0, 1)

    def test_eighth_column_starts_next_group(self) -> None:
        assert col_to_bank_tube(8) == (2, 0)

    def test_last_column_is_last_back_bank(self) -> None:
        assert col_to_bank_tube(EQSANS_NTUBES - 1) == (
            EQSANS_NBANKS - 1, EQSANS_NTUBES_PER_BANK - 1,
        )


class TestColToBankTubeBoundaries:
    def test_negative_col_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            col_to_bank_tube(-1)

    def test_too_large_col_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            col_to_bank_tube(EQSANS_NTUBES)


class TestBankTubeToColBoundaries:
    def test_negative_bank_raises(self) -> None:
        with pytest.raises(ValueError, match="bank"):
            bank_tube_to_col(-1, 0)

    def test_too_large_bank_raises(self) -> None:
        with pytest.raises(ValueError, match="bank"):
            bank_tube_to_col(EQSANS_NBANKS, 0)

    def test_negative_tube_raises(self) -> None:
        with pytest.raises(ValueError, match="tube_in_bank"):
            bank_tube_to_col(0, -1)

    def test_too_large_tube_raises(self) -> None:
        with pytest.raises(ValueError, match="tube_in_bank"):
            bank_tube_to_col(0, EQSANS_NTUBES_PER_BANK)


class TestColsForBank:
    def test_first_bank_columns(self) -> None:
        # Bank 0 = front of group 0 → cols 0,2,4,6.
        assert cols_for_bank(0) == [0, 2, 4, 6]

    def test_second_bank_columns(self) -> None:
        # Bank 1 = back of group 0 → cols 1,3,5,7.
        assert cols_for_bank(1) == [1, 3, 5, 7]

    def test_each_bank_has_four_tubes(self) -> None:
        for bank in range(EQSANS_NBANKS):
            assert len(cols_for_bank(bank)) == EQSANS_NTUBES_PER_BANK


class TestParseSpec:
    def test_empty(self) -> None:
        assert parse_spec("") == []

    def test_single_bank(self) -> None:
        assert parse_spec("b0") == [0, 2, 4, 6]

    def test_single_tube(self) -> None:
        assert parse_spec("t10") == [10]

    def test_tube_range(self) -> None:
        assert parse_spec("t10-13") == [10, 11, 12, 13]

    def test_bank_range(self) -> None:
        # Banks 0 and 1 = all of group 0 = cols 0..7.
        assert parse_spec("b0-1") == [0, 1, 2, 3, 4, 5, 6, 7]

    def test_mixed_separators(self) -> None:
        assert parse_spec("b0, t5; t9") == [0, 2, 4, 5, 6, 9]

    def test_dedup_and_sort(self) -> None:
        # Bank 0 includes col 4; explicit t4 is collapsed.
        assert parse_spec("b0 t4 t2") == [0, 2, 4, 6]

    def test_uppercase_ok(self) -> None:
        assert parse_spec("B0") == [0, 2, 4, 6]

    def test_reverse_range_ok(self) -> None:
        assert parse_spec("t5-3") == [3, 4, 5]

    def test_unknown_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="must start with"):
            parse_spec("x5")

    def test_tube_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            parse_spec(f"t{EQSANS_NTUBES}")

    def test_bank_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            parse_spec(f"b{EQSANS_NBANKS}")


class TestColsToRuns:
    def test_empty(self) -> None:
        assert cols_to_runs([]) == []

    def test_single(self) -> None:
        assert cols_to_runs([5]) == [(5, 5)]

    def test_consecutive(self) -> None:
        assert cols_to_runs([4, 5, 6]) == [(4, 6)]

    def test_split(self) -> None:
        assert cols_to_runs([4, 5, 6, 9, 10]) == [(4, 6), (9, 10)]

    def test_dedup_and_sort(self) -> None:
        assert cols_to_runs([10, 4, 5, 6, 4]) == [(4, 6), (10, 10)]
