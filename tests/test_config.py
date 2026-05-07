"""Tests for sansdir.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from sansdir.config import (
    CONFIG_ENV_VAR,
    Config,
    KeysConfig,
    MailConfig,
    UiConfig,
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


def test_load_ui_section_overrides_theme(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[ui]\ntheme = "monokai"\n', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.ui.theme == "monokai"


def test_load_ui_section_defaults_when_missing(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('[mail]\ncommand = "mail"\n', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.ui == UiConfig()


def test_load_keys_section_collects_string_overrides(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        """
        [keys]
        f5 = "ui.copy_tagged"
        slash = "view.set_filter"
        """,
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.keys.overrides == {
        "f5": "ui.copy_tagged",
        "slash": "view.set_filter",
    }


def test_load_keys_section_drops_non_string_values(tmp_path: Path) -> None:
    """Defensive: ``f5 = 123`` is silently dropped, not a startup crash."""
    p = tmp_path / "config.toml"
    p.write_text("[keys]\nf5 = 123\nf6 = \"ui.move_tagged\"\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.keys.overrides == {"f6": "ui.move_tagged"}


def test_load_keys_section_default_is_empty_dict(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.keys == KeysConfig()
    assert cfg.keys.overrides == {}
