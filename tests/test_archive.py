"""Tests for sansdir.core.archive."""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

import pytest

from sansdir.core.archive import make_tar_gz, make_zip


@pytest.fixture(autouse=True)
def isolate_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# make_zip
# ---------------------------------------------------------------------------


def test_zip_two_files(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.txt", "alpha")
    b = _write(tmp_path / "b.txt", "beta")
    out = make_zip([a, b], tmp_path / "out.zip")
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        assert sorted(zf.namelist()) == ["a.txt", "b.txt"]
        assert zf.read("a.txt").decode() == "alpha"


def test_zip_includes_directory_recursively(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "deep" / "leaf.txt", "x")
    _write(tmp_path / "src" / "top.txt", "y")
    out = make_zip([tmp_path / "src"], tmp_path / "src.zip")
    with zipfile.ZipFile(out) as zf:
        names = sorted(zf.namelist())
    assert names == ["src/deep/leaf.txt", "src/top.txt"]


def test_zip_progress_callback(tmp_path: Path) -> None:
    files = [_write(tmp_path / f"f{i}.txt", str(i)) for i in range(3)]
    seen: list[tuple[int, int]] = []
    make_zip(files, tmp_path / "p.zip", on_progress=lambda i, n: seen.append((i, n)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_zip_refuses_to_overwrite(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.txt", "x")
    out = tmp_path / "x.zip"
    out.write_bytes(b"already here")
    with pytest.raises(FileExistsError):
        make_zip([a], out)


def test_zip_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        make_zip([tmp_path / "ghost"], tmp_path / "x.zip")


def test_zip_rejects_empty_srcs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no source"):
        make_zip([], tmp_path / "x.zip")


# ---------------------------------------------------------------------------
# make_tar_gz
# ---------------------------------------------------------------------------


def test_tar_gz_round_trip(tmp_path: Path) -> None:
    a = _write(tmp_path / "src" / "a.txt", "alpha")
    b = _write(tmp_path / "src" / "b.txt", "beta")
    out = make_tar_gz([a, b], tmp_path / "out.tar.gz")
    assert out.exists()
    with tarfile.open(out, "r:gz") as tf:
        assert sorted(m.name for m in tf.getmembers()) == ["a.txt", "b.txt"]
        member = tf.getmember("a.txt")
        with tf.extractfile(member) as fh:  # type: ignore[union-attr]
            assert fh.read().decode() == "alpha"


def test_tar_gz_includes_directory(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "deep" / "leaf.txt", "x")
    _write(tmp_path / "src" / "top.txt", "y")
    out = make_tar_gz([tmp_path / "src"], tmp_path / "src.tar.gz")
    with tarfile.open(out, "r:gz") as tf:
        names = sorted(m.name for m in tf.getmembers())
    assert "src/deep/leaf.txt" in names
    assert "src/top.txt" in names


def test_tar_gz_refuses_to_overwrite(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.txt", "x")
    out = tmp_path / "x.tar.gz"
    out.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        make_tar_gz([a], out)


# ---------------------------------------------------------------------------
# history log
# ---------------------------------------------------------------------------


def test_zip_writes_history_log(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.txt", "x")
    out = make_zip([a], tmp_path / "z.zip")
    log = (tmp_path / "cache" / "history.log").read_text(encoding="utf-8")
    assert "zip" in log
    assert str(out) in log
