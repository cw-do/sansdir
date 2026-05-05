"""Command registry — the single dispatch path for every user-facing action.

Every keybinding, every entry on the ``:`` command line, every CLI subcommand,
and (eventually) every LLM tool-call routes through :class:`CommandRegistry`.
There is intentionally no other path: business-logic functions are wrapped as
:class:`Command` instances and invoked exclusively via :meth:`dispatch`.

See ``PLANNING.md`` §12 for the architectural rationale.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

ParamType = str  # "path" | "glob" | "string" | "int" | "float" | "bool" | "enum" | "files"

VALID_PARAM_TYPES: frozenset[str] = frozenset(
    {"path", "glob", "string", "int", "float", "bool", "enum", "files"}
)


class CommandError(Exception):
    """Base class for registry errors."""


class DuplicateCommandError(CommandError):
    """Raised when a command name or alias is already registered."""


class UnknownCommandError(CommandError, KeyError):
    """Raised when dispatch is asked for an unregistered name."""


@dataclass(frozen=True)
class CommandParam:
    """One typed parameter on a :class:`Command`.

    Attributes:
        name: The parameter's name as accepted by the handler (kwarg).
        type: One of :data:`VALID_PARAM_TYPES`.
        description: Human-readable, one sentence. Surfaces in `?` help and in
            the LLM tool-schema export.
        required: Whether the user must supply a value.
        default: Default value when ``required`` is False.
        choices: Allowed values when ``type`` is ``"enum"``.
    """

    name: str
    type: ParamType
    description: str
    required: bool = True
    default: Any = None
    choices: list[str] | None = None

    def __post_init__(self) -> None:
        if self.type not in VALID_PARAM_TYPES:
            raise ValueError(
                f"CommandParam {self.name!r}: unknown type {self.type!r} "
                f"(valid: {sorted(VALID_PARAM_TYPES)})"
            )
        if self.type == "enum" and not self.choices:
            raise ValueError(f"CommandParam {self.name!r}: type='enum' requires non-empty choices")
        if self.type != "enum" and self.choices is not None:
            raise ValueError(f"CommandParam {self.name!r}: choices only valid for type='enum'")


@dataclass(frozen=True)
class Command:
    """A user-facing action.

    Handlers may be sync or async; :meth:`CommandRegistry.dispatch` always
    returns an awaitable so callers have one calling convention.

    Attributes:
        name: Dotted, scoped, lowercase identifier (e.g. ``"plot.iq"``).
            See PLANNING.md §12.3 for the naming convention.
        description: One-sentence human-readable summary.
        params: Typed parameter list; positional order is the canonical order
            for ``:`` command-line parsing.
        handler: Callable invoked by :meth:`CommandRegistry.dispatch`. May be
            sync or async; will be awaited if it returns a coroutine.
        aliases: Alternate names accepted by :meth:`CommandRegistry.get` /
            :meth:`dispatch`.
        examples: ``:``-line examples shown in help.
        danger: If True, the LLM layer must request an extra confirmation
            before executing this command (PLANNING.md §12.4).
    """

    name: str
    description: str
    params: tuple[CommandParam, ...]
    handler: Callable[..., Any | Awaitable[Any]]
    aliases: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    danger: bool = False

    def __post_init__(self) -> None:
        if not self.name or " " in self.name:
            raise ValueError(f"Command name must be non-empty and whitespace-free: {self.name!r}")
        seen: set[str] = set()
        for p in self.params:
            if p.name in seen:
                raise ValueError(f"Command {self.name!r}: duplicate param {p.name!r}")
            seen.add(p.name)


class CommandRegistry:
    """In-memory registry of all :class:`Command` instances.

    The registry is the only path through which user intent becomes execution.
    Adding a new keybinding, ``:`` command, or LLM tool means registering a
    :class:`Command` here — never wiring a handler to an event directly.
    """

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}
        self._alias_to_name: dict[str, str] = {}

    # ---- registration -----------------------------------------------------

    def register(self, cmd: Command) -> None:
        """Register ``cmd``; raises :class:`DuplicateCommandError` on collision."""
        if cmd.name in self._commands:
            raise DuplicateCommandError(f"command already registered: {cmd.name!r}")
        if cmd.name in self._alias_to_name:
            raise DuplicateCommandError(
                f"name {cmd.name!r} collides with alias of {self._alias_to_name[cmd.name]!r}"
            )
        for alias in cmd.aliases:
            if alias in self._commands or alias in self._alias_to_name:
                raise DuplicateCommandError(f"alias {alias!r} already in use")
        self._commands[cmd.name] = cmd
        for alias in cmd.aliases:
            self._alias_to_name[alias] = cmd.name

    # ---- lookup -----------------------------------------------------------

    def get(self, name_or_alias: str) -> Command:
        """Resolve a name or alias to its :class:`Command`."""
        if name_or_alias in self._commands:
            return self._commands[name_or_alias]
        canonical = self._alias_to_name.get(name_or_alias)
        if canonical is None:
            raise UnknownCommandError(name_or_alias)
        return self._commands[canonical]

    def __contains__(self, name_or_alias: object) -> bool:
        if not isinstance(name_or_alias, str):
            return False
        return name_or_alias in self._commands or name_or_alias in self._alias_to_name

    def all(self) -> list[Command]:
        """Return all registered commands, sorted by name."""
        return sorted(self._commands.values(), key=lambda c: c.name)

    # ---- dispatch ---------------------------------------------------------

    async def dispatch(self, name: str, /, **kwargs: Any) -> Any:
        """Invoke ``name`` (or alias) with ``**kwargs``.

        Sync handlers are run inline; async handlers are awaited. Required
        params must be supplied; unknown kwargs raise :class:`TypeError`.
        """
        cmd = self.get(name)
        self._validate_kwargs(cmd, kwargs)
        result = cmd.handler(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def dispatch_sync(self, name: str, /, **kwargs: Any) -> Any:
        """Synchronous wrapper around :meth:`dispatch`.

        Convenient for keybinding code paths that aren't already inside an
        event loop. Raises :class:`RuntimeError` if called from one.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.dispatch(name, **kwargs))
        raise RuntimeError(
            "dispatch_sync() called from within a running event loop; "
            "use `await registry.dispatch(...)` instead"
        )

    @staticmethod
    def _validate_kwargs(cmd: Command, kwargs: dict[str, Any]) -> None:
        known = {p.name for p in cmd.params}
        unknown = set(kwargs) - known
        if unknown:
            raise TypeError(f"command {cmd.name!r}: unknown argument(s): {sorted(unknown)}")
        missing = [p.name for p in cmd.params if p.required and p.name not in kwargs]
        if missing:
            raise TypeError(f"command {cmd.name!r}: missing required argument(s): {missing}")
