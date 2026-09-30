"""Tests for sansdir.core.editor — the F4 editor command line."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from sansdir.core.editor import VI_KEYS_HELP, default_editor, editor_command


def test_default_editor_honours_editor_then_visual(monkeypatch) -> None:
    monkeypatch.setenv("EDITOR", "nano")
    monkeypatch.setenv("VISUAL", "emacs")
    assert default_editor() == "nano"
    monkeypatch.delenv("EDITOR")
    assert default_editor() == "emacs"


def test_default_editor_prefers_full_vim(monkeypatch) -> None:
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/vim" if name == "vim" else None)
    assert default_editor() == "vim"
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert default_editor() == "vi"


def test_vi_family_gets_the_edit_mode_banner(tmp_path: Path) -> None:
    argv = shlex.split(editor_command(tmp_path / "setup.csv", "/usr/bin/vim"))
    assert argv[0] == "/usr/bin/vim"
    assert argv[-1] == str(tmp_path / "setup.csv")
    script = " ".join(argv[1:-1])
    assert "EDIT MODE" in script and "setup.csv in vim" in script
    assert VI_KEYS_HELP in script
    assert ":q!" in script


def test_other_editors_are_launched_unchanged(tmp_path: Path) -> None:
    target = tmp_path / "a b.txt"
    assert shlex.split(editor_command(target, "nano -m")) == ["nano", "-m", str(target)]


def test_awkward_filenames_cannot_break_the_vimscript(tmp_path: Path) -> None:
    """A quote or ``|`` in the name must not end the string or split the command."""
    target = tmp_path / "it's|100%.csv"
    argv = shlex.split(editor_command(target, "vim"))
    assert argv[-1] == str(target)
    script = argv[-2]
    assert "it''s¦100%%.csv" in script
    # Only the four separators between the -c sub-commands.
    assert script.count("|") == 4


@pytest.mark.skipif(shutil.which("vim") is None, reason="vim not installed")
def test_real_vim_accepts_the_banner_commands(tmp_path: Path) -> None:
    target = tmp_path / "it's|100%.csv"
    target.write_text("a,b\n")
    dump = tmp_path / "dump.txt"
    argv = shlex.split(editor_command(target, "vim"))
    argv[0:1] = ["vim", "-es", "-N", "-u", "NONE"]
    argv[-1:-1] = [
        "-c",
        f"redir! > {dump} | echo &statusline | echo 'ERR<' . v:errmsg . '>' | redir END",
        "-c",
        "qa!",
    ]
    subprocess.run(argv, check=True, timeout=20)
    text = dump.read_text()
    assert VI_KEYS_HELP in text
    assert "ERR<>" in text, text
