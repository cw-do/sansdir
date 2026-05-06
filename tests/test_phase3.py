"""End-to-end tests for the Phase-3 ``z`` (zip) and ``e`` (mail) flows."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

from sansdir.app import SansdirApp
from sansdir.core.history import CommandHistory


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "no-config.toml"))


def _scratch(tmp_path: Path) -> tuple[Path, Path]:
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    (left / "a.dat").write_text("aa", encoding="utf-8")
    (left / "b.dat").write_text("bb", encoding="utf-8")
    (left / "c.dat").write_text("cc", encoding="utf-8")
    return left, right


def _real_app(tmp_path: Path) -> SansdirApp:
    left, right = _scratch(tmp_path)
    history = CommandHistory(path=tmp_path / "hist", load=False)
    return SansdirApp(start_path=left, right_path=right, history=history)


# ---------------------------------------------------------------------------
# z — zip
# ---------------------------------------------------------------------------


async def test_z_zips_tagged_into_inactive_pane(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Tag every .dat file via tag-glob.
        await pilot.press("+")
        for ch in "*.dat":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.active_panel.tags) == 3
        # `z` opens the prompt with a default name — accept it.
        await pilot.press("z")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        # Default name is `<active-cwd-basename>.zip` → "L.zip".
        out = app.inactive_panel.cwd / "L.zip"
        assert out.exists(), f"expected zip at {out}"
        with zipfile.ZipFile(out) as zf:
            assert sorted(zf.namelist()) == ["a.dat", "b.dat", "c.dat"]
        await pilot.press("q")


async def test_z_with_no_selection_notifies(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Cursor on '..' — no selection.
        await pilot.press("z")
        await pilot.pause()
        # No prompt should appear; right pane unchanged.
        right_files = list(app.inactive_panel.cwd.iterdir())
        assert right_files == []
        await pilot.press("q")


async def test_z_can_be_cancelled(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("+")
        for ch in "*.dat":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("z")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not (app.inactive_panel.cwd / "L.zip").exists()
        await pilot.press("q")


# ---------------------------------------------------------------------------
# e — mail (mocking the mail subprocess)
# ---------------------------------------------------------------------------


def _install_fake_mail(monkeypatch: pytest.MonkeyPatch, captured: dict) -> None:
    """Make ``shutil.which("mail")`` succeed and ``subprocess.run`` capture."""
    from sansdir.core import mailer

    def fake_which(cmd: str) -> str:
        return f"/usr/bin/{cmd}"

    def fake_run(argv, input=None, capture_output=False, text=False, timeout=None, check=False):  # type: ignore[no-untyped-def]
        captured["argv"] = list(argv)
        captured["input"] = input
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mailer.shutil, "which", fake_which)
    monkeypatch.setattr(mailer.subprocess, "run", fake_run)


async def test_e_opens_dialog_and_sends(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    _install_fake_mail(monkeypatch, captured)
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("+")
        for ch in "*.dat":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        # MailDialog focuses the recipient input; type address.
        for ch in "user@example.com":
            await pilot.press(ch)
        # Subject is pre-filled with the default; just append a marker.
        await pilot.press("tab")
        for ch in " :: the data":
            await pilot.press(ch)
        # Ctrl+S sends without touching the body.
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert captured["argv"] is not None
        assert captured["argv"][-1] == "user@example.com"
        # Subject is the value after `-s`. Should end with our suffix.
        s_idx = captured["argv"].index("-s")
        assert captured["argv"][s_idx + 1].endswith("the data")
        # Three attachments were tagged → three -a entries.
        assert captured["argv"].count("-a") == 3
        await pilot.press("q")


async def test_e_blank_recipient_keeps_dialog_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}
    _install_fake_mail(monkeypatch, captured)
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("+")
        for ch in "*.dat":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        # Empty recipient → submit must not call mail.
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert "argv" not in captured or captured.get("argv") is None
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("q")


# ---------------------------------------------------------------------------
# DoD: tag → zip → mail the zip in one Pilot session
# ---------------------------------------------------------------------------


async def test_phase3_dod_tag_zip_mail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    _install_fake_mail(monkeypatch, captured)
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # 1. Tag everything.
        await pilot.press("+")
        for ch in "*.dat":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        # 2. Zip into the inactive pane (default name).
        await pilot.press("z")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        zip_path = app.inactive_panel.cwd / "L.zip"
        assert zip_path.exists()
        # 3. Switch to the inactive pane (now holding the zip), tag the zip.
        await pilot.press("tab")
        await pilot.pause()
        # The zip should be visible in the now-active pane.
        await pilot.press("down")  # off ".."
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        # 4. Mail it.
        await pilot.press("e")
        await pilot.pause()
        for ch in "lab@example.com":
            await pilot.press(ch)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert captured["argv"] is not None
        assert captured["argv"][-1] == "lab@example.com"
        assert str(zip_path.resolve()) in captured["argv"]
        await pilot.press("q")
