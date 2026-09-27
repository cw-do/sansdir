"""Async OnCat client — per-user access via the Device Authorization Grant.

Authentication mirrors ``cw-do/eqsanscli``
(``src/eqsanscli/integrations/oncat.py``) and the ORNL OnCat guidance:

  * **Device Authorization Grant** (default). A *public* client id, no secret.
    The user approves sign-in once in a browser (works over SSH — a URL and
    code are shown); a personal token is cached under their home and reused
    silently, so OnCat returns only the experiments *that user* may access.
    :func:`login` performs the sign-in; data calls never open a browser
    themselves (token-first) and raise :class:`OnCatAuthError` when no token
    exists, which the front ends turn into "run :oncat login first".
  * **Password Grant** (deprecated, browser-free fallback for unattended
    services). Used only when the deployment sets ``ONCAT_USERNAME`` /
    ``ONCAT_PASSWORD`` / ``ONCAT_CLIENT_ID`` / ``ONCAT_CLIENT_SECRET`` in the
    environment — nothing secret is committed.

The public async surface (:class:`OnCatClient`, :class:`Experiment`,
:class:`Datafile`) is unchanged; ``pyoncat`` is synchronous, so its calls run
in :func:`asyncio.to_thread`. OnCat has no fuzzy keyword endpoint — we list
every experiment for the instrument (cheap server-side) and filter locally,
caching the listing on disk for the configured TTL.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sansdir.config import OnCatConfig, default_config_path
from sansdir.core.history import default_history_path

if TYPE_CHECKING:
    import pyoncat

# Personal token cache override (tests / NDIP). Path, not a secret.
TOKEN_ENV: str = "SANSDIR_ONCAT_TOKEN"
# Scopes requested for human sign-in. Read-only catalog + data access.
SCOPES: tuple[str, ...] = ("api:read", "data:read", "openid")

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

    @property
    def ipts_number(self) -> int:
        """Numeric IPTS portion (e.g. ``"IPTS-12345"`` → ``12345``); 0 on miss."""
        tail = self.ipts.rsplit("-", 1)[-1] if self.ipts else ""
        try:
            return int(tail)
        except ValueError:
            return 0

    @property
    def sort_date_key(self) -> str:
        """Most recent acquisition end (or start) for date-sort; ``""`` if unknown."""
        return self.acquisition_end or self.acquisition_start

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
    """One run-file row from OnCat datafiles listing.

    .. note::

       OnCat's ``DASlogs.detectorz.average_value`` is reported in
       **millimetres** (the SNS DASlogs convention). The
       :attr:`detector_distance_m` property does the unit conversion so
       UI code can quote the more natural "metres" without remembering
       which side of the wire keeps which unit.
    """

    run_number: int
    title: str
    start_time: str
    duration_s: float
    total_counts: int = 0
    detector_distance_mm: float = 0.0
    wavelength_a: float = 0.0

    @property
    def detector_distance_m(self) -> float:
        """Detector distance in metres (1 / 1000 of the raw mm value)."""
        return self.detector_distance_mm / 1000.0


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
# Authentication (module-level; per-user device flow via pyoncat)
# ---------------------------------------------------------------------------

# A front end (the TUI) registers how the device-flow verification URL/code is
# shown. The default prints to stderr, right for a plain terminal and the
# standalone `sansdir oncat login` step.
_verification_handler: Callable[[Any], None] | None = None


def set_verification_handler(handler: Callable[[Any], None] | None) -> None:
    """Register (or clear) how the device-flow sign-in prompt is displayed."""
    global _verification_handler
    _verification_handler = handler


def _default_verification_handler(challenge: Any) -> None:
    import sys

    link = getattr(challenge, "verification_uri_complete", None) or challenge.verification_uri
    print("\n" + "=" * 70, file=sys.stderr)
    print("  OnCat sign-in required — open this URL in a browser:", file=sys.stderr)
    print(f"    {link}", file=sys.stderr)
    if not getattr(challenge, "verification_uri_complete", None):
        print(f"  and enter the code: {challenge.user_code}", file=sys.stderr)
    print("  Sign in with your UCAMS/XCAMS and approve. Waiting...", file=sys.stderr)
    print("=" * 70 + "\n", file=sys.stderr)


def token_path(config: OnCatConfig) -> Path:
    """Where the per-user token is cached.

    ``$SANSDIR_ONCAT_TOKEN`` wins, then ``[oncat].token_path``, else
    ``<config dir>/oncat_token.json`` next to ``config.toml``.
    """
    env = os.environ.get(TOKEN_ENV)
    if env:
        return Path(env).expanduser()
    if config.token_path:
        return Path(config.token_path).expanduser()
    return default_config_path().parent / "oncat_token.json"


def _token_store(config: OnCatConfig) -> pyoncat.FileSystemTokenStore:
    import pyoncat

    path = token_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path.parent, 0o700)
    return pyoncat.FileSystemTokenStore(str(path))


def _env_password_credentials() -> tuple[str, str, str, str] | None:
    """``(user, password, client_id, client_secret)`` if the deployment set all
    four, else ``None`` — the browserless Password-Grant fallback. Nothing
    secret lives in the code; a service opts in via the environment."""
    user = os.environ.get("ONCAT_USERNAME")
    pw = os.environ.get("ONCAT_PASSWORD")
    cid = os.environ.get("ONCAT_CLIENT_ID")
    secret = os.environ.get("ONCAT_CLIENT_SECRET")
    if user and pw and cid and secret:
        return user, pw, cid, secret
    return None


def _make_client(config: OnCatConfig, *, interactive: bool) -> pyoncat.ONCat:
    """Build a pyoncat client.

    ``interactive=False`` (data calls): token-first, never prompts. Uses the
    env Password Grant if configured; otherwise a device-flow client pinned to
    ``REAUTH_NEVER`` so an expired/absent token raises instead of popping a
    browser. ``interactive=True`` (:func:`login`): allows the browser flow.
    """
    try:
        import pyoncat
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise OnCatError(
            "pyoncat is required for OnCat access — install it with 'pip install pyoncat>=2.6'"
        ) from exc

    store = _token_store(config)
    creds = _env_password_credentials()
    if creds:
        user, pw, cid, secret = creds
        return pyoncat.ONCat(
            config.endpoint,
            client_id=cid,
            client_secret=secret,
            token_getter=store.read_token,
            token_setter=store.write_token,
            login_prompt=lambda: (user, pw),
            flow=pyoncat.RESOURCE_OWNER_CREDENTIALS_FLOW,
            timeout=config.request_timeout_seconds,
        )

    if not interactive and not token_path(config).exists():
        raise OnCatAuthError(
            "Not signed in to OnCat. Run the one-time sign-in "
            "(in the TUI: :oncat login; or the terminal: sansdir oncat login), "
            "approve in your browser, then retry. Unattended services can set "
            "ONCAT_USERNAME / ONCAT_PASSWORD / ONCAT_CLIENT_ID / ONCAT_CLIENT_SECRET."
        )

    return pyoncat.ONCat(
        config.endpoint,
        client_id=config.client_id,
        scopes=list(SCOPES),
        token_getter=store.read_token,
        token_setter=store.write_token,
        flow=pyoncat.DEVICE_AUTHORIZATION_FLOW,
        verification_handler=_verification_handler or _default_verification_handler,
        reauth_on_expired=(pyoncat.REAUTH_PROMPT if interactive else pyoncat.REAUTH_NEVER),
        timeout=config.request_timeout_seconds,
    )


def login(config: OnCatConfig) -> dict[str, Any]:
    """Perform an interactive OnCat sign-in and cache the token.

    Returns the signed-in user's summary (id/name/entitlements). Safe to call
    when already signed in — it validates/refreshes and returns the summary.
    Blocks while polling for browser approval, so callers on an event loop
    should run it in a worker thread.
    """
    import getpass

    client = _make_client(config, interactive=True)
    try:
        client.login()
        me: dict[str, Any] = dict(client.User.retrieve(getpass.getuser()).to_dict())
    except OnCatError:
        raise
    except Exception as exc:
        # If the token was obtained but the identity lookup failed, still
        # report success with the local username.
        if token_path(config).exists():
            return {"id": getpass.getuser()}
        raise _translate_auth_error(exc) from exc
    return me


def is_signed_in(config: OnCatConfig) -> bool:
    """True if a cached token exists or env credentials are configured. Does
    not hit the network (a stored token may still prove expired on use)."""
    return _env_password_credentials() is not None or token_path(config).exists()


def sign_out(config: OnCatConfig) -> bool:
    """Delete the cached token. Returns True if one was removed."""
    path = token_path(config)
    try:
        path.unlink()
        return True
    except OSError:
        return False


def _translate_auth_error(exc: Exception) -> OnCatError:
    """Map a pyoncat failure to an actionable OnCat error."""
    try:
        import pyoncat
    except ImportError:  # pragma: no cover
        return OnCatNetworkError(str(exc))
    auth_types = tuple(
        t
        for t in (
            getattr(pyoncat, "InvalidRefreshTokenError", None),
            getattr(pyoncat, "LoginRequiredError", None),
            getattr(pyoncat, "InteractionRequiredError", None),
            getattr(pyoncat, "UnauthorizedError", None),
            getattr(pyoncat, "InvalidUserCredentialsError", None),
            getattr(pyoncat, "InvalidClientCredentialsError", None),
        )
        if isinstance(t, type)
    )
    if auth_types and isinstance(exc, auth_types):
        return OnCatAuthError(
            "OnCat session expired or not signed in. Sign in again "
            "(:oncat login, or sansdir oncat login), then retry."
        )
    return OnCatNetworkError(f"OnCat request failed: {exc}")


def _to_plain(obj: Any) -> Any:
    """Recursively convert pyoncat ONCatObjects into plain nested dicts/lists,
    so the ``_normalise_*`` helpers (which use dict access) work unchanged."""
    if hasattr(obj, "to_dict"):
        obj = obj.to_dict()
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# OnCat client
# ---------------------------------------------------------------------------


class OnCatClient:
    """Async wrapper over pyoncat's per-user catalog access.

    pyoncat is synchronous; each network call runs in :func:`asyncio.to_thread`
    so the public interface stays async. A pre-built pyoncat client may be
    injected via ``client=`` (tests); otherwise one is created per call,
    token-first, from the cached personal token.
    """

    def __init__(
        self,
        config: OnCatConfig,
        *,
        client: pyoncat.ONCat | None = None,
        in_memory_cache: dict[str, _CacheEntry] | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._mem: dict[str, _CacheEntry] = in_memory_cache if in_memory_cache is not None else {}

    async def __aenter__(self) -> OnCatClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        # pyoncat manages its own requests session; nothing to close.
        return None

    def _sync_client(self) -> pyoncat.ONCat:
        return (
            self._client
            if self._client is not None
            else _make_client(self._config, interactive=False)
        )

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
        rows = await asyncio.to_thread(self._fetch_experiments, instrument, facility)
        experiments = [_normalise_experiment(r, instrument, facility) for r in rows]
        self._mem[cache_key] = _CacheEntry(fetched_at=time.time(), experiments=experiments)
        _save_disk_cache(experiments, instrument, facility)
        return experiments

    def _fetch_experiments(self, instrument: str, facility: str) -> list[dict[str, Any]]:
        """Blocking pyoncat experiment listing (runs in a worker thread)."""
        client = self._sync_client()
        try:
            client.login()  # token-first; no browser (REAUTH_NEVER)
            objs = client.Experiment.list(
                facility=facility,
                instrument=instrument,
                projection=list(DEFAULT_PROJECTION_EXPERIMENT),
            )
        except OnCatError:
            raise
        except Exception as exc:
            raise _translate_auth_error(exc) from exc
        return [_to_plain(o) for o in objs]

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
        rows = await asyncio.to_thread(
            self._fetch_datafiles, ipts, instrument, facility, tuple(exts)
        )
        return [_normalise_datafile(r) for r in rows]

    def _fetch_datafiles(
        self, ipts: str, instrument: str, facility: str, exts: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        """Blocking pyoncat datafile listing (runs in a worker thread)."""
        client = self._sync_client()
        try:
            client.login()  # token-first; no browser (REAUTH_NEVER)
            objs = client.Datafile.list(
                facility=facility,
                instrument=instrument,
                experiment=ipts,
                projection=list(DEFAULT_PROJECTION_DATAFILE),
                exts=list(exts),
            )
        except OnCatError:
            raise
        except Exception as exc:
            raise _translate_auth_error(exc) from exc
        return [_to_plain(o) for o in objs]


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
        # OnCat reports detectorz in mm; we keep the raw value and let the
        # ``detector_distance_m`` property convert at display time.
        detector_distance_mm=_avg(daslogs.get("detectorz")),
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
