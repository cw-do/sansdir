"""Tests for sansdir.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from sansdir.config import (
    CONFIG_ENV_VAR,
    Config,
    MailConfig,
    default_config_path,
    load_config,
)


def test_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "does-not-exist.toml")
    assert cfg == Config()
    assert cfg.mail.command == "mail"


def test_load_overrides_mail_section(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        """
        [mail]
        command = "mutt"
        default_subject = "data here"
        """,
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.mail == MailConfig(command="mutt", default_subject="data here")


def test_default_config_path_honours_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "custom.toml"
    monkeypatch.setenv(CONFIG_ENV_VAR, str(target))
    assert default_config_path() == target


def test_default_config_path_xdg_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/somewhere")
    assert default_config_path() == Path("/tmp/somewhere/sansdir/config.toml")


def test_default_config_path_home_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    p = default_config_path()
    assert p.parts[-3:] == (".config", "sansdir", "config.toml")
