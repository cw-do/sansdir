"""Tests for sansdir.core.oncat — pytest-httpx mocks all OnCat traffic."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx
import pytest

from sansdir.config import OnCatConfig
from sansdir.core import oncat

EXPERIMENTS_RE = re.compile(r"https://oncat\.test/api/experiments\b.*")
DATAFILES_RE = re.compile(r"https://oncat\.test/api/datafiles\b.*")


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANSDIR_CACHE_DIR", str(tmp_path / "cache"))


def _config(client_id: str = "id", client_secret: str = "secret") -> OnCatConfig:
    return OnCatConfig(
        endpoint="https://oncat.test",
        client_id=client_id,
        client_secret=client_secret,
        default_instrument="EQSANS",
        cache_ttl_seconds=3600,
        request_timeout_seconds=5.0,
    )


def _stub_token(httpx_mock, *, expires_in: int = 3600) -> None:  # type: ignore[no-untyped-def]
    httpx_mock.add_response(
        method="POST",
        url="https://oncat.test/oauth/token",
        json={"access_token": "tk", "expires_in": expires_in, "token_type": "Bearer"},
    )


def _stub_experiments(httpx_mock, rows: list[dict]) -> None:  # type: ignore[no-untyped-def]
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"https://oncat\.test/api/experiments\b.*"),
        json=rows,
    )


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


async def test_cache_with_old_schema_version_is_discarded(
    httpx_mock,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    """A pre-fix cache (no `version` field, or wrong version) is ignored."""
    cache_file = tmp_path / "cache" / "oncat" / "SNS-EQSANS-experiments.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                # No version key — counts as version 0.
                "fetched_at": time.time(),  # current — would otherwise hit
                "experiments": [
                    {
                        "ipts": "IPTS-STALE",
                        "title": "stringified-dict garbage",
                        "pi": "x",
                        "members": ["{'name': 'X'}"],  # the bug we fixed
                        "activity": "",
                        "instrument": "EQSANS",
                        "facility": "SNS",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    _stub_token(httpx_mock)
    httpx_mock.add_response(method="GET", url=EXPERIMENTS_RE, json=SAMPLE_ROWS)
    async with oncat.OnCatClient(_config()) as client:
        hits = await client.search_experiments("")
    # Stale entry rejected; fresh OnCat fetch happened instead.
    assert "IPTS-STALE" not in {h.ipts for h in hits}


def test_normalise_datafile_extracts_daslogs() -> None:
    raw = {
        "indexed": {"run_number": 12345},
        "metadata": {
            "entry": {
                "title": "sample",
                "start_time": "2026-04-25T08:00:00",
                "duration": 1200.0,
                "total_counts": 1234567,
                "daslogs": {
                    "detectorz": {"average_value": 4.0},
                    "wavelength": {"average_value": 2.5},
                },
            }
        },
    }
    d = oncat._normalise_datafile(raw)
    assert d.run_number == 12345
    assert d.detector_distance_m == 4.0
    assert d.wavelength_a == 2.5
    assert d.total_counts == 1234567


# ---------------------------------------------------------------------------
# OAuth token flow
# ---------------------------------------------------------------------------


async def test_missing_credentials_raises_auth_error(tmp_path: Path) -> None:
    cfg = _config(client_id="", client_secret="")
    async with oncat.OnCatClient(cfg) as client:
        with pytest.raises(oncat.OnCatAuthError, match="no OnCat credentials"):
            await client.search_experiments("anything")


async def test_token_fetched_once_and_reused(httpx_mock) -> None:  # type: ignore[no-untyped-def]
    _stub_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=EXPERIMENTS_RE,
        json=[],
    )
    httpx_mock.add_response(
        method="GET",
        url=EXPERIMENTS_RE,
        json=[],
    )
    async with oncat.OnCatClient(_config()) as client:
        await client.search_experiments("x", instrument="A")
        await client.search_experiments("x", instrument="B")
    # One POST to /oauth/token total, even across two GETs (different
    # instruments → different cache keys → both hit the network).
    posts = [r for r in httpx_mock.get_requests() if r.method == "POST"]
    assert len(posts) == 1


async def test_oauth_failure_surfaces_clean_error(httpx_mock) -> None:  # type: ignore[no-untyped-def]
    httpx_mock.add_response(
        method="POST",
        url="https://oncat.test/oauth/token",
        status_code=401,
        text="bad credentials",
    )
    async with oncat.OnCatClient(_config()) as client:
        with pytest.raises(oncat.OnCatAuthError, match="oauth failed"):
            await client.search_experiments("x")


async def test_network_error_wraps_to_oncat_error(httpx_mock) -> None:  # type: ignore[no-untyped-def]
    httpx_mock.add_exception(
        httpx.ConnectError("boom"),
        method="POST",
        url="https://oncat.test/oauth/token",
    )
    async with oncat.OnCatClient(_config()) as client:
        with pytest.raises(oncat.OnCatNetworkError, match="oauth request failed"):
            await client.search_experiments("x")


# ---------------------------------------------------------------------------
# Listing + searching
# ---------------------------------------------------------------------------


SAMPLE_ROWS = [
    {
        "id": "IPTS-12345",
        "title": "Bio-membrane assembly under shear",
        "members": ["Alice", "Bob"],
        "activity": "2024-04-01",
    },
    {
        "id": "IPTS-22222",
        "title": "Polymer micelle structure",
        "members": ["Carol"],
        "activity": "2024-03-15",
    },
    {
        "id": "IPTS-33333",
        "title": "Membrane protein refolding",
        "members": ["Bob"],
        "activity": "2024-02-01",
    },
]


async def test_search_filters_by_keyword(httpx_mock) -> None:  # type: ignore[no-untyped-def]
    _stub_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=EXPERIMENTS_RE,
        json=SAMPLE_ROWS,
    )
    async with oncat.OnCatClient(_config()) as client:
        hits = await client.search_experiments("membrane")
    ids = {h.ipts for h in hits}
    assert ids == {"IPTS-12345", "IPTS-33333"}


async def test_search_matches_pi_or_member(httpx_mock) -> None:  # type: ignore[no-untyped-def]
    _stub_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=EXPERIMENTS_RE,
        json=SAMPLE_ROWS,
    )
    async with oncat.OnCatClient(_config()) as client:
        hits = await client.search_experiments("bob")
    ids = {h.ipts for h in hits}
    assert ids == {"IPTS-12345", "IPTS-33333"}


async def test_search_respects_limit(httpx_mock) -> None:  # type: ignore[no-untyped-def]
    _stub_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=EXPERIMENTS_RE,
        json=SAMPLE_ROWS,
    )
    async with oncat.OnCatClient(_config()) as client:
        hits = await client.search_experiments("", limit=2)
    assert len(hits) == 2


# ---------------------------------------------------------------------------
# Caching: in-memory + on-disk
# ---------------------------------------------------------------------------


async def test_in_memory_cache_skips_network_on_repeat(httpx_mock) -> None:  # type: ignore[no-untyped-def]
    _stub_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=EXPERIMENTS_RE,
        json=SAMPLE_ROWS,
    )
    async with oncat.OnCatClient(_config()) as client:
        await client.search_experiments("a")
        await client.search_experiments("b")
    # Only one GET to /api/experiments — the second search reuses cache.
    gets = [r for r in httpx_mock.get_requests() if r.method == "GET"]
    assert len(gets) == 1


async def test_disk_cache_survives_new_client(httpx_mock, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _stub_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=EXPERIMENTS_RE,
        json=SAMPLE_ROWS,
    )
    cfg = _config()
    async with oncat.OnCatClient(cfg) as client1:
        await client1.search_experiments("a")
    # New client with empty in-memory cache reads the disk JSON written above.
    async with oncat.OnCatClient(cfg) as client2:
        hits = await client2.search_experiments("polymer")
    assert {h.ipts for h in hits} == {"IPTS-22222"}
    # Disk cache file exists under the configured cache dir.
    assert (tmp_path / "cache" / "oncat").exists()


async def test_expired_disk_cache_triggers_refetch(
    httpx_mock,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
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
    _stub_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=EXPERIMENTS_RE,
        json=SAMPLE_ROWS,
    )
    async with oncat.OnCatClient(_config()) as client:
        hits = await client.search_experiments("")
    ids = {h.ipts for h in hits}
    assert "IPTS-OLD" not in ids


# ---------------------------------------------------------------------------
# Datafile listing
# ---------------------------------------------------------------------------


async def test_list_datafiles_normalises_rows(httpx_mock) -> None:  # type: ignore[no-untyped-def]
    _stub_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=DATAFILES_RE,
        json=[
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
        ],
    )
    async with oncat.OnCatClient(_config()) as client:
        files = await client.list_datafiles("12345")
    assert [f.run_number for f in files] == [12001, 12002]
    assert files[1].title == "sample A"
    assert files[0].duration_s == 600.0
