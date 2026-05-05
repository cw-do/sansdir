"""Built-in command registrations.

Phase 0: a single ``app.quit`` command is registered as proof of pattern.
Subsequent phases extend ``register_builtins`` with navigation, file ops,
plotting, HDF5, and OnCat commands — each addition is a new ``Command``
object, never an inline handler bound to a key.
"""

from __future__ import annotations

from sansdir.commands.registry import Command, CommandRegistry


def _quit_handler() -> str:
    """Return a sentinel; the Textual app translates this to ``App.exit()``.

    Keeping the handler pure (no side effects, no Textual import) lets the
    command be tested without a running app.
    """
    return "quit"


_APP_QUIT = Command(
    name="app.quit",
    description="Exit the sansdir application.",
    params=(),
    handler=_quit_handler,
    aliases=("quit", "q"),
    examples=(":quit", ":q"),
)


def register_builtins(registry: CommandRegistry) -> CommandRegistry:
    """Register every Phase-0 built-in command on ``registry``.

    Returns the same registry to enable chaining.
    """
    registry.register(_APP_QUIT)
    return registry


def build_default_registry() -> CommandRegistry:
    """Create a fresh registry pre-populated with all built-ins."""
    return register_builtins(CommandRegistry())
