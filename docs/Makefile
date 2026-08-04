# Build the sansdir technical report.
#
#   make            -> sansdir-report.pdf
#   make figures    -> regenerate screenshots and plots from the live code
#   make clean      -> remove LaTeX intermediates
#   make distclean  -> also remove the PDF and generated figures
#
# Requires a full TeX Live (the ornltm class pulls in wallpaper, adjustbox,
# acro, tocloft, framed, seqsplit, biblatex-chicago) and biber. Overleaf has
# all of these; a minimal distro TeX install does not.

DOC      := sansdir-report
PYTHON   := ../.venv/bin/python
FIGDIR   := figures

# Figures that are generated from the running application / real data.
GENFIGS  := $(FIGDIR)/tui-panes.pdf \
            $(FIGDIR)/hdf-search.pdf \
            $(FIGDIR)/help-overlay.pdf \
            $(FIGDIR)/plot-iq.pdf \
            $(FIGDIR)/plot-detector.pdf

.PHONY: all figures clean distclean

all: $(DOC).pdf

$(DOC).pdf: $(DOC).tex sansdir.bib sansdir-abbreviations.tex \
            $(FIGDIR)/fig-architecture.tex $(GENFIGS)
	pdflatex -interaction=nonstopmode $(DOC)
	biber $(DOC)
	pdflatex -interaction=nonstopmode $(DOC)
	pdflatex -interaction=nonstopmode $(DOC)

# Screenshots are captured by driving the real app through Textual's headless
# pilot; plots are produced by sansdir's own plotting modules. Both are
# regenerated from scratch, so the figures never drift from the code.
figures:
	cd .. && $(PYTHON) docs/make_figures.py

clean:
	rm -f $(DOC).aux $(DOC).log $(DOC).out $(DOC).toc $(DOC).lof $(DOC).lot \
	      $(DOC).bbl $(DOC).bcf $(DOC).blg $(DOC).run.xml $(DOC).acr

distclean: clean
	rm -f $(DOC).pdf $(GENFIGS) $(FIGDIR)/*.svg
