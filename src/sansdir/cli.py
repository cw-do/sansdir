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


@click.group(
    cls=_SansdirGroup,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
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
    """Launch the interactive TUI."""
    # Lazy import: avoids paying Textual's import cost on `version`/`extract`.
    from sansdir.app import run_tui

    run_tui(start_path=path)


@main.command()
@click.option(
    "--keys",
    "-k",
    multiple=True,
    required=True,
    help="HDF5 key path (repeatable). E.g. -k DASlogs/temperature/value",
)
@click.option(
    "--out",
    "-o",
    default=None,
    type=click.Path(dir_okay=False, writable=True),
    help="Output file (default: ./extracted_<timestamp>.tsv).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["tsv", "csv", "columns"]),
    default="tsv",
    show_default=True,
)
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False))
def extract(keys: tuple[str, ...], out: str | None, fmt: str, files: tuple[str, ...]) -> None:
    """Batch-extract HDF5 metadata from FILES into a tabular file."""
    from sansdir.hdf.batch import extract_to_file

    extract_to_file(files=files, keys=keys, out_path=out, fmt=fmt)


@main.command()
def version() -> None:
    """Print the sansdir version and exit."""
    click.echo(f"sansdir {__version__}")


if __name__ == "__main__":
    main()
