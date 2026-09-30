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


def test_empty_cell_rows_come_first_as_t_then_b(runs_5x: list[FakeRun], data_dir_5x: Path) -> None:
    table = _table(runs_5x, data_dir_5x)
    assert [(r.flag, r.name) for r in table.rows[:2]] == [
        ("t", "emptyBanjo_T"),
        ("b", "emptyBanjo"),
    ]
    assert table.rows[0].span == table.rows[1].span
    assert [r.flag for r in table.rows[2:]] == ["s", "s", "s"]


def test_transmission_row_can_be_turned_off(runs_5x: list[FakeRun], data_dir_5x: Path) -> None:
    groups = group_runs(runs_5x)
    reconcile(groups, data_dir_5x)
    table = ReductionTable.from_groups(
        "IPTS-1", groups, default_background(groups), transmission_row=False
    )
    assert [r.flag for r in table.rows][:2] == ["b", "s"]


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
        ("t", "emptyBanjo-restart_T"),
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
    assert data[:2] == ["t,emptyBanjo_T,1003,4,0.1", "b,emptyBanjo,1003,4,0.1"]
    assert any("t=empty cell" in line for line in lines if line.startswith("#"))
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


# ---------------------------------------------------------------------------
# The 't' row
# ---------------------------------------------------------------------------


def _rows(*cells: tuple[str, str, int, int]) -> ReductionTable:
    return ReductionTable(
        ipts="IPTS-1",
        rows=[
            Row(flag=f, name=n, start_run=s, num_runs=k, thickness_cm=0.2) for f, n, s, k in cells
        ],
    )


def test_a_t_row_parses(tmp_path: Path) -> None:
    path = tmp_path / "setup.csv"
    path.write_text("t,E_T,100,4,0.2\nb,E,100,4,0.2\ns,S0,104,4,0.2\n", encoding="utf-8")
    table = ReductionTable.from_csv(path)
    assert [r.flag for r in table.rows] == ["t", "b", "s"]
    assert table.transmissions[0].is_transmission
    assert table.validate() == []
    assert table.advisories() == []


def test_two_t_rows_are_refused() -> None:
    table = _rows(
        ("t", "E_T", 100, 4), ("t", "F_T", 100, 4), ("b", "E", 100, 4), ("s", "S", 104, 4)
    )
    assert any("2 transmission rows" in p for p in table.validate())


def test_t_and_b_must_cover_the_same_runs() -> None:
    table = _rows(("t", "E_T", 100, 4), ("b", "E", 101, 3), ("s", "S", 104, 4))
    assert any("cover different runs" in p for p in table.validate())


def test_b_without_t_warns_that_t_is_one() -> None:
    table = _rows(("b", "E", 100, 4), ("s", "S", 104, 4))
    assert table.validate() == [], "still reducible"
    assert any("T = 1" in a for a in table.advisories())


def test_set_background_leaves_the_t_row_alone() -> None:
    table = _rows(("t", "E_T", 100, 4), ("b", "E", 100, 4), ("s", "S", 104, 4))
    assert table.set_background("S")
    assert [r.flag for r in table.rows] == ["t", "s", "b"]


def test_num_of_scans_spans_a_mid_block_exclude() -> None:
    """usansred reads range(num_of_scans) from start and skips excludes."""
    groups = group_runs(make_block(100, "S0", 4))
    groups[0].scan_runs = [100, 101, 103]
    row = ReductionTable.from_groups("IPTS-1", groups, None).rows[0]
    assert (row.start_run, row.num_runs, row.exclude) == (100, 4, [102])
    assert row.end_run == 103


def test_engine_config_maps_flags_onto_usansred_json() -> None:
    table = _rows(("t", "E_T", 100, 4), ("b", "E", 100, 4), ("s", "S", 104, 4))
    cfg = table.to_engine_config()
    assert cfg["empty_cell"] == {"name": "E_T", "start_scan_num": 100, "num_of_scans": 4}
    assert cfg["background"]["name"] == "E" and cfg["background"]["thickness"] == 0.2
    assert [s["name"] for s in cfg["samples"]] == ["S"]
    assert "empty_cell" not in _rows(("b", "E", 100, 4), ("s", "S", 104, 4)).to_engine_config()
