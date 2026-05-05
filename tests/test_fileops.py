"""Tests for sansdir.core.fileops.

Send-to-trash is monkeypatched onto an in-tmp_path "trash" directory so
the test suite never touches the user's real trash bin.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sansdir.core import fileops


@pytest.fixture(autouse=True)
def isolate_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect history.log into the tmp_path of every test."""
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))


# ---------------------------------------------------------------------------
# make_dir
# ---------------------------------------------------------------------------


def test_make_dir_creates(tmp_path: Path) -> None:
    out = fileops.make_dir(tmp_path, "newdir")
    assert out.is_dir()
    assert out == (tmp_path / "newdir").resolve()


def test_make_dir_refuses_overwrite(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    with pytest.raises(FileExistsError):
        fileops.make_dir(tmp_path, "x")


def test_make_dir_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="refusing to create outside"):
        fileops.make_dir(tmp_path, "../escape")


def test_make_dir_rejects_blank(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        fileops.make_dir(tmp_path, "")
    with pytest.raises(ValueError):
        fileops.make_dir(tmp_path, ".")
    with pytest.raises(ValueError):
        fileops.make_dir(tmp_path, "..")


def test_make_dir_supports_nested(tmp_path: Path) -> None:
    out = fileops.make_dir(tmp_path, "a/b/c")
    assert out.is_dir()


# ---------------------------------------------------------------------------
# copy_paths
# ---------------------------------------------------------------------------


def test_copy_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")
    (src / "b.txt").write_text("world", encoding="utf-8")
    out = fileops.copy_paths([src / "a.txt", src / "b.txt"], dst)
    assert {p.name for p in out} == {"a.txt", "b.txt"}
    assert (dst / "a.txt").read_text(encoding="utf-8") == "hello"
    # Source untouched.
    assert (src / "a.txt").exists()


def test_copy_directory_recursively(tmp_path: Path) -> None:
    src = tmp_path / "src"
    sub = src / "sub"
    sub.mkdir(parents=True)
    (sub / "leaf.txt").write_text("z", encoding="utf-8")
    dst = tmp_path / "dst"
    dst.mkdir()
    fileops.copy_paths([src], dst)
    assert (dst / "src" / "sub" / "leaf.txt").read_text(encoding="utf-8") == "z"


def test_copy_refuses_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("1", encoding="utf-8")
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "a.txt").write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError):
        fileops.copy_paths([src], dst)


def test_copy_rejects_non_directory_dst(tmp_path: Path) -> None:
    src = tmp_path / "a"
    src.write_text("1", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        fileops.copy_paths([src], tmp_path / "nope")


# ---------------------------------------------------------------------------
# move_paths
# ---------------------------------------------------------------------------


def test_move_files_into_dir(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    dst = tmp_path / "dst"
    src_dir.mkdir()
    dst.mkdir()
    (src_dir / "a.txt").write_text("hi", encoding="utf-8")
    fileops.move_paths([src_dir / "a.txt"], dst)
    assert (dst / "a.txt").exists()
    assert not (src_dir / "a.txt").exists()


def test_move_single_to_nonexistent_is_rename(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("hi", encoding="utf-8")
    new = tmp_path / "renamed.txt"
    fileops.move_paths([src], new)
    assert new.exists()
    assert not src.exists()


def test_move_refuses_overwrite_in_dir(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("1", encoding="utf-8")
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "a.txt").write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError):
        fileops.move_paths([src], dst)


# ---------------------------------------------------------------------------
# delete_paths
# ---------------------------------------------------------------------------


def test_delete_paths_no_trash(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    a.write_text("x", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "leaf").write_text("y", encoding="utf-8")
    out = fileops.delete_paths([a, sub], trash=False)
    assert set(out) == {a, sub}
    assert not a.exists()
    assert not sub.exists()


def test_delete_paths_via_trash_uses_send2trash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[str] = []

    def fake_send2trash(path: str) -> None:
        captured.append(path)
        Path(path).unlink()

    import sys
    import types

    fake_mod = types.ModuleType("send2trash")
    fake_mod.send2trash = fake_send2trash  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "send2trash", fake_mod)

    a = tmp_path / "a"
    a.write_text("x", encoding="utf-8")
    fileops.delete_paths([a], trash=True)
    assert captured == [str(a)]


def test_delete_paths_swallows_per_file_errors(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    a.write_text("x", encoding="utf-8")
    missing = tmp_path / "does-not-exist"
    out = fileops.delete_paths([a, missing], trash=False)
    assert a not in (p for p in [tmp_path / "a.txt"] if p.exists())
    assert out == [a]


# ---------------------------------------------------------------------------
# history log
# ---------------------------------------------------------------------------


def test_destructive_ops_log(tmp_path: Path) -> None:
    fileops.make_dir(tmp_path, "x")
    log = fileops.history_log_path()
    assert log.exists()
    content = log.read_text(encoding="utf-8")
    assert "mkdir" in content
    assert "/x" in content
