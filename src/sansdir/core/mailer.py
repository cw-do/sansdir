"""Send email by shelling out to ``mail`` or ``mutt``.

Both tools share enough flags that a single argv builder works for either:
``-s SUBJECT``, ``-a ATTACHMENT`` (repeatable), recipient last, body on
stdin. ``mutt`` requires a ``--`` separator before the recipient when
attachments are present, which we add unconditionally — both tools
tolerate it.

A successful send writes one line to ``~/.cache/sansdir/history.log``.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from sansdir.core.fileops import _log

DEFAULT_COMMAND: str = "mail"


@dataclass(frozen=True)
class MailResult:
    """Outcome of one ``send_mail`` call."""

    returncode: int
    argv: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def build_argv(
    *,
    recipient: str,
    subject: str,
    attachments: Iterable[Path] = (),
    command: str = DEFAULT_COMMAND,
) -> list[str]:
    """Construct the argv for ``mail``/``mutt``.

    Public so the LLM layer can preview the command before executing.
    """
    if not recipient:
        raise ValueError("recipient is required")
    argv: list[str] = [command, "-s", subject]
    for att in attachments:
        argv.extend(["-a", str(att)])
    if any(True for _ in attachments) and command == "mutt":
        # mutt parses everything after `--` as recipients.
        argv.append("--")
    argv.append(recipient)
    return argv


def send_mail(
    *,
    recipient: str,
    subject: str,
    attachments: Iterable[Path] = (),
    body: str = "",
    command: str | None = None,
    timeout: float | None = 60.0,
) -> MailResult:
    """Run the configured mail command and return its result.

    Args:
        recipient: ``user@example.com``.
        subject: Mail subject.
        attachments: Paths to attach. Each must exist or :class:`FileNotFoundError`.
        body: Plain-text body (piped via stdin).
        command: Override the default mail command. Defaults to
            :data:`DEFAULT_COMMAND` if unset; the executable must exist
            on ``$PATH``.
        timeout: Subprocess timeout in seconds; ``None`` to wait forever.

    Returns:
        :class:`MailResult`.

    Raises:
        FileNotFoundError: an attachment path is missing.
        RuntimeError: the configured mail command isn't on ``$PATH``.
    """
    cmd = command or DEFAULT_COMMAND
    if shutil.which(cmd) is None:
        raise RuntimeError(f"mail command {cmd!r} not found on PATH")
    att_list = [Path(a).expanduser().resolve() for a in attachments]
    for a in att_list:
        if not a.exists():
            raise FileNotFoundError(a)
    argv = build_argv(
        recipient=recipient,
        subject=subject,
        attachments=att_list,
        command=cmd,
    )
    try:
        proc = subprocess.run(
            argv,
            input=body,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return MailResult(
            returncode=124,
            argv=argv,
            stderr=f"timeout after {exc.timeout}s",
        )
    if proc.returncode == 0:
        _log("mail", att_list, Path(recipient))
    return MailResult(
        returncode=proc.returncode,
        argv=argv,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
