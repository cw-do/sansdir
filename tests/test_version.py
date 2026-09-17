"""One version string, three places — keep them in lockstep.

``__init__.py`` is the source of truth. ``pyproject.toml`` must match it
for packaging, and the README's header banner must match it because that
is what people read on GitHub — it lagged two releases behind once.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from sansdir import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - 3.10 fallback, mirrors src/sansdir/config.py
    import tomli as tomllib


def test_pyproject_matches_package_version() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == __version__


def test_readme_banner_matches_package_version() -> None:
    readme_head = (REPO_ROOT / "README.md").read_text()[:500]
    match = re.search(r"\*\*SansDIR v([0-9][0-9.]*)\*\*", readme_head)
    assert match is not None, "README banner must contain '**SansDIR v<version>**'"
    assert match.group(1) == __version__, (
        f"README banner says v{match.group(1)} but the package is {__version__} — "
        "bump the README header (and add a changelog section) when tagging a release"
    )
