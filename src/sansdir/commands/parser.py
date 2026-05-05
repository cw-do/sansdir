"""Parse a ``:``-command line into a registered :class:`Command` and kwargs.

Grammar (whitespace-tokenized via :mod:`shlex`):

* ``cmd``                          — call ``cmd`` with no args.
* ``cmd a b c``                    — three positional args, mapped onto
                                     ``cmd.params`` in declaration order.
* ``cmd key=value``                — keyword arg (key must be a known param).
* ``cmd a key=v``                  — mixed; positional fills *unused* params.
* ``! whatever you want``          — shell-out to ``shell.run``.
* ``cd``, ``q``, ...               — aliases resolve via the registry.

Type coercion is driven by the param's ``type`` field:

* ``int`` / ``float``  — :func:`int` / :func:`float`.
* ``bool``             — ``true``/``yes``/``on``/``1`` (and inverses).
* ``enum``             — must match one of ``param.choices``.
* ``files``            — variadic; consumes all remaining positionals.
* ``string`` / ``path`` / ``glob`` — passed through verbatim.
"""

from __future__ import annotations

import shlex
from typing import Any

from sansdir.commands.registry import Command, CommandParam, CommandRegistry

_BOOL_TRUE: frozenset[str] = frozenset({"true", "yes", "on", "1", "t", "y"})
_BOOL_FALSE: frozenset[str] = frozenset({"false", "no", "off", "0", "f", "n"})


class ParseError(ValueError):
    """Raised when a ``:``-line can't be turned into a valid dispatch."""


def parse_command_line(line: str, registry: CommandRegistry) -> tuple[Command, dict[str, Any]]:
    """Return ``(command, kwargs)`` for a ``:``-line, or raise :class:`ParseError`.

    The returned tuple is suitable for ``await registry.dispatch(cmd.name, **kwargs)``.
    """
    stripped = line.strip()
    if not stripped:
        raise ParseError("empty command line")

    # `:!some shell pipe | etc` shells out. We bypass shlex here so quoting
    # inside the shell command doesn't require double-escaping.
    if stripped.startswith("!"):
        rest = stripped[1:].lstrip()
        try:
            cmd = registry.get("shell.run")
        except KeyError as exc:
            raise ParseError("shell.run is not registered") from exc
        return cmd, {"cmd": rest}

    try:
        tokens = shlex.split(stripped)
    except ValueError as exc:
        raise ParseError(f"could not tokenize: {exc}") from exc

    name, args = tokens[0], tokens[1:]
    try:
        cmd = registry.get(name)
    except KeyError as exc:
        raise ParseError(f"unknown command: {name!r}") from exc

    return cmd, _bind_args(cmd, args)


def _bind_args(cmd: Command, tokens: list[str]) -> dict[str, Any]:
    """Map positional + keyword tokens onto ``cmd.params``."""
    params_by_name = {p.name: p for p in cmd.params}
    kwargs: dict[str, Any] = {}
    positional: list[str] = []

    for tok in tokens:
        if "=" in tok:
            key, value = tok.split("=", 1)
            if key in params_by_name:
                kwargs[key] = _coerce(value, params_by_name[key])
                continue
        positional.append(tok)

    used = set(kwargs)
    pos_iter = iter(positional)
    for param in cmd.params:
        if param.name in used:
            continue
        if param.type == "files":
            # Variadic: consume *all* remaining positionals.
            kwargs[param.name] = list(pos_iter)
            break
        try:
            tok = next(pos_iter)
        except StopIteration:
            if param.required:
                raise ParseError(
                    f"missing required argument {param.name!r} for {cmd.name!r}"
                ) from None
            continue
        kwargs[param.name] = _coerce(tok, param)

    leftover = list(pos_iter)
    if leftover:
        raise ParseError(f"too many arguments for {cmd.name!r}: extra {leftover!r}")
    return kwargs


def _coerce(token: str, param: CommandParam) -> Any:
    t = param.type
    if t == "int":
        try:
            return int(token)
        except ValueError as exc:
            raise ParseError(f"{param.name}: expected int, got {token!r}") from exc
    if t == "float":
        try:
            return float(token)
        except ValueError as exc:
            raise ParseError(f"{param.name}: expected float, got {token!r}") from exc
    if t == "bool":
        low = token.lower()
        if low in _BOOL_TRUE:
            return True
        if low in _BOOL_FALSE:
            return False
        raise ParseError(f"{param.name}: cannot parse bool from {token!r}")
    if t == "enum":
        if not param.choices or token not in param.choices:
            raise ParseError(f"{param.name}: {token!r} not in {param.choices!r}")
        return token
    # string / path / glob (single)
    return token


def complete_command_name(prefix: str, registry: CommandRegistry) -> list[str]:
    """Return registered command names (and aliases) starting with ``prefix``.

    Used for Tab-completion in the ``:``-input. Sorted with canonical names
    first, aliases after, both alphabetical.
    """
    if not prefix:
        return [c.name for c in registry.all()]
    names = [c.name for c in registry.all() if c.name.startswith(prefix)]
    aliases = sorted(
        a for c in registry.all() for a in c.aliases if a.startswith(prefix) and a not in names
    )
    return names + aliases


def common_prefix(strings: list[str]) -> str:
    """Longest common prefix of ``strings`` (empty if list is empty)."""
    if not strings:
        return ""
    s1 = min(strings)
    s2 = max(strings)
    for i, ch in enumerate(s1):
        if i >= len(s2) or ch != s2[i]:
            return s1[:i]
    return s1
