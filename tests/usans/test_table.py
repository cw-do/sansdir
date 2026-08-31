"""Tests for sansdir.usans.table — the setup CSV writer / reader / validator.

The written CSV must be byte-compatible with what ``reduceUSANS`` parses:
``flag,name,start_scan,num_of_scans,thickness_cm[,exclude;runs]`` with
``#`` comments.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sansdir.usans.grouping import Group, apply_start_run, default_background, group_runs
from sansdir.usans.reconcile import reconcile
from sansdir.usans.table import ReductionTable, Row, TableError
from tests.usans.conftest import FakeRun, make_block


def _table(runs_5x: list[FakeRun], data_dir: Path) -> ReductionTable:
    groups = group_runs(runs_5x)
    apply_start_run(groups, 1003)
    reconcile(groups, data_dir)
    return ReductionTable.from_groups("IPTS-1", groups, default_background(groups))


# ---------------------------------------------------------------------------
# Row rendering
# ---------------------------------------------------------------------------


def test_row_cells_omit_exclude_when_empty() -> None:
    row = Row(flag="s", name="S0", start_run=100, num_runs=4)
    assert row.to_cells() == ["s", "S0", "100", "4", "0.1"]


def test_row_cells_join_exclude_with_semicolons() -> None:
    row = Row(flag="s", name="S0", start_run=100, num_runs=4, exclude=[101, 102])
    assert row.to_cells()[-1] == "101;102"


def test_row_end_run_spans_num_runs() -> None:
    assert Row(flag="s", name="S0", start_run=100, num_runs=4).end_run == 103


# ---------------------------------------------------------------------------
# from_groups
# ---------------------------------------------------------------------------


def test_background_row_comes_first(runs_5x: list[FakeRun], data_dir_5x: Path) -> None:
    table = _table(runs_5x, data_dir_5x)
    assert table.rows[0].flag == "b"
    assert table.rows[0].name == "emptyBanjo"
    assert [r.flag for r in table.rows[1:]] == ["s", "s", "s"]


def test_rows_use_reconciled_scan_counts(runs_5x: list[FakeRun], data_dir_5x: Path) -> None:
    table = _table(runs_5x, data_dir_5x)
    assert {r.num_runs for r in table.rows} == {4}


def test_excluded_and_scanless_blocks_are_left_out(
    runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    table = _table(runs_5x, data_dir_5x)
    assert "alignment" not in {r.name for r in table.rows}


def test_extra_empty_block_is_kept_as_a_sample() -> None:
    """Only one row may carry the 'b' flag; a second empty block reduces as 's'."""
    groups = group_runs(
        make_block(100, "emptyBanjo", 2)
        + make_block(102, "S0", 2)
        + make_block(104, "emptyBanjo-restart", 2)
    )
    table = ReductionTable.from_groups("IPTS-1", groups, default_background(groups))
    assert [(r.flag, r.name) for r in table.rows] == [
        ("b", "emptyBanjo-restart"),
        ("s", "emptyBanjo"),
        ("s", "S0"),
    ]


def test_annotation_survives_into_the_row() -> None:
    groups = group_runs(make_block(100, "S0-20C 1p", 2))
    table = ReductionTable.from_groups("IPTS-1", groups, None)
    assert table.rows[0].name == "S0-20C"
    assert table.rows[0].annotation == "1p"


# ---------------------------------------------------------------------------
# CSV round-trip
# ---------------------------------------------------------------------------


def test_written_csv_matches_the_engine_format(
    tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    out = _table(runs_5x, data_dir_5x).to_csv(tmp_path / "setup.csv")
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# USANS reduction table for IPTS-1")
    data = [line for line in lines if not line.startswith("#")]
    assert data[0] == "b,emptyBanjo,1003,4,0.1"
    assert "s,S0-20C,1008,4,0.1" in data


def test_csv_round_trips(tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path) -> None:
    original = _table(runs_5x, data_dir_5x)
    path = original.to_csv(tmp_path / "setup.csv")
    parsed = ReductionTable.from_csv(path)
    assert parsed.ipts == "IPTS-1"
    assert [(r.flag, r.name, r.start_run, r.num_runs) for r in parsed.rows] == [
        (r.flag, r.name, r.start_run, r.num_runs) for r in original.rows
    ]


def test_from_csv_reads_exclude_and_thickness(tmp_path: Path) -> None:
    path = tmp_path / "setup.csv"
    path.write_text(
        "# USANS reduction table for IPTS-37679\n"
        "b,Empty,36301,5,0.1\n"
        "s,A2_56C_3hr,36330,5,0.25,36331;36332\n",
        encoding="utf-8",
    )
    table = ReductionTable.from_csv(path)
    assert table.ipts == "IPTS-37679"
    assert table.rows[1].thickness_cm == 0.25
    assert table.rows[1].exclude == [36331, 36332]


def test_from_csv_rejects_a_short_row(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("s,S0,100\n", encoding="utf-8")
    with pytest.raises(TableError, match="at least 4 columns"):
        ReductionTable.from_csv(path)


def test_from_csv_rejects_an_unknown_flag(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("x,S0,100,4,0.1\n", encoding="utf-8")
    with pytest.raises(TableError, match="flag must be"):
        ReductionTable.from_csv(path)


def test_from_csv_rejects_a_non_numeric_run(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("s,S0,first,4,0.1\n", encoding="utf-8")
    with pytest.raises(TableError):
        ReductionTable.from_csv(path)


# ---------------------------------------------------------------------------
# Validation — what blocks a reduce
# ---------------------------------------------------------------------------


def test_valid_table_has_no_problems(runs_5x: list[FakeRun], data_dir_5x: Path) -> None:
    assert _table(runs_5x, data_dir_5x).validate() == []


def test_missing_background_is_a_problem() -> None:
    table = ReductionTable("IPTS-1", [Row("s", "S0", 100, 4)])
    assert any("no background row" in p for p in table.validate())


def test_two_backgrounds_is_a_problem() -> None:
    table = ReductionTable("IPTS-1", [Row("b", "E1", 100, 4), Row("b", "E2", 104, 4)])
    assert any("2 background rows" in p for p in table.validate())


def test_empty_table_is_a_problem() -> None:
    assert any("nothing to reduce" in p for p in ReductionTable("IPTS-1", []).validate())


def test_nonpositive_counts_and_thickness_are_problems() -> None:
    table = ReductionTable("IPTS-1", [Row("b", "E", 100, 0), Row("s", "S", 104, 4, 0.0)])
    problems = " ".join(table.validate())
    assert "num_of_scans is 0" in problems
    assert "thickness is 0 cm" in problems


def test_exclude_outside_the_span_is_a_problem() -> None:
    table = ReductionTable("IPTS-1", [Row("b", "E", 100, 4, exclude=[999])])
    assert any("falls outside" in p for p in table.validate())


def test_duplicate_names_are_a_problem() -> None:
    table = ReductionTable("IPTS-1", [Row("b", "E", 100, 4), Row("s", "E", 104, 4)])
    assert any("duplicate sample name" in p for p in table.validate())


# ---------------------------------------------------------------------------
# Editing helpers
# ---------------------------------------------------------------------------


def test_set_background_demotes_the_previous_one() -> None:
    table = ReductionTable("IPTS-1", [Row("b", "E", 100, 4), Row("s", "S0", 104, 4)])
    assert table.set_background("S0")
    assert [r.flag for r in table.rows] == ["s", "b"]


def test_set_background_and_thickness_report_unknown_names() -> None:
    table = ReductionTable("IPTS-1", [Row("b", "E", 100, 4)])
    assert not table.set_background("nope")
    assert not table.set_thickness("nope", 0.2)
    assert table.set_thickness("E", 0.2)
    assert table.rows[0].thickness_cm == 0.2


def test_group_with_no_reducible_runs_never_becomes_a_row() -> None:
    groups = [Group(title="dead", runs=[100], scan_runs=[])]
    assert ReductionTable.from_groups("IPTS-1", groups, None).rows == []
