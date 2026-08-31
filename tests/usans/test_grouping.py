"""Tests for sansdir.usans.grouping — title blocking and background pick."""

from __future__ import annotations

from sansdir.usans.grouping import (
    Group,
    apply_start_run,
    default_background,
    group_runs,
)
from tests.usans.conftest import FakeRun, make_block


def test_consecutive_same_title_runs_form_one_block() -> None:
    groups = group_runs(make_block(100, "S0-20C", 5))
    assert len(groups) == 1
    assert groups[0].runs == [100, 101, 102, 103, 104]
    assert groups[0].start_run == 100
    assert groups[0].count == 5


def test_title_change_starts_a_new_block(runs_5x: list[FakeRun]) -> None:
    titles = [g.title for g in group_runs(runs_5x)]
    assert titles == ["alignment", "emptyBanjo", "S0-20C 1p", "S0-40C", "S1-L62 0p"]


def test_run_number_gap_splits_a_repeated_title() -> None:
    """Same title on either side of a gap is two measurements, not one."""
    runs = make_block(100, "S0", 2) + make_block(105, "S0", 2)
    groups = group_runs(runs)
    assert [g.runs for g in groups] == [[100, 101], [105, 106]]


def test_runs_are_sorted_before_grouping() -> None:
    shuffled = [FakeRun(102, "A"), FakeRun(100, "A"), FakeRun(101, "A")]
    assert group_runs(shuffled)[0].runs == [100, 101, 102]


def test_empty_run_list_yields_no_groups() -> None:
    assert group_runs([]) == []


def test_name_is_first_token_and_annotation_is_the_rest() -> None:
    g = Group(title="S0-20C 1p", runs=[1])
    assert g.name == "S0-20C"
    assert g.annotation == "1p"


def test_name_falls_back_to_the_whole_title_when_blank() -> None:
    g = Group(title="", runs=[1])
    assert g.name == ""
    assert g.annotation == ""


def test_background_detection_is_keyword_based() -> None:
    assert Group(title="emptyBanjo", runs=[1]).is_background
    assert Group(title="Empty Cell", runs=[1]).is_background
    assert Group(title="the BANJO", runs=[1]).is_background
    assert not Group(title="S0-20C", runs=[1]).is_background


def test_flag_follows_background_detection() -> None:
    assert Group(title="emptyBanjo", runs=[1]).flag == "b"
    assert Group(title="S0-20C", runs=[1]).flag == "s"


def test_default_background_picks_the_last_included_empty_block() -> None:
    groups = group_runs(
        make_block(100, "emptyBanjo", 2)
        + make_block(102, "S0", 2)
        + make_block(104, "emptyBanjo-restart", 2)
    )
    bg = default_background(groups)
    assert bg is not None
    assert bg.start_run == 104


def test_default_background_ignores_excluded_blocks() -> None:
    groups = group_runs(make_block(100, "emptyBanjo", 2) + make_block(102, "S0", 2))
    apply_start_run(groups, 102)
    assert default_background(groups) is None


def test_default_background_is_none_without_an_empty_block() -> None:
    assert default_background(group_runs(make_block(100, "S0", 2))) is None


def test_apply_start_run_excludes_earlier_blocks(runs_5x: list[FakeRun]) -> None:
    groups = group_runs(runs_5x)
    excluded = apply_start_run(groups, 1003)
    assert excluded == 1
    assert [g.title for g in groups if not g.included] == ["alignment"]


def test_apply_start_run_with_none_includes_everything(runs_5x: list[FakeRun]) -> None:
    groups = group_runs(runs_5x)
    assert apply_start_run(groups, None) == 0
    assert all(g.included for g in groups)


def test_unreconciled_group_reduces_the_whole_title_block() -> None:
    """Without a data dir we have no better information than the titles."""
    g = group_runs(make_block(100, "S0", 5))[0]
    assert g.scan_runs is None
    assert g.reduce_runs == [100, 101, 102, 103, 104]
    assert g.reduce_count == 5
    assert g.transmission_runs == []


def test_reduce_exclude_lists_mid_block_gaps() -> None:
    g = Group(title="S0", runs=[100, 101, 102, 103], scan_runs=[100, 102, 103])
    assert g.reduce_start == 100
    assert g.reduce_count == 3
    assert g.reduce_exclude == [101]
    assert g.reduce_span == 4


def test_window_overrides_scan_runs_for_reduction() -> None:
    g = Group(title="S0", runs=list(range(100, 110)), scan_runs=list(range(100, 109)))
    g.window = [105, 106, 107, 108]
    assert g.reduce_runs == [105, 106, 107, 108]
    assert g.dropped_runs == [100, 101, 102, 103, 104]
