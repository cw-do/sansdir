"""Tests for sansdir.usans.runner — engine lookup, staging, invocation.

The real ``reduceUSANS`` isn't available off-cluster, so most of these use
a stub script. :func:`test_reduce_smoke` runs the genuine engine and skips
when either the pixi env or the sample data is absent.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from sansdir.usans import runner
from sansdir.usans.runner import ReduceError

# A real IPTS on the ORNL cluster used by the opt-in smoke test.
SMOKE_DATA_DIR = Path("/SNS/USANS/IPTS-37679/shared/autoreduce")


def _stub_engine(tmp_path: Path, body: str) -> Path:
    """Write an executable stand-in for ``reduceUSANS`` and return its path."""
    script = tmp_path / "reduceUSANS"
    script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


# ---------------------------------------------------------------------------
# find_engine
# ---------------------------------------------------------------------------


def test_find_engine_prefers_an_explicit_command() -> None:
    assert runner.find_engine(command="my-reduce --flag") == ["my-reduce", "--flag"]


def test_find_engine_uses_the_pixi_console_script(tmp_path: Path) -> None:
    binary = tmp_path / ".pixi/envs/default/bin/reduceUSANS"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    assert runner.find_engine(pixi_manifest=str(tmp_path)) == [str(binary)]


def test_find_engine_raises_when_nothing_is_installed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda _name: None)
    with pytest.raises(ReduceError, match="not found"):
        runner.find_engine(pixi_manifest=str(tmp_path / "nowhere"))


def test_clean_env_disables_user_site_packages() -> None:
    env = runner.clean_env({"PYTHONPATH": "/home/u/lib", "PYTHONHOME": "/opt/py"})
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["PYTHONPATH"] == ""
    assert "PYTHONHOME" not in env


def test_build_command_puts_logbin_and_output_in_order(tmp_path: Path) -> None:
    argv = runner.build_command(
        tmp_path / "setup.csv", tmp_path / "out", logbin=True, command="reduceUSANS"
    )
    assert argv == ["reduceUSANS", "-l", "-o", str(tmp_path / "out"), str(tmp_path / "setup.csv")]


def test_build_command_omits_logbin_when_disabled(tmp_path: Path) -> None:
    argv = runner.build_command(
        tmp_path / "setup.csv", tmp_path / "out", logbin=False, command="reduceUSANS"
    )
    assert "-l" not in argv


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------


def test_stage_inputs_symlinks_the_data_and_copies_the_csv(tmp_path: Path) -> None:
    data_dir = tmp_path / "autoreduce"
    data_dir.mkdir()
    (data_dir / "USANS_100_monitor_scan_ARN.txt").write_text("data", encoding="utf-8")
    (data_dir / "subdir").mkdir()
    csv = tmp_path / "setup.csv"
    csv.write_text("b,E,100,4,0.1\n", encoding="utf-8")
    stage = tmp_path / "stage"

    staged = runner.stage_inputs(csv, data_dir, stage)

    assert staged == stage / "setup.csv"
    assert staged.read_text(encoding="utf-8") == "b,E,100,4,0.1\n"
    assert not staged.is_symlink(), "the CSV is copied, not linked"
    linked = stage / "USANS_100_monitor_scan_ARN.txt"
    assert linked.is_symlink()
    assert linked.read_text(encoding="utf-8") == "data"
    assert not (stage / "subdir").exists(), "directories are skipped"


def test_stage_inputs_never_writes_through_a_same_named_link(tmp_path: Path) -> None:
    """Regression: copying onto a symlink would edit the instrument's file."""
    data_dir = tmp_path / "autoreduce"
    data_dir.mkdir()
    original = data_dir / "setup.csv"
    original.write_text("ORIGINAL\n", encoding="utf-8")
    csv = tmp_path / "mine" / "setup.csv"
    csv.parent.mkdir()
    csv.write_text("MINE\n", encoding="utf-8")

    runner.stage_inputs(csv, data_dir, tmp_path / "stage")

    assert original.read_text(encoding="utf-8") == "ORIGINAL\n"


# ---------------------------------------------------------------------------
# reduce_csv
# ---------------------------------------------------------------------------


def test_reduce_csv_runs_the_engine_in_the_staging_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "autoreduce"
    data_dir.mkdir()
    (data_dir / "USANS_100_monitor_scan_ARN.txt").write_text("x", encoding="utf-8")
    csv = tmp_path / "setup.csv"
    csv.write_text("b,E,100,4,0.1\n", encoding="utf-8")
    out = tmp_path / "out"
    # The stub proves cwd holds both the staged CSV and the linked ARN file,
    # and writes one reduced curve so `produced` has something to find.
    engine = _stub_engine(
        tmp_path,
        "test -f setup.csv || exit 3\n"
        "test -f USANS_100_monitor_scan_ARN.txt || exit 4\n"
        'echo "$@" > "$3/UN_E_det_1_lb.txt"\n',
    )

    result = runner.reduce_csv(
        csv, data_dir=data_dir, output_dir=out, command=str(engine), logbin=True
    )

    assert result.ok, result.stderr
    assert result.returncode == 0
    assert [p.name for p in result.produced] == ["UN_E_det_1_lb.txt"]
    assert out.is_dir()


def test_reduce_csv_runs_in_place_when_the_csv_sits_in_the_data_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "autoreduce"
    data_dir.mkdir()
    csv = data_dir / "setup.csv"
    csv.write_text("b,E,100,4,0.1\n", encoding="utf-8")
    engine = _stub_engine(tmp_path, f'test "$(pwd)" = "{data_dir.resolve()}" || exit 5\n')

    result = runner.reduce_csv(
        csv, data_dir=data_dir, output_dir=tmp_path / "out", command=str(engine)
    )
    assert result.ok


def test_reduce_csv_reports_a_failing_engine(tmp_path: Path) -> None:
    data_dir = tmp_path / "autoreduce"
    data_dir.mkdir()
    csv = tmp_path / "setup.csv"
    csv.write_text("b,E,100,4,0.1\n", encoding="utf-8")
    engine = _stub_engine(tmp_path, 'echo "FileNotFoundError: boom" >&2\nexit 1\n')

    result = runner.reduce_csv(
        csv, data_dir=data_dir, output_dir=tmp_path / "out", command=str(engine)
    )
    assert not result.ok
    assert result.returncode == 1
    assert "FileNotFoundError" in result.tail()


def test_reduce_csv_cleans_up_its_staging_directory(tmp_path: Path) -> None:
    data_dir = tmp_path / "autoreduce"
    data_dir.mkdir()
    csv = tmp_path / "setup.csv"
    csv.write_text("b,E,100,4,0.1\n", encoding="utf-8")
    engine = _stub_engine(tmp_path, "exit 0\n")

    before = set(Path(os.environ.get("TMPDIR", "/tmp")).glob(f"{runner._STAGE_PREFIX}*"))
    runner.reduce_csv(csv, data_dir=data_dir, output_dir=tmp_path / "out", command=str(engine))
    after = set(Path(os.environ.get("TMPDIR", "/tmp")).glob(f"{runner._STAGE_PREFIX}*"))
    assert after == before


def test_reduce_csv_rejects_a_missing_csv(tmp_path: Path) -> None:
    data_dir = tmp_path / "autoreduce"
    data_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="setup CSV"):
        runner.reduce_csv(tmp_path / "nope.csv", data_dir=data_dir, output_dir=tmp_path / "out")


def test_reduce_csv_rejects_a_missing_data_dir(tmp_path: Path) -> None:
    csv = tmp_path / "setup.csv"
    csv.write_text("b,E,100,4,0.1\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="data directory"):
        runner.reduce_csv(csv, data_dir=tmp_path / "nope", output_dir=tmp_path / "out")


def test_reduce_csv_honours_a_timeout(tmp_path: Path) -> None:
    data_dir = tmp_path / "autoreduce"
    data_dir.mkdir()
    csv = tmp_path / "setup.csv"
    csv.write_text("b,E,100,4,0.1\n", encoding="utf-8")
    engine = _stub_engine(tmp_path, "sleep 5\n")
    with pytest.raises(ReduceError, match="timed out"):
        runner.reduce_csv(
            csv,
            data_dir=data_dir,
            output_dir=tmp_path / "out",
            command=str(engine),
            timeout=0.5,
        )


# ---------------------------------------------------------------------------
# Opt-in smoke test against the real engine + real data
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not SMOKE_DATA_DIR.is_dir(),
    reason="real USANS autoreduce data not present on this host",
)
def test_reduce_smoke(tmp_path: Path) -> None:
    """End-to-end: two rows through the genuine ``reduceUSANS``."""
    try:
        runner.find_engine()
    except ReduceError as exc:
        pytest.skip(str(exc))

    csv = tmp_path / "IPTS-37679_setup.csv"
    csv.write_text(
        "# USANS reduction table for IPTS-37679\n"
        "b,emptyBanjo-restart,49434,4,0.1\n"
        "s,S0-20C,49439,4,0.1\n",
        encoding="utf-8",
    )
    out = tmp_path / "output"
    result = runner.reduce_csv(csv, data_dir=SMOKE_DATA_DIR, output_dir=out, logbin=True)

    assert result.ok, result.tail(20)
    names = {p.name for p in result.produced}
    assert "UN_S0-20C_det_1_lb.txt" in names
    assert "UN_S0-20C_det_1_background_subtracted.txt" in names
