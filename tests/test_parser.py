"""Tests for sansdir.commands.parser."""

from __future__ import annotations

import pytest

from sansdir.commands.builtins import build_default_registry
from sansdir.commands.parser import (
    ParseError,
    common_prefix,
    complete_command_name,
    parse_command_line,
)
from sansdir.commands.registry import Command, CommandParam, CommandRegistry


def _registry_with(*cmds: Command) -> CommandRegistry:
    reg = CommandRegistry()
    for c in cmds:
        reg.register(c)
    return reg


def _shell_run() -> Command:
    return Command(
        name="shell.run",
        description="Run a shell command.",
        params=(CommandParam(name="cmd", type="string", description="Shell line."),),
        handler=lambda cmd: cmd,
    )


# ---------------------------------------------------------------------------
# Basic dispatch shape
# ---------------------------------------------------------------------------


def test_empty_line_rejected() -> None:
    reg = build_default_registry()
    with pytest.raises(ParseError):
        parse_command_line("   ", reg)


def test_unknown_command_rejected() -> None:
    reg = build_default_registry()
    with pytest.raises(ParseError, match="unknown command"):
        parse_command_line("nope", reg)


def test_resolves_canonical_name() -> None:
    reg = build_default_registry()
    cmd, kwargs = parse_command_line("app.quit", reg)
    assert cmd.name == "app.quit"
    assert kwargs == {}


def test_resolves_alias() -> None:
    reg = build_default_registry()
    cmd, _ = parse_command_line("q", reg)
    assert cmd.name == "app.quit"


# ---------------------------------------------------------------------------
# Positional argument binding
# ---------------------------------------------------------------------------


def test_single_positional_string_param() -> None:
    cmd = Command(
        name="echo",
        description="",
        params=(CommandParam(name="text", type="string", description=""),),
        handler=lambda text: text,
    )
    reg = _registry_with(cmd)
    _, kwargs = parse_command_line("echo hello", reg)
    assert kwargs == {"text": "hello"}


def test_quoted_argument_kept_intact() -> None:
    cmd = Command(
        name="echo",
        description="",
        params=(CommandParam(name="text", type="string", description=""),),
        handler=lambda text: text,
    )
    reg = _registry_with(cmd)
    _, kwargs = parse_command_line('echo "hello world"', reg)
    assert kwargs == {"text": "hello world"}


def test_multiple_positionals_in_declaration_order() -> None:
    cmd = Command(
        name="cp",
        description="",
        params=(
            CommandParam(name="src", type="path", description=""),
            CommandParam(name="dst", type="path", description=""),
        ),
        handler=lambda src, dst: (src, dst),
    )
    reg = _registry_with(cmd)
    _, kwargs = parse_command_line("cp /a /b", reg)
    assert kwargs == {"src": "/a", "dst": "/b"}


def test_files_param_consumes_remaining() -> None:
    cmd = Command(
        name="zip",
        description="",
        params=(
            CommandParam(name="archive", type="path", description=""),
            CommandParam(name="files", type="files", description=""),
        ),
        handler=lambda archive, files: (archive, files),
    )
    reg = _registry_with(cmd)
    _, kwargs = parse_command_line("zip out.zip a.txt b.txt c.txt", reg)
    assert kwargs == {"archive": "out.zip", "files": ["a.txt", "b.txt", "c.txt"]}


def test_too_many_args_rejected() -> None:
    cmd = Command(
        name="echo",
        description="",
        params=(CommandParam(name="text", type="string", description=""),),
        handler=lambda text: text,
    )
    reg = _registry_with(cmd)
    with pytest.raises(ParseError, match="too many"):
        parse_command_line("echo a b c", reg)


def test_missing_required_arg_rejected() -> None:
    cmd = Command(
        name="echo",
        description="",
        params=(CommandParam(name="text", type="string", description=""),),
        handler=lambda text: text,
    )
    reg = _registry_with(cmd)
    with pytest.raises(ParseError, match="missing required"):
        parse_command_line("echo", reg)


def test_optional_arg_omitted_is_fine() -> None:
    cmd = Command(
        name="rm",
        description="",
        params=(
            CommandParam(name="path", type="path", description=""),
            CommandParam(
                name="recursive",
                type="bool",
                description="",
                required=False,
                default=False,
            ),
        ),
        handler=lambda **kw: kw,
    )
    reg = _registry_with(cmd)
    _, kwargs = parse_command_line("rm /tmp/foo", reg)
    assert kwargs == {"path": "/tmp/foo"}


# ---------------------------------------------------------------------------
# Keyword argument binding
# ---------------------------------------------------------------------------


def test_keyword_arg_overrides_positional_order() -> None:
    cmd = Command(
        name="set",
        description="",
        params=(
            CommandParam(name="key", type="string", description=""),
            CommandParam(name="value", type="string", description=""),
        ),
        handler=lambda key, value: (key, value),
    )
    reg = _registry_with(cmd)
    _, kwargs = parse_command_line("set value=42 mykey", reg)
    assert kwargs == {"value": "42", "key": "mykey"}


def test_keyword_arg_for_unknown_param_falls_back_to_positional() -> None:
    cmd = Command(
        name="echo",
        description="",
        params=(CommandParam(name="text", type="string", description=""),),
        handler=lambda text: text,
    )
    reg = _registry_with(cmd)
    # ``foo=bar`` is not a known param of ``echo``, so it's treated as a
    # positional token. Useful for `:cd a=b/` style paths.
    _, kwargs = parse_command_line("echo foo=bar", reg)
    assert kwargs == {"text": "foo=bar"}


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("true", True),
        ("yes", True),
        ("on", True),
        ("1", True),
        ("false", False),
        ("no", False),
        ("off", False),
        ("0", False),
        ("True", True),
        ("FALSE", False),
    ],
)
def test_bool_coercion(token: str, expected: bool) -> None:
    cmd = Command(
        name="t",
        description="",
        params=(CommandParam(name="b", type="bool", description=""),),
        handler=lambda b: b,
    )
    reg = _registry_with(cmd)
    _, kwargs = parse_command_line(f"t {token}", reg)
    assert kwargs == {"b": expected}


def test_bool_coercion_rejects_garbage() -> None:
    cmd = Command(
        name="t",
        description="",
        params=(CommandParam(name="b", type="bool", description=""),),
        handler=lambda b: b,
    )
    reg = _registry_with(cmd)
    with pytest.raises(ParseError, match="bool"):
        parse_command_line("t maybe", reg)


def test_int_and_float_coercion() -> None:
    cmd = Command(
        name="m",
        description="",
        params=(
            CommandParam(name="i", type="int", description=""),
            CommandParam(name="f", type="float", description=""),
        ),
        handler=lambda i, f: (i, f),
    )
    reg = _registry_with(cmd)
    _, kwargs = parse_command_line("m 42 3.14", reg)
    assert kwargs == {"i": 42, "f": 3.14}


def test_enum_coercion_rejects_invalid() -> None:
    cmd = Command(
        name="s",
        description="",
        params=(
            CommandParam(
                name="key",
                type="enum",
                description="",
                choices=["name", "mtime"],
            ),
        ),
        handler=lambda key: key,
    )
    reg = _registry_with(cmd)
    _, kwargs = parse_command_line("s name", reg)
    assert kwargs == {"key": "name"}
    with pytest.raises(ParseError, match="not in"):
        parse_command_line("s bogus", reg)


# ---------------------------------------------------------------------------
# Shell-out (`!cmd`)
# ---------------------------------------------------------------------------


def test_shell_form_dispatches_to_shell_run() -> None:
    reg = _registry_with(_shell_run())
    cmd, kwargs = parse_command_line("!ls -la /tmp", reg)
    assert cmd.name == "shell.run"
    assert kwargs == {"cmd": "ls -la /tmp"}


def test_shell_form_preserves_quoting() -> None:
    reg = _registry_with(_shell_run())
    _, kwargs = parse_command_line("! echo 'a b' | wc -l", reg)
    assert kwargs == {"cmd": "echo 'a b' | wc -l"}


def test_shell_form_requires_shell_run_registered() -> None:
    reg = CommandRegistry()
    with pytest.raises(ParseError, match=r"shell\.run"):
        parse_command_line("!ls", reg)


# ---------------------------------------------------------------------------
# Tab completion
# ---------------------------------------------------------------------------


def test_complete_command_name_prefix() -> None:
    reg = _registry_with(
        Command(name="nav.cd", description="", params=(), handler=lambda: None),
        Command(name="nav.up", description="", params=(), handler=lambda: None),
        Command(name="pane.swap", description="", params=(), handler=lambda: None),
    )
    assert complete_command_name("nav.", reg) == ["nav.cd", "nav.up"]
    assert complete_command_name("pa", reg) == ["pane.swap"]
    assert complete_command_name("zz", reg) == []


def test_complete_includes_aliases() -> None:
    reg = _registry_with(
        Command(
            name="app.quit",
            description="",
            params=(),
            handler=lambda: None,
            aliases=("q", "quit"),
        ),
    )
    out = complete_command_name("q", reg)
    assert "app.quit" not in out  # doesn't start with q
    assert set(out) == {"q", "quit"}


def test_complete_empty_returns_all() -> None:
    reg = build_default_registry()
    out = complete_command_name("", reg)
    assert "app.quit" in out


def test_common_prefix() -> None:
    assert common_prefix(["nav.cd", "nav.up", "nav.tag"]) == "nav."
    assert common_prefix(["foo", "foobar"]) == "foo"
    assert common_prefix(["a", "b"]) == ""
    assert common_prefix([]) == ""
    assert common_prefix(["only"]) == "only"
