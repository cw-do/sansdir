"""Tests for sansdir.core.filesystem."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sansdir.core.filesystem import (
    VALID_SORT_KEYS,
    FileEntry,
    cycle_sort_key,
    format_size,
    list_dir,
    sort_entries,
)


def _make_tree(root: Path) -> None:
    (root / "alpha").mkdir()
    (root / "beta").mkdir()
    (root / "data.dat").write_text("a b c\n", encoding="utf-8")
    (root / "report.txt").write_text("hello\n", encoding="utf-8")
    (root / "EQSANS_1.nxs.h5").write_bytes(b"\x00" * 4096)
    (root / ".hidden").write_text("x", encoding="utf-8")


# ---------------------------------------------------------------------------
# list_dir
# ---------------------------------------------------------------------------


def test_list_dir_skips_hidden_by_default(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    names = [e.name for e in list_dir(tmp_path)]
    assert ".hidden" not in names
    assert "alpha" in names and "data.dat" in names


def test_list_dir_includes_hidden_when_asked(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    names = [e.name for e in list_dir(tmp_path, show_hidden=True)]
    assert ".hidden" in names


def test_list_dir_pins_parent_at_top(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    entries = list_dir(tmp_path)
    assert entries[0].name == ".."
    assert entries[0].is_parent


def test_list_dir_omits_parent_when_requested(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    entries = list_dir(tmp_path, include_parent=False)
    assert all(e.name != ".." for e in entries)


def test_list_dir_groups_dirs_before_files(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    entries = [e for e in list_dir(tmp_path) if not e.is_parent]
    # All dirs should come before any file.
    saw_file = False
    for e in entries:
        if not e.is_dir:
            saw_file = True
        else:
            assert not saw_file, f"dir {e.name!r} appears after a file"


def test_list_dir_rejects_unknown_sort_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown sort_key"):
        list_dir(tmp_path, sort_key="bogus")


def test_list_dir_perf_under_100ms(tmp_path: Path) -> None:
    """Per PLANNING.md §10 — 1000-file dir must list in <100 ms."""
    for i in range(1000):
        (tmp_path / f"f_{i:04d}.dat").write_bytes(b"")
    start = time.perf_counter()
    entries = list_dir(tmp_path)
    elapsed = time.perf_counter() - start
    assert len(entries) >= 1000
    assert elapsed < 0.1, f"list_dir took {elapsed * 1000:.1f} ms (budget 100 ms)"


# ---------------------------------------------------------------------------
# sort_entries
# ---------------------------------------------------------------------------


def _make_entries() -> list[FileEntry]:
    return [
        FileEntry(Path("/x/a.txt"), "a.txt", False, False, 100, 100.0),
        FileEntry(Path("/x/B.dat"), "B.dat", False, False, 50, 200.0),
        FileEntry(Path("/x/c.h5"), "c.h5", False, False, 999, 50.0),
        FileEntry(Path("/x/dir1"), "dir1", True, False, 0, 10.0),
        FileEntry(Path("/x/.."), "..", True, False, 0, 0.0),
    ]


def test_sort_by_name_case_insensitive() -> None:
    out = sort_entries(_make_entries(), sort_key="name")
    assert [e.name for e in out] == ["..", "dir1", "a.txt", "B.dat", "c.h5"]


def test_sort_by_size() -> None:
    out = sort_entries(_make_entries(), sort_key="size")
    file_names = [e.name for e in out if not e.is_dir]
    assert file_names == ["B.dat", "a.txt", "c.h5"]


def test_sort_by_mtime() -> None:
    out = sort_entries(_make_entries(), sort_key="mtime")
    file_names = [e.name for e in out if not e.is_dir]
    assert file_names == ["c.h5", "a.txt", "B.dat"]


def test_sort_reverse() -> None:
    out = sort_entries(_make_entries(), sort_key="name", reverse=True)
    file_names = [e.name for e in out if not e.is_dir]
    assert file_names == ["c.h5", "B.dat", "a.txt"]


def test_sort_ext_groups_compound_suffixes() -> None:
    entries = [
        FileEntry(Path("/x/a.txt"), "a.txt", False, False, 0, 0.0),
        FileEntry(Path("/x/b.dat"), "b.dat", False, False, 0, 0.0),
        FileEntry(Path("/x/c.nxs.h5"), "c.nxs.h5", False, False, 0, 0.0),
        FileEntry(Path("/x/d.h5"), "d.h5", False, False, 0, 0.0),
    ]
    out = [e.name for e in sort_entries(entries, sort_key="ext")]
    # nxs.h5 stays distinct from h5 (compound-extension awareness).
    assert out == ["b.dat", "d.h5", "c.nxs.h5", "a.txt"]


# ---------------------------------------------------------------------------
# misc helpers
# ---------------------------------------------------------------------------


def test_cycle_sort_key_wraps() -> None:
    chain: list[str] = []
    cur = VALID_SORT_KEYS[0]
    for _ in range(len(VALID_SORT_KEYS) + 1):
        chain.append(cur)
        cur = cycle_sort_key(cur)
    assert chain[0] == chain[-1] == VALID_SORT_KEYS[0]
    assert set(chain[:-1]) == set(VALID_SORT_KEYS)


def test_cycle_sort_key_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        cycle_sort_key("nope")


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (0, "0 B"),
        (1023, "1023 B"),
        (1024, "1.0 KB"),
        (12_300, "12.0 KB"),
        (1_500_000, "1.4 MB"),
        (3_400_000_000, "3.2 GB"),
    ],
)
def test_format_size(n: int, expected: str) -> None:
    assert format_size(n) == expected
