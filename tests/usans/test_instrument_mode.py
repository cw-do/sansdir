"""Instrument mode: detection, keymap scoping, hint bar, catalog columns, App.

The load-bearing assertion in this file is the negative one: with no USANS
path and no USANS config, everything must look exactly as it did before
the feature existed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sansdir.commands.builtins import build_default_registry
from sansdir.core.instrument import (
    KNOWN_INSTRUMENTS,
    MODE_SANS,
    MODE_USANS,
    detect_instrument,
    is_usans_path,
    mode_for_instrument,
    normalise_instrument,
    resolve_instrument,
)
from sansdir.ui.key_hint_bar import KeyHintBar
from sansdir.ui.keys import default_keymap, usans_keymap
from sansdir.ui.run_catalog import COLUMNS_SANS, COLUMNS_USANS, columns_for

# ---------------------------------------------------------------------------
# core.instrument
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "mode"),
    [
        ("USANS", MODE_USANS),
        ("usans", MODE_USANS),
        (" UsAnS ", MODE_USANS),
        ("EQSANS", MODE_SANS),
        ("BIOSANS", MODE_SANS),
        ("GPSANS", MODE_SANS),
        ("SOMETHING-NEW", MODE_SANS),
    ],
)
def test_mode_for_instrument(name: str, mode: str) -> None:
    assert mode_for_instrument(name) == mode


def test_normalise_instrument_upcases_and_trims() -> None:
    assert normalise_instrument("  usans ") == "USANS"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/SNS/USANS/IPTS-37679/shared", True),
        ("/sns/usans/IPTS-1", True),
        ("/home/u/my-usans-work", True),
        ("/SNS/EQSANS/IPTS-12345/shared", False),
        ("/HFIR/CG3/IPTS-1", False),
        ("/gpfs/.../EQSANS/shared/script/sansdir", False),
    ],
)
def test_is_usans_path(path: str, expected: bool) -> None:
    assert is_usans_path(path) is expected


def test_detect_instrument_returns_none_without_an_opinion() -> None:
    assert detect_instrument(["/SNS/EQSANS/IPTS-1", "/tmp"]) is None


def test_detect_instrument_finds_usans_in_any_position() -> None:
    assert detect_instrument(["/tmp", "/SNS/USANS/IPTS-1"]) == "USANS"


def test_resolve_instrument_path_beats_config() -> None:
    got = resolve_instrument(["/SNS/USANS/IPTS-1"], configured="EQSANS", fallback="EQSANS")
    assert got == "USANS"


def test_resolve_instrument_falls_back_to_config_then_oncat_default() -> None:
    assert resolve_instrument(["/tmp"], configured="BIOSANS", fallback="EQSANS") == "BIOSANS"
    assert resolve_instrument(["/tmp"], configured="", fallback="EQSANS") == "EQSANS"


def test_resolve_instrument_honours_auto_detect_off() -> None:
    got = resolve_instrument(
        ["/SNS/USANS/IPTS-1"], configured="EQSANS", fallback="EQSANS", auto_detect=False
    )
    assert got == "EQSANS"


def test_usans_is_a_known_instrument() -> None:
    assert "USANS" in KNOWN_INSTRUMENTS
    assert "EQSANS" in KNOWN_INSTRUMENTS


# ---------------------------------------------------------------------------
# Keymap scoping
# ---------------------------------------------------------------------------


def test_sans_keymap_is_unchanged_by_the_usans_feature() -> None:
    """No USANS key may leak into the default (SANS) keymap."""
    sans_keys = {kb.key for kb in default_keymap()}
    assert "r" not in sans_keys
    assert not any(kb.command.startswith("usans.") for kb in default_keymap())


def test_usans_mode_adds_r_and_keeps_every_sans_binding() -> None:
    sans = default_keymap()
    usans = default_keymap(mode="USANS")
    assert usans[: len(sans)] == sans
    assert [kb.key for kb in usans[len(sans) :]] == ["r"]
    assert usans[-1].command == "usans.reduce"


def test_usans_bindings_name_registered_commands(tmp_path: Path) -> None:
    from tests.test_phase1_commands import FakeApp, FakePanel

    left = tmp_path / "L"
    left.mkdir()
    app = FakeApp(left=FakePanel(cwd=left), right=FakePanel(cwd=left), instrument="USANS")
    known = {c.name for c in build_default_registry(app=app).all()}
    for kb in usans_keymap():
        assert kb.command in known


def test_usans_keys_do_not_collide_with_sans_keys() -> None:
    sans_keys = {kb.key for kb in default_keymap()}
    assert not sans_keys & {kb.key for kb in usans_keymap()}


# ---------------------------------------------------------------------------
# Hint bar
# ---------------------------------------------------------------------------


def test_hint_bar_hides_usans_cells_in_sans_mode() -> None:
    assert "r:Reduce" not in KeyHintBar(default_keymap()).render().plain


def test_hint_bar_shows_reduce_in_usans_mode() -> None:
    bar = KeyHintBar(default_keymap(mode="USANS"), mode="USANS")
    rendered = bar.render().plain
    assert "r:Reduce" in rendered
    # The familiar SANS cells are still there, in the same order.
    assert "F5:Refresh" in rendered
    assert "p,l:Plot" in rendered


def test_hint_bar_set_keymap_switches_modes() -> None:
    bar = KeyHintBar(default_keymap(), mode="SANS")
    bar.set_keymap(default_keymap(mode="USANS"), mode="USANS")
    assert "r:Reduce" in bar.render().plain
    bar.set_keymap(default_keymap(), mode="SANS")
    assert "r:Reduce" not in bar.render().plain


# ---------------------------------------------------------------------------
# Catalog columns
# ---------------------------------------------------------------------------


def test_columns_for_drops_dist_and_wavelength_on_usans() -> None:
    assert columns_for("USANS") == COLUMNS_USANS
    assert columns_for("EQSANS") == COLUMNS_SANS
    assert "Dist (m)" not in COLUMNS_USANS
    assert "λ (Å)" not in COLUMNS_USANS
    assert COLUMNS_USANS == ("Run #", "Title", "Count", "Time(s)")


# ---------------------------------------------------------------------------
# App wiring (Pilot)
# ---------------------------------------------------------------------------


def _run(coro) -> None:  # type: ignore[no-untyped-def]
    """Drive a Textual pilot coroutine (no pytest-asyncio on the cluster)."""
    asyncio.run(coro)


def test_app_defaults_to_sans_mode(tmp_path: Path, monkeypatch) -> None:
    from sansdir.app import SansdirApp

    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    app = SansdirApp(start_path=tmp_path)
    assert app.instrument == "EQSANS"
    assert app.instrument_mode == "SANS"
    assert "r" not in {kb.key for kb in app.keymap}


def test_app_auto_detects_usans_from_the_launch_path(tmp_path: Path, monkeypatch) -> None:
    from sansdir.app import SansdirApp

    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    usans_dir = tmp_path / "SNS" / "USANS" / "IPTS-1"
    usans_dir.mkdir(parents=True)
    app = SansdirApp(start_path=usans_dir)
    assert app.instrument == "USANS"
    assert app.instrument_mode == "USANS"
    assert "r" in {kb.key for kb in app.keymap}


def test_app_honours_the_configured_instrument(tmp_path: Path, monkeypatch) -> None:
    from sansdir.app import SansdirApp

    cfg = tmp_path / "config.toml"
    cfg.write_text('[instrument]\ndefault = "USANS"\n', encoding="utf-8")
    monkeypatch.setenv("SANSDIR_CONFIG", str(cfg))
    app = SansdirApp(start_path=tmp_path)
    assert app.instrument == "USANS"


def test_app_auto_detect_can_be_switched_off(tmp_path: Path, monkeypatch) -> None:
    from sansdir.app import SansdirApp

    cfg = tmp_path / "config.toml"
    cfg.write_text('[instrument]\ndefault = "EQSANS"\nauto_detect = false\n', encoding="utf-8")
    monkeypatch.setenv("SANSDIR_CONFIG", str(cfg))
    usans_dir = tmp_path / "usans-work"
    usans_dir.mkdir()
    app = SansdirApp(start_path=usans_dir)
    assert app.instrument == "EQSANS"


def test_app_set_instrument_rebuilds_keymap_and_hint_bar(tmp_path: Path, monkeypatch) -> None:
    from sansdir.app import SansdirApp

    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path)
        async with app.run_test() as pilot:
            assert "r" not in {kb.key for kb in app.keymap}
            await pilot.pause()
            app.set_instrument("usans")
            await pilot.pause()
            assert app.instrument_mode == "USANS"
            assert "r" in {kb.key for kb in app.keymap}
            assert "r:Reduce" in app._hintbar.render().plain
            app.set_instrument("eqsans")
            await pilot.pause()
            assert "r" not in {kb.key for kb in app.keymap}

    _run(_drive())


def test_app_instrument_command_switches_via_the_command_line(tmp_path: Path, monkeypatch) -> None:
    from sansdir.app import SansdirApp

    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.run_command_line("instrument usans")
            await pilot.pause()
            assert app.instrument == "USANS"

    _run(_drive())


def test_app_loaded_catalog_is_none_until_an_ipts_is_loaded(tmp_path: Path, monkeypatch) -> None:
    from sansdir.app import SansdirApp
    from sansdir.core.oncat import Datafile

    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.loaded_catalog() is None
            runs = [
                Datafile(run_number=100, title="emptyBanjo", start_time="", duration_s=1.0),
                Datafile(run_number=101, title="S0", start_time="", duration_s=1.0),
            ]
            app.show_catalog_in_other_pane("IPTS-1", runs, instrument="USANS")
            await pilot.pause()
            ipts, loaded = app.loaded_catalog()  # type: ignore[misc]
            assert ipts == "IPTS-1"
            assert [r.run_number for r in loaded] == [100, 101]

    _run(_drive())


def test_catalog_uses_usans_columns_when_shown_in_usans_mode(tmp_path: Path, monkeypatch) -> None:
    from sansdir.app import SansdirApp
    from sansdir.core.oncat import Datafile

    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))

    async def _drive() -> None:
        app = SansdirApp(start_path=tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            runs = [Datafile(run_number=100, title="S0 1p", start_time="", duration_s=12.0)]
            app.show_catalog_in_other_pane("IPTS-1", runs, instrument="USANS")
            await pilot.pause()
            catalog = app._right_slot.catalog
            assert catalog._columns == COLUMNS_USANS
            assert len(catalog.table.columns) == len(COLUMNS_USANS)
            # And switching back re-installs the SANS header.
            catalog.set_instrument("EQSANS")
            await pilot.pause()
            assert catalog._columns == COLUMNS_SANS
            assert len(catalog.table.columns) == len(COLUMNS_SANS)

    _run(_drive())


def test_r_key_dispatches_usans_reduce_only_in_usans_mode(tmp_path: Path, monkeypatch) -> None:
    """The end-to-end key path: ``r`` on a setup CSV runs the reduce command."""
    from sansdir.app import SansdirApp

    work = tmp_path / "usans-work"
    work.mkdir()
    csv = work / "IPTS-1_setup.csv"
    csv.write_text("b,E,100,4,0.1\n", encoding="utf-8")
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))

    async def _drive() -> None:
        app = SansdirApp(start_path=work)
        calls: list[dict] = []

        async def _fake(**kwargs: object) -> None:
            calls.append(dict(kwargs))

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.instrument_mode == "USANS", "path detection should have fired"
            # Swap the real handler so the test never spawns reduceUSANS.
            object.__setattr__(app.registry.get("usans.reduce"), "handler", _fake)
            app.active_panel.set_cwd(work)
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            assert calls, "r did not reach usans.reduce"

            # Back on SANS, `r` is not bound at all.
            app.set_instrument("eqsans")
            await pilot.pause()
            calls.clear()
            await pilot.press("r")
            await pilot.pause()
            assert calls == []

    _run(_drive())


def test_enter_on_the_catalog_writes_the_csv_next_to_the_file_pane(
    tmp_path: Path, monkeypatch
) -> None:
    """End-to-end: ``i`` then Tab then Enter lands the CSV in <IPTS>/shared."""
    from sansdir.app import SansdirApp
    from sansdir.core.oncat import Datafile

    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    root = tmp_path / "usans-root"
    shared = root / "IPTS-1" / "shared"
    shared.mkdir(parents=True)
    runs = [
        Datafile(run_number=n, title=t, start_time="", duration_s=1.0)
        for n, t in [(100, "emptyBanjo"), (101, "emptyBanjo"), (102, "S0"), (103, "S0")]
    ]

    async def _drive() -> None:
        app = SansdirApp(start_path=root)
        async with app.run_test() as pilot:
            await pilot.pause()
            # What `oncat.search` does: cd the active pane, catalog opposite.
            app.active_panel.set_cwd(shared)
            app.show_catalog_in_other_pane("IPTS-1", runs, instrument="USANS")
            await pilot.pause()
            await pilot.press("tab")
            await pilot.pause()
            assert app.active_panel.cwd == root, "the catalog slot's pane is elsewhere"
            assert app.working_panel.cwd == shared, "but the working dir follows the file pane"
            await app.registry.dispatch("usans.init_table", start_run=100)
            await pilot.pause()
            assert (shared / "IPTS-1_setup.csv").is_file()

    _run(_drive())


def test_generated_csv_ends_up_under_the_cursor(tmp_path: Path, monkeypatch) -> None:
    """Real FilePanel: after generating, the cursor is on the new CSV."""
    from sansdir.app import SansdirApp
    from sansdir.core.oncat import Datafile

    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "absent.toml"))
    shared = tmp_path / "usans" / "IPTS-1" / "shared"
    shared.mkdir(parents=True)
    (shared / "aaa_first.txt").write_text("", encoding="utf-8")
    runs = [
        Datafile(run_number=n, title=t, start_time="", duration_s=1.0)
        for n, t in [(100, "emptyBanjo"), (101, "emptyBanjo"), (102, "S0"), (103, "S0")]
    ]

    async def _drive() -> None:
        app = SansdirApp(start_path=shared)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.show_catalog_in_other_pane("IPTS-1", runs, instrument="USANS")
            await pilot.pause()
            # Park on ``..`` — row 0 — the way a fresh pane starts.
            app.active_panel.move_cursor(row=0)
            await pilot.pause()
            assert app.active_panel.cursor_path == shared.parent

            await app.registry.dispatch("usans.init_table", start_run=100)
            await pilot.pause()

            assert app.active_panel.cursor_path == shared / "IPTS-1_setup.csv"

    _run(_drive())
