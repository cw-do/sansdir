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
        # F2 toggles back to the filelist.
        await pilot.press("f2")
        await pilot.pause()
        assert not slot.catalog_visible
        # F2 again brings the catalog back without another OnCat round-trip.
        await pilot.press("f2")
        await pilot.pause()
        assert slot.catalog_visible
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


async def test_f2_without_loaded_catalog_notifies(tmp_path: Path, fake_oncat_config: Path) -> None:
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f2")
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
