"""Lightweight TOML config loader.

Reads ``~/.config/sansdir/config.toml`` if present (override with the
``SANSDIR_CONFIG`` env var, which tests use). Returns a small frozen
dataclass; missing keys fall back to defaults so the app works on a
fresh checkout with zero setup.

Phase 3 only needs ``[mail].command``. As later phases need more keys
they extend the dataclass — please keep the loader free of import-time
side effects so ``sansdir version`` stays cheap.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Python 3.11+ ships ``tomllib``; we depend on ``tomli`` for 3.10.
if sys.version_info >= (3, 11):
    import tomllib as _toml
else:  # pragma: no cover — exercised only on 3.10 CI
    import tomli as _toml  # type: ignore[no-redef]


CONFIG_ENV_VAR: str = "SANSDIR_CONFIG"


@dataclass(frozen=True)
class MailConfig:
    """``[mail]`` section."""

    command: str = "mail"
    default_subject: str = "[sansdir] data"


@dataclass(frozen=True)
class Config:
    """Top-level config. Add new sections here as later phases need them."""

    mail: MailConfig = MailConfig()


def default_config_path() -> Path:
    """Resolve which file to read.

    ``$SANSDIR_CONFIG`` overrides everything (used by tests). Otherwise we
    look at ``$XDG_CONFIG_HOME/sansdir/config.toml`` if set, else
    ``~/.config/sansdir/config.toml``.
    """
    env = os.environ.get(CONFIG_ENV_VAR)
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "sansdir" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    """Load and parse the config file. Missing files yield :class:`Config()`."""
    target = path if path is not None else default_config_path()
    try:
        data = _toml.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Config()
    except OSError:
        return Config()
    mail_section = data.get("mail", {}) if isinstance(data, dict) else {}
    return Config(
        mail=MailConfig(
            command=str(mail_section.get("command", MailConfig.command)),
            default_subject=str(mail_section.get("default_subject", MailConfig.default_subject)),
        ),
    )
