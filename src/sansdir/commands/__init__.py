"""Central command registry — single source of truth for user-facing actions.

See PLANNING.md §12 for the design rationale.
"""

from __future__ import annotations

from sansdir.commands.registry import (
    Command,
    CommandError,
    CommandParam,
    CommandRegistry,
    DuplicateCommandError,
    UnknownCommandError,
)

__all__ = [
    "Command",
    "CommandError",
    "CommandParam",
    "CommandRegistry",
    "DuplicateCommandError",
    "UnknownCommandError",
]
