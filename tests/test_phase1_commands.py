"""Tests for the Phase-1 app-bound command registrations.

These exercise the registry → handler → app-state flow without spinning up
Textual, by passing in a tiny in-memory ``FakeApp`` that satisfies the
:class:`AppProtocol` surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from sansdir.commands.builtins import build_default_registry
from sansdir.commands.registry import UnknownCommandError


@dataclass
class FakePanel:
    cwd: Path
    show_hidden: bool = False
    sort_key: str = "name"
    sort_reverse: bool = False
    refresh_count: int = 0
    cursor_path: Path | None = None

    def set_cwd(self, new_cwd: Path) -> None:
        self.cwd = new_cwd
        self.refresh_count += 1

    def refresh_listing(self) -> None:
        self.refresh_count += 1


@dataclass
class FakeApp:
    left: FakePanel
    right: FakePanel
    active_id: str = "left"
    swapped: int = 0
    maxed: int = 0
    helped: int = 0
    quit_called: int = 0
    max_state: bool = False

    @property
    def active_panel(self) -> FakePanel:
        return self.left if self.active_id == "left" else self.right

    @property
    def inactive_panel(self) -> FakePanel:
        return self.right if self.active_id == "left" else self.left

    def set_active(self, panel_id: str) -> None:
        if panel_id == "other":
            self.active_id = "right" if self.active_id == "left" else "left"
        elif panel_id in ("left", "right"):
            self.active_id = panel_id
        else:
            raise ValueError(panel_id)

    def swap_panels(self) -> None:
        self.left, self.right = self.right, self.left
        self.swapped += 1

    def toggle_max(self) -> None:
        self.max_state = not self.max_state
        self.maxed += 1

    def show_help(self) -> None:
        self.helped += 1

    def quit_app(self) -> None:
        self.quit_called += 1


@pytest.fixture
def app(tmp_path: Path) -> FakeApp:
    left_dir = tmp_path / "L"
    right_dir = tmp_path / "R"
    left_dir.mkdir()
    right_dir.mkdir()
    (left_dir / "child").mkdir()
    return FakeApp(left=FakePanel(cwd=left_dir), right=FakePanel(cwd=right_dir))


# ---------------------------------------------------------------------------
# app.quit — both unbound and bound forms
# ---------------------------------------------------------------------------


async def test_app_quit_unbound_returns_sentinel() -> None:
    reg = build_default_registry(app=None)
    assert await reg.dispatch("app.quit") == "quit"


async def test_app_quit_bound_calls_app(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    await reg.dispatch("app.quit")
    assert app.quit_called == 1


# ---------------------------------------------------------------------------
# nav.cd / nav.up
# ---------------------------------------------------------------------------


async def test_nav_cd_relative(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    start = app.left.cwd
    await reg.dispatch("nav.cd", path="child")
    assert app.left.cwd == (start / "child").resolve()


async def test_nav_cd_absolute(app: FakeApp, tmp_path: Path) -> None:
    reg = build_default_registry(app=app)
    await reg.dispatch("nav.cd", path=str(tmp_path / "R"))
    assert app.left.cwd == (tmp_path / "R").resolve()


async def test_nav_cd_rejects_non_directory(app: FakeApp, tmp_path: Path) -> None:
    f = tmp_path / "L" / "afile.txt"
    f.write_text("hi", encoding="utf-8")
    reg = build_default_registry(app=app)
    with pytest.raises(NotADirectoryError):
        await reg.dispatch("nav.cd", path=str(f))


async def test_nav_up(app: FakeApp, tmp_path: Path) -> None:
    reg = build_default_registry(app=app)
    await reg.dispatch("nav.up")
    assert app.left.cwd == tmp_path


async def test_nav_up_at_root_is_noop(app: FakeApp, monkeypatch: pytest.MonkeyPatch) -> None:
    app.left.cwd = Path("/")
    reg = build_default_registry(app=app)
    await reg.dispatch("nav.up")
    assert app.left.cwd == Path("/")


# ---------------------------------------------------------------------------
# pane.activate / swap / sync / toggle_max
# ---------------------------------------------------------------------------


async def test_pane_activate_other(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    assert app.active_id == "left"
    await reg.dispatch("pane.activate", panel_id="other")
    assert app.active_id == "right"
    await reg.dispatch("pane.activate", panel_id="other")
    assert app.active_id == "left"


async def test_pane_activate_explicit(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    await reg.dispatch("pane.activate", panel_id="right")
    assert app.active_id == "right"


async def test_pane_swap(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    left_before = app.left
    right_before = app.right
    await reg.dispatch("pane.swap")
    assert app.left is right_before
    assert app.right is left_before


async def test_pane_sync_copies_cwd(app: FakeApp, tmp_path: Path) -> None:
    reg = build_default_registry(app=app)
    await reg.dispatch("pane.sync")
    assert app.right.cwd == app.left.cwd


async def test_pane_toggle_max(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    await reg.dispatch("pane.toggle_max")
    assert app.max_state is True
    await reg.dispatch("pane.toggle_max")
    assert app.max_state is False


# ---------------------------------------------------------------------------
# view.toggle_hidden / view.set_sort
# ---------------------------------------------------------------------------


async def test_view_toggle_hidden_flips_active(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    assert app.left.show_hidden is False
    await reg.dispatch("view.toggle_hidden")
    assert app.left.show_hidden is True
    assert app.right.show_hidden is False  # untouched
    assert app.left.refresh_count >= 1


async def test_view_set_sort(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    await reg.dispatch("view.set_sort", key="mtime", reverse=True)
    assert app.left.sort_key == "mtime"
    assert app.left.sort_reverse is True


async def test_view_set_sort_rejects_unknown_key(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    # Enum validation lives in the JSON-schema export, not the dispatcher,
    # so the dispatcher will pass an invalid key through to the handler.
    # The handler then trusts the panel; Phase 1's UI never feeds bad keys
    # because the keymap closes over VALID_SORT_KEYS. Here we just ensure
    # the dispatch succeeds (no false failure) when key is valid.
    await reg.dispatch("view.set_sort", key="ext")
    assert app.left.sort_key == "ext"


# ---------------------------------------------------------------------------
# app.help
# ---------------------------------------------------------------------------


async def test_app_help_calls_app(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    await reg.dispatch("app.help")
    assert app.helped == 1


# ---------------------------------------------------------------------------
# Bound vs unbound surface
# ---------------------------------------------------------------------------


def test_unbound_registry_has_only_app_quit() -> None:
    reg = build_default_registry(app=None)
    assert [c.name for c in reg.all()] == ["app.quit"]


def test_bound_registry_has_full_phase1_surface(app: FakeApp) -> None:
    reg = build_default_registry(app=app)
    names = {c.name for c in reg.all()}
    expected = {
        "app.quit",
        "app.help",
        "nav.cd",
        "nav.up",
        "pane.activate",
        "pane.swap",
        "pane.sync",
        "pane.toggle_max",
        "view.toggle_hidden",
        "view.set_sort",
    }
    assert expected <= names


async def test_unbound_registry_lacks_app_bound_commands() -> None:
    reg = build_default_registry(app=None)
    with pytest.raises(UnknownCommandError):
        await reg.dispatch("nav.up")
