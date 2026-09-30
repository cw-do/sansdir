"""Build the shell command ``F4`` runs to edit a file.

sansdir suspends itself while the editor owns the terminal, so none of its
own keys work there — and most users who land in ``vi`` by default don't
know its commands. For the vi family we therefore pass a few ``-c``
commands that keep a banner on screen for the whole session: a top line
saying *you are editing X in vim*, and a bottom line listing the handful of
commands needed to type, save and get back out. Editors that already show
their own key help (nano, emacs, …) are launched unchanged.
"""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path

# Executable names that accept vim's ``-c`` / ``let &statusline`` syntax.
VI_FAMILY: frozenset[str] = frozenset(
    {"vi", "vim", "nvim", "view", "vim.basic", "vim.tiny", "vim.nox", "vim.gtk3"}
)

# The minimum a vi newcomer needs. No ``|`` (it separates ``-c`` commands),
# no ``'`` (it ends the vimscript string), no ``%`` (a statusline item).
VI_KEYS_HELP: str = (
    "i type · Esc stop typing · :w save · :wq save & quit · :q! quit, discard · u undo"
)


def default_editor() -> str:
    """``$EDITOR``, then ``$VISUAL``, then full ``vim`` if installed, else ``vi``.

    On RHEL ``vi`` is the minimal vim build, which cannot draw a status
    line, so the full one is preferred when the user hasn't chosen.
    """
    chosen = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if chosen:
        return chosen
    return "vim" if shutil.which("vim") else "vi"


def _vim_escape(text: str) -> str:
    """Make ``text`` safe inside a single-quoted vimscript statusline string."""
    return text.replace("'", "''").replace("%", "%%").replace("|", "¦")


def vi_banner_args(name: str, path: Path) -> list[str]:
    """``-c`` arguments that put an edit-mode banner above and below the file.

    Minimal builds (RHEL's ``vi``: no ``+eval``, no ``+statusline``) skip the
    ``if`` block silently and only get ``showmode``'s ``-- INSERT --`` —
    which is why :func:`default_editor` prefers full ``vim``.

    Args:
        name: Editor executable name, shown in the banner.
        path: The file being edited, shown in the top line.

    Returns:
        Arguments to append before the file path.
    """
    fname = _vim_escape(path.name)
    top = f" sansdir ▸ EDIT MODE — {fname} in {name} — sansdir keys resume when you quit "
    bottom = f" {VI_KEYS_HELP} %<%= %m %l:%c "
    return [
        "-c",
        "set showmode",
        "-c",
        (
            "if has('statusline') "
            f"| set showtabline=2 laststatus=2 | let &tabline='{top}' "
            f"| let &statusline='{bottom}' | endif"
        ),
    ]


def editor_command(path: Path, editor: str | None = None) -> str:
    """Shell command line that opens ``path`` in ``editor``.

    Args:
        path: File to edit.
        editor: Editor command, possibly with its own arguments. ``None``
            uses :func:`default_editor`.

    Returns:
        A fully quoted command line for ``subprocess.run(..., shell=True)``.
    """
    argv = shlex.split(editor or default_editor()) or ["vi"]
    name = Path(argv[0]).name
    if name in VI_FAMILY:
        argv += vi_banner_args(name, path)
    return shlex.join([*argv, str(path)])
