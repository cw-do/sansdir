"""Tests for sansdir.core.oncat.

Network access is mocked by injecting a fake pyoncat client into
``OnCatClient(client=...)``; no real HTTP or browser flow is exercised. The
per-user device-flow helpers (login/status/logout/token_path) are tested
against the filesystem with an isolated token path.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from sansdir.config import OnCatConfig
from sansdir.core import oncat


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))
    # Point the personal token at a path that does not exist by default, and
    # clear any real password-grant env so tests are hermetic.
    monkeypatch.setenv("SANSDIR_ONCAT_TOKEN", str(tmp_path / "token.json"))
    for var in ("ONCAT_USERNAME", "ONCAT_PASSWORD", "ONCAT_CLIENT_ID", "ONCAT_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)


def _config() -> OnCatConfig:
    return OnCatConfig(
        endpoint="https://oncat.test",
        default_instrument="EQSANS",
        cache_ttl_seconds=3600,
        request_timeout_seconds=5.0,
    )


# ---------------------------------------------------------------------------
# Fake pyoncat client
# ---------------------------------------------------------------------------


class _FakeObj:
    """Stands in for a pyoncat ONCatObject: carries a nested dict, to_dict()."""

    def __init__(self, content: dict[str, Any]) -> None:
        self._content = content

    def to_dict(self) -> dict[str, Any]:
        return self._content


class _Endpoint:
    def __init__(self, rows: list[dict[str, Any]], counter: dict[str, int], key: str) -> None:
        self._rows = rows
        self._counter = counter
        self._key = key

    def list(self, **_kwargs: Any) -> list[_FakeObj]:
        self._counter[self._key] += 1
        return [_FakeObj(r) for r in self._rows]


class FakeONCat:
    """Minimal stand-in for ``pyoncat.ONCat`` used by OnCatClient."""

    def __init__(
        self,
        *,
        experiments: list[dict[str, Any]] | None = None,
        datafiles: list[dict[str, Any]] | None = None,
        login_error: Exception | None = None,
        list_error: Exception | None = None,
    ) -> None:
        self._experiments = experiments or []
        self._datafiles = datafiles or []
        self._login_error = login_error
        self._list_error = list_error
        self.calls = {"login": 0, "experiments": 0, "datafiles": 0}

    def login(self) -> None:
        self.calls["login"] += 1
        if self._login_error is not None:
            raise self._login_error

    @property
    def Experiment(self) -> _Endpoint:  # noqa: N802 - mirrors pyoncat's attribute name
        if self._list_error is not None:
            raise self._list_error
        return _Endpoint(self._experiments, self.calls, "experiments")

    @property
    def Datafile(self) -> _Endpoint:  # noqa: N802 - mirrors pyoncat's attribute name
        if self._list_error is not None:
            raise self._list_error
        return _Endpoint(self._datafiles, self.calls, "datafiles")


SAMPLE_ROWS = [
    {
        "id": "IPTS-12345",
        "rank": 12345,
        "title": "Bio-membrane assembly under shear",
        "members": ["Alice", "Bob"],
        "activity": "2024-04-01",
    },
    {
        "id": "IPTS-22222",
        "rank": 22222,
        "title": "Polymer micelle structure",
        "members": ["Carol"],
        "activity": "2024-03-15",
    },
    {
        "id": "IPTS-33333",
        "rank": 33333,
        "title": "Membrane protein refolding",
        "members": ["Bob"],
        "activity": "2024-02-01",
    },
]


# ---------------------------------------------------------------------------
# Experiment dataclass behavior
# ---------------------------------------------------------------------------


def test_experiment_matches_keyword() -> None:
    e = oncat.Experiment(
        ipts="IPTS-12345",
        title="Bio-membrane assembly",
        pi="Alice",
        members=("Alice", "Bob"),
        activity="2024-04-01",
        instrument="EQSANS",
        facility="SNS",
    )
    assert e.matches("bio")
    assert e.matches("BIO-MEMBRANE")
    assert e.matches("12345")
    assert e.matches("alice")
    assert e.matches("bob")
    assert not e.matches("zzz")
    assert e.matches("")  # empty keyword always matches


def test_experiment_cluster_path() -> None:
    e = oncat.Experiment(
        ipts="IPTS-9",
        title="x",
        pi="x",
        members=(),
        activity="",
        instrument="EQSANS",
        facility="SNS",
    )
    assert e.cluster_path() == Path("/SNS/EQSANS/IPTS-9")
    assert e.cluster_path("/scratch/test") == Path("/scratch/test/EQSANS/IPTS-9")


def test_experiment_hfir_facility_uses_hfir_root() -> None:
    e = oncat.Experiment(
        ipts="IPTS-7",
        title="x",
        pi="x",
        members=(),
        activity="",
        instrument="BIOSANS",
        facility="HFIR",
    )
    assert e.cluster_path() == Path("/HFIR/BIOSANS/IPTS-7")


def test_experiment_date_range_and_members_summary() -> None:
    e = oncat.Experiment(
        ipts="IPTS-1",
        title="x",
        pi="A",
        members=("Alice", "Bob", "Carol", "Dave", "Eve"),
        activity="",
        instrument="EQSANS",
        facility="SNS",
        acquisition_start="2026-04-25T08:00:00",
        acquisition_end="2026-04-27T20:00:00",
    )
    assert e.date_range() == "2026-04-25 — 2026-04-27"
    assert e.members_summary(max_shown=3) == "Alice, Bob, Carol (+2)"
    assert e.members_summary(max_shown=10) == "Alice, Bob, Carol, Dave, Eve"


def test_experiment_date_range_handles_missing() -> None:
    e = oncat.Experiment(
        ipts="IPTS-1",
        title="",
        pi="",
        members=(),
        activity="",
        instrument="EQSANS",
        facility="SNS",
    )
    assert e.date_range() == ""


def test_normalise_experiment_pulls_size_and_acquisition() -> None:
    raw = {
        "id": "IPTS-42",
        "title": "X",
        "members": ["A"],
        "size": 151,
        "activity": {"acquisition": {"start": "2026-04-25", "end": "2026-04-27"}},
    }
    e = oncat._normalise_experiment(raw, "EQSANS", "SNS")
    assert e.runs_count == 151
    assert e.acquisition_start == "2026-04-25"
    assert e.acquisition_end == "2026-04-27"


def test_normalise_experiment_real_oncat_shape() -> None:
    """OnCat returns members as dicts and acquisition as a list of timestamps."""
    raw = {
        "id": "IPTS-37211",
        "rank": 37211,
        "title": "Elucidating Solvent Effects",
        "size": 151,
        "members": [
            {"name": "Solomon, Chandler", "email": "x@y", "orcid": "0000-0001"},
            {"name": "Davis, Eric", "email": "y@z"},
        ],
        "activity": {
            "acquisition": ["2026-04-01T08:00:00", "2026-04-02", "2026-04-03T20:00"],
        },
    }
    e = oncat._normalise_experiment(raw, "EQSANS", "SNS")
    assert e.ipts == "IPTS-37211"
    assert e.runs_count == 151
    assert e.members == ("Solomon, Chandler", "Davis, Eric")
    assert e.acquisition_start == "2026-04-01T08:00:00"
    assert e.acquisition_end == "2026-04-03T20:00"
    assert e.date_range() == "2026-04-01 — 2026-04-03"


def test_normalise_experiment_member_with_first_last_only() -> None:
    raw = {
        "id": "IPTS-1",
        "members": [{"first_name": "Alice", "last_name": "Wong"}],
    }
    e = oncat._normalise_experiment(raw, "EQSANS", "SNS")
    assert e.members == ("Wong, Alice",)


def test_ipts_label_falls_back_to_id() -> None:
    assert oncat._ipts_label({"rank": 9}) == "IPTS-9"
    assert oncat._ipts_label({"id": "IPTS-9"}) == "IPTS-9"
    assert oncat._ipts_label({"id": "9"}) == "IPTS-9"
    assert oncat._ipts_label({}) == ""


def test_experiment_ipts_number_extracts_numeric_part() -> None:
    e = oncat.Experiment(
        ipts="IPTS-37211",
        title="",
        pi="",
        members=(),
        activity="",
        instrument="EQSANS",
        facility="SNS",
    )
    assert e.ipts_number == 37211


def test_experiment_ipts_number_zero_when_unparseable() -> None:
    e = oncat.Experiment(
        ipts="",
        title="",
        pi="",
        members=(),
        activity="",
        instrument="EQSANS",
        facility="SNS",
    )
    assert e.ipts_number == 0


def test_experiment_sort_date_key_prefers_end_then_start() -> None:
    e1 = oncat.Experiment(
        ipts="IPTS-1",
        title="",
        pi="",
        members=(),
        activity="",
        instrument="EQSANS",
        facility="SNS",
        acquisition_start="2024-01-01",
        acquisition_end="2024-01-05",
    )
    e2 = oncat.Experiment(
        ipts="IPTS-2",
        title="",
        pi="",
        members=(),
        activity="",
        instrument="EQSANS",
        facility="SNS",
        acquisition_start="2024-02-01",
        acquisition_end="",
    )
    e3 = oncat.Experiment(
        ipts="IPTS-3",
        title="",
        pi="",
        members=(),
        activity="",
        instrument="EQSANS",
        facility="SNS",
    )
    assert e1.sort_date_key == "2024-01-05"
    assert e2.sort_date_key == "2024-02-01"
    assert e3.sort_date_key == ""


def test_normalise_datafile_extracts_daslogs() -> None:
    """detectorz from OnCat is in mm; the dataclass keeps it raw and
    exposes ``detector_distance_m`` for the m unit."""
    raw = {
        "indexed": {"run_number": 12345},
        "metadata": {
            "entry": {
                "title": "sample",
                "start_time": "2026-04-25T08:00:00",
                "duration": 1200.0,
                "total_counts": 1234567,
                "daslogs": {
                    "detectorz": {"average_value": 4000.0},  # 4000 mm = 4 m
                    "wavelength": {"average_value": 2.5},
                },
            }
        },
    }
    d = oncat._normalise_datafile(raw)
    assert d.run_number == 12345
    assert d.detector_distance_mm == 4000.0
    assert d.detector_distance_m == 4.0
    assert d.wavelength_a == 2.5
    assert d.total_counts == 1234567


def test_datafile_detector_distance_m_property() -> None:
    """1300 mm → 1.3 m."""
    d = oncat.Datafile(
        run_number=1,
        title="",
        start_time="",
        duration_s=0,
        detector_distance_mm=1300.0,
    )
    assert d.detector_distance_m == 1.3


# ---------------------------------------------------------------------------
# _to_plain: pyoncat ONCatObject → nested plain dicts
# ---------------------------------------------------------------------------


def test_to_plain_recurses_into_nested_oncatobjects() -> None:
    """Nested ONCatObjects (not just the top level) must become plain dicts, or
    _normalise_datafile's isinstance(daslogs, dict) check silently fails."""
    nested = _FakeObj(
        {
            "indexed": _FakeObj({"run_number": 5}),
            "metadata": _FakeObj(
                {"entry": _FakeObj({"daslogs": _FakeObj({"detectorz": {"average_value": 2000.0}})})}
            ),
        }
    )
    plain = oncat._to_plain(nested)
    assert plain["indexed"]["run_number"] == 5
    d = oncat._normalise_datafile(plain)
    assert d.detector_distance_mm == 2000.0


# ---------------------------------------------------------------------------
# Listing + searching (via injected fake pyoncat client)
# ---------------------------------------------------------------------------


async def test_search_filters_by_keyword() -> None:
    fake = FakeONCat(experiments=SAMPLE_ROWS)
    async with oncat.OnCatClient(_config(), client=fake) as client:
        hits = await client.search_experiments("membrane")
    assert {h.ipts for h in hits} == {"IPTS-12345", "IPTS-33333"}


async def test_search_matches_pi_or_member() -> None:
    fake = FakeONCat(experiments=SAMPLE_ROWS)
    async with oncat.OnCatClient(_config(), client=fake) as client:
        hits = await client.search_experiments("bob")
    assert {h.ipts for h in hits} == {"IPTS-12345", "IPTS-33333"}


async def test_search_respects_limit() -> None:
    fake = FakeONCat(experiments=SAMPLE_ROWS)
    async with oncat.OnCatClient(_config(), client=fake) as client:
        hits = await client.search_experiments("", limit=2)
    assert len(hits) == 2


async def test_login_called_before_listing() -> None:
    fake = FakeONCat(experiments=SAMPLE_ROWS)
    async with oncat.OnCatClient(_config(), client=fake) as client:
        await client.search_experiments("")
    assert fake.calls["login"] == 1


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


async def test_auth_error_from_pyoncat_maps_to_oncat_auth_error() -> None:
    import pyoncat

    fake = FakeONCat(login_error=pyoncat.LoginRequiredError("expired"))
    async with oncat.OnCatClient(_config(), client=fake) as client:
        with pytest.raises(oncat.OnCatAuthError):
            await client.search_experiments("x")


async def test_generic_error_maps_to_network_error() -> None:
    fake = FakeONCat(list_error=RuntimeError("boom"))
    async with oncat.OnCatClient(_config(), client=fake) as client:
        with pytest.raises(oncat.OnCatNetworkError):
            await client.search_experiments("x")


async def test_not_signed_in_raises_auth_error(tmp_path: Path) -> None:
    """With no injected client, no token file, and no env creds, a data call
    raises a clear 'not signed in' error instead of silently using a shared
    account."""
    async with oncat.OnCatClient(_config()) as client:
        with pytest.raises(oncat.OnCatAuthError, match="Not signed in"):
            await client.search_experiments("x")


# ---------------------------------------------------------------------------
# Caching: in-memory + on-disk
# ---------------------------------------------------------------------------


async def test_in_memory_cache_skips_network_on_repeat() -> None:
    fake = FakeONCat(experiments=SAMPLE_ROWS)
    async with oncat.OnCatClient(_config(), client=fake) as client:
        await client.search_experiments("a")
        await client.search_experiments("b")
    # Only one listing call — the second search reuses the in-memory cache.
    assert fake.calls["experiments"] == 1


async def test_disk_cache_survives_new_client(tmp_path: Path) -> None:
    cfg = _config()
    fake1 = FakeONCat(experiments=SAMPLE_ROWS)
    async with oncat.OnCatClient(cfg, client=fake1) as client1:
        await client1.search_experiments("a")
    # New client with a fresh in-memory cache reads the disk JSON written above;
    # its fake would report a listing call if the network were hit.
    fake2 = FakeONCat(experiments=SAMPLE_ROWS)
    async with oncat.OnCatClient(cfg, client=fake2) as client2:
        hits = await client2.search_experiments("polymer")
    assert {h.ipts for h in hits} == {"IPTS-22222"}
    assert fake2.calls["experiments"] == 0
    assert (tmp_path / "cache" / "oncat").exists()


async def test_cache_with_old_schema_version_is_discarded(tmp_path: Path) -> None:
    """A pre-fix cache (no `version` field) is ignored and refetched."""
    cache_file = tmp_path / "cache" / "oncat" / "SNS-EQSANS-experiments.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "fetched_at": time.time(),  # current — would otherwise hit
                "experiments": [
                    {
                        "ipts": "IPTS-STALE",
                        "title": "stringified-dict garbage",
                        "pi": "x",
                        "members": ["{'name': 'X'}"],
                        "activity": "",
                        "instrument": "EQSANS",
                        "facility": "SNS",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fake = FakeONCat(experiments=SAMPLE_ROWS)
    async with oncat.OnCatClient(_config(), client=fake) as client:
        hits = await client.search_experiments("")
    assert "IPTS-STALE" not in {h.ipts for h in hits}
    assert fake.calls["experiments"] == 1


async def test_expired_disk_cache_triggers_refetch(tmp_path: Path) -> None:
    cache_file = tmp_path / "cache" / "oncat" / "SNS-EQSANS-experiments.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "version": oncat.CACHE_SCHEMA_VERSION,
                "fetched_at": 0.0,  # epoch — definitely expired
                "experiments": [
                    {
                        "ipts": "IPTS-OLD",
                        "title": "stale",
                        "pi": "x",
                        "members": ["x"],
                        "activity": "",
                        "instrument": "EQSANS",
                        "facility": "SNS",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fake = FakeONCat(experiments=SAMPLE_ROWS)
    async with oncat.OnCatClient(_config(), client=fake) as client:
        hits = await client.search_experiments("")
    assert "IPTS-OLD" not in {h.ipts for h in hits}


# ---------------------------------------------------------------------------
# Datafile listing
# ---------------------------------------------------------------------------


async def test_list_datafiles_normalises_rows() -> None:
    fake = FakeONCat(
        datafiles=[
            {
                "indexed": {"run_number": 12001},
                "metadata": {
                    "entry": {
                        "title": "background",
                        "start_time": "2024-04-01T08:00:00",
                        "duration": 600.0,
                    }
                },
            },
            {
                "indexed": {"run_number": 12002},
                "metadata": {
                    "entry": {
                        "title": "sample A",
                        "start_time": "2024-04-01T08:30:00",
                        "duration": 1200.0,
                    }
                },
            },
        ]
    )
    async with oncat.OnCatClient(_config(), client=fake) as client:
        files = await client.list_datafiles("12345")
    assert [f.run_number for f in files] == [12001, 12002]
    assert files[1].title == "sample A"
    assert files[0].duration_s == 600.0


# ---------------------------------------------------------------------------
# Per-user sign-in helpers
# ---------------------------------------------------------------------------


def test_token_path_honours_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_ONCAT_TOKEN", str(tmp_path / "custom.json"))
    assert oncat.token_path(_config()) == tmp_path / "custom.json"


def test_token_path_falls_back_to_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SANSDIR_ONCAT_TOKEN", raising=False)
    cfg = OnCatConfig(token_path=str(tmp_path / "cfg.json"))
    assert oncat.token_path(cfg) == tmp_path / "cfg.json"


def test_is_signed_in_reflects_token_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token = tmp_path / "tok.json"
    monkeypatch.setenv("SANSDIR_ONCAT_TOKEN", str(token))
    cfg = _config()
    assert not oncat.is_signed_in(cfg)
    token.write_text("{}", encoding="utf-8")
    assert oncat.is_signed_in(cfg)


def test_is_signed_in_true_with_env_password_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    for var, val in (
        ("ONCAT_USERNAME", "u"),
        ("ONCAT_PASSWORD", "p"),
        ("ONCAT_CLIENT_ID", "c"),
        ("ONCAT_CLIENT_SECRET", "s"),
    ):
        monkeypatch.setenv(var, val)
    assert oncat.is_signed_in(_config())


def test_sign_out_removes_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token = tmp_path / "tok.json"
    monkeypatch.setenv("SANSDIR_ONCAT_TOKEN", str(token))
    token.write_text("{}", encoding="utf-8")
    cfg = _config()
    assert oncat.sign_out(cfg) is True
    assert not token.exists()
    # Second call: nothing to remove.
    assert oncat.sign_out(cfg) is False


# ---------------------------------------------------------------------------
# Command registry: oncat status / logout / router
# ---------------------------------------------------------------------------


async def test_oncat_status_and_logout_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_phase1_commands import FakeApp, FakePanel, bind_registry

    token = tmp_path / "tok.json"
    monkeypatch.setenv("SANSDIR_ONCAT_TOKEN", str(token))
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "nope.toml"))  # defaults
    app = FakeApp(left=FakePanel(cwd=tmp_path), right=FakePanel(cwd=tmp_path))
    reg = bind_registry(app)

    await reg.dispatch("oncat.status")
    assert "not signed in" in app.notifications[-1]

    token.write_text("{}", encoding="utf-8")
    await reg.dispatch("oncat.status")
    assert "signed in" in app.notifications[-1]

    await reg.dispatch("oncat.logout")
    assert "signed out" in app.notifications[-1]
    assert not token.exists()


async def test_oncat_router_delegates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_phase1_commands import FakeApp, FakePanel, bind_registry

    monkeypatch.setenv("SANSDIR_ONCAT_TOKEN", str(tmp_path / "tok.json"))
    monkeypatch.setenv("SANSDIR_CONFIG", str(tmp_path / "nope.toml"))
    app = FakeApp(left=FakePanel(cwd=tmp_path), right=FakePanel(cwd=tmp_path))
    reg = bind_registry(app)

    # Bare 'oncat' defaults to status.
    await reg.dispatch("oncat")
    assert "OnCat:" in app.notifications[-1]
    # Explicit logout routes through to oncat.logout.
    await reg.dispatch("oncat", action="logout")
    assert "token" in app.notifications[-1].lower()
