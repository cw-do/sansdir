"""Tests for sansdir.usans.catalog — build_catalog, NOTE rendering, outputs."""

from __future__ import annotations

from pathlib import Path

from sansdir.usans.catalog import (
    build_catalog,
    default_data_dir,
    ipts_from_path,
    ipts_label,
    output_paths,
    render_note,
    summarize,
    write_outputs,
)
from tests.usans.conftest import FakeRun, make_block, write_arn


def test_ipts_label_normalises_every_spelling() -> None:
    assert ipts_label(37679) == "IPTS-37679"
    assert ipts_label("37679") == "IPTS-37679"
    assert ipts_label("IPTS-37679") == "IPTS-37679"
    assert ipts_label("ipts-37679") == "IPTS-37679"
    assert ipts_label("") == ""


def test_default_data_dir_follows_the_cluster_convention() -> None:
    assert default_data_dir(37679) == Path("/SNS/USANS/IPTS-37679/shared/autoreduce")


def test_default_data_dir_honours_a_template() -> None:
    got = default_data_dir(1, template="/tmp/{ipts}/data")
    assert got == Path("/tmp/IPTS-1/data")


def test_ipts_from_path_finds_the_label(tmp_path: Path) -> None:
    target = tmp_path / "IPTS-37679" / "shared" / "setup.csv"
    target.parent.mkdir(parents=True)
    target.write_text("", encoding="utf-8")
    assert ipts_from_path(target) == "IPTS-37679"


def test_ipts_from_path_returns_blank_when_absent(tmp_path: Path) -> None:
    assert ipts_from_path(tmp_path / "setup.csv") == ""


# ---------------------------------------------------------------------------
# build_catalog
# ---------------------------------------------------------------------------


def test_build_catalog_reconciles_when_the_data_dir_exists(
    runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    cat = build_catalog("IPTS-1", runs_5x, start_run=1003, data_dir=data_dir_5x)
    assert cat.reconciled
    assert cat.data_dir == data_dir_5x
    assert cat.background is not None
    assert cat.background.name == "emptyBanjo"
    assert [(r.flag, r.num_runs) for r in cat.table.rows] == [
        ("t", 4),
        ("b", 4),
        ("s", 4),
        ("s", 4),
        ("s", 4),
    ]
    assert cat.warnings == []


def test_build_catalog_without_a_data_dir_falls_back_to_title_counts(
    runs_5x: list[FakeRun], tmp_path: Path
) -> None:
    cat = build_catalog("IPTS-1", runs_5x, start_run=1003, data_dir=tmp_path / "missing")
    assert not cat.reconciled
    assert cat.data_dir is None
    # Unverified: the whole 5-run title block, transmission run included.
    assert {r.num_runs for r in cat.table.rows} == {5}
    assert any("unverified" in w for w in cat.warnings)


def test_build_catalog_never_touches_the_network(
    runs_5x: list[FakeRun], data_dir_5x: Path, monkeypatch
) -> None:
    """Guards the 'pure core' rule: no network path may be exercised."""
    import socket

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("build_catalog opened a socket")

    monkeypatch.setattr(socket, "socket", _boom)
    cat = build_catalog("IPTS-1", runs_5x, data_dir=data_dir_5x)
    assert cat.table.rows


def test_build_catalog_applies_a_thickness_override(
    runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    cat = build_catalog("IPTS-1", runs_5x, data_dir=data_dir_5x, thickness_cm=0.25)
    assert {r.thickness_cm for r in cat.table.rows} == {0.25}


def test_build_catalog_warns_about_a_missing_background(tmp_path: Path) -> None:
    data_dir = tmp_path / "autoreduce"
    write_arn(data_dir, [100, 101, 102, 103])
    cat = build_catalog("IPTS-1", make_block(100, "S0", 5), data_dir=data_dir)
    assert cat.background is None
    assert any("no background" in w for w in cat.warnings)


def test_build_catalog_warns_about_restarts(tmp_path: Path) -> None:
    runs = make_block(100, "S0", 5) + make_block(105, "S1", 5) + make_block(110, "S2", 10)
    data_dir = tmp_path / "autoreduce"
    write_arn(data_dir, [100, 101, 102, 103, 105, 106, 107, 108, *range(110, 119)])
    cat = build_catalog("IPTS-1", runs, data_dir=data_dir)
    assert [g.name for g in cat.restarts] == ["S2"]
    assert any("possible restart" in w for w in cat.warnings)


def test_summarize_is_a_one_liner(runs_5x: list[FakeRun], data_dir_5x: Path) -> None:
    cat = build_catalog("IPTS-1", runs_5x, start_run=1003, data_dir=data_dir_5x)
    assert summarize(cat) == "5 rows · bg=emptyBanjo · reconciled"


# ---------------------------------------------------------------------------
# NOTE rendering
# ---------------------------------------------------------------------------


def test_note_records_the_left_out_runs_with_a_reason(
    runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    cat = build_catalog("IPTS-1", runs_5x, start_run=1003, data_dir=data_dir_5x)
    note = render_note(cat, today="2026-01-01")
    assert "## Runs left out of each block, and why" in note
    assert "**S0-20C** (`S0-20C 1p`, runs 1008-1012):" in note
    assert "  - 1012: no ARN scan files (transmission run?)" in note


def test_note_records_excluded_and_annotated_blocks(
    runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    cat = build_catalog("IPTS-1", runs_5x, start_run=1003, data_dir=data_dir_5x)
    note = render_note(cat, today="2026-01-01")
    assert "before start_run" in note
    assert "`alignment`" in note
    assert "**S0-20C**: `1p`" in note


def test_note_flags_restarts_for_review(tmp_path: Path) -> None:
    runs = make_block(100, "S0", 5) + make_block(105, "S1", 5) + make_block(110, "S2", 10)
    data_dir = tmp_path / "autoreduce"
    write_arn(data_dir, [100, 101, 102, 103, 105, 106, 107, 108, *range(110, 119)])
    note = render_note(build_catalog("IPTS-1", runs, data_dir=data_dir))
    assert "Possible restarts" in note
    assert "kept 115-118" in note
    assert "dropped 110, 111, 112, 113, 114" in note


def test_note_says_so_when_the_data_dir_is_missing(runs_5x: list[FakeRun], tmp_path: Path) -> None:
    cat = build_catalog("IPTS-1", runs_5x, data_dir=tmp_path / "missing")
    assert "**not found**" in render_note(cat)


def test_note_ends_with_a_newline(runs_5x: list[FakeRun], data_dir_5x: Path) -> None:
    note = render_note(build_catalog("IPTS-1", runs_5x, data_dir=data_dir_5x))
    assert note.endswith("\n")
    assert not note.endswith("\n\n")


# ---------------------------------------------------------------------------
# Output files
# ---------------------------------------------------------------------------


def test_output_paths_are_named_after_the_ipts(tmp_path: Path) -> None:
    csv_path, note_path = output_paths("37679", tmp_path)
    assert csv_path == tmp_path / "IPTS-37679_setup.csv"
    assert note_path == tmp_path / "IPTS-37679_NOTE.md"


def test_write_outputs_creates_both_files(
    tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    cat = build_catalog("IPTS-1", runs_5x, start_run=1003, data_dir=data_dir_5x)
    out = tmp_path / "work"
    csv_path, note_path = write_outputs(cat, *output_paths(cat, out), today="2026-01-01")
    assert csv_path.is_file()
    assert note_path.is_file()
    assert "b,emptyBanjo,1003,4,0.1" in csv_path.read_text(encoding="utf-8")
    assert "2026-01-01" in note_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Reduced-filename legend
# ---------------------------------------------------------------------------


def test_note_explains_the_output_filenames(runs_5x: list[FakeRun], data_dir_5x: Path) -> None:
    """The postfixes are the engine's and are easy to misread — spell them out."""
    cat = build_catalog("IPTS-1", runs_5x, start_run=1003, data_dir=data_dir_5x)
    note = render_note(cat, today="2026-01-01")

    assert "## What the reduced filenames mean" in note
    for name in (
        "UN_<name>_det_1_unscaled.txt",
        "UN_<name>_det_1.txt",
        "UN_<name>_det_1_lb.txt",
        "UN_<name>_det_1_background_subtracted.txt",
    ):
        assert name in note
    # The two facts that actually bite.
    assert "_lbs.txt" in note, "must connect the new name to the old one"
    assert "subtraction's *input*" in note
    assert "emptyBanjo" in note, "names the background that gets no subtracted file"


def test_note_legend_follows_the_logbin_setting(runs_5x: list[FakeRun], data_dir_5x: Path) -> None:
    cat = build_catalog("IPTS-1", runs_5x, start_run=1003, data_dir=data_dir_5x)

    with_lb = render_note(cat, today="2026-01-01", logbin=True)
    without = render_note(cat, today="2026-01-01", logbin=False)

    assert "_lb.txt" in with_lb
    assert "_det_1_lb.txt" not in without, "no -l means no _lb.txt is written"
    assert "interpolation" in without
    # Either way the final curve is the same filename.
    for note in (with_lb, without):
        assert "**Plot `UN_<name>_det_1_background_subtracted.txt`" in note


def test_write_outputs_threads_the_logbin_flag(
    tmp_path: Path, runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    cat = build_catalog("IPTS-1", runs_5x, start_run=1003, data_dir=data_dir_5x)
    _, note_path = write_outputs(cat, *output_paths(cat, tmp_path), logbin=False)
    assert "interpolation" in note_path.read_text(encoding="utf-8")


def test_note_legend_names_the_short_alias_when_enabled(
    runs_5x: list[FakeRun], data_dir_5x: Path
) -> None:
    cat = build_catalog("IPTS-1", runs_5x, start_run=1003, data_dir=data_dir_5x)
    with_alias = render_note(cat, today="2026-01-01", short_name_copy=True)
    without = render_note(cat, today="2026-01-01", short_name_copy=False)
    assert "UN_<name>_det_1_bsub.txt" in with_alias
    assert "identical contents" in with_alias
    assert "_bsub.txt" not in without


# ---------------------------------------------------------------------------
# IPTS-35306: 1.2 Å first runs, pause runs, t + b empty cell
# ---------------------------------------------------------------------------


def test_ipts_35306_shape_reproduces_the_verified_table(
    tmp_path: Path, runs_35306: list, data_dir_35306: Path
) -> None:
    from tests.usans.conftest import EXPECTED_35306

    cat = build_catalog("IPTS-35306", runs_35306, data_dir=data_dir_35306, thickness_cm=0.2)
    path = cat.table.to_csv(tmp_path / "setup.csv")
    data = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    assert data == EXPECTED_35306
    assert cat.restarts == [], "AO's 5 scans are an odd size, not a restart"


def test_ipts_35306_note_lists_every_left_out_run_with_its_reason(
    runs_35306: list, data_dir_35306: Path
) -> None:
    cat = build_catalog("IPTS-35306", runs_35306, data_dir=data_dir_35306)
    note = render_note(cat, today="2026-09-30")
    for run in (48219, 48226, 48234, 48241, 48249, 48256, 48263, 48270, 48277, 48284, 48291):
        assert f"  - {run}: off-wavelength — recorded at 1.2 Å (no _3.6 files)" in note, run
    assert "  - 48233: pause — no ARN scan files, monitor 10 counts" in note
    assert "  - 48248: pause" in note
    assert "Transmission runs" not in note
    assert "`t,Blank_T`" in note
    assert "Blocks with ≠ 6 scan runs" in note and "`AO Buffer` — 5 scans" in note
    assert "THICKNESS — CONFIRM BEFORE REDUCING" in note
    assert "sansdir's built-in default" in note


def test_off_wavelength_runs_can_be_kept(runs_35306: list, data_dir_35306: Path) -> None:
    cat = build_catalog(
        "IPTS-35306", runs_35306, data_dir=data_dir_35306, skip_off_wavelength=False
    )
    one = cat.table.find("#1")
    assert one is not None and (one.start_run, one.num_runs) == (48226, 7)
    note = render_note(cat, today="2026-09-30")
    assert "## ⚠ Runs kept but worth a look" in note
    assert "48226: off-wavelength" in note


def test_thickness_callout_names_a_configured_value(runs_5x: list, data_dir_5x: Path) -> None:
    cat = build_catalog("IPTS-1", runs_5x, data_dir=data_dir_5x, thickness_cm=0.2)
    note = render_note(cat, today="2026-01-01")
    assert "**0.2 cm**" in note and "`[usans].thickness_cm` setting" in note


def test_legend_explains_what_the_t_and_b_rows_do(runs_5x: list, data_dir_5x: Path) -> None:
    note = render_note(build_catalog("IPTS-1", runs_5x, data_dir=data_dir_5x), today="x")
    assert "| `b` only | **1** (no correction) | `b` | S - B |" in note
    assert "| `t` only | from the `t` row | `t` (the empty cell) | S/T - EC |" in note
    assert "`t` → `empty_cell`" in note
