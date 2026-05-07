"""Tests for ``sansdir.hdf.batch`` — parallel metadata extraction."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from sansdir.hdf import batch

# ---------------------------------------------------------------------------
# Fixture helpers — make several synthetic NeXus files that share keys.
# ---------------------------------------------------------------------------


def _write_nexus(
    path: Path,
    *,
    temperature_mean: float,
    shear_mean: float,
    duration: float,
    n_samples: int = 10,
    seed: int = 0,
) -> None:
    """Three keys that the batch tests exercise: temperature, shear, duration."""
    import h5py

    rng = np.random.default_rng(seed=seed)
    with h5py.File(path, "w") as fh:
        entry = fh.create_group("entry")
        entry.create_dataset("duration", data=np.float64(duration))
        daslogs = entry.create_group("DASlogs")
        for name, mean in (("temperature", temperature_mean), ("shear", shear_mean)):
            grp = daslogs.create_group(name)
            grp.create_dataset(
                "value",
                data=rng.normal(loc=mean, scale=0.1, size=n_samples).astype("float64"),
            )
            grp.create_dataset("time", data=np.linspace(0.0, 600.0, n_samples))


@pytest.fixture
def three_files(tmp_path: Path) -> list[Path]:
    """Three synthetic files with deterministic, distinguishable means."""
    paths = []
    for i, (temp, shear) in enumerate(
        [(298.0, 1.0), (300.0, 2.0), (302.0, 3.0)],
        start=1,
    ):
        p = tmp_path / f"EQSANS_{i:03d}.nxs.h5"
        _write_nexus(p, temperature_mean=temp, shear_mean=shear, duration=600 * i, seed=i)
        paths.append(p)
    return paths


# ---------------------------------------------------------------------------
# extract_one
# ---------------------------------------------------------------------------


def test_extract_one_returns_each_key(three_files: list[Path]) -> None:
    keys = ["/entry/DASlogs/temperature/value", "/entry/duration"]
    row = batch.extract_one(three_files[0], keys)
    assert row.error is None
    assert set(row.values.keys()) == set(keys)
    assert row.values["/entry/duration"].value == pytest.approx(600.0)
    # Time series → mean ≈ true mean ± noise.
    assert abs(row.values["/entry/DASlogs/temperature/value"].value - 298.0) < 0.5
    assert row.values["/entry/DASlogs/temperature/value"].n_points == 10
    assert row.values["/entry/DASlogs/temperature/value"].stdev is not None


def test_extract_one_blanks_missing_key(three_files: list[Path]) -> None:
    """Missing key → ``values[key] = None``; the file is still readable."""
    row = batch.extract_one(three_files[0], ["/entry/duration", "/entry/DASlogs/nope/value"])
    assert row.error is None
    assert row.values["/entry/duration"] is not None
    assert row.values["/entry/DASlogs/nope/value"] is None


def test_extract_one_unreadable_file_sets_error(tmp_path: Path) -> None:
    """A missing file becomes ``Row.error``, not an exception."""
    row = batch.extract_one(tmp_path / "does-not-exist.nxs.h5", ["/entry/duration"])
    assert row.error is not None
    assert row.values == {}


# ---------------------------------------------------------------------------
# extract_many
# ---------------------------------------------------------------------------


def test_extract_many_preserves_input_order(three_files: list[Path]) -> None:
    rows = batch.extract_many(three_files, ["/entry/duration"], max_workers=4)
    # Even with parallel execution, output order matches input order.
    assert [r.path.name for r in rows] == [p.name for p in three_files]
    durations = [r.values["/entry/duration"].value for r in rows]
    assert durations == pytest.approx([600.0, 1200.0, 1800.0])


def test_extract_many_progress_callback_fires_per_file(three_files: list[Path]) -> None:
    seen: list[tuple[int, int]] = []
    batch.extract_many(
        three_files,
        ["/entry/duration"],
        progress_cb=lambda done, total: seen.append((done, total)),
    )
    # Each file generates one callback; all report the same total.
    assert [s[1] for s in seen] == [3, 3, 3]
    assert {s[0] for s in seen} == {1, 2, 3}


def test_extract_many_empty_input_returns_empty_list() -> None:
    assert batch.extract_many([], ["/entry/duration"]) == []


# ---------------------------------------------------------------------------
# write_table — formats
# ---------------------------------------------------------------------------


def test_write_table_tsv_round_trip(three_files: list[Path], tmp_path: Path) -> None:
    keys = ["/entry/DASlogs/temperature/value", "/entry/duration"]
    rows = batch.extract_many(three_files, keys)
    out = tmp_path / "out.tsv"
    written = batch.write_table(rows, keys, out, fmt="tsv")
    assert written == out
    with out.open(newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        header, *body = list(reader)
    # Column headers are the *short* names of each key.
    assert header == ["filename", "temperature", "duration"]
    assert len(body) == 3
    # Values reflect the means we wrote (within the per-sample noise band).
    means = [float(r[1]) for r in body]
    assert means == pytest.approx([298.0, 300.0, 302.0], abs=0.5)


def test_write_table_csv_uses_commas(three_files: list[Path], tmp_path: Path) -> None:
    keys = ["/entry/duration"]
    rows = batch.extract_many(three_files, keys)
    out = tmp_path / "out.csv"
    batch.write_table(rows, keys, out, fmt="csv")
    text = out.read_text()
    assert text.startswith("filename,duration\n")
    assert "EQSANS_001.nxs.h5,600\n" in text


def test_write_table_columns_aligns_to_widest_cell(three_files: list[Path], tmp_path: Path) -> None:
    keys = ["/entry/duration"]
    rows = batch.extract_many(three_files, keys)
    out = tmp_path / "out.txt"
    batch.write_table(rows, keys, out, fmt="columns")
    lines = out.read_text().splitlines()
    # All lines share the same width (right-padded).
    widths = {len(line) for line in lines if line}
    assert len(widths) == 1


def test_write_table_with_stats_emits_stdev_and_n_columns(
    three_files: list[Path], tmp_path: Path
) -> None:
    keys = ["/entry/DASlogs/temperature/value"]
    rows = batch.extract_many(three_files, keys)
    out = tmp_path / "out.tsv"
    batch.write_table(rows, keys, out, fmt="tsv", with_stats=True)
    with out.open(newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        header, *body = list(reader)
    assert header == ["filename", "temperature", "temperature_stdev", "temperature_n"]
    # Time-series stdev ~ 0.1 (the seed); non-empty.
    stdevs = [float(r[2]) for r in body]
    assert all(0.0 < s < 1.0 for s in stdevs)
    assert {r[3] for r in body} == {"10"}


def test_write_table_skips_unreadable_files(tmp_path: Path) -> None:
    bogus = tmp_path / "does-not-exist.nxs.h5"
    rows = batch.extract_many([bogus], ["/entry/duration"])
    out = tmp_path / "out.tsv"
    batch.write_table(rows, ["/entry/duration"], out, fmt="tsv")
    # Header only — the unreadable file row is dropped.
    assert out.read_text().splitlines() == ["filename\tduration"]


def test_write_table_unknown_format_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown fmt"):
        batch.write_table([], [], tmp_path / "x.tsv", fmt="xml")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# extract_to_file — one-shot
# ---------------------------------------------------------------------------


def test_extract_to_file_default_path_uses_timestamp(
    three_files: list[Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    written = batch.extract_to_file(three_files, ["/entry/duration"])
    assert written.parent == tmp_path
    assert written.name.startswith("extracted_")
    assert written.suffix == ".tsv"


def test_extract_to_file_writes_explicit_path(three_files: list[Path], tmp_path: Path) -> None:
    out = tmp_path / "sub/results.csv"
    written = batch.extract_to_file(three_files, ["/entry/duration"], out_path=out, fmt="csv")
    assert written == out
    assert out.exists()


# ---------------------------------------------------------------------------
# Per-file mode — <filename> placeholder triggers full-array output
# ---------------------------------------------------------------------------


def test_extract_to_file_per_file_mode_writes_one_csv_per_input(
    three_files: list[Path], tmp_path: Path
) -> None:
    """``<filename>`` in the path → one output per input, full arrays."""
    out_template = tmp_path / "<filename>_temp.csv"
    result = batch.extract_to_file(
        three_files,
        ["/entry/DASlogs/temperature/time", "/entry/DASlogs/temperature/value"],
        out_path=out_template,
        fmt="csv",
    )
    assert isinstance(result, list)
    assert len(result) == 3
    # Each output is named after its input's stem.
    assert {p.name for p in result} == {
        "EQSANS_001_temp.csv",
        "EQSANS_002_temp.csv",
        "EQSANS_003_temp.csv",
    }
    # Each file holds the *full* 10-sample arrays — header + 10 rows.
    with result[0].open(newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["time", "temperature"]
    assert len(rows) == 11  # header + 10 samples


def test_per_file_mode_broadcasts_scalars_across_array_rows(
    three_files: list[Path], tmp_path: Path
) -> None:
    """A scalar key (``/entry/duration``) is repeated on every array row."""
    out_template = tmp_path / "<filename>_mix.tsv"
    result = batch.extract_per_file(
        three_files,
        ["/entry/duration", "/entry/DASlogs/temperature/value"],
        out_template,
        fmt="tsv",
    )
    assert len(result) == 3
    with result[0].open(newline="") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    assert rows[0] == ["duration", "temperature"]
    body = rows[1:]
    assert len(body) == 10
    durations = {r[0] for r in body}
    assert len(durations) == 1
    assert float(next(iter(durations))) == pytest.approx(600.0)


def test_per_file_mode_filename_strips_double_suffix(tmp_path: Path) -> None:
    """``EQSANS_172749.nxs.h5`` → ``<filename>`` resolves to ``EQSANS_172749``."""
    f = tmp_path / "EQSANS_172749.nxs.h5"
    _write_nexus(f, temperature_mean=300.0, shear_mean=1.0, duration=600.0)
    result = batch.extract_per_file(
        [f], ["/entry/duration"], tmp_path / "<filename>_x.csv"
    )
    assert result[0].name == "EQSANS_172749_x.csv"


def test_per_file_requires_template_placeholder(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="<filename>"):
        batch.extract_per_file([tmp_path / "x.nxs.h5"], ["/k"], tmp_path / "no-tpl.csv")


def test_per_file_skips_unreadable_files(tmp_path: Path) -> None:
    bogus = tmp_path / "missing.nxs.h5"
    out = batch.extract_per_file([bogus], ["/entry/duration"], tmp_path / "<filename>.csv")
    assert out == []


# ---------------------------------------------------------------------------
# suggest_keys
# ---------------------------------------------------------------------------


def test_suggest_keys_lists_daslogs_value_paths(synthetic_nexus: Path) -> None:
    keys = batch.suggest_keys(synthetic_nexus)
    # synthetic_nexus has DASlogs/temperature, DASlogs/shear.
    assert "/entry/DASlogs/temperature/value" in keys
    assert "/entry/DASlogs/shear/value" in keys
    assert keys == sorted(keys)  # deterministic order for the dialog


def test_suggest_keys_missing_prefix_returns_empty(tmp_path: Path) -> None:
    import h5py

    f = tmp_path / "no-daslogs.nxs.h5"
    with h5py.File(f, "w") as fh:
        fh.create_group("entry")
    assert batch.suggest_keys(f) == []


def test_suggest_keys_unreadable_file_returns_empty(tmp_path: Path) -> None:
    assert batch.suggest_keys(tmp_path / "missing.nxs.h5") == []


# ---------------------------------------------------------------------------
# Header naming — short keys for DASlogs and basenames otherwise
# ---------------------------------------------------------------------------


def test_short_key_strips_value_suffix() -> None:
    assert batch._short_key("/entry/DASlogs/temperature/value") == "temperature"
    assert batch._short_key("entry/DASlogs/temperature") == "temperature"


def test_short_key_falls_back_to_basename() -> None:
    assert batch._short_key("/entry/duration") == "duration"
    assert batch._short_key("foo") == "foo"


# ---------------------------------------------------------------------------
# CLI subcommand — sansdir extract
# ---------------------------------------------------------------------------


def test_cli_extract_writes_table(three_files: list[Path], tmp_path: Path) -> None:
    """``sansdir extract -k ... FILES...`` produces a usable TSV."""
    from click.testing import CliRunner

    from sansdir.cli import main

    out = tmp_path / "cli-out.tsv"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "extract",
            "-k",
            "/entry/duration",
            "-k",
            "/entry/DASlogs/temperature/value",
            "--out",
            str(out),
            *(str(p) for p in three_files),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    with out.open(newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        header, *body = list(reader)
    assert header == ["filename", "duration", "temperature"]
    assert len(body) == 3


def test_cli_extract_with_stats_adds_stdev_and_n_columns(
    three_files: list[Path], tmp_path: Path
) -> None:
    from click.testing import CliRunner

    from sansdir.cli import main

    out = tmp_path / "stats.tsv"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "extract",
            "-k",
            "/entry/DASlogs/temperature/value",
            "--with-stats",
            "--out",
            str(out),
            *(str(p) for p in three_files),
        ],
    )
    assert result.exit_code == 0, result.output
    with out.open(newline="") as fh:
        header, *_ = list(csv.reader(fh, delimiter="\t"))
    assert header == ["filename", "temperature", "temperature_stdev", "temperature_n"]


# ---------------------------------------------------------------------------
# DoD: 100 files end-to-end
# ---------------------------------------------------------------------------


def test_dod_100_files_under_10s(tmp_path: Path) -> None:
    """Phase 8 DoD: 100 files x 3 keys -> TSV in <10 s."""
    import time

    files: list[Path] = []
    for i in range(100):
        p = tmp_path / f"EQSANS_{i:04d}.nxs.h5"
        _write_nexus(p, temperature_mean=298 + i * 0.1, shear_mean=1.0, duration=600.0, seed=i)
        files.append(p)
    out = tmp_path / "extracted.tsv"
    keys = [
        "/entry/DASlogs/temperature/value",
        "/entry/DASlogs/shear/value",
        "/entry/duration",
    ]
    t0 = time.perf_counter()
    written = batch.extract_to_file(files, keys, out_path=out, fmt="tsv")
    dt = time.perf_counter() - t0
    assert dt < 10.0, f"100 files / 3 keys took {dt:.2f}s — over the 10 s budget"
    assert written == out
    with out.open(newline="") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    # 1 header + 100 data rows.
    assert len(rows) == 101
