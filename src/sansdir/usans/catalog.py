"""Turn an IPTS run list into a reviewable reduction table + NOTE.md.

This is the heart of ``usans.init_table``: take an already-fetched run list
(the OnCat call happens in the caller, so this module stays network-free),
group it into titled blocks, reconcile each block against the pre-processed
ASCII files on disk so ``num_of_scans`` counts only the ARN rocking scans
the engine can use, auto-pick the background, and emit both the
engine-ready setup CSV and a human-readable NOTE.

The CSV is **preliminary by design**. Everything the generator had to guess
— restarts, odd block sizes, missing ARN files — is surfaced in the NOTE so
the user can correct the CSV with ``F4`` before reducing.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sansdir.usans.grouping import (
    DEFAULT_THICKNESS_CM,
    Group,
    RunLike,
    apply_start_run,
    default_background,
    group_runs,
)
from sansdir.usans.reconcile import (
    REASON_OFF_WAVELENGTH,
    REASON_PAUSE,
    flag_restarts,
    modal_scan_count,
    reconcile,
)
from sansdir.usans.table import ReductionTable

# Where the pre-processed per-run ASCII files live, by convention.
DATA_DIR_TEMPLATE: str = "/SNS/USANS/{ipts}/shared/autoreduce"

# Filenames written next to each other by :func:`write_outputs`.
SETUP_CSV_TEMPLATE: str = "{ipts}_setup.csv"
NOTE_TEMPLATE: str = "{ipts}_NOTE.md"


def ipts_label(ipts: str | int) -> str:
    """Normalise ``37679`` / ``"37679"`` / ``"IPTS-37679"`` → ``"IPTS-37679"``."""
    text = str(ipts).strip()
    if not text:
        return ""
    if text.upper().startswith("IPTS-"):
        return "IPTS-" + text[5:]
    return f"IPTS-{text}"


def default_data_dir(ipts: str | int, template: str = DATA_DIR_TEMPLATE) -> Path:
    """The autoreduce folder holding the pre-processed ASCII files."""
    return Path(template.format(ipts=ipts_label(ipts)))


def ipts_from_path(path: str | Path) -> str:
    """Recover ``IPTS-NNNNN`` from any path containing it; ``""`` on miss."""
    for part in Path(path).resolve().parts:
        if part.upper().startswith("IPTS-") and part[5:].isdigit():
            return f"IPTS-{part[5:]}"
    return ""


@dataclass
class Catalog:
    """The full result of :func:`build_catalog`.

    Attributes:
        ipts: Normalised IPTS label.
        groups: Every titled block, included or not.
        background: The block chosen as the empty cell, or ``None``.
        table: The engine-ready :class:`~sansdir.usans.table.ReductionTable`.
        data_dir: The autoreduce folder used for reconciliation, if any.
        reconciled: True when ``num_of_scans`` was verified against ARN files.
        restarts: Blocks narrowed by the restart heuristic; need review.
    """

    ipts: str
    groups: list[Group]
    background: Group | None
    table: ReductionTable
    data_dir: Path | None
    reconciled: bool
    restarts: list[Group]

    @property
    def warnings(self) -> list[str]:
        """One-line problems worth showing in the status bar / CLI output."""
        out: list[str] = []
        if not self.reconciled:
            out.append("data dir not found — num_of_scans is unverified (title grouping only)")
        if self.background is None:
            out.append("no background block detected — set one ('b' flag) before reducing")
        if self.restarts:
            names = ", ".join(g.name for g in self.restarts)
            out.append(f"possible restart in: {names} — verify start_scan/num_of_scans")
        empty = [g.name for g in self.groups if g.included and g.reduce_count == 0]
        if empty:
            out.append(f"no ARN scans on disk for: {', '.join(empty)} (left out of the CSV)")
        # A block's trailing transmission run is routine; runs dropped for
        # any other reason are worth a status-bar mention.
        unusual = [
            r
            for g in self.groups
            if g.included and g.reduce_count
            for r, why in g.skipped.items()
            if why.startswith((REASON_OFF_WAVELENGTH, REASON_PAUSE))
        ]
        if unusual:
            out.append(
                f"{len(unusual)} pause/off-wavelength runs left out of their blocks — "
                "listed with reasons in the NOTE"
            )
        odd = [r for g in self.groups if g.included for r in g.run_warnings]
        if odd:
            out.append(f"suspicious runs kept: {', '.join(map(str, odd))} — see the NOTE")
        out.extend(self.table.validate())
        out.extend(self.table.advisories())
        return out


def build_catalog(
    ipts: str | int,
    runs: Sequence[RunLike],
    *,
    start_run: int | None = None,
    data_dir: str | Path | None = None,
    data_dir_template: str = DATA_DIR_TEMPLATE,
    thickness_cm: float | None = None,
    skip_off_wavelength: bool = True,
    transmission_row: bool = True,
) -> Catalog:
    """Build a preliminary reduction table from an already-fetched run list.

    Deliberately network-free: the caller (TUI command or CLI) fetches the
    runs via :class:`sansdir.core.oncat.OnCatClient` and passes them in.

    Args:
        ipts: IPTS number or label.
        runs: Objects with ``run_number`` and ``title`` (OnCat ``Datafile``
            satisfies this).
        start_run: Drop blocks starting before this run from the table.
        data_dir: Autoreduce folder to reconcile against. ``None`` derives
            it from ``ipts`` and uses it only if it exists.
        data_dir_template: Override the ``/SNS/USANS/{ipts}/shared/autoreduce``
            convention (config: ``[usans].data_dir_template``).
        thickness_cm: Default sample thickness for every row.
        skip_off_wavelength: Leave out runs recorded only at a non-primary
            wavelength (the 1.2 Å first run of each block); see
            :mod:`sansdir.usans.reconcile`. Always listed in the NOTE.
        transmission_row: Write the empty cell as a ``t`` row as well as a
            ``b`` row, so the engine divides by T before subtracting.

    Returns:
        A :class:`Catalog` holding the blocks, the table and the warnings.
    """
    label = ipts_label(ipts)
    groups = group_runs(runs)
    if thickness_cm is not None:
        for g in groups:
            g.thickness_cm = thickness_cm
    apply_start_run(groups, start_run)

    resolved = (
        Path(data_dir) if data_dir is not None else default_data_dir(label, data_dir_template)
    )
    reconciled = resolved.is_dir()
    if reconciled:
        reconcile(groups, resolved, skip_off_wavelength=skip_off_wavelength)
        restarts = flag_restarts(groups)
    else:
        restarts = []

    background = default_background(groups)
    table = ReductionTable.from_groups(label, groups, background, transmission_row=transmission_row)
    return Catalog(
        ipts=label,
        groups=groups,
        background=background,
        table=table,
        data_dir=resolved if reconciled else None,
        reconciled=reconciled,
        restarts=restarts,
    )


# ---------------------------------------------------------------------------
# NOTE.md rendering
# ---------------------------------------------------------------------------


def render_note(
    cat: Catalog,
    *,
    today: str | None = None,
    logbin: bool = True,
    short_name_copy: bool = True,
) -> str:
    """Render the human-readable companion to the setup CSV.

    Everything the generator guessed or dropped goes here: skipped
    pre-start blocks, runs left out of each block (and why), title annotations, restart
    suspicions and odd block sizes — plus a legend for the reduced-output
    filenames, which are the engine's and are easy to misread.

    Args:
        cat: The catalog to describe.
        today: Override the generation date (tests pin this).
        logbin: Whether the reduction will pass ``-l``. Changes which
            files appear and what ``_background_subtracted`` contains.
        short_name_copy: Whether the reduce will also write ``_bsub.txt``
            aliases; documented in the legend so the user knows both names
            point at the same curve.
    """
    today = today or date.today().isoformat()
    typical = modal_scan_count(cat.groups)
    lines: list[str] = [
        f"# USANS reduction notes — {cat.ipts}",
        "",
        "- Instrument: USANS",
        f"- Generated: {today} by sansdir",
    ]
    if cat.groups:
        lines.append(
            f"- Titled blocks: {len(cat.groups)} "
            f"(runs {cat.groups[0].start_run}-{cat.groups[-1].runs[-1]})"
        )
    if cat.reconciled:
        lines.append(f"- Data dir: `{cat.data_dir}` (reconciled against ARN-scan files)")
        if typical:
            lines.append(
                f"- Typical block: {typical} usable rocking scans; runs left out "
                "of each block are listed below with the reason."
            )
    else:
        lines.append(
            "- Data dir: **not found** — `num_of_scans` reflects OnCat title "
            "grouping only (NOT verified against ARN-scan files)."
        )
    bg = cat.background
    if bg is not None and bg.reduce_count:
        lines.append(
            f"- Background (empty cell): **{bg.name}** runs "
            f"{bg.reduce_start}-{bg.reduce_runs[-1]} ({bg.reduce_count} scans)"
        )
        if cat.table.transmissions:
            lines.append(
                f"  - written twice: `t,{cat.table.transmissions[0].name}` (empty cell: "
                f"transmission reference, divides by T) and `b,{bg.name}` (subtracted) "
                "→ I = S/T - B. At reduce time sansdir converts the CSV to usansred's JSON "
                "(`t` → `empty_cell`, `b` → `background`) — the engine's CSV reader cannot "
                "take an empty cell."
            )
    else:
        lines.append(
            "- Background: **none detected** — flag the empty cell `b` (and `t`, as a "
            "second row over the same runs) in the CSV before reducing."
        )
    lines.append("")
    lines.extend(_render_thickness_callout(cat))
    lines.append("Review this table, fix the CSV with `F4`, then reduce with `r`.")
    lines.append("")

    lines.extend(_render_table_section(cat))
    lines.extend(_render_restart_section(cat))
    lines.extend(_render_skipped_section(cat))
    lines.extend(_render_run_warning_section(cat))
    lines.extend(_render_annotation_section(cat))
    lines.extend(_render_excluded_section(cat))
    lines.extend(_render_odd_size_section(cat, typical))
    lines.extend(_render_output_legend(cat, logbin=logbin, short_name_copy=short_name_copy))
    return "\n".join(lines).rstrip() + "\n"


def _render_table_section(cat: Catalog) -> list[str]:
    lines = [
        "## Samples in reduction table",
        "",
        "| name | scan runs | # | thickness (cm) | note |",
        "|------|-----------|---|----------------|------|",
    ]
    for r in cat.table.rows:
        span = f"{r.start_run}-{r.end_run}" if r.num_runs > 1 else f"{r.start_run}"
        excl = f" (excl {','.join(map(str, r.exclude))})" if r.exclude else ""
        notes = []
        if r.is_transmission:
            notes.append("transmission reference (t)")
        if r.is_background:
            notes.append("background (b)")
        if r.restart_suspect:
            notes.append("⚠ possible restart")
        if r.annotation:
            notes.append(r.annotation)
        lines.append(
            f"| {r.name} | {span}{excl} | {r.num_runs} | {r.thickness_cm:g} | {'; '.join(notes)} |"
        )
    lines.append("")
    return lines


def _render_restart_section(cat: Catalog) -> list[str]:
    if not cat.restarts:
        return []
    lines = [
        "## ⚠ Possible restarts — verify before reducing",
        "",
        "These titles hold more ARN scans than the rest of the experiment, "
        "which usually means the measurement was stopped and restarted under "
        "the same title. sansdir guessed the **last** window is the real "
        "measurement; confirm `start_scan` / `num_of_scans` in the CSV.",
        "",
    ]
    for g in cat.restarts:
        rr = g.reduce_runs
        kept = f"{rr[0]}-{rr[-1]}" if rr else "none"
        dropped = ", ".join(map(str, g.dropped_runs)) or "none"
        lines.append(f"- `{g.title}` — kept {kept} ({g.reduce_count} scans); dropped {dropped}")
    lines.append("")
    return lines


def _render_thickness_callout(cat: Catalog) -> list[str]:
    """Loud reminder that every thickness is a placeholder, not a measurement."""
    values = sorted({r.thickness_cm for r in cat.table.rows})
    if not values:
        return []
    shown = ", ".join(f"{v:g}" for v in values)
    default = values == [DEFAULT_THICKNESS_CM]
    return [
        "> **⚠ THICKNESS — CONFIRM BEFORE REDUCING.** Every row uses "
        f"**{shown} cm**, "
        + ("sansdir's built-in default, " if default else "the `[usans].thickness_cm` setting, ")
        + "not a measured value. The engine divides by it, so a wrong value "
        "rescales the whole curve. Fix column 5 of the CSV with `F4`.",
        "",
    ]


def _render_skipped_section(cat: Catalog) -> list[str]:
    """Every run left out of an included block, grouped by block, with the reason."""
    blocks = [g for g in cat.groups if g.included and g.skipped]
    if not blocks:
        return []
    lines = [
        "## Runs left out of each block, and why",
        "",
        "The engine reads `num_of_scans` consecutive runs from `start_scan`, so a "
        "run left out at the start or end of a block moves `start_scan` / "
        "`num_of_scans`, and one in the middle goes in the `exclude` column.",
        "",
        "- **pause** — no ARN scan files and a near-zero monitor.",
        "- **no ARN scan files** — typically the block's transmission run; "
        "reading it makes `reduceUSANS` fail with `FileNotFoundError`.",
        "- **off-wavelength** — recorded only at a non-primary wavelength "
        "(`USANS_<run>_detector_1.2.txt`, no `_3.6`). It has ARN files but "
        "essentially no usable counts. Why these runs exist is not yet known; set "
        "`[usans].skip_off_wavelength = false` to keep them.",
        "",
    ]
    for g in blocks:
        lines.append(f"- **{g.name}** (`{g.title}`, runs {g.start_run}-{g.runs[-1]}):")
        lines.extend(f"  - {run}: {reason}" for run, reason in sorted(g.skipped.items()))
    lines.append("")
    return lines


def _render_run_warning_section(cat: Catalog) -> list[str]:
    blocks = [g for g in cat.groups if g.included and g.run_warnings]
    if not blocks:
        return []
    lines = ["## ⚠ Runs kept but worth a look", ""]
    for g in blocks:
        lines.extend(
            f"- **{g.name}** {run}: {note}" for run, note in sorted(g.run_warnings.items())
        )
    lines.append("")
    return lines


def _render_annotation_section(cat: Catalog) -> list[str]:
    annotated = [(r.name, r.annotation) for r in cat.table.rows if r.annotation]
    if not annotated:
        return []
    lines = [
        "## Title annotations",
        "",
        "Extra text after the sample name in the run title, kept verbatim "
        "(e.g. `1p`/`0p` sample-position markers):",
        "",
    ]
    lines.extend(f"- **{name}**: `{ann}`" for name, ann in annotated)
    lines.append("")
    return lines


def _render_excluded_section(cat: Catalog) -> list[str]:
    excluded = [g for g in cat.groups if not g.included]
    empty = [g for g in cat.groups if g.included and g.reduce_count == 0]
    if not excluded and not empty:
        return []
    lines = ["## Blocks left out of the reduction table", ""]
    for g in excluded:
        lines.append(
            f"- `{g.title}` - runs {g.start_run}-{g.runs[-1]} ({g.count} runs) — before start_run"
        )
    for g in empty:
        lines.append(
            f"- `{g.title}` - runs {g.start_run}-{g.runs[-1]} "
            f"({g.count} runs) — no ARN scan files on disk"
        )
    lines.append("")
    return lines


def _render_odd_size_section(cat: Catalog, typical: int | None) -> list[str]:
    if typical is None:
        return []
    odd = [
        g
        for g in cat.groups
        if g.included and not g.is_background and 0 < g.reduce_count != typical
    ]
    if not odd:
        return []
    lines = [f"## ⚠ Blocks with ≠ {typical} scan runs", ""]
    for g in odd:
        rr = g.reduce_runs
        span = f"{rr[0]}-{rr[-1]}" if rr else "none"
        lines.append(f"- `{g.title}` — {g.reduce_count} scans ({span}) — verify before reducing")
    lines.append("")
    return lines


def _render_output_legend(
    cat: Catalog, *, logbin: bool = True, short_name_copy: bool = True
) -> list[str]:
    """Explain the reduced-output filename postfixes.

    These names come from ``reduceUSANS`` itself, not from sansdir, and
    they are genuinely confusing: ``_lb`` looks final but is the
    subtraction's *input*, and the file you actually want was called
    ``_lbs.txt`` by the older loose script. Spelling it out next to every
    generated table costs nothing and saves plotting the wrong curve.

    When ``short_name_copy`` is on, the legend also names the ``_bsub.txt``
    alias sansdir writes beside the engine's verbose file.
    """
    bg_name = cat.background.name if cat.background is not None else "<background>"
    final = "UN_<name>_det_1_background_subtracted.txt"
    plot_line = f"**Plot `{final}`**" + (
        " (or its shorter alias `UN_<name>_det_1_bsub.txt`)" if short_name_copy else ""
    )
    lines = [
        "## What the reduced filenames mean",
        "",
        "`reduceUSANS` writes one set of these per sample into the output "
        "directory you choose at reduce time. The names are the engine's "
        "(`usansred`), not sansdir's.",
        "",
    ]
    if logbin:
        lines += [
            "| file | scaled | log-binned | background subtracted |",
            "|------|--------|------------|-----------------------|",
            "| `UN_<name>_det_1_unscaled.txt` | no | no | no |",
            "| `UN_<name>_det_1.txt` | yes | no | no |",
            "| `UN_<name>_det_1_lb.txt` | yes | yes | **no** |",
            f"| `{final}` | yes | yes | **yes** |",
            "",
            f"{plot_line}. That is the "
            "final reduced curve — log-binned *and* background subtracted. "
            "Older scripts called this file `_lbs.txt`; `usansred` renamed it.",
            "",
            "`_lb.txt` is the subtraction's *input*, not its output: it still "
            "contains the empty-cell scattering. If your data looks like the "
            "background was never subtracted, you are probably looking at this file.",
        ]
    else:
        lines += [
            "Reduction is running **without** `-l` (log-binning off), so there is "
            "no `_lb.txt`, and the subtraction is done by interpolation onto the "
            "sample's own q values rather than on a shared log grid.",
            "",
            "| file | scaled | background subtracted |",
            "|------|--------|-----------------------|",
            "| `UN_<name>_det_1_unscaled.txt` | no | no |",
            "| `UN_<name>_det_1.txt` | yes | no |",
            f"| `{final}` | yes | **yes** |",
            "",
            f"{plot_line} for the final curve.",
        ]
    if short_name_copy:
        lines += [
            "",
            "sansdir also writes a shorter alias, "
            "`UN_<name>_det_1_bsub.txt`, beside each `_background_subtracted.txt` "
            "(identical contents). The long name is kept so the engine's "
            "`summary.xlsx` and other tools still find it.",
        ]
    lines += [
        "",
        "Which corrections are in `_background_subtracted` depends on the flags:",
        "",
        "| rows in the CSV | T (transmission) | empty cell subtracted | result |",
        "|-----------------|------------------|-----------------------|--------|",
        "| `t` + `b` (same runs) | from the `t` row | `b` | S/T - B |",
        "| `b` only | **1** (no correction) | `b` | S - B |",
        "| `t` only | from the `t` row | `t` (the empty cell) | S/T - EC |",
        "| neither | **1** | **nothing** | S |",
        "",
        "Without a `b` or `t` row nothing is subtracted, so `_background_subtracted` "
        "is really the unsubtracted data. Check the engine log for "
        "`Transmission coefficient for sample <name>`: exactly 1.0000 means no "
        "empty cell was used. T is computed by usansred 1.9.0 as the sample's "
        "(detector + transmission counts) / monitor over the empty cell's; the "
        "translated config is kept beside the output as `<csv stem>.usansred.json`.",
        "",
        f"The background sample itself (`{bg_name}`) gets **no** "
        "`_background_subtracted.txt` — nothing is subtracted from itself, so it "
        "has one file fewer than each sample. That is correct, not a failed run.",
        "",
        "All curves are `q,I,E`, comma-separated with a trailing delimiter. "
        "`summary.xlsx` collects them with plots. At low q the subtraction "
        "commonly goes negative, where sample and empty cell are both "
        "direct-beam dominated; those points cannot be drawn on a log-log plot "
        "and simply disappear, which is expected rather than missing data.",
        "",
    ]
    return lines


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def output_paths(cat_or_ipts: Catalog | str, out_dir: str | Path) -> tuple[Path, Path]:
    """``(setup_csv, note_md)`` paths for an IPTS inside ``out_dir``."""
    label = cat_or_ipts.ipts if isinstance(cat_or_ipts, Catalog) else ipts_label(cat_or_ipts)
    base = Path(out_dir)
    return (
        base / SETUP_CSV_TEMPLATE.format(ipts=label),
        base / NOTE_TEMPLATE.format(ipts=label),
    )


def write_outputs(
    cat: Catalog,
    csv_path: str | Path,
    note_path: str | Path,
    *,
    today: str | None = None,
    logbin: bool = True,
    short_name_copy: bool = True,
) -> tuple[Path, Path]:
    """Write the setup CSV and the NOTE; returns both paths.

    ``logbin`` and ``short_name_copy`` should match what the reduction will
    actually do, so the NOTE's filename legend describes the files the user
    will really get.
    """
    csv_path = Path(csv_path)
    note_path = Path(note_path)
    cat.table.to_csv(csv_path)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        render_note(
            cat,
            today=today,
            logbin=logbin,
            short_name_copy=short_name_copy,
        ),
        encoding="utf-8",
    )
    return csv_path, note_path


def summarize(cat: Catalog) -> str:
    """One-line summary suitable for a status-bar notify."""
    bits: Iterable[str] = (
        f"{len(cat.table.rows)} rows",
        f"bg={cat.background.name}" if cat.background else "bg=?",
        "reconciled" if cat.reconciled else "unverified",
    )
    return " · ".join(bits)
