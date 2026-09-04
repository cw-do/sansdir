"""Locate and invoke the instrument team's installed ``reduceUSANS``.

sansdir does **not** implement USANS reduction. The maths lives in
``neutrons/usansred``, deployed on the analysis cluster as a pixi
environment; we shell out to its ``reduceUSANS`` console script so users
always get the version the instrument team maintains.

Two deployment details this module exists to handle:

**Environment pollution.** The pixi console script inherits the invoking
user's ``~/.local`` site-packages and dies on a stale ``pandas`` /
``pytz``. Every invocation therefore runs with ``PYTHONNOUSERSITE=1`` and
an emptied ``PYTHONPATH``.

**Where the engine reads its input.** ``reduceUSANS`` resolves the
per-run ASCII files relative to *the directory holding the setup CSV*, not
the working directory. Since the reviewed CSV normally lives in the user's
own folder — and the autoreduce folder is instrument data we must not write
to — we build a throwaway staging directory of symlinks to the data files,
drop a copy of the CSV in it, and run there. Nothing under ``/SNS`` is
modified.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Root of the instrument-team pixi deployment. ``pixi run --manifest-path``
# points here, and the console script lives under ``.pixi/envs/default/bin``.
DEFAULT_PIXI_MANIFEST: str = "/usr/local/pixi/usansred"

# Relative location of the console script inside a pixi env.
_ENV_BIN: str = ".pixi/envs/default/bin/reduceUSANS"

CONSOLE_SCRIPT: str = "reduceUSANS"

# Only these are needed by the engine, but symlinking every plain file in
# the data directory is simpler and immune to the engine growing a new
# input pattern. The count is a couple of thousand — microseconds.
_STAGE_PREFIX: str = "sansdir-usans-"

# Reduced-output filenames the engine writes into the output directory.
OUTPUT_GLOB: str = "UN_*_det_1*.txt"

# The engine (usansred) hard-codes verbose output suffixes. This maps the
# long ones sansdir aliases to shorter, plot-friendly names. The originals
# are always kept, so the engine's own ``summary.xlsx`` and any downstream
# tooling that expects the standard name keep working.
SHORT_NAME_MAP: dict[str, str] = {
    "_det_1_background_subtracted.txt": "_det_1_bsub.txt",
}


class ReduceError(RuntimeError):
    """Raised when ``reduceUSANS`` can't be found or exits non-zero."""


@dataclass(frozen=True)
class ReduceResult:
    """Outcome of one ``reduceUSANS`` invocation.

    Attributes:
        output_dir: Where the reduced curves were written.
        returncode: The engine's exit status (0 on success).
        command: The argv actually executed, for the log / error message.
        stdout: Captured standard output.
        stderr: Captured standard error.
        produced: Reduced ``UN_*_det_1*.txt`` files found afterwards.
    """

    output_dir: Path
    returncode: int
    command: tuple[str, ...]
    stdout: str = ""
    stderr: str = ""
    produced: tuple[Path, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """True when the engine exited cleanly."""
        return self.returncode == 0

    def tail(self, lines: int = 12) -> str:
        """Last few lines of the engine's output — what to show on failure."""
        text = (self.stderr or self.stdout).strip()
        if not text:
            return ""
        return "\n".join(text.splitlines()[-lines:])


# ---------------------------------------------------------------------------
# Locating the engine
# ---------------------------------------------------------------------------


def find_engine(
    *,
    command: str = "",
    pixi_manifest: str = DEFAULT_PIXI_MANIFEST,
) -> list[str]:
    """Resolve the argv prefix that runs ``reduceUSANS``.

    Resolution order:

    1. ``command`` — an explicit override from ``[usans].reduce_command``.
    2. The console script inside the pixi env (fastest; verified working
       on the cluster once the user site-packages are disabled).
    3. ``pixi run --manifest-path <manifest> reduceUSANS`` when ``pixi``
       is on ``PATH`` and the manifest directory exists.
    4. ``reduceUSANS`` on ``PATH`` — e.g. inside an activated
       ``nsd-pixi-shell.sh usansred`` session.

    Args:
        command: Override; split on whitespace, used verbatim.
        pixi_manifest: Root of the ``usansred`` pixi deployment.

    Returns:
        The argv prefix, ready to have engine flags appended.

    Raises:
        ReduceError: When nothing usable was found.
    """
    if command.strip():
        import shlex

        return shlex.split(command)

    manifest = Path(pixi_manifest) if pixi_manifest else None
    if manifest is not None:
        binary = manifest / _ENV_BIN
        if binary.is_file() and os.access(binary, os.X_OK):
            return [str(binary)]

    pixi = shutil.which("pixi")
    if pixi and manifest is not None and manifest.is_dir():
        return [pixi, "run", "--manifest-path", str(manifest), CONSOLE_SCRIPT]

    on_path = shutil.which(CONSOLE_SCRIPT)
    if on_path:
        return [on_path]

    raise ReduceError(
        f"{CONSOLE_SCRIPT} not found — looked in {pixi_manifest}/{_ENV_BIN}, "
        f"`pixi run --manifest-path {pixi_manifest}`, and $PATH. "
        "Set [usans].reduce_command in ~/.config/sansdir/config.toml."
    )


def clean_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """A copy of the environment with user site-packages disabled.

    The pixi console script otherwise picks up ``~/.local/lib/pythonX.Y``
    and can crash on a stale ``pandas``/``pytz`` — confirmed on the ORNL
    analysis cluster.
    """
    env = dict(os.environ if base is None else base)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONPATH"] = ""
    env.pop("PYTHONHOME", None)
    return env


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------


def _same_dir(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:  # pragma: no cover — unreadable mount
        return False


def stage_inputs(setup_csv: Path, data_dir: Path, stage_dir: Path) -> Path:
    """Populate ``stage_dir`` with symlinks to ``data_dir`` plus the CSV.

    The engine reads its per-run ASCII input from the CSV's own directory,
    so this is how a CSV living in the user's working folder gets reduced
    without copying gigabytes or writing into the instrument's autoreduce
    directory.

    Args:
        setup_csv: The reviewed setup CSV (copied, not linked, so the
            engine can't be confused by a dangling link).
        data_dir: The IPTS ``shared/autoreduce`` folder.
        stage_dir: An existing, empty directory to populate.

    Returns:
        Path to the staged CSV inside ``stage_dir``.
    """
    stage_dir.mkdir(parents=True, exist_ok=True)
    with os.scandir(data_dir) as entries:
        for entry in entries:
            if not entry.is_file():
                continue
            link = stage_dir / entry.name
            if link.exists() or link.is_symlink():
                continue
            try:
                link.symlink_to(entry.path)
            except OSError:
                # A filesystem without symlink support: fall back to a copy
                # of just that file rather than failing the whole run.
                shutil.copyfile(entry.path, link)
    staged_csv = stage_dir / setup_csv.name
    # The data dir may already hold a file of that name, in which case the
    # loop above symlinked it — copying onto the link would write *through*
    # it into the instrument directory. Drop the link first.
    if staged_csv.is_symlink() or staged_csv.exists():
        staged_csv.unlink()
    shutil.copyfile(setup_csv, staged_csv)
    return staged_csv


# ---------------------------------------------------------------------------
# Short-name aliases
# ---------------------------------------------------------------------------


def write_short_name_copies(output_dir: str | Path) -> list[Path]:
    """Alongside each verbose engine output, write a short-named copy.

    ``usansred`` names its final curve ``UN_<name>_det_1_background_subtracted.txt``;
    this adds ``UN_<name>_det_1_bsub.txt`` with identical contents. A copy,
    not a symlink: the reduced curves are a deliverable users move and share,
    and a dangling link after a move is worse than a duplicate file.

    Non-destructive — the original is always kept — so it is safe to run
    unconditionally. Only files whose short alias is missing or older than
    the source are (re)written, so a repeated reduce doesn't thrash.

    Returns:
        The alias paths written (empty when the engine produced no
        verbose-named output, e.g. an empty-cell-only run).
    """
    out = Path(output_dir)
    made: list[Path] = []
    for long_suffix, short_suffix in SHORT_NAME_MAP.items():
        for src in sorted(out.glob(f"UN_*{long_suffix}")):
            dst = src.with_name(src.name[: -len(long_suffix)] + short_suffix)
            try:
                if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
                    continue
                shutil.copyfile(src, dst)
            except OSError:
                continue
            made.append(dst)
    return made


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def build_command(
    setup_csv: Path,
    output_dir: Path,
    *,
    logbin: bool = True,
    command: str = "",
    pixi_manifest: str = DEFAULT_PIXI_MANIFEST,
) -> list[str]:
    """Full argv for one reduction, engine location included."""
    argv = find_engine(command=command, pixi_manifest=pixi_manifest)
    if logbin:
        argv.append("-l")
    argv.extend(["-o", str(output_dir), str(setup_csv)])
    return argv


def reduce_csv(
    setup_csv: str | Path,
    *,
    data_dir: str | Path,
    output_dir: str | Path,
    logbin: bool = True,
    command: str = "",
    pixi_manifest: str = DEFAULT_PIXI_MANIFEST,
    timeout: float | None = None,
    short_name_copy: bool = True,
) -> ReduceResult:
    """Reduce every sample in ``setup_csv`` with the installed engine.

    Blocking — call it from a worker thread (``asyncio.to_thread``) so the
    TUI stays responsive.

    Args:
        setup_csv: The reviewed setup CSV.
        data_dir: Folder holding the pre-processed ``USANS_<run>_*`` ASCII.
        output_dir: Where reduced curves are written (created if absent).
        logbin: Pass ``-l``; on by default because it produces the standard
            ``UN_<name>_det_1_lb.txt`` and makes ``_background_subtracted``
            the log-binned curve scientists actually plot.
        command: ``[usans].reduce_command`` override.
        pixi_manifest: Root of the ``usansred`` pixi deployment.
        timeout: Seconds before the engine is killed; ``None`` waits.
        short_name_copy: After a successful run, also write short-named
            aliases of the verbose engine output (see
            :func:`write_short_name_copies`). Non-destructive.

    Returns:
        A :class:`ReduceResult`; check :attr:`ReduceResult.ok`.

    Raises:
        FileNotFoundError: When the CSV or the data directory is missing.
        ReduceError: When the engine can't be located or timed out.
    """
    setup_csv = Path(setup_csv).expanduser().resolve()
    data_dir = Path(data_dir).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    if not setup_csv.is_file():
        raise FileNotFoundError(f"setup CSV not found: {setup_csv}")
    if not data_dir.is_dir():
        raise FileNotFoundError(f"USANS data directory not found: {data_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    stage: str | None = None
    try:
        if _same_dir(setup_csv.parent, data_dir):
            # Already sitting next to the ASCII files — run in place, which
            # is exactly the command the instrument team documents.
            run_csv = setup_csv
            cwd = data_dir
        else:
            stage = tempfile.mkdtemp(prefix=_STAGE_PREFIX)
            run_csv = stage_inputs(setup_csv, data_dir, Path(stage))
            cwd = Path(stage)
        argv = build_command(
            run_csv,
            output_dir,
            logbin=logbin,
            command=command,
            pixi_manifest=pixi_manifest,
        )
        try:
            proc = subprocess.run(  # argv list, never shell=True
                argv,
                cwd=str(cwd),
                env=clean_env(),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReduceError(f"reduceUSANS timed out after {timeout}s") from exc
        except OSError as exc:
            raise ReduceError(f"could not run {argv[0]}: {exc}") from exc
    finally:
        if stage:
            shutil.rmtree(stage, ignore_errors=True)

    # Count the engine's own output *before* aliasing, so the reduced-curve
    # count the user sees stays honest (one curve, not one plus its alias).
    produced = tuple(sorted(output_dir.glob(OUTPUT_GLOB)))
    if short_name_copy and proc.returncode == 0:
        write_short_name_copies(output_dir)
    return ReduceResult(
        output_dir=output_dir,
        returncode=proc.returncode,
        command=tuple(argv),
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        produced=produced,
    )
