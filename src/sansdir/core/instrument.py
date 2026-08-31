"""Instrument mode — the SANS ⟷ USANS switch.

sansdir serves two instrument families out of one TUI. The *mode* decides
which OnCat instrument the ``i`` browser queries, which columns the run
catalog shows, and whether the USANS commands and their keys are live.

Everything else — panes, file ops, plotting, ``$EDITOR`` — is identical in
both modes, which is why this is one small enum-ish module rather than a
second application.

Default is SANS. A launch path under ``/SNS/USANS`` (or any path whose
lower-cased form contains ``usans``) flips it to USANS automatically;
``:instrument <name>`` switches at runtime.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

MODE_SANS: str = "SANS"
MODE_USANS: str = "USANS"

VALID_MODES: frozenset[str] = frozenset({MODE_SANS, MODE_USANS})

# Instruments sansdir knows by name. Anything else is accepted verbatim
# (OnCat may know instruments this list doesn't) and treated as SANS.
SANS_INSTRUMENTS: tuple[str, ...] = ("EQSANS", "BIOSANS", "GPSANS", "CG2", "CG3")
USANS_INSTRUMENTS: tuple[str, ...] = ("USANS",)

KNOWN_INSTRUMENTS: tuple[str, ...] = SANS_INSTRUMENTS + USANS_INSTRUMENTS

# Substring that marks a filesystem path as USANS territory.
_USANS_MARKER: str = "usans"


def normalise_instrument(name: str) -> str:
    """Upper-case and trim an instrument name (``" usans "`` → ``"USANS"``)."""
    return name.strip().upper()


def mode_for_instrument(name: str) -> str:
    """Return the mode an instrument belongs to.

    Unknown instruments default to :data:`MODE_SANS` — sansdir's original
    behaviour — so a new SANS beamline works without a code change.
    """
    return MODE_USANS if normalise_instrument(name) in USANS_INSTRUMENTS else MODE_SANS


def is_usans_path(path: str | Path) -> bool:
    """True when ``path`` looks like it lives under a USANS experiment.

    Matches ``/SNS/USANS/IPTS-…`` and anything else with ``usans`` in it,
    which covers the scratch/analysis folders users actually work in.
    ``eqsans`` does not contain ``usans``, so SANS paths never match.
    """
    return _USANS_MARKER in str(path).lower()


def detect_instrument(paths: Iterable[str | Path]) -> str | None:
    """Sniff an instrument from the paths sansdir was launched on.

    Args:
        paths: Launch paths (left pane, right pane, cwd…).

    Returns:
        ``"USANS"`` when any path is USANS territory, else ``None`` meaning
        "no opinion — use the configured default".
    """
    for p in paths:
        if p and is_usans_path(p):
            return MODE_USANS
    return None


def resolve_instrument(
    paths: Iterable[str | Path],
    *,
    configured: str = "",
    fallback: str = "EQSANS",
    auto_detect: bool = True,
) -> str:
    """Pick the instrument for a session.

    Precedence: path detection (when enabled) → ``[instrument].default`` →
    ``[oncat].default_instrument``. Path detection wins because a user who
    opens a USANS IPTS folder means it, whatever their config says.
    """
    if auto_detect:
        detected = detect_instrument(paths)
        if detected is not None:
            return detected
    if configured.strip():
        return normalise_instrument(configured)
    return normalise_instrument(fallback)
