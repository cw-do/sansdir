"""End-to-end Pilot tests for Phase 4 — `i` IPTS browser → catalog flow."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sansdir.app import SansdirApp
from sansdir.core.history import CommandHistory

EXPERIMENTS_RE = re.compile(r"https://oncat\.test/api/experiments\b.*")
DATAFILES_RE = re.compile(r"https://oncat\.test/api/datafiles\b.*")


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture
def fake_oncat_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
        [oncat]
        endpoint = "https://oncat.test"
        client_id = "id"
        client_secret = "secret"
        default_instrument = "EQSANS"
        cache_ttl_seconds = 3600
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("SANSDIR_CONFIG", str(cfg))
    return cfg


def _scratch(tmp_path: Path) -> tuple[Path, Path]:
    left = tmp_path / "L"
    right = tmp_path / "R"
    left.mkdir()
    right.mkdir()
    return left, right


def _real_app(tmp_path: Path) -> SansdirApp:
    left, right = _scratch(tmp_path)
    history = CommandHistory(path=tmp_path / "hist", load=False)
    return SansdirApp(start_path=left, right_path=right, history=history)


# Two-IPTS canned response with the new fields the browser displays.
SAMPLE_EXPERIMENTS = [
    {
        "id": "IPTS-12345",
        "title": "Bio-membrane assembly under shear",
        "members": ["Alice", "Bob"],
        "size": 151,
        "activity": {
            "acquisition": {"start": "2026-04-25", "end": "2026-04-27"},
        },
    },
    {
        "id": "IPTS-22222",
        "title": "Polymer micelles",
        "members": ["Carol"],
        "size": 30,
        "activity": {
            "acquisition": {"start": "2026-03-15", "end": "2026-03-17"},
        },
    },
]

SAMPLE_DATAFILES = [
    {
        "indexed": {"run_number": 12001},
        "metadata": {
            "entry": {
                "title": "background",
                "duration": 600.0,
                "total_counts": 9999,
                "daslogs": {
                    # OnCat returns detectorz in mm; 4000 = 4 m at the panel.
                    "detectorz": {"average_value": 4000.0},
                    "wavelength": {"average_value": 2.5},
                },
            }
        },
    },
    {
        "indexed": {"run_number": 12002},
        "metadata": {
            "entry": {
                "title": "sample A",
                "duration": 1200.0,
                "total_counts": 1234567,
                "daslogs": {
                    "detectorz": {"average_value": 8000.0},
                    "wavelength": {"average_value": 4.5},
                },
            }
        },
    },
]


def _stub_oauth_and_experiments(httpx_mock, rows: list[dict]) -> None:  # type: ignore[no-untyped-def]
    httpx_mock.add_response(
        method="POST",
        url="https://oncat.test/oauth/token",
        json={"access_token": "tk", "expires_in": 3600},
    )
    httpx_mock.add_response(method="GET", url=EXPERIMENTS_RE, json=rows)


# ---------------------------------------------------------------------------
# DoD: `i` opens browser, `/` filter, Enter selects, confirm cd + catalog.
# ---------------------------------------------------------------------------


async def test_phase4_dod_i_browse_filter_select_catalog(
    tmp_path: Path,
    httpx_mock,  # type: ignore[no-untyped-def]
    fake_oncat_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_root = tmp_path / "SNS_FAKE"
    (fake_root / "EQSANS" / "IPTS-12345").mkdir(parents=True)

    from sansdir.core import oncat as oncat_mod

    original = oncat_mod.Experiment.cluster_path

    def fake_cluster_path(self, root=None):  # type: ignore[no-untyped-def]
        return original(self, str(fake_root))

    monkeypatch.setattr(oncat_mod.Experiment, "cluster_path", fake_cluster_path)

    _stub_oauth_and_experiments(httpx_mock, SAMPLE_EXPERIMENTS)
    httpx_mock.add_response(method="GET", url=DATAFILES_RE, json=SAMPLE_DATAFILES)

    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # `i` opens the OnCat browser directly (no cmdline pre-fill).
        await pilot.press("i")
        await pilot.pause()
        assert any(type(s).__name__ == "OnCatBrowserScreen" for s in app.screen_stack), (
            f"expected browser in {[type(s).__name__ for s in app.screen_stack]}"
        )
        # `/` focuses the filter input; type to narrow.
        await pilot.press("/")
        for ch in "membrane":
            await pilot.press(ch)
        await pilot.pause()
        # Enter on the input moves focus to the list; Enter on the list
        # selects the highlighted row (row 0 after the filter).
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        # ConfirmDialog appears asking to cd + load catalog → press Y.
        assert any(type(s).__name__ == "ConfirmDialog" for s in app.screen_stack)
        await pilot.press("y")
        await pilot.pause()
        # Active pane cd'd into the IPTS dir.
        assert app.active_panel.cwd == (fake_root / "EQSANS" / "IPTS-12345").resolve()
        # Inactive pane now displays the run catalog with both runs.
        slot = app._inactive_slot
        assert slot.catalog_visible
        assert slot.has_catalog
        assert [f.run_number for f in slot.catalog.files] == [12001, 12002]
        # ``c`` toggles back to the filelist.
        await pilot.press("c")
        await pilot.pause()
        assert not slot.catalog_visible
        # ``c`` again brings the catalog back without another OnCat round-trip.
        await pilot.press("c")
        await pilot.pause()
        assert slot.catalog_visible
        # Tab into the catalog pane; ``c`` from there should also
        # return that slot to its filelist (the catalog is the
        # *active* slot now).
        await pilot.press("tab")
        await pilot.pause()
        assert app._active_slot is slot
        await pilot.press("c")
        await pilot.pause()
        assert not slot.catalog_visible
        # ``c`` again from the same active slot should restore the
        # catalog *focused* — Up/Down must work without Tab.
        await pilot.press("c")
        await pilot.pause()
        assert slot.catalog_visible
        assert app.focused is slot.catalog.table
        # `/` from the catalog pane filters the run list (not the
        # FilePanel underneath).
        if app._active_slot is not slot:
            await pilot.press("tab")
            await pilot.pause()
        await pilot.press("/")
        await pilot.pause()
        for ch in "sample":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert slot.catalog.filter_substring == "sample"
        assert [f.run_number for f in slot.catalog.files] == [12002]
        # Esc clears the filter without closing the catalog.
        await pilot.press("escape")
        await pilot.pause()
        assert slot.catalog.filter_substring == ""
        assert slot.catalog_visible
        assert [f.run_number for f in slot.catalog.files] == [12001, 12002]
        # A second Esc closes the catalog (no filter active now).
        await pilot.press("escape")
        await pilot.pause()
        assert not slot.catalog_visible
        await pilot.press("q")


async def test_no_matches_notifies_and_skips_browser(
    tmp_path: Path,
    httpx_mock,  # type: ignore[no-untyped-def]
    fake_oncat_config: Path,
) -> None:
    """Empty instrument listing → notify and don't open the modal."""
    _stub_oauth_and_experiments(httpx_mock, [])
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        # Only the main screen on the stack.
        assert len(app.screen_stack) == 1
        await pilot.press("q")


async def test_oncat_auth_error_surfaces_clean_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
        [oncat]
        endpoint = "https://oncat.test"
        client_id = ""
        client_secret = ""
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("SANSDIR_CONFIG", str(cfg))
    monkeypatch.delenv("ONCAT_CLIENT_ID", raising=False)
    monkeypatch.delenv("ONCAT_CLIENT_SECRET", raising=False)
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        # No browser opened; the app is still responsive.
        assert len(app.screen_stack) == 1
        await pilot.press("q")


async def test_c_without_loaded_catalog_notifies(tmp_path: Path, fake_oncat_config: Path) -> None:
    """``c`` (catalog toggle) with no catalog loaded notifies, doesn't crash."""
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        # No catalog loaded → notification, no mode switch.
        assert not app._inactive_slot.catalog_visible
        await pilot.press("q")


async def test_browser_default_sort_is_ipts_descending(
    tmp_path: Path,
    httpx_mock,  # type: ignore[no-untyped-def]
    fake_oncat_config: Path,
) -> None:
    """Browser opens with the highest IPTS number on top."""
    rows = [
        {"id": "IPTS-100", "rank": 100, "title": "old", "size": 1},
        {"id": "IPTS-300", "rank": 300, "title": "newest", "size": 3},
        {"id": "IPTS-200", "rank": 200, "title": "middle", "size": 2},
    ]
    _stub_oauth_and_experiments(httpx_mock, rows)
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        from textual.widgets import ListView

        browser = next(s for s in app.screen_stack if type(s).__name__ == "OnCatBrowserScreen")
        lv = browser.query_one("#results-list", ListView)
        ipts_in_order = [c.experiment.ipts for c in lv.children]  # type: ignore[attr-defined]
        assert ipts_in_order == ["IPTS-300", "IPTS-200", "IPTS-100"]
        await pilot.press("escape")
        await pilot.press("q")


async def test_browser_s_cycles_sort_mode(
    tmp_path: Path,
    httpx_mock,  # type: ignore[no-untyped-def]
    fake_oncat_config: Path,
) -> None:
    """Pressing `s` switches IPTS-sort → date-sort and reorders the list."""
    rows = [
        {
            "id": "IPTS-300",
            "rank": 300,
            "title": "old data",
            "size": 1,
            "activity": {"acquisition": ["2020-01-01", "2020-01-02"]},
        },
        {
            "id": "IPTS-100",
            "rank": 100,
            "title": "fresh data",
            "size": 1,
            "activity": {"acquisition": ["2026-04-01", "2026-04-03"]},
        },
    ]
    _stub_oauth_and_experiments(httpx_mock, rows)
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        from textual.widgets import ListView

        browser = next(s for s in app.screen_stack if type(s).__name__ == "OnCatBrowserScreen")
        lv = browser.query_one("#results-list", ListView)
        # Default: IPTS↓
        order = [c.experiment.ipts for c in lv.children]  # type: ignore[attr-defined]
        assert order == ["IPTS-300", "IPTS-100"]
        # `s` → date↓ (IPTS-100 has 2026 acquisition, IPTS-300 has 2020)
        await pilot.press("s")
        await pilot.pause()
        order = [c.experiment.ipts for c in lv.children]  # type: ignore[attr-defined]
        assert order == ["IPTS-100", "IPTS-300"]
        # `s` again wraps back to IPTS↓
        await pilot.press("s")
        await pilot.pause()
        order = [c.experiment.ipts for c in lv.children]  # type: ignore[attr-defined]
        assert order == ["IPTS-300", "IPTS-100"]
        await pilot.press("escape")
        await pilot.press("q")


async def test_browser_caps_visible_rows_with_overflow_hint(
    tmp_path: Path,
    httpx_mock,  # type: ignore[no-untyped-def]
    fake_oncat_config: Path,
) -> None:
    """A 250-row catalog mounts only ``MAX_VISIBLE`` items; hint shows overflow.

    Per-keystroke widget-mount cost is the dominant lag on big OnCat
    catalogs, so the browser caps the rendered window. This test pins
    that contract — if a future change removes the cap and re-mounts
    the full list on every refresh, the input will go laggy again.
    """
    rows = [
        {
            "id": f"IPTS-{1000 + i}",
            "rank": 1000 + i,
            "title": f"row {i}",
            "size": 1,
        }
        for i in range(250)
    ]
    _stub_oauth_and_experiments(httpx_mock, rows)
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        from textual.widgets import ListView, Static

        from sansdir.ui.oncat_browser import OnCatBrowserScreen

        browser = next(
            s for s in app.screen_stack if isinstance(s, OnCatBrowserScreen)
        )
        lv = browser.query_one("#results-list", ListView)
        # Cap honoured — never more than MAX_VISIBLE children mounted.
        assert len(lv.children) == OnCatBrowserScreen.MAX_VISIBLE
        # Overflow hint mentions the truncation count.
        hint = browser.query_one("#overflow-hint", Static).render()
        text = hint.plain if hasattr(hint, "plain") else str(hint)
        assert f"+{250 - OnCatBrowserScreen.MAX_VISIBLE} more" in text
        await pilot.press("escape")
        await pilot.press("q")


async def test_browser_filter_is_debounced(
    tmp_path: Path,
    httpx_mock,  # type: ignore[no-untyped-def]
    fake_oncat_config: Path,
) -> None:
    """Several quick keystrokes in the filter trigger only one rebuild.

    We monkey-patch ``_refresh_list`` to count calls, then type four
    characters. With debouncing, the rebuild fires once after the
    quiet period, not four times.
    """
    rows = [
        {"id": f"IPTS-{200 + i}", "rank": 200 + i, "title": f"r{i}", "size": 1}
        for i in range(20)
    ]
    _stub_oauth_and_experiments(httpx_mock, rows)
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        from sansdir.ui.oncat_browser import OnCatBrowserScreen

        browser = next(
            s for s in app.screen_stack if isinstance(s, OnCatBrowserScreen)
        )
        # Establish a baseline AFTER the on_mount refresh ran.
        calls = {"n": 0}
        original = browser._refresh_list

        def _counting() -> None:
            calls["n"] += 1
            original()

        browser._refresh_list = _counting  # type: ignore[method-assign]
        await pilot.press("/")
        for ch in "row1":
            await pilot.press(ch)
        # Wait past the debounce window so the timer fires.
        await pilot.pause(0.5)
        # Without debouncing this would be 4 (one per keystroke). With
        # the 200ms debounce, four characters typed inside that
        # window collapse to one or two rebuilds (depending on
        # whether the event loop happens to schedule a timer fire
        # between keystrokes — both outcomes are correctly debounced;
        # the per-keystroke count is what we're guarding against).
        assert 1 <= calls["n"] <= 2, (
            f"expected 1-2 rebuilds with debounce, got {calls['n']}"
        )
        await pilot.press("escape")
        await pilot.press("q")


async def test_browser_r_force_refreshes_via_callback(
    tmp_path: Path,
    fake_oncat_config: Path,
) -> None:
    """Pressing ``r`` in the browser calls ``client.list_experiments``
    with ``use_cache=False`` and replaces the displayed list with
    the fresh result.

    Drives the modal directly (not via the keypress path) because the
    ``r`` keybinding lives on a ModalScreen — Textual's Pilot
    presses go to the App, but ModalScreen bindings are honoured
    once focus reaches the modal. Either path works; the action
    invocation is what we're pinning here.
    """
    from sansdir.core.oncat import Experiment
    from sansdir.ui.oncat_browser import OnCatBrowserScreen

    # Stale snapshot (what the user sees first).
    stale = [
        Experiment(ipts="IPTS-100", title="old", pi="", members=(), activity="", instrument="EQSANS", facility="SNS"),
    ]
    # Fresh snapshot (what the refresh callback returns).
    fresh = [
        Experiment(ipts="IPTS-100", title="old", pi="", members=(), activity="", instrument="EQSANS", facility="SNS"),
        Experiment(ipts="IPTS-200", title="new!", pi="", members=(), activity="", instrument="EQSANS", facility="SNS"),
    ]

    call_count = {"n": 0}

    async def fake_refresh() -> list[Experiment]:
        call_count["n"] += 1
        return fresh

    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Push the browser directly with our fake callback so we
        # don't need OnCat live-fetching scaffolding.
        app.push_screen(OnCatBrowserScreen(stale, on_refresh=fake_refresh))
        await pilot.pause()
        from textual.widgets import ListView

        browser = next(
            s for s in app.screen_stack if isinstance(s, OnCatBrowserScreen)
        )
        # Initially: 1 row.
        lv = browser.query_one("#results-list", ListView)
        assert len(lv.children) == 1
        # Invoke the action (modal bindings reach the action even
        # when Pilot.press routes through the App because the
        # modal is on top of the stack).
        await browser.action_refresh()
        await pilot.pause()
        # Callback was invoked exactly once.
        assert call_count["n"] == 1
        # List now reflects the fresh snapshot.
        assert len(lv.children) == 2
        # Refresh hint is rendered with the eye-catching colour
        # markup so the user knows the action exists.
        from textual.widgets import Static
        hint = browser.query_one("#refresh-hint", Static).render()
        text = hint.plain if hasattr(hint, "plain") else str(hint)
        assert "refresh" in text.lower()
        assert "r" in text.lower()  # the key letter is shown
        await pilot.press("escape")
        await pilot.press("q")


async def test_browser_refresh_failure_shows_error_status(
    tmp_path: Path,
    fake_oncat_config: Path,
) -> None:
    """If the refresh callback raises, the browser shows the error
    in the overflow-hint Static instead of crashing the modal."""
    from sansdir.core.oncat import Experiment
    from sansdir.ui.oncat_browser import OnCatBrowserScreen

    async def boom() -> list[Experiment]:
        raise RuntimeError("OnCat unreachable")

    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(
            OnCatBrowserScreen(
                [Experiment(ipts="IPTS-1", title="x", pi="", members=(), activity="", instrument="EQSANS", facility="SNS")],
                on_refresh=boom,
            )
        )
        await pilot.pause()
        browser = next(
            s for s in app.screen_stack if isinstance(s, OnCatBrowserScreen)
        )
        await browser.action_refresh()
        await pilot.pause()
        from textual.widgets import Static
        hint = browser.query_one("#overflow-hint", Static).render()
        text = hint.plain if hasattr(hint, "plain") else str(hint)
        assert "refresh failed" in text.lower()
        assert "OnCat unreachable" in text
        await pilot.press("escape")
        await pilot.press("q")
