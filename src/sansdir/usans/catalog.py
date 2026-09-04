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
    Group,
    RunLike,
    apply_start_run,
    default_background,
    group_runs,
)
from sansdir.usans.reconcile import flag_restarts, modal_scan_count, reconcile
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
        out.extend(self.table.validate())
        return out


def build_catalog(
    ipts: str | int,
    runs: Sequence[RunLike],
    *,
    start_run: int | None = None,
    data_dir: str | Path | None = None,
    data_dir_template: str = DATA_DIR_TEMPLATE,
    thickness_cm: float | None = None,
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
        reconcile(groups, resolved)
        restarts = flag_restarts(groups)
    else:
        restarts = []

    background = default_background(groups)
    table = ReductionTable.from_groups(label, groups, background)
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
    pre-start blocks, transmission runs, title annotations, restart
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
                f"- Each block = {typical} ARN rocking scans + 1 transmission run; "
                "only the ARN scans are reduced."
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
    else:
        lines.append(
            "- Background: **none detected** — flip one row's flag to `b` "
            "in the CSV before reducing."
        )
    lines.append("")
    lines.append("Review this table, fix the CSV with `F4`, then reduce with `r`.")
    lines.append("")

    lines.extend(_render_table_section(cat))
    lines.extend(_render_restart_section(cat))
    lines.extend(_render_transmission_section(cat))
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
        if r.is_background:
            notes.append("background")
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


def _render_transmission_section(cat: Catalog) -> list[str]:
    trans = [
        (g.name, g.transmission_runs) for g in cat.groups if g.included and g.transmission_runs
    ]
    if not trans:
        return []
    lines = [
        "## Transmission runs (excluded from reduction)",
        "",
        "Last run of each block — no ARN rocking scan, so the engine cannot "
        "read it. Including it is what makes `reduceUSANS` fail with "
        "`FileNotFoundError`.",
        "",
    ]
    lines.extend(f"- **{name}**: {', '.join(map(str, runs))}" for name, runs in trans)
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
    plot_line = (
        f"**Plot `{final}`**"
        + (" (or its shorter alias `UN_<name>_det_1_bsub.txt`)" if short_name_copy else "")
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
        render_note(cat, today=today, logbin=logbin, short_name_copy=short_name_copy),
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
