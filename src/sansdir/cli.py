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

Docs: docs/sansdir-report.pdf in the repo. Issues: github.com/cw-do/sansdir
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


_MASK_EPILOG = """\
Examples:

  \b
  # Beam-stop circle + four corner rectangles in pixel coordinates.
  sansdir mask EQSANS_172749.nxs.h5 \\
    --circle 96,128,12 \\
    --rect 0,0,15,15 --rect 176,0,191,15 \\
    --rect 0,240,15,255 --rect 176,240,191,255 \\
    --output beam_stop_mask.nxs

  \b
  # Replay the same mask later from its sidecar log.
  sansdir mask EQSANS_172749.nxs.h5 \\
    --shapes-json beam_stop_mask.mask_log.json \\
    --output replay_mask.xml --format xml
"""


@main.command(epilog=_MASK_EPILOG)
@click.option(
    "--rect",
    "rects",
    multiple=True,
    metavar="X0,Y0,X1,Y1",
    help="Axis-aligned rectangle in pixel coords (repeatable).",
)
@click.option(
    "--ellipse",
    "ellipses",
    multiple=True,
    metavar="XC,YC,RX,RY",
    help="Axis-aligned ellipse (repeatable).",
)
@click.option(
    "--circle",
    "circles",
    multiple=True,
    metavar="XC,YC,R",
    help="Circle (repeatable).",
)
@click.option(
    "--polygon",
    "polygons",
    multiple=True,
    metavar="X1,Y1,X2,Y2,...",
    help="Polygon, ≥3 vertices, comma-separated (repeatable).",
)
@click.option(
    "--shapes-json",
    "shapes_json",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to a mask_log.json (or compatible) — appended to --rect/etc.",
)
@click.option(
    "--inverse",
    is_flag=True,
    default=False,
    help="Invert the FINAL union mask (1 ↔ 0).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Output file. Default: <source-stem>_mask.<ext> next to the source.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["xml", "nxs", "npy"]),
    default="nxs",
    show_default=True,
    help="Output format.",
)
@click.argument(
    "source",
    type=click.Path(exists=True, dir_okay=False),
)
def mask(
    source: str,
    rects: tuple[str, ...],
    ellipses: tuple[str, ...],
    circles: tuple[str, ...],
    polygons: tuple[str, ...],
    shapes_json: str | None,
    inverse: bool,
    output: str | None,
    fmt: str,
) -> None:
    """Build a Mantid-loadable detector mask for a raw EQSANS .nxs.h5 file.

    Mask convention: 1 = masked (excluded), 0 = kept.
    """
    from sansdir.mask.api import (
        create_mask,
        parse_circle,
        parse_ellipse,
        parse_polygon,
        parse_rect,
        shapes_from_json,
    )

    shapes = []
    for spec in rects:
        shapes.append(parse_rect(spec))
    for spec in ellipses:
        shapes.append(parse_ellipse(spec))
    for spec in circles:
        shapes.append(parse_circle(spec))
    for spec in polygons:
        shapes.append(parse_polygon(spec))
    json_inverse = False
    if shapes_json:
        from_json, json_inverse = shapes_from_json(shapes_json)
        shapes.extend(from_json)
    if not shapes:
        raise click.UsageError(
            "no shapes given — use --rect / --ellipse / --circle / "
            "--polygon / --shapes-json"
        )
    result = create_mask(
        source=source,
        shapes=shapes,
        output=output,
        fmt=fmt,
        inverse=inverse or json_inverse,
    )
    click.echo(str(result.output_path))
    click.echo(
        f"# masked {result.n_masked} of {result.n_total} pixels "
        f"({result.n_masked / result.n_total:.2%})"
    )
    click.echo(f"# log: {result.log_path}")


_USANS_EPILOG = """\
Examples:

  \b
  # Build a preliminary setup CSV + NOTE.md for an IPTS.
  sansdir usans init 37679 --start-run 49434

  \b
  # Review it, then reduce it (log-binning is on by default).
  $EDITOR IPTS-37679_setup.csv
  sansdir usans reduce IPTS-37679_setup.csv -o ./output

Reduction is delegated to the instrument team's `reduceUSANS`
(neutrons/usansred); sansdir only prepares the table and invokes it in a
clean environment. Nothing under /SNS is written to.
"""


@main.group(epilog=_USANS_EPILOG)
def usans() -> None:
    """USANS reduction — build a setup table, then reduce it.

    The same two operations the TUI exposes as ``usans.init_table`` and
    ``usans.reduce``, available headless for scripts and batch jobs.
    """


@usans.command("init")
@click.argument("ipts")
@click.option(
    "--start-run",
    type=int,
    default=None,
    help="First run of the experiment; earlier blocks are recorded in the NOTE only.",
)
@click.option(
    "--data-dir",
    type=click.Path(file_okay=False),
    default=None,
    help="Folder of pre-processed ARN ASCII (default: /SNS/USANS/<IPTS>/shared/autoreduce).",
)
@click.option(
    "--out-dir",
    "-d",
    type=click.Path(file_okay=False),
    default=".",
    show_default=True,
    help="Directory to write <IPTS>_setup.csv and <IPTS>_NOTE.md into.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False),
    default=None,
    help="Explicit setup-CSV path (overrides --out-dir for the CSV).",
)
@click.option(
    "--thickness",
    type=float,
    default=None,
    help="Default sample thickness in cm (default: [usans].thickness_cm).",
)
def usans_init(
    ipts: str,
    start_run: int | None,
    data_dir: str | None,
    out_dir: str,
    output: str | None,
    thickness: float | None,
) -> None:
    """Build a preliminary USANS reduction table for IPTS from OnCat.

    Groups the run list by title, auto-detects the empty-cell background,
    and sets num_of_scans from the ARN-scan files actually on disk. The
    result is *preliminary*: read the NOTE and correct the CSV before
    reducing.
    """
    import asyncio
    from pathlib import Path

    from sansdir.config import load_config
    from sansdir.core.oncat import OnCatClient, OnCatError
    from sansdir.usans.catalog import build_catalog, ipts_label, output_paths, write_outputs

    cfg = load_config()
    label = ipts_label(ipts)

    async def _fetch() -> list:  # type: ignore[type-arg]
        async with OnCatClient(cfg.oncat) as client:
            return await client.list_datafiles(label, instrument="USANS")

    try:
        runs = asyncio.run(_fetch())
    except OnCatError as exc:
        raise click.ClickException(f"OnCat: {exc}") from exc
    if not runs:
        raise click.ClickException(f"OnCat returned no USANS runs for {label}")

    cat = build_catalog(
        label,
        runs,
        start_run=start_run,
        data_dir=data_dir,
        data_dir_template=cfg.usans.data_dir_template,
        thickness_cm=thickness if thickness is not None else cfg.usans.thickness_cm,
    )
    csv_path, note_path = output_paths(cat, out_dir)
    if output:
        csv_path = Path(output)
        note_path = csv_path.with_name(f"{label}_NOTE.md")
    write_outputs(cat, csv_path, note_path, logbin=cfg.usans.logbin)
    click.echo(str(csv_path))
    click.echo(str(note_path))
    for warning in cat.warnings:
        click.echo(f"# warning: {warning}", err=True)


@usans.command("reduce")
@click.argument("setup_csv", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--data-dir",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Folder of pre-processed ARN ASCII (default: derived from the IPTS).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=False),
    default="output",
    show_default=True,
    help="Directory for the reduced curves.",
)
@click.option(
    "--no-logbin",
    is_flag=True,
    default=False,
    help="Skip -l; reduce without log-binning (no UN_*_det_1_lb.txt).",
)
def usans_reduce(
    setup_csv: str,
    data_dir: str | None,
    output: str,
    no_logbin: bool,
) -> None:
    """Reduce SETUP_CSV with the installed reduceUSANS engine.

    The engine reads its per-run ASCII from the directory holding the CSV,
    so when the CSV lives elsewhere sansdir stages a throwaway directory of
    symlinks — the instrument's data folder is never written to.
    """
    from sansdir.config import load_config
    from sansdir.usans import runner
    from sansdir.usans.catalog import default_data_dir, ipts_from_path
    from sansdir.usans.table import ReductionTable, TableError

    cfg = load_config()
    if setup_csv.lower().endswith(".csv"):
        try:
            table = ReductionTable.from_csv(setup_csv)
        except TableError as exc:
            raise click.ClickException(str(exc)) from exc
        problems = table.validate()
        if problems:
            raise click.ClickException(
                "setup table is not reducible:\n  " + "\n  ".join(problems)
            )
        ipts = table.ipts or ipts_from_path(setup_csv)
    else:
        ipts = ipts_from_path(setup_csv)

    resolved = data_dir or (
        str(default_data_dir(ipts, cfg.usans.data_dir_template)) if ipts else ""
    )
    if not resolved:
        raise click.ClickException(
            "could not derive the USANS data directory from the CSV — pass --data-dir"
        )

    try:
        result = runner.reduce_csv(
            setup_csv,
            data_dir=resolved,
            output_dir=output,
            logbin=not no_logbin and cfg.usans.logbin,
            command=cfg.usans.reduce_command,
            pixi_manifest=cfg.usans.pixi_manifest,
            timeout=cfg.usans.reduce_timeout_seconds or None,
        )
    except (runner.ReduceError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    if not result.ok:
        click.echo(result.stdout, err=True)
        click.echo(result.stderr, err=True)
        raise click.ClickException(f"reduceUSANS exited {result.returncode}")
    for path in result.produced:
        click.echo(str(path))


@main.command()
def version() -> None:
    """Print the sansdir version and exit."""
    click.echo(f"sansdir {__version__}")


if __name__ == "__main__":
    main()
