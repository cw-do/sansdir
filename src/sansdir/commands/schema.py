"""JSON-schema export for the command registry.

Produces a list of tool definitions in the shape that Anthropic's
``messages.create(tools=...)`` accepts, so the future LLM layer
(PLANNING.md §12.4) can pass ``registry.to_json_schema()`` straight through
to the SDK with no glue code.
"""

from __future__ import annotations

from typing import Any

from sansdir.commands.registry import Command, CommandParam, CommandRegistry

# Maps our internal param types to JSON-schema primitives understood by the
# Anthropic tool-use schema (which is a subset of JSON Schema).
_TYPE_TO_JSONSCHEMA: dict[str, dict[str, Any]] = {
    "string": {"type": "string"},
    "path": {"type": "string", "format": "path"},
    "glob": {"type": "string", "format": "glob"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "bool": {"type": "boolean"},
    "files": {"type": "array", "items": {"type": "string", "format": "path"}},
    # "enum" is handled specially below since it needs `choices`.
}


def _param_schema(param: CommandParam) -> dict[str, Any]:
    if param.type == "enum":
        schema: dict[str, Any] = {"type": "string", "enum": list(param.choices or [])}
    else:
        schema = dict(_TYPE_TO_JSONSCHEMA[param.type])
    schema["description"] = param.description
    if not param.required and param.default is not None:
        schema["default"] = param.default
    return schema


def command_to_tool_schema(cmd: Command) -> dict[str, Any]:
    """Convert one :class:`Command` to an Anthropic tool definition."""
    properties: dict[str, Any] = {p.name: _param_schema(p) for p in cmd.params}
    required: list[str] = [p.name for p in cmd.params if p.required]
    description = cmd.description
    if cmd.danger:
        description = f"[DANGER — destructive] {description}"
    tool: dict[str, Any] = {
        "name": cmd.name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }
    return tool


def registry_to_tool_schemas(registry: CommandRegistry) -> list[dict[str, Any]]:
    """Convert every command in ``registry`` to a tool definition."""
    return [command_to_tool_schema(cmd) for cmd in registry.all()]
