"""Tests for sansdir.commands.registry and .schema and .builtins."""

from __future__ import annotations

import json

import pytest

from sansdir.commands import (
    Command,
    CommandParam,
    CommandRegistry,
    DuplicateCommandError,
    UnknownCommandError,
)
from sansdir.commands.builtins import build_default_registry
from sansdir.commands.schema import command_to_tool_schema, registry_to_tool_schemas

# ---------------------------------------------------------------------------
# CommandParam validation
# ---------------------------------------------------------------------------


def test_param_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="unknown type"):
        CommandParam(name="x", type="not-a-type", description="")


def test_enum_param_requires_choices() -> None:
    with pytest.raises(ValueError, match="non-empty choices"):
        CommandParam(name="mode", type="enum", description="")


def test_choices_only_valid_for_enum() -> None:
    with pytest.raises(ValueError, match="only valid for type='enum'"):
        CommandParam(name="x", type="string", description="", choices=["a"])


def test_command_rejects_duplicate_param_names() -> None:
    p1 = CommandParam(name="src", type="path", description="src")
    p2 = CommandParam(name="src", type="path", description="dup")
    with pytest.raises(ValueError, match="duplicate param"):
        Command(name="x", description="", params=(p1, p2), handler=lambda **_: None)


def test_command_rejects_blank_or_spacey_name() -> None:
    with pytest.raises(ValueError):
        Command(name="", description="", params=(), handler=lambda: None)
    with pytest.raises(ValueError):
        Command(name="bad name", description="", params=(), handler=lambda: None)


# ---------------------------------------------------------------------------
# Registry: register / get / lookup
# ---------------------------------------------------------------------------


def _trivial(name: str = "ping") -> Command:
    return Command(
        name=name,
        description="reply with pong",
        params=(),
        handler=lambda: "pong",
    )


def test_register_and_get() -> None:
    reg = CommandRegistry()
    cmd = _trivial()
    reg.register(cmd)
    assert reg.get("ping") is cmd
    assert "ping" in reg
    assert reg.all() == [cmd]


def test_register_duplicate_name_rejected() -> None:
    reg = CommandRegistry()
    reg.register(_trivial())
    with pytest.raises(DuplicateCommandError):
        reg.register(_trivial())


def test_register_alias_collides_with_name() -> None:
    reg = CommandRegistry()
    reg.register(_trivial("first"))
    second = Command(
        name="second",
        description="",
        params=(),
        handler=lambda: None,
        aliases=("first",),
    )
    with pytest.raises(DuplicateCommandError):
        reg.register(second)


def test_register_name_collides_with_existing_alias() -> None:
    reg = CommandRegistry()
    reg.register(
        Command(
            name="first",
            description="",
            params=(),
            handler=lambda: None,
            aliases=("alias1",),
        )
    )
    with pytest.raises(DuplicateCommandError):
        reg.register(_trivial("alias1"))


def test_get_unknown_raises() -> None:
    reg = CommandRegistry()
    with pytest.raises(UnknownCommandError):
        reg.get("nope")


def test_alias_resolves_to_canonical() -> None:
    reg = CommandRegistry()
    cmd = Command(
        name="app.quit",
        description="",
        params=(),
        handler=lambda: "quit",
        aliases=("q", "quit"),
    )
    reg.register(cmd)
    assert reg.get("q") is cmd
    assert reg.get("quit") is cmd
    assert reg.get("app.quit") is cmd


def test_all_returns_sorted() -> None:
    reg = CommandRegistry()
    reg.register(_trivial("zeta"))
    reg.register(_trivial("alpha"))
    reg.register(_trivial("mu"))
    assert [c.name for c in reg.all()] == ["alpha", "mu", "zeta"]


# ---------------------------------------------------------------------------
# Dispatch (sync + async + validation)
# ---------------------------------------------------------------------------


async def test_dispatch_sync_handler() -> None:
    reg = CommandRegistry()
    reg.register(_trivial())
    assert await reg.dispatch("ping") == "pong"


async def test_dispatch_async_handler() -> None:
    async def _handler(x: int) -> int:
        return x * 2

    reg = CommandRegistry()
    reg.register(
        Command(
            name="math.double",
            description="",
            params=(CommandParam(name="x", type="int", description="input"),),
            handler=_handler,
        )
    )
    assert await reg.dispatch("math.double", x=21) == 42


async def test_dispatch_through_alias() -> None:
    reg = CommandRegistry()
    reg.register(
        Command(
            name="app.quit",
            description="",
            params=(),
            handler=lambda: "bye",
            aliases=("q",),
        )
    )
    assert await reg.dispatch("q") == "bye"


async def test_dispatch_missing_required_arg() -> None:
    reg = CommandRegistry()
    reg.register(
        Command(
            name="needs",
            description="",
            params=(CommandParam(name="x", type="int", description=""),),
            handler=lambda x: x,
        )
    )
    with pytest.raises(TypeError, match="missing required"):
        await reg.dispatch("needs")


async def test_dispatch_unknown_kwarg() -> None:
    reg = CommandRegistry()
    reg.register(_trivial())
    with pytest.raises(TypeError, match="unknown argument"):
        await reg.dispatch("ping", bogus=1)


async def test_dispatch_unknown_command() -> None:
    reg = CommandRegistry()
    with pytest.raises(UnknownCommandError):
        await reg.dispatch("nope")


# ---------------------------------------------------------------------------
# Schema export
# ---------------------------------------------------------------------------


def test_schema_for_trivial_command() -> None:
    cmd = _trivial()
    tool = command_to_tool_schema(cmd)
    assert tool == {
        "name": "ping",
        "description": "reply with pong",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    }


def test_schema_includes_param_types_and_required() -> None:
    cmd = Command(
        name="file.copy",
        description="Copy files.",
        params=(
            CommandParam(name="src", type="files", description="sources"),
            CommandParam(name="dst", type="path", description="destination"),
            CommandParam(
                name="overwrite",
                type="bool",
                description="overwrite existing",
                required=False,
                default=False,
            ),
            CommandParam(
                name="mode",
                type="enum",
                description="conflict resolution",
                required=False,
                default="ask",
                choices=["ask", "skip", "rename"],
            ),
        ),
        handler=lambda **_: None,
    )
    tool = command_to_tool_schema(cmd)
    props = tool["input_schema"]["properties"]
    assert props["src"] == {
        "type": "array",
        "items": {"type": "string", "format": "path"},
        "description": "sources",
    }
    assert props["dst"]["format"] == "path"
    assert props["overwrite"] == {
        "type": "boolean",
        "description": "overwrite existing",
        "default": False,
    }
    assert props["mode"]["enum"] == ["ask", "skip", "rename"]
    assert tool["input_schema"]["required"] == ["src", "dst"]


def test_schema_marks_dangerous_commands() -> None:
    cmd = Command(
        name="file.delete",
        description="Delete tagged files.",
        params=(),
        handler=lambda: None,
        danger=True,
    )
    tool = command_to_tool_schema(cmd)
    assert tool["description"].startswith("[DANGER")


def test_registry_schema_is_valid_json() -> None:
    reg = build_default_registry()
    schemas = registry_to_tool_schemas(reg)
    # Must round-trip through json — this is what we'd send to Anthropic.
    serialised = json.dumps(schemas)
    reloaded = json.loads(serialised)
    assert isinstance(reloaded, list)
    assert any(t["name"] == "app.quit" for t in reloaded)


# ---------------------------------------------------------------------------
# Built-ins (Phase 0 proof of pattern)
# ---------------------------------------------------------------------------


async def test_app_quit_dispatches() -> None:
    reg = build_default_registry()
    assert await reg.dispatch("app.quit") == "quit"
    assert await reg.dispatch("q") == "quit"
    assert await reg.dispatch("quit") == "quit"


def test_default_registry_contains_app_quit() -> None:
    reg = build_default_registry()
    assert "app.quit" in reg
    assert reg.get("app.quit").examples == (":quit", ":q")
