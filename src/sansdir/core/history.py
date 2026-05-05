"""Persistent command-line history for the ``:``-input.

Stores one entry per line at ``~/.cache/sansdir/cmd_history`` (configurable
via the ``SANSDIR_CACHE_DIR`` env var), capped at :data:`MAX_HISTORY`. The
class also tracks an in-memory cursor used by ``Up`` / ``Down`` navigation
in :class:`~sansdir.ui.command_input.CommandInput`.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

MAX_HISTORY: int = 1000

DEFAULT_CACHE_DIR_ENV: str = "SANSDIR_CACHE_DIR"


def default_history_path() -> Path:
    """Return the canonical history file path.

    Honors ``$SANSDIR_CACHE_DIR`` (used by tests) and otherwise falls back
    to ``~/.cache/sansdir/cmd_history``.
    """
    base = os.environ.get(DEFAULT_CACHE_DIR_ENV)
    if base:
        return Path(base) / "cmd_history"
    return Path.home() / ".cache" / "sansdir" / "cmd_history"


class CommandHistory:
    """In-memory ring of submitted command lines, persisted to disk.

    Behavior matches what most shells and Claude Code do:

    * ``Up`` walks backwards through history starting from the most recent.
    * ``Down`` walks forward; reaching the end restores the user's draft.
    * Submitting the *same* line twice in a row is collapsed into one
      entry, so spamming Enter doesn't pollute history.
    * Every successful append is flushed to disk so a crashed session
      doesn't lose recent commands.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        max_entries: int = MAX_HISTORY,
        load: bool = True,
    ) -> None:
        self._path = path or default_history_path()
        self._max = max_entries
        self._entries: list[str] = []
        self._cursor: int | None = None
        self._draft: str = ""
        if load:
            self.load()

    # ---- I/O --------------------------------------------------------------

    def load(self) -> None:
        """Read the history file. Missing or unreadable files are tolerated."""
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._entries = []
            return
        except OSError:
            self._entries = []
            return
        # ``str.splitlines`` discards the trailing newline correctly.
        self._entries = [ln for ln in text.splitlines() if ln.strip()]
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max :]

    def save(self) -> None:
        """Write the history file, creating its parent directory if needed."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("\n".join(self._entries) + "\n", encoding="utf-8")
        except OSError:
            # Disk full / permission denied — silently drop. The in-memory
            # ring still works for the rest of the session.
            pass

    # ---- mutation ---------------------------------------------------------

    def append(self, line: str) -> None:
        """Append ``line`` to history, deduplicating against the previous one."""
        line = line.rstrip()
        if not line:
            return
        if self._entries and self._entries[-1] == line:
            self._reset_cursor()
            return
        self._entries.append(line)
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max :]
        self._reset_cursor()
        self.save()

    def extend(self, lines: Iterable[str]) -> None:
        for ln in lines:
            self.append(ln)

    # ---- cursor (Up / Down navigation) -----------------------------------

    def begin(self, current_draft: str) -> None:
        """Snapshot the user's current draft before they walk into history."""
        self._draft = current_draft
        self._cursor = None

    def previous(self, current: str) -> str:
        """Step backwards in history; return the line to display.

        ``current`` is the input's *current* value, used to start the cursor
        from the bottom of the ring on the first ``Up`` press.
        """
        if not self._entries:
            return current
        if self._cursor is None:
            self._draft = current
            self._cursor = len(self._entries) - 1
        elif self._cursor > 0:
            self._cursor -= 1
        return self._entries[self._cursor]

    def next(self, current: str) -> str:
        """Step forwards in history; return the line to display.

        Walking past the most recent entry restores the user's draft.
        """
        if self._cursor is None:
            return current
        self._cursor += 1
        if self._cursor >= len(self._entries):
            self._cursor = None
            return self._draft
        return self._entries[self._cursor]

    def _reset_cursor(self) -> None:
        self._cursor = None
        self._draft = ""

    # ---- introspection ----------------------------------------------------

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    def entries(self) -> list[str]:
        return list(self._entries)

    @property
    def path(self) -> Path:
        return self._path
