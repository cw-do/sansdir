"""End-to-end Pilot tests for Phase 4 — `i` IPTS search."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sansdir.app import SansdirApp
from sansdir.core.history import CommandHistory

EXPERIMENTS_RE = re.compile(r"https://oncat\.test/api/experiments\b.*")


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture
def fake_oncat_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Drop a config that points at the test OnCat endpoint with credentials."""
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


def _stub_oncat(
    httpx_mock,  # type: ignore[no-untyped-def]
    rows: list[dict],
) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://oncat.test/oauth/token",
        json={"access_token": "tk", "expires_in": 3600},
    )
    httpx_mock.add_response(method="GET", url=EXPERIMENTS_RE, json=rows)


# ---------------------------------------------------------------------------
# DoD: type `i bio-membrane`, pick a result, active pane jumps to /SNS/...
# ---------------------------------------------------------------------------


async def test_phase4_dod_i_search_and_cd(
    tmp_path: Path,
    httpx_mock,  # type: ignore[no-untyped-def]
    fake_oncat_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Make the cluster path that matches the chosen IPTS exist locally so
    # the cd succeeds. The OnCat client returns Experiment.cluster_path
    # rooted at `/SNS` by default; we override it for the test by
    # monkey-patching the dataclass method.
    fake_root = tmp_path / "SNS_FAKE"
    (fake_root / "EQSANS" / "IPTS-12345").mkdir(parents=True)

    from sansdir.core import oncat as oncat_mod

    original_cluster_path = oncat_mod.Experiment.cluster_path

    def fake_cluster_path(self, root: str = "/SNS") -> Path:  # type: ignore[no-untyped-def]
        return original_cluster_path(self, str(fake_root))

    monkeypatch.setattr(oncat_mod.Experiment, "cluster_path", fake_cluster_path)

    _stub_oncat(
        httpx_mock,
        [
            {
                "id": "IPTS-12345",
                "title": "Bio-membrane assembly under shear",
                "members": ["Alice", "Bob"],
                "activity": "2024-04-01",
            },
            {
                "id": "IPTS-22222",
                "title": "Polymer micelles",
                "members": ["Carol"],
                "activity": "2024-03-15",
            },
        ],
    )

    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # `i` opens the cmdline pre-filled with "ipts ".
        await pilot.press("i")
        await pilot.pause()
        assert app._cmdline.value == "ipts "
        # Type the keyword and submit.
        for ch in "membrane":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        # OnCat results dialog should now be on the screen stack.
        assert any(type(s).__name__ == "OnCatResultsDialog" for s in app.screen_stack), (
            f"expected OnCatResultsDialog in {[type(s).__name__ for s in app.screen_stack]}"
        )
        # Press Enter to pick the cursor row (row 0 = the single match).
        await pilot.press("enter")
        await pilot.pause()
        # Active pane should now be at the IPTS dir.
        target = fake_root / "EQSANS" / "IPTS-12345"
        assert app.active_panel.cwd == target.resolve()
        await pilot.press("q")


async def test_no_matches_notifies_and_skips_dialog(
    tmp_path: Path,
    httpx_mock,  # type: ignore[no-untyped-def]
    fake_oncat_config: Path,
) -> None:
    _stub_oncat(httpx_mock, [])
    app = _real_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        for ch in "ghost":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        # No OnCat dialog — only the main screen on the stack.
        assert len(app.screen_stack) == 1
        await pilot.press("q")


async def test_oncat_auth_error_surfaces_clean_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Explicitly empty credentials → OnCatAuthError; UI must notify and
    # stay alive. We override BOTH the config and the env vars so the
    # built-in defaults can't accidentally make the test hit a real
    # network.
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
        for ch in "anything":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        # No dialog opened; the app is still responsive.
        assert len(app.screen_stack) == 1
        await pilot.press("q")
