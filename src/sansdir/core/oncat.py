"""Async OnCat client.

Cross-checked against the ``pyoncat`` usage in ``cw-do/eqsanscli``
(``src/eqsanscli/integrations/oncat.py``); re-implemented in plain
``httpx.AsyncClient`` so we don't take on a Mantid/PyORNL dependency.

Auth flow: OAuth2 ``client_credentials`` grant against
``/oauth/token``; the resulting bearer token is cached until just
before its ``expires_in`` window closes. Endpoints, credentials, and
the cache TTL all come from :class:`sansdir.config.OnCatConfig` so a
user can point at a staging instance or paste their own ``client_id``
without touching code.

OnCat doesn't expose a fuzzy "search by keyword" endpoint — instead we
list every experiment for the configured instrument (cheap on the
server, big-but-rare from our side) and filter client-side. The full
listing is cached on disk for the configured TTL so subsequent
searches are sub-second.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from sansdir.config import OnCatConfig
from sansdir.core.history import default_history_path

DEFAULT_PROJECTION_EXPERIMENT: tuple[str, ...] = (
    "id",
    "rank",
    "title",
    "members",
    "size",
    "activity",
)

# Bump whenever the on-disk cache JSON shape changes — older entries are
# silently discarded on read, forcing a fresh OnCat fetch. We're at v2
# after the fix that changed members from str(dict) to extracted names
# and that adds runs_count + acquisition_start/end.
CACHE_SCHEMA_VERSION: int = 2
# Datafile fields needed for the run-catalog DataTable (run_number / title /
# detector distance / wavelength / total counts / duration). Mirrors the
# PROJECTION constant in cw-do/eqsanscli/src/eqsanscli/integrations/oncat.py.
DEFAULT_PROJECTION_DATAFILE: tuple[str, ...] = (
    "indexed.run_number",
    "metadata.entry.title",
    "metadata.entry.start_time",
    "metadata.entry.duration",
    "metadata.entry.total_counts",
    "metadata.entry.daslogs.detectorz.average_value",
    "metadata.entry.daslogs.wavelength.average_value",
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Experiment:
    """One row of OnCat experiment-list output, normalised.

    The "summary" fields (``runs_count``, ``acquisition_start``,
    ``acquisition_end``) come straight from OnCat's ``size`` and
    ``activity.acquisition.{start,end}`` — no extra round trip required
    to count runs per IPTS.
    """

    ipts: str  # e.g. "IPTS-12345"
    title: str
    pi: str
    members: tuple[str, ...]
    activity: str  # last-active date (free-text from OnCat)
    instrument: str
    facility: str
    runs_count: int = 0
    acquisition_start: str = ""
    acquisition_end: str = ""

    def matches(self, keyword: str) -> bool:
        """Case-insensitive substring match against id / title / any member."""
        if not keyword:
            return True
        kw = keyword.lower()
        if kw in self.ipts.lower() or kw in self.title.lower():
            return True
        return any(kw in m.lower() for m in self.members)

    def cluster_path(self, root: str | None = None) -> Path:
        """Conventional on-disk path: ``/<FACILITY>/<INSTR>/IPTS-NNNNN``.

        ``root`` overrides the facility-derived prefix (handy for tests).
        """
        prefix = Path(root) if root else Path("/") / self.facility
        return prefix / self.instrument / self.ipts

    def date_range(self) -> str:
        """Human-readable date range, ``""`` if unavailable."""
        if not self.acquisition_start and not self.acquisition_end:
            return ""
        if self.acquisition_start == self.acquisition_end:
            return _short_date(self.acquisition_start)
        return f"{_short_date(self.acquisition_start)} — {_short_date(self.acquisition_end)}"

    def members_summary(self, max_shown: int = 3) -> str:
        """Comma-list of the first ``max_shown`` members, with ``(+N)`` overflow."""
        if not self.members:
            return ""
        head = list(self.members[:max_shown])
        rest = len(self.members) - len(head)
        out = ", ".join(head)
        if rest > 0:
            out += f" (+{rest})"
        return out


def _short_date(timestamp: str) -> str:
    """Trim an OnCat ISO timestamp down to ``YYYY-MM-DD``; pass through otherwise."""
    return timestamp[:10] if timestamp else ""


@dataclass(frozen=True, slots=True)
class Datafile:
    """One run-file row from OnCat datafiles listing."""

    run_number: int
    title: str
    start_time: str
    duration_s: float
    total_counts: int = 0
    detector_distance_m: float = 0.0
    wavelength_a: float = 0.0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OnCatError(RuntimeError):
    """Base for all OnCat-related failures surfaced to the UI."""


class OnCatAuthError(OnCatError):
    """Raised when OAuth fails or no credentials are configured."""


class OnCatNetworkError(OnCatError):
    """Connection or HTTP-level failure that isn't an auth issue."""


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_dir() -> Path:
    return default_history_path().parent / "oncat"


@dataclass
class _CacheEntry:
    fetched_at: float
    experiments: list[Experiment] = field(default_factory=list)


def _disk_path(instrument: str, facility: str) -> Path:
    return _cache_dir() / f"{facility}-{instrument}-experiments.json"


def _load_disk_cache(instrument: str, facility: str, ttl: float) -> list[Experiment] | None:
    path = _disk_path(instrument, facility)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    # Reject caches written by an older code path with a different row
    # shape (e.g. members serialized as `str(dict)` strings).
    if int(data.get("version", 0)) != CACHE_SCHEMA_VERSION:
        return None
    fetched_at = float(data.get("fetched_at", 0))
    if time.time() - fetched_at > ttl:
        return None
    rows = data.get("experiments", [])
    return [Experiment(**_promote_members(r)) for r in rows]


def _save_disk_cache(experiments: list[Experiment], instrument: str, facility: str) -> None:
    path = _disk_path(instrument, facility)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "version": CACHE_SCHEMA_VERSION,
                    "fetched_at": time.time(),
                    "experiments": [{**asdict(e), "members": list(e.members)} for e in experiments],
                },
                indent=0,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def _promote_members(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw cache row back into an Experiment-friendly dict."""
    out = dict(raw)
    out["members"] = tuple(out.get("members", []))
    return out


# ---------------------------------------------------------------------------
# OnCat client
# ---------------------------------------------------------------------------


class OnCatClient:
    """Thin async wrapper around OnCat's REST API."""

    def __init__(
        self,
        config: OnCatConfig,
        *,
        client: httpx.AsyncClient | None = None,
        in_memory_cache: dict[str, _CacheEntry] | None = None,
    ) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(
            base_url=config.endpoint,
            timeout=config.request_timeout_seconds,
        )
        self._owns_client = client is None
        self._mem: dict[str, _CacheEntry] = in_memory_cache if in_memory_cache is not None else {}
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    async def __aenter__(self) -> OnCatClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ---- auth -----------------------------------------------------------

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        if not self._config.client_id or not self._config.client_secret:
            raise OnCatAuthError(
                "no OnCat credentials configured — set [oncat].client_id / "
                "client_secret in ~/.config/sansdir/config.toml or the "
                "ONCAT_CLIENT_ID / ONCAT_CLIENT_SECRET env vars"
            )
        try:
            resp = await self._client.post(
                "/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._config.client_id,
                    "client_secret": self._config.client_secret,
                },
            )
        except httpx.RequestError as exc:
            raise OnCatNetworkError(f"oauth request failed: {exc}") from exc
        if resp.status_code != 200:
            raise OnCatAuthError(f"oauth failed: HTTP {resp.status_code} — {resp.text[:200]}")
        body = resp.json()
        token = str(body.get("access_token") or "")
        if not token:
            raise OnCatAuthError("oauth response missing access_token")
        self._token = token
        # Refresh slightly before the server-stated expiry.
        self._token_expires_at = time.time() + float(body.get("expires_in", 3600))
        return token

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        token = await self._get_token()
        try:
            resp = await self._client.get(
                path,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.RequestError as exc:
            raise OnCatNetworkError(f"GET {path} failed: {exc}") from exc
        if resp.status_code == 401:
            # Maybe the token expired between check and use; retry once.
            self._token = None
            token = await self._get_token()
            try:
                resp = await self._client.get(
                    path,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.RequestError as exc:
                raise OnCatNetworkError(f"GET {path} retry failed: {exc}") from exc
        if resp.status_code >= 400:
            raise OnCatNetworkError(f"GET {path}: HTTP {resp.status_code} — {resp.text[:200]}")
        return resp.json()

    # ---- experiments ----------------------------------------------------

    async def list_experiments(
        self,
        *,
        instrument: str | None = None,
        facility: str = "SNS",
        use_cache: bool = True,
    ) -> list[Experiment]:
        """Return every experiment for ``instrument`` (cached)."""
        instrument = instrument or self._config.default_instrument
        cache_key = f"{facility}:{instrument}"
        ttl = float(self._config.cache_ttl_seconds)
        if use_cache and cache_key in self._mem:
            entry = self._mem[cache_key]
            if time.time() - entry.fetched_at <= ttl:
                return entry.experiments
        if use_cache:
            on_disk = _load_disk_cache(instrument, facility, ttl)
            if on_disk is not None:
                self._mem[cache_key] = _CacheEntry(fetched_at=time.time(), experiments=on_disk)
                return on_disk
        rows = await self._get(
            "/api/experiments",
            {
                "facility": facility,
                "instrument": instrument,
                "projection": list(DEFAULT_PROJECTION_EXPERIMENT),
            },
        )
        experiments = [_normalise_experiment(r, instrument, facility) for r in rows]
        self._mem[cache_key] = _CacheEntry(fetched_at=time.time(), experiments=experiments)
        _save_disk_cache(experiments, instrument, facility)
        return experiments

    async def search_experiments(
        self,
        keyword: str,
        *,
        instrument: str | None = None,
        facility: str = "SNS",
        limit: int = 50,
    ) -> list[Experiment]:
        """Substring filter on a (cached) full instrument listing."""
        all_exp = await self.list_experiments(instrument=instrument, facility=facility)
        matches = [e for e in all_exp if e.matches(keyword)]
        return matches[:limit]

    # ---- datafiles ------------------------------------------------------

    async def list_datafiles(
        self,
        ipts: str,
        *,
        instrument: str | None = None,
        facility: str = "SNS",
        exts: Iterable[str] = (".nxs.h5",),
    ) -> list[Datafile]:
        instrument = instrument or self._config.default_instrument
        if not ipts.startswith("IPTS-"):
            ipts = f"IPTS-{ipts}"
        rows = await self._get(
            "/api/datafiles",
            {
                "facility": facility,
                "instrument": instrument,
                "experiment": ipts,
                "projection": list(DEFAULT_PROJECTION_DATAFILE),
                "exts": list(exts),
            },
        )
        return [_normalise_datafile(r) for r in rows]


# ---------------------------------------------------------------------------
# Row normalisation
# ---------------------------------------------------------------------------


def _normalise_experiment(raw: dict[str, Any], instrument: str, facility: str) -> Experiment:
    # IPTS identifier. Real OnCat puts the numeric IPTS in ``rank``;
    # ``id`` is the canonical OnCat object id (often the same string,
    # sometimes a hash). Match eqsanscli: prefer rank, fall back to id.
    ipts = _ipts_label(raw)

    # Members come back as a list of dicts on real OnCat
    # (``{"name": "Last, First", "email": ..., "orcid": ...}``). Tests
    # sometimes pass plain strings; tolerate both.
    members = _extract_member_names(raw.get("members") or [])

    # ``activity.acquisition`` is a *list* of timestamps per
    # eqsanscli/_fetch_all_experiments (date_range = first → last). Older
    # mock shapes used a {start, end} dict — keep that path working.
    activity = raw.get("activity")
    start, end, activity_str = _extract_acquisition(activity)

    return Experiment(
        ipts=ipts,
        title=str(raw.get("title", "")),
        pi=members[0] if members else "",
        members=tuple(members),
        activity=activity_str,
        instrument=instrument,
        facility=facility,
        runs_count=int(raw.get("size", 0) or 0),
        acquisition_start=start,
        acquisition_end=end,
    )


def _ipts_label(raw: dict[str, Any]) -> str:
    rank = raw.get("rank")
    if rank not in (None, ""):
        return f"IPTS-{rank}"
    raw_id = str(raw.get("id", ""))
    if not raw_id:
        return ""
    return raw_id if raw_id.startswith("IPTS-") else f"IPTS-{raw_id}"


def _extract_member_names(members_raw: Any) -> list[str]:
    if isinstance(members_raw, str):
        return [members_raw]
    out: list[str] = []
    for m in members_raw:
        if isinstance(m, str):
            if m:
                out.append(m)
            continue
        if not isinstance(m, dict):
            continue
        name = m.get("name")
        if not name:
            last = (m.get("last_name") or "").strip()
            first = (m.get("first_name") or "").strip()
            name = f"{last}, {first}".strip(", ").strip()
        if name:
            out.append(str(name))
    return out


def _extract_acquisition(activity: Any) -> tuple[str, str, str]:
    """Return ``(start, end, activity_summary)`` from an OnCat activity field."""
    if not isinstance(activity, dict):
        return "", "", str(activity or "")
    acq = activity.get("acquisition") or []
    activity_str = str(activity.get("date", ""))
    if isinstance(acq, list) and acq:
        return str(acq[0]), str(acq[-1]), activity_str
    if isinstance(acq, dict):
        return str(acq.get("start", "")), str(acq.get("end", "")), activity_str
    return "", "", activity_str


def _normalise_datafile(raw: dict[str, Any]) -> Datafile:
    indexed = raw.get("indexed") or {}
    metadata = (
        raw.get("metadata", {}).get("entry", {}) if isinstance(raw.get("metadata"), dict) else {}
    )
    daslogs = metadata.get("daslogs") if isinstance(metadata, dict) else None
    if not isinstance(daslogs, dict):
        daslogs = {}
    return Datafile(
        run_number=int(indexed.get("run_number", 0)),
        title=str(metadata.get("title", "")),
        start_time=str(metadata.get("start_time", "")),
        duration_s=float(metadata.get("duration", 0.0) or 0.0),
        total_counts=int(metadata.get("total_counts", 0) or 0),
        detector_distance_m=_avg(daslogs.get("detectorz")),
        wavelength_a=_avg(daslogs.get("wavelength")),
    )


def _avg(maybe_dict: Any) -> float:
    """Pull ``average_value`` out of an OnCat DASlog node; 0.0 on miss."""
    if isinstance(maybe_dict, dict):
        try:
            return float(maybe_dict.get("average_value", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0
