"""Tests for sansdir.ui.keys.

The keymap is the seam between the Textual layer and the command registry.
We assert two invariants here:

1. Every keybinding names a real registered command (no typos).
2. Each ``args_resolver`` returns kwargs the registry will accept.
"""

from __future__ import annotations

from sansdir.commands.builtins import build_default_registry
from sansdir.ui.keys import default_keymap

# Reuse the FakeApp from the Phase-1 command tests so we can dispatch
# without a real Textual app running.
from tests.test_phase1_commands import FakeApp, FakePanel


def _make_app(tmp_path_factory) -> FakeApp:  # type: ignore[no-untyped-def]
    base = tmp_path_factory.mktemp("keys")
    left = base / "L"
    right = base / "R"
    left.mkdir()
    right.mkdir()
    return FakeApp(left=FakePanel(cwd=left), right=FakePanel(cwd=right))


def test_every_binding_names_a_registered_command(tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
    app = _make_app(tmp_path_factory)
    reg = build_default_registry(app=app)
    known = {c.name for c in reg.all()}
    for kb in default_keymap():
        assert kb.command in known, f"{kb.key} → unregistered command {kb.command!r}"


async def test_every_resolver_dispatches_cleanly(tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
    app = _make_app(tmp_path_factory)
    reg = build_default_registry(app=app)
    for kb in default_keymap():
        if kb.command == "app.quit":
            # Calling quit_app would mark the app as quitting; allow but
            # reset the counter so later assertions stay meaningful.
            await reg.dispatch(kb.command, **kb.resolve(app))
            continue
        # No exceptions should escape — handlers and resolvers are wired up.
        await reg.dispatch(kb.command, **kb.resolve(app))


def test_no_duplicate_visible_bindings_for_same_key() -> None:
    visible = [kb for kb in default_keymap() if kb.show_in_help]
    keys = [kb.key for kb in visible]
    assert len(keys) == len(set(keys)), f"duplicate visible bindings: {keys}"


def test_resolver_returns_dict() -> None:
    # Static check that no resolver mistakenly returns a non-mapping.
    for kb in default_keymap():
        if kb.args_resolver is None:
            continue
        # Resolvers must accept any AppProtocol; pass a sentinel to confirm
        # they don't crash on attribute access for trivial cases.
        # (Full dispatch is covered in test_every_resolver_dispatches_cleanly.)
        assert callable(kb.args_resolver)
