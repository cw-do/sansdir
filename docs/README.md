# sansdir technical report

ORNL Technical Memorandum describing sansdir, built on the ORNL report template
(`ornltm.cls`).

## Files

| File | Role |
|---|---|
| `sansdir-report.tex` | The report. |
| `sansdir-abbreviations.tex` | Acronym declarations for this report. |
| `sansdir.bib` | Bibliography. |
| `figures/` | Generated figures (see below). |
| `Makefile` | Build targets. |
| `make_figures.py` | Regenerates every figure from the live code. |
| `ornltm.cls`, `ornltm-style.sty`, `luggage/` | The ORNL template, unmodified. |
| `ornl-report-example.tex`, `abbreviations.tex`, `example.bib` | The template's own example, left pristine for reference. |

## Building

`sansdir-report.pdf` (49 pp.) is checked in, so you only need to build after
editing.

On Overleaf or any `texlive-full` host:

```bash
make            # pdflatex -> biber -> pdflatex x2
make figures    # regenerate screenshots and plots from the code
make clean
```

### Building on the analysis cluster

The cluster's stock TeX Live 2020 is missing everything `ornltm.cls` needs
(`wallpaper`, `adjustbox`, `emptypage`, `acro`, `tocloft`, `framed`,
`seqsplit`), the `newtx` Times fonts, several report dependencies
(`biblatex-chicago`, `threeparttable`, `multirow`, `xpatch`, `xstring`,
`hyphenat`, `logreq`), and `biber`. Fedora's `tlmgr` refuses `--usermode`
installs here, so `fetch-texdeps.sh` downloads them into a private tree
instead. Nothing outside that tree is touched:

```bash
./fetch-texdeps.sh                                     # ~40 MB into /tmp/texdeps/tl
export TEXMFHOME=/tmp/texdeps/tl
export PATH="/tmp/texdeps/tl/bin/x86_64-linux:$PATH"   # for biber
eval "$(./fetch-texdeps.sh --libnsl-env)"              # only if biber errors on libnsl.so.1
make figures    # only needed after `make distclean`, or the first time
make
```

This is the toolchain that produces the checked-in PDF; a clean run finishes
with no errors, no undefined references or citations, and one 2.8pt overfull
hbox (cosmetic — nothing is clipped).

Two things worth knowing if this ever breaks again:

**The mirror is a dated snapshot, not the live one, and that is load-bearing.**
`fetch-texdeps.sh` pins `MIRROR` to a specific date on
`texlive.info/tlnet-archive` rather than CTAN's live tlnet, because the live
mirror's packages drift forward in time and eventually stop being compatible
with this host's TeX Live 2020 format — that happened once already (2026-08:
the live mirror's `tocloft` required LaTeX format 2023-11-01 and the build
silently produced a shorter, wrong PDF). Pinning one date keeps every fetched
package mutually consistent. If a future edit needs a package not in the
pinned snapshot, bump `SNAPSHOT_DATE` in the script and re-verify the whole
build — don't add a second mirror for just the new package, or the
consistency guarantee is gone.

Also do **not** add `l3kernel`, `l3packages`, or `l3backend` to the fetch
list: current versions need a newer LaTeX format than the 2020 one installed
here and abort with "Mismatched LaTeX support files detected." The system's
own `expl3` works with the `acro` release the script fetches.

**`biber` can fail with `libnsl.so.1: cannot open shared object file`.** It
was built against a glibc old enough to still ship `libnsl` directly; modern
distros provide the ABI-compatible replacement under a different soname
(this host's RHEL 9 `libnsl2` package gives `libnsl.so.3`). Rather than hunt
for a path by hand, `./fetch-texdeps.sh --libnsl-env` asks the dynamic linker
what is actually installed, symlinks a `libnsl.so.1` shim next to the fetched
tree, and prints the `export LD_LIBRARY_PATH=...` line to `eval`. If it exits
with "no libnsl.so.\* found," install `libnsl2` (or your distro's equivalent)
first.

## Figures

No figure is drawn by hand. `make_figures.py` produces them from the live code
base so they cannot drift from the program:

- `tui-panes.pdf`, `hdf-search.pdf`, `help-overlay.pdf` — real screenshots,
  captured by driving `SansdirApp` through Textual's headless pilot and calling
  `save_screenshot()`. SVG output is converted to PDF with `rsvg-convert`.
- `plot-iq.pdf`, `plot-detector.pdf` — real plots, produced by calling
  sansdir's own `make_iq_figure()` and `make_detector_figure()` on the
  fixtures in `tests/data/`.
- `fig-architecture.tex`, `fig-plotflow.tex` — TikZ source, `\input` directly.

## Before submitting

- Replace `\reportnum{ORNL/TM-20XX/XXXX}` with the number issued by RESolution.
  The title in RESolution must match the `\title{}` here exactly.
- Remove `\reportdraft` for public release and unlimited distribution.
- Confirm `\division{}` is correct.
