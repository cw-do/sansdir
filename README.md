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
editing. It currently lags `sansdir-report.tex`, which gained the USANS
reduction section in v0.10 — see the regression note below.

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
installs here, so `fetch-texdeps.sh` downloads them straight from the CTAN
tlnet archive into a private tree instead. Nothing outside that tree is
touched:

```bash
./fetch-texdeps.sh                                    # ~40 MB into /tmp/texdeps/tl
export TEXMFHOME=/tmp/texdeps/tl
export PATH="/tmp/texdeps/tl/bin/x86_64-linux:$PATH"  # biber
make
```

This is the toolchain that produced the checked-in PDF; a clean run finishes
with no errors, no undefined references or citations, and one overfull hbox.

One caveat, documented in the script: do **not** add `l3kernel`, `l3packages`,
or `l3backend` to it. Current versions need a newer LaTeX format than the 2020
one installed here and abort with "Mismatched LaTeX support files detected."
The system's own `expl3` works with the `acro` release the script fetches.

**Known regression (2026-08).** The script pulls from the *current* tlnet
archive, so it now fetches a `tocloft` that requires LaTeX 2023-11-01. On this
host's 2020 format it throws `Undefined control sequence`
(`\IfDocumentMetadataTF`, `\DeclareInstance`) and mangles the table of
contents — `make` still emits a PDF, but a shorter, wrong one. Until the script
pins versions, **build the report on Overleaf or a `texlive-full` host** and
treat a PDF produced here as untrustworthy. The `.tex` remains the source of
truth; the checked-in PDF is only refreshed from a good toolchain.

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
