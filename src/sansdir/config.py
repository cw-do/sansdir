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
from dataclasses import dataclass, field
from pathlib import Path

# Python 3.11+ ships ``tomllib``; we depend on ``tomli`` for 3.10.
if sys.version_info >= (3, 11):
    import tomllib as _toml
else:  # pragma: no cover — exercised only on 3.10 CI
    import tomli as _toml  # type: ignore[no-redef]


CONFIG_ENV_VAR: str = "SANSDIR_CONFIG"


@dataclass(frozen=True)
class UiConfig:
    """``[ui]`` section."""

    # Default Textual theme. Anything in ``app.available_themes`` works
    # — built-ins include ``textual-dark``, ``textual-light``, ``monokai``,
    # ``nord``, ``dracula``, ``gruvbox``, ``catppuccin-mocha``,
    # ``solarized-dark``, ``tokyo-night``, ``rose-pine``, etc. Unknown
    # values fall back to the built-in default with a notify, so a
    # typo never blocks startup.
    theme: str = "textual-dark"


@dataclass(frozen=True)
class KeysConfig:
    """``[keys]`` section.

    Maps keystroke (Textual key syntax — ``f5``, ``ctrl+u``, ``slash``,
    ``space``, ``a``, ``A``…) to a registry command name (e.g.
    ``ui.copy_tagged``, ``view.set_filter``). Entries override or extend
    the built-in keymap loaded from :mod:`sansdir.ui.keys`. Unknown
    command names are dropped at startup with a notify.
    """

    overrides: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MailConfig:
    """``[mail]`` section."""

    command: str = "mail"
    default_subject: str = "[sansdir] data"


@dataclass(frozen=True)
class OnCatConfig:
    """``[oncat]`` section.

    Defaults reuse the public OAuth client identifiers that the same
    author's ``cw-do/eqsanscli`` ships with — they're application IDs
    for an OnCat read-only catalog client, not user secrets, so anyone
    running sansdir on the ORNL cluster gets a working out-of-the-box
    experience.

    Override per host via ``[oncat]`` in
    ``~/.config/sansdir/config.toml`` or the ``ONCAT_CLIENT_ID`` /
    ``ONCAT_CLIENT_SECRET`` env vars.
    """

    endpoint: str = "https://oncat.ornl.gov"
    # Public OAuth client_credentials for the EQSANS catalog tooling.
    # Source: cw-do/eqsanscli/src/eqsanscli/integrations/oncat.py.
    client_id: str = "17ddcb3e-a727-41a2-aec5-43533988ab69"
    client_secret: str = "3027a2b1-da09-4e13-bf97-f389ff1a747f"
    default_instrument: str = "EQSANS"
    cache_ttl_seconds: int = 86400
    request_timeout_seconds: float = 30.0


@dataclass(frozen=True)
class Config:
    """Top-level config. Add new sections here as later phases need them."""

    ui: UiConfig = field(default_factory=UiConfig)
    keys: KeysConfig = field(default_factory=KeysConfig)
    mail: MailConfig = field(default_factory=MailConfig)
    oncat: OnCatConfig = field(default_factory=OnCatConfig)


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
    ui_section = data.get("ui", {}) if isinstance(data, dict) else {}
    keys_section = data.get("keys", {}) if isinstance(data, dict) else {}
    mail_section = data.get("mail", {}) if isinstance(data, dict) else {}
    oncat_section = data.get("oncat", {}) if isinstance(data, dict) else {}
    return Config(
        ui=UiConfig(theme=str(ui_section.get("theme", UiConfig.theme))),
        keys=KeysConfig(
            # Drop non-string values defensively (e.g. user wrote
            # `f5 = 123`); the rest are normalised to lowercase keys.
            overrides={
                str(k): str(v) for k, v in keys_section.items() if isinstance(v, str)
            }
        ),
        mail=MailConfig(
            command=str(mail_section.get("command", MailConfig.command)),
            default_subject=str(mail_section.get("default_subject", MailConfig.default_subject)),
        ),
        oncat=OnCatConfig(
            endpoint=str(oncat_section.get("endpoint", OnCatConfig.endpoint)),
            # Override chain: [oncat] section → env var → built-in default.
            client_id=str(
                oncat_section.get(
                    "client_id",
                    os.environ.get("ONCAT_CLIENT_ID", OnCatConfig.client_id),
                )
            ),
            client_secret=str(
                oncat_section.get(
                    "client_secret",
                    os.environ.get("ONCAT_CLIENT_SECRET", OnCatConfig.client_secret),
                )
            ),
            default_instrument=str(
                oncat_section.get("default_instrument", OnCatConfig.default_instrument)
            ),
            cache_ttl_seconds=int(
                oncat_section.get("cache_ttl_seconds", OnCatConfig.cache_ttl_seconds)
            ),
            request_timeout_seconds=float(
                oncat_section.get("request_timeout_seconds", OnCatConfig.request_timeout_seconds)
            ),
        ),
    )
