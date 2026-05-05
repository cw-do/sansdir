"""Tests for sansdir.core.history."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sansdir.core.history import CommandHistory, default_history_path


@pytest.fixture
def hist_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path))
    return default_history_path()


def test_default_path_uses_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path))
    assert default_history_path() == tmp_path / "cmd_history"


def test_default_path_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SANSDIR_CACHE_DIR", raising=False)
    p = default_history_path()
    assert p.parts[-2:] == ("sansdir", "cmd_history")


def test_append_persists_to_disk(hist_path: Path) -> None:
    h = CommandHistory(path=hist_path, load=False)
    h.append("cd /tmp")
    h.append("q")
    h2 = CommandHistory(path=hist_path)
    assert h2.entries() == ["cd /tmp", "q"]


def test_append_dedupes_consecutive(hist_path: Path) -> None:
    h = CommandHistory(path=hist_path, load=False)
    h.append("ls")
    h.append("ls")
    h.append("ls")
    h.append("q")
    h.append("ls")  # ok now — not consecutive with last "ls"
    assert h.entries() == ["ls", "q", "ls"]


def test_append_ignores_blank(hist_path: Path) -> None:
    h = CommandHistory(path=hist_path, load=False)
    h.append("")
    h.append("   ")
    assert h.entries() == []


def test_max_entries_caps_size(hist_path: Path) -> None:
    h = CommandHistory(path=hist_path, max_entries=3, load=False)
    for ln in ("a", "b", "c", "d", "e"):
        h.append(ln)
    assert h.entries() == ["c", "d", "e"]


def test_load_caps_at_max(hist_path: Path) -> None:
    hist_path.parent.mkdir(parents=True, exist_ok=True)
    hist_path.write_text("\n".join(str(i) for i in range(10)) + "\n", encoding="utf-8")
    h = CommandHistory(path=hist_path, max_entries=3)
    assert h.entries() == ["7", "8", "9"]


def test_load_missing_file_is_ok(hist_path: Path) -> None:
    h = CommandHistory(path=hist_path)
    assert h.entries() == []


def test_save_creates_parent_dir(tmp_path: Path) -> None:
    p = tmp_path / "deeply" / "nested" / "dir" / "history"
    h = CommandHistory(path=p, load=False)
    h.append("hello")
    assert p.exists()
    assert p.read_text(encoding="utf-8").strip() == "hello"


# ---------------------------------------------------------------------------
# Up / Down cursor
# ---------------------------------------------------------------------------


def test_previous_walks_back_from_most_recent(hist_path: Path) -> None:
    h = CommandHistory(path=hist_path, load=False)
    h.extend(["a", "b", "c"])
    assert h.previous("draft") == "c"
    assert h.previous("c") == "b"
    assert h.previous("b") == "a"
    # Bottom of history — stays put.
    assert h.previous("a") == "a"


def test_previous_with_empty_history_returns_current(hist_path: Path) -> None:
    h = CommandHistory(path=hist_path, load=False)
    assert h.previous("typing") == "typing"


def test_next_restores_draft_after_walking_off_top(hist_path: Path) -> None:
    h = CommandHistory(path=hist_path, load=False)
    h.extend(["a", "b", "c"])
    h.previous("my draft")  # cursor → c, draft = "my draft"
    h.previous("c")  # cursor → b
    assert h.next("b") == "c"  # forward → c
    assert h.next("c") == "my draft"  # past top → draft


def test_next_with_no_active_cursor_is_noop(hist_path: Path) -> None:
    h = CommandHistory(path=hist_path, load=False)
    h.extend(["a"])
    assert h.next("draft") == "draft"


def test_append_resets_cursor(hist_path: Path) -> None:
    h = CommandHistory(path=hist_path, load=False)
    h.extend(["a", "b"])
    h.previous("d")
    h.append("c")
    # Cursor reset, draft cleared. Up should now restore from "draft" again.
    assert h.previous("draft2") == "c"


def test_disk_persistence_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path))
    h = CommandHistory(path=default_history_path(), load=False)
    for ln in ("first", "second", "third"):
        h.append(ln)
    assert os.path.exists(default_history_path())
    h2 = CommandHistory(path=default_history_path())
    assert h2.entries() == ["first", "second", "third"]
