"""Phase 9 — themes + per-user key rebinding."""

from __future__ import annotations

from pathlib import Path

import pytest

from sansdir.app import SansdirApp, _apply_keymap_overrides
from sansdir.commands.builtins import build_default_registry
from sansdir.commands.registry import CommandRegistry
from sansdir.core.history import CommandHistory
from sansdir.ui.keys import KeyBinding, default_keymap


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))


def _real_app(tmp_path: Path) -> SansdirApp:
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    return SansdirApp(
        start_path=left,
        right_path=right,
        history=CommandHistory(path=tmp_path / "hist", load=False),
    )


# ---------------------------------------------------------------------------
# _apply_keymap_overrides — pure-function unit tests
# ---------------------------------------------------------------------------


def _registry() -> CommandRegistry:
    """Build a registry that knows app-bound commands without a real app."""

    class _StubApp:
        active_panel = None
        inactive_panel = None

        def __getattr__(self, name):  # type: ignore[no-untyped-def]
            return lambda *a, **k: None

    return build_default_registry(app=_StubApp())  # type: ignore[arg-type]


def test_overrides_replace_existing_binding() -> None:
    base = default_keymap()
    reg = _registry()
    # F5 is bound to the refresh command in the default keymap; users
    # can override it like any other binding.
    f5_before = next(kb for kb in base if kb.key == "f5")
    assert f5_before.command == "ui.refresh"
    merged = _apply_keymap_overrides(base, {"f5": "ui.move_tagged"}, reg)
    f5_after = next(kb for kb in merged if kb.key == "f5")
    assert f5_after.command == "ui.move_tagged"
    assert "(custom)" in f5_after.description


def test_overrides_add_new_binding() -> None:
    base = default_keymap()
    reg = _registry()
    merged = _apply_keymap_overrides(base, {"ctrl+y": "view.toggle_hidden"}, reg)
    new = next(kb for kb in merged if kb.key == "ctrl+y")
    assert new.command == "view.toggle_hidden"


def test_overrides_drop_unknown_command_keep_default() -> None:
    base = default_keymap()
    reg = _registry()
    merged = _apply_keymap_overrides(
        base, {"f5": "no.such.command"}, reg
    )
    f5 = next(kb for kb in merged if kb.key == "f5")
    # Default kept; bogus override silently dropped.
    assert f5.command == "ui.refresh"


def test_overrides_empty_returns_base_unchanged() -> None:
    base = default_keymap()
    merged = _apply_keymap_overrides(base, {}, _registry())
    assert merged is base


# ---------------------------------------------------------------------------
# Theme — applied from config at startup, switchable via :theme cmdline
# ---------------------------------------------------------------------------


async def test_default_theme_is_textual_dark(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "textual-dark"
        await pilot.press("q")


async def test_config_theme_applied_on_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('[ui]\ntheme = "monokai"\n', encoding="utf-8")
    monkeypatch.setenv("SANSDIR_CONFIG", str(cfg))
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "monokai"
        await pilot.press("q")


async def test_theme_command_switches_at_runtime(tmp_path: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.registry.dispatch("ui.set_theme", name="dracula")
        assert app.theme == "dracula"
        # Unknown name leaves theme alone.
        await app.registry.dispatch("ui.set_theme", name="not-a-theme")
        assert app.theme == "dracula"
        await pilot.press("q")


async def test_keys_config_overrides_at_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``[keys]`` in config must produce a merged keymap on the live App."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('[keys]\n"ctrl+y" = "view.toggle_hidden"\n', encoding="utf-8")
    monkeypatch.setenv("SANSDIR_CONFIG", str(cfg))
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        bound = [kb for kb in app.keymap if kb.key == "ctrl+y"]
        assert bound, "ctrl+y should be present after [keys] override"
        assert bound[0].command == "view.toggle_hidden"
        await pilot.press("q")


def test_display_path_rewrites_gpfs_to_sns(tmp_path: Path) -> None:
    """``/gpfs/neutronsfs/instruments/...`` → ``/SNS/...`` for display only."""
    from sansdir.ui.pathbar import _GPFS_PREFIX, display_path

    assert display_path("/SNS/EQSANS/IPTS-12345") == "/SNS/EQSANS/IPTS-12345"
    assert (
        display_path(f"{_GPFS_PREFIX}/EQSANS/IPTS-12345/shared")
        == "/SNS/EQSANS/IPTS-12345/shared"
    )
    # Non-cluster paths pass through unchanged.
    assert display_path(tmp_path) == str(tmp_path)
    # Substring match is anchored to the prefix — a similarly-named
    # path elsewhere isn't rewritten.
    assert display_path("/gpfs/neutronsfs/instruments-elsewhere") == (
        "/gpfs/neutronsfs/instruments-elsewhere"
    )


async def test_pathbar_shows_both_pane_paths_and_tracks_cd(tmp_path: Path) -> None:
    """The bar renders left/right cwds and updates when either pane navigates."""
    from textual.widgets import Static

    app = _real_app(tmp_path)
    # _real_app already created L/ and R/; add a child to cd into.
    sub_l = tmp_path / "L" / "data"
    sub_r = tmp_path / "R" / "scratch"
    sub_l.mkdir()
    sub_r.mkdir()
    async with app.run_test() as pilot:
        await pilot.pause()
        left_cell = app._pathbar.query_one("#pathbar-left", Static)
        right_cell = app._pathbar.query_one("#pathbar-right", Static)
        assert str(tmp_path / "L") in str(left_cell.render())
        assert str(tmp_path / "R") in str(right_cell.render())
        # Active styling follows the active pane.
        assert left_cell.has_class("-active")
        assert not right_cell.has_class("-active")
        # cd in the active (left) pane updates only the left cell.
        app._left.set_cwd(sub_l)
        await pilot.pause()
        assert str(sub_l) in str(left_cell.render())
        # Tab → right becomes active; styling moves with it.
        await pilot.press("tab")
        await pilot.pause()
        assert right_cell.has_class("-active")
        assert not left_cell.has_class("-active")
        await pilot.press("q")


async def test_catalog_always_lands_on_right_regardless_of_active_pane(
    tmp_path: Path,
) -> None:
    """``show_catalog_in_other_pane`` always targets the right slot.

    Mirrors the user-facing convention "right is for IPTS catalogs,
    left is for working files". Tested directly so we don't need the
    full OnCat browser flow.
    """
    from sansdir.core.oncat import Datafile

    runs = [
        Datafile(
            run_number=100,
            title="t",
            start_time="",
            duration_s=0,
            detector_distance_mm=2500.0,
            wavelength_a=2.5,
            total_counts=0,
        )
    ]
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Start with active=left; loading the catalog still pins it
        # to the right slot.
        assert app._active_id == "left"
        app.show_catalog_in_other_pane("IPTS-99999", runs)
        await pilot.pause()
        assert app._right_slot.catalog_visible
        assert not app._left_slot.catalog_visible
        # Now Tab to right and re-load with a different IPTS — still
        # right, regardless of which pane initiated.
        await pilot.press("tab")
        await pilot.pause()
        assert app._active_id == "right"
        app.show_catalog_in_other_pane("IPTS-77777", runs)
        await pilot.pause()
        assert app._right_slot.catalog_visible
        assert app._right_slot.catalog.ipts == "IPTS-77777"
        assert not app._left_slot.catalog_visible
        await pilot.press("q")


async def test_swap_panels_does_not_move_the_catalog(tmp_path: Path) -> None:
    """Ctrl+U swaps file panels' cwds but leaves the catalog on the right."""
    from sansdir.core.oncat import Datafile

    runs = [
        Datafile(
            run_number=1,
            title="t",
            start_time="",
            duration_s=0,
            detector_distance_mm=2500.0,
            wavelength_a=2.5,
            total_counts=0,
        )
    ]
    sub_l = tmp_path / "L" / "data"
    sub_r = tmp_path / "R" / "scratch"
    app = _real_app(tmp_path)
    sub_l.mkdir()
    sub_r.mkdir()
    async with app.run_test() as pilot:
        await pilot.pause()
        app._left.set_cwd(sub_l)
        app._right.set_cwd(sub_r)
        app.show_catalog_in_other_pane("IPTS-12345", runs)
        await pilot.pause()
        assert app._right_slot.catalog_visible
        # Swap.
        await pilot.press("ctrl+u")
        await pilot.pause()
        # File pane cwds traded sides…
        assert app._left.cwd == sub_r
        assert app._right.cwd == sub_l
        # …but the catalog overlay stays put on the right.
        assert app._right_slot.catalog_visible
        assert not app._left_slot.catalog_visible
        await pilot.press("q")


def test_keybinding_dataclass_minimal_construction() -> None:
    """``_apply_keymap_overrides`` constructs new bindings without resolvers."""
    kb = KeyBinding(key="ctrl+y", command="view.toggle_hidden", description="x")
    assert kb.key == "ctrl+y"
    assert kb.command == "view.toggle_hidden"
