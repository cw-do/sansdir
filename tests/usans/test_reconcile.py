"""Tests for sansdir.usans.reconcile — the ARN-scan reconciliation.

The invariant these protect: ``num_of_scans`` must be the count of runs
that actually have ARN files, not the OnCat title count. A live test on
IPTS-37679 proved ``num=5`` crashes ``reduceUSANS`` on the missing
transmission-run ASCII where ``num=4`` succeeds.
"""

from __future__ import annotations

from pathlib import Path

from sansdir.usans.grouping import Group, group_runs
from sansdir.usans.reconcile import (
    flag_restarts,
    is_reducible,
    modal_scan_count,
    reconcile,
    reducible_runs,
)
from tests.usans.conftest import FakeRun, make_block, write_arn


def test_is_reducible_needs_both_arn_files(tmp_path: Path) -> None:
    from sansdir.usans.reconcile import MONITOR_PATTERN

    assert not is_reducible(tmp_path, 100)
    (tmp_path / MONITOR_PATTERN.format(run=100)).write_text("", encoding="utf-8")
    assert not is_reducible(tmp_path, 100), "monitor alone is not enough"
    write_arn(tmp_path, [100])
    assert is_reducible(tmp_path, 100)


def test_reducible_runs_preserves_order_and_drops_missing(tmp_path: Path) -> None:
    write_arn(tmp_path, [100, 102])
    assert reducible_runs(tmp_path, [100, 101, 102, 103]) == [100, 102]


def test_reconcile_drops_the_trailing_transmission_run(
    runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    groups = group_runs(runs_5x)
    reconcile(groups, data_dir_5x)
    sample = next(g for g in groups if g.name == "S0-20C")
    assert sample.count == 5, "the title block really is five runs"
    assert sample.reduce_count == 4, "but only four of them are ARN scans"
    assert sample.reduce_start == 1008
    assert sample.transmission_runs == [1012]


def test_reconcile_marks_blocks_with_no_arn_files_as_empty(
    runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    groups = group_runs(runs_5x)
    reconcile(groups, data_dir_5x)
    alignment = next(g for g in groups if g.title == "alignment")
    assert alignment.scan_runs == []
    assert alignment.reduce_count == 0


def test_variable_block_sizes_are_handled_without_configuration(tmp_path: Path) -> None:
    """4-, 5- and 6-run blocks each reduce to (N-1) scans, no flags needed."""
    runs = make_block(100, "A", 4) + make_block(104, "B", 5) + make_block(109, "C", 6)
    data_dir = tmp_path / "autoreduce"
    write_arn(data_dir, [100, 101, 102, 104, 105, 106, 107, 109, 110, 111, 112, 113])
    groups = group_runs(runs)
    reconcile(groups, data_dir)
    assert [g.reduce_count for g in groups] == [3, 4, 5]


def test_modal_scan_count_ignores_the_background(runs_5x: list[FakeRun], data_dir_5x: Path) -> None:
    groups = group_runs(runs_5x)
    reconcile(groups, data_dir_5x)
    assert modal_scan_count(groups) == 4


def test_modal_scan_count_is_none_without_reducible_blocks() -> None:
    assert modal_scan_count([]) is None
    assert modal_scan_count([Group(title="A", runs=[1], scan_runs=[])]) is None


def test_flag_restarts_narrows_an_oversized_block_to_the_last_window(tmp_path: Path) -> None:
    """A stopped-and-restarted block keeps its last modal-size window."""
    runs = (
        make_block(100, "S0", 5)
        + make_block(105, "S1", 5)
        # S2 was started, aborted, and restarted under the same title.
        + make_block(110, "S2", 10)
    )
    data_dir = tmp_path / "autoreduce"
    scans = [100, 101, 102, 103, 105, 106, 107, 108, *range(110, 119)]
    write_arn(data_dir, scans)
    groups = group_runs(runs)
    reconcile(groups, data_dir)
    flagged = flag_restarts(groups)

    assert [g.name for g in flagged] == ["S2"]
    s2 = flagged[0]
    assert s2.restart_suspect
    assert s2.reduce_runs == [115, 116, 117, 118]
    assert s2.dropped_runs == [110, 111, 112, 113, 114]


def test_flag_restarts_leaves_normal_blocks_untouched(
    runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    groups = group_runs(runs_5x)
    reconcile(groups, data_dir_5x)
    assert flag_restarts(groups) == []
    assert all(g.window is None for g in groups)
    assert not any(g.restart_suspect for g in groups)


def test_flag_restarts_needs_a_baseline_of_at_least_two_blocks(tmp_path: Path) -> None:
    """One long block and one short one is not enough to call a restart."""
    runs = make_block(100, "A", 3) + make_block(103, "B", 9)
    data_dir = tmp_path / "autoreduce"
    write_arn(data_dir, [*range(100, 103), *range(103, 112)])
    groups = group_runs(runs)
    reconcile(groups, data_dir)
    assert flag_restarts(groups) == []
