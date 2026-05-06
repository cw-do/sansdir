"""Tests for sansdir.core.mailer."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sansdir.core import mailer


@pytest.fixture(autouse=True)
def isolate_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))


# ---------------------------------------------------------------------------
# build_argv
# ---------------------------------------------------------------------------


def test_argv_basic_no_attachments() -> None:
    argv = mailer.build_argv(
        recipient="user@example.com",
        subject="hello",
    )
    assert argv == ["mail", "-s", "hello", "user@example.com"]


def test_argv_with_attachments_uses_dash_a() -> None:
    argv = mailer.build_argv(
        recipient="user@example.com",
        subject="hi",
        attachments=[Path("/tmp/a.txt"), Path("/tmp/b.txt")],
    )
    assert argv == [
        "mail",
        "-s",
        "hi",
        "-a",
        "/tmp/a.txt",
        "-a",
        "/tmp/b.txt",
        "user@example.com",
    ]


def test_argv_mutt_inserts_dash_dash_separator() -> None:
    argv = mailer.build_argv(
        recipient="user@example.com",
        subject="hi",
        attachments=[Path("/tmp/a.txt")],
        command="mutt",
    )
    assert argv == [
        "mutt",
        "-s",
        "hi",
        "-a",
        "/tmp/a.txt",
        "--",
        "user@example.com",
    ]


def test_argv_rejects_blank_recipient() -> None:
    with pytest.raises(ValueError):
        mailer.build_argv(recipient="", subject="x")


# ---------------------------------------------------------------------------
# send_mail (subprocess mocked)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_mail(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Replace shutil.which + subprocess.run with capturing fakes."""
    captured: dict = {"argv": None, "input": None, "raises": None}

    def fake_which(cmd: str) -> str:
        return f"/usr/bin/{cmd}"

    def fake_run(argv, input=None, capture_output=False, text=False, timeout=None, check=False):  # type: ignore[no-untyped-def]
        captured["argv"] = list(argv)
        captured["input"] = input
        if captured["raises"]:
            raise captured["raises"]
        return subprocess.CompletedProcess(
            args=argv, returncode=captured.get("returncode", 0), stdout="", stderr=""
        )

    monkeypatch.setattr(mailer.shutil, "which", fake_which)
    monkeypatch.setattr(mailer.subprocess, "run", fake_run)
    return captured


def test_send_mail_pipes_body(tmp_path: Path, fake_mail: dict) -> None:
    att = tmp_path / "data.txt"
    att.write_text("payload", encoding="utf-8")
    result = mailer.send_mail(
        recipient="dest@example.com",
        subject="re: test",
        attachments=[att],
        body="hello body",
    )
    assert result.ok
    assert fake_mail["input"] == "hello body"
    assert "-s" in fake_mail["argv"]
    assert "re: test" in fake_mail["argv"]
    assert str(att.resolve()) in fake_mail["argv"]
    assert fake_mail["argv"][-1] == "dest@example.com"


def test_send_mail_logs_on_success(tmp_path: Path, fake_mail: dict) -> None:
    att = tmp_path / "x"
    att.write_text("y", encoding="utf-8")
    mailer.send_mail(recipient="a@b", subject="s", attachments=[att])
    log = (tmp_path / "cache" / "history.log").read_text(encoding="utf-8")
    assert "mail" in log
    assert "a@b" in log


def test_send_mail_returns_failure_code(tmp_path: Path, fake_mail: dict) -> None:
    fake_mail["returncode"] = 67
    result = mailer.send_mail(recipient="a@b", subject="s")
    assert not result.ok
    assert result.returncode == 67


def test_send_mail_handles_timeout(tmp_path: Path, fake_mail: dict) -> None:
    fake_mail["raises"] = subprocess.TimeoutExpired(cmd="mail", timeout=1)
    result = mailer.send_mail(recipient="a@b", subject="s", timeout=1)
    assert result.returncode == 124
    assert "timeout" in result.stderr


def test_send_mail_missing_attachment_raises(tmp_path: Path, fake_mail: dict) -> None:
    with pytest.raises(FileNotFoundError):
        mailer.send_mail(
            recipient="a@b",
            subject="s",
            attachments=[tmp_path / "ghost"],
        )


def test_send_mail_missing_command_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mailer.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="not found"):
        mailer.send_mail(recipient="a@b", subject="s")
