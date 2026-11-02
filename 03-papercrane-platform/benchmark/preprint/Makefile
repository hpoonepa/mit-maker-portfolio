# Paper Crane benchmark preprint build
#
# Targets:
#   make build    - compile paper.pdf via pdflatex + bibtex
#   make clean    - remove LaTeX build artifacts and paper.pdf
#   make assets   - regenerate figures/ and tables/ from the live database
#   make package  - build and zip a versioned release archive

SHELL        := /bin/bash
PAPER        := paper
VERSION      ?= $(shell date -u +%Y.%m)
DATE         ?= $(shell date -u +%Y%m%d)
ZIP_NAME     := benchmark-v$(VERSION)-$(DATE).zip
METHODOLOGY  := methodology

.PHONY: build clean assets package

build: $(PAPER).pdf

$(PAPER).pdf: $(PAPER).tex references.bib tables/results.tex
	pdflatex -interaction=nonstopmode -halt-on-error $(PAPER).tex
	bibtex $(PAPER)
	pdflatex -interaction=nonstopmode -halt-on-error $(PAPER).tex
	pdflatex -interaction=nonstopmode -halt-on-error $(PAPER).tex

clean:
	rm -f *.aux *.log *.bbl *.blg *.out *.toc $(PAPER).pdf

assets:
	tsx generate-assets.ts

# Create a methodology symlink (points to the repo-wide methodology bundle if
# it exists) so the packaged archive can ship it without duplicating files.
$(METHODOLOGY):
	@if [ ! -e $(METHODOLOGY) ]; then \
		if [ -d ../methodology ]; then \
			ln -s ../methodology $(METHODOLOGY); \
		else \
			mkdir -p $(METHODOLOGY); \
			echo "Placeholder methodology bundle. See repository docs." \
				> $(METHODOLOGY)/README.txt; \
		fi; \
	fi

package: build $(METHODOLOGY)
	rm -f $(ZIP_NAME)
	zip -r $(ZIP_NAME) \
		$(PAPER).pdf \
		data \
		figures \
		tables \
		$(METHODOLOGY)
	@echo "Packaged $(ZIP_NAME)"
