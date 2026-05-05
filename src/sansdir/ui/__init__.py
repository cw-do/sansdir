"""Textual UI widgets and key-binding tables.

This package contains *only* presentation and event-routing code. All
business logic lives behind :class:`~sansdir.commands.registry.CommandRegistry`
(see ``PLANNING.md`` §12.6) — widgets here translate user input into
``registry.dispatch(...)`` calls and never reach into ``core/``, ``hdf/``,
``plot/``, or the filesystem directly.
"""
