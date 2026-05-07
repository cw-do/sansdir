"""Click-based command-line entry point.

Heavy modules (Textual, matplotlib, h5py, httpx, the command registry)
are imported lazily inside subcommand bodies so that bare invocations
like ``sansdir version`` and ``sansdir --help`` stay under the 300 ms
cold-start budget defined in CLAUDE.md / PLANNING.md.
"""

from __future__ import annotations

import click

from sansdir import __version__


class _SansdirGroup(click.Group):
    """A group whose first positional arg may be a subcommand OR a path.

    ``sansdir version``           → run the ``version`` subcommand.
    ``sansdir /SNS/EQSANS``       → equivalent to ``sansdir tui /SNS/EQSANS``.
    ``sansdir``                   → equivalent to ``sansdir tui``.
    """

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = ["tui", *args]
        return super().resolve_command(ctx, args)


_EPILOG = """\
Examples:

  \b
  sansdir                                # launch the TUI in cwd
  sansdir /SNS/EQSANS/IPTS-12345/shared  # launch the TUI in a folder
  sansdir extract -k /entry/duration *.nxs.h5
  sansdir version

Config: ~/.config/sansdir/config.toml (sections: [ui], [keys], [oncat], [mail]).
Override the path with $SANSDIR_CONFIG.

Docs / issues: see PLANNING.md and TASKS.md in the repo.
"""


@click.group(
    cls=_SansdirGroup,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog=_EPILOG,
)
@click.version_option(version=__version__, prog_name="sansdir", message="sansdir %(version)s")
@click.pass_context
def main(ctx: click.Context) -> None:
    """sansdir — MDIR-style terminal file manager for SANS data.

    With no subcommand, launches the TUI in the current directory.
    A bare path argument is treated as ``sansdir tui PATH``.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(tui, path=None)


@main.command()
@click.argument("path", required=False, type=click.Path(exists=True, file_okay=False))
def tui(path: str | None) -> None:
    """Launch the interactive dual-pane TUI.

    PATH is the starting directory for the left pane (default: cwd).
    The right pane mirrors PATH initially. From inside the TUI press
    ``?`` for keybindings, ``i`` for OnCat IPTS search, ``M`` for
    batch metadata extract.
    """
    # Lazy import: avoids paying Textual's import cost on `version`/`extract`.
    from sansdir.app import run_tui

    run_tui(start_path=path)


_EXTRACT_EPILOG = """\
Examples:

  \b
  # Summary table: one row per file, time-series reduced to means.
  sansdir extract -k /entry/DASlogs/temperature/value \\
                  -k /entry/duration \\
                  --out summary.tsv \\
                  /SNS/EQSANS/IPTS-12345/nexus/EQSANS_*.nxs.h5

  \b
  # Per-file mode: <filename> in --out → one CSV per input
  # with the *full* DASlogs arrays preserved.
  sansdir extract -k /entry/DASlogs/temperature/time \\
                  -k /entry/DASlogs/temperature/value \\
                  --out '<filename>_temp.csv' \\
                  EQSANS_172749.nxs.h5 EQSANS_172750.nxs.h5
"""


@main.command(epilog=_EXTRACT_EPILOG)
@click.option(
    "--keys",
    "-k",
    multiple=True,
    required=True,
    help="HDF5 key path (repeatable). E.g. -k /entry/DASlogs/temperature/value",
)
@click.option(
    "--out",
    "-o",
    default=None,
    type=click.Path(dir_okay=False, writable=True),
    help=(
        "Output file. Summary mode: ./extracted_<timestamp>.<ext> if blank. "
        "Per-file mode: include '<filename>' to emit one file per input."
    ),
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["tsv", "csv", "columns"]),
    default="tsv",
    show_default=True,
    help="Output table format.",
)
@click.option(
    "--with-stats",
    is_flag=True,
    default=False,
    help="Add <key>_stdev and <key>_n columns next to each value.",
)
@click.option(
    "--workers",
    type=click.IntRange(min=1),
    default=8,
    show_default=True,
    help="Thread pool size for parallel reads.",
)
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False))
def extract(
    keys: tuple[str, ...],
    out: str | None,
    fmt: str,
    with_stats: bool,
    workers: int,
    files: tuple[str, ...],
) -> None:
    """Batch-extract HDF5 metadata from FILES into a tabular file.

    Two modes, picked by the shape of --out:

    \b
    * Summary mode (default): one row per input file, time-series
      values reduced to their mean. --with-stats adds <key>_stdev
      and <key>_n columns.
    * Per-file mode: triggered by '<filename>' in --out — each input
      gets its own table with the *full* arrays preserved.
    """
    from pathlib import Path

    from sansdir.hdf.batch import extract_to_file

    written = extract_to_file(
        files=[Path(f) for f in files],
        keys=keys,
        out_path=out,
        fmt=fmt,  # type: ignore[arg-type]
        with_stats=with_stats,
        max_workers=workers,
    )
    if isinstance(written, list):
        for p in written:
            click.echo(str(p))
    else:
        click.echo(str(written))


@main.command()
def version() -> None:
    """Print the sansdir version and exit."""
    click.echo(f"sansdir {__version__}")


if __name__ == "__main__":
    main()
