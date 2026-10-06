latexcmd = latexmk -pdf -jobname=thesis
chapters = $(wildcard chapters/*.tex)
configs = $(wildcard config/*.tex)

.PHONY: all clean clean-all

all: thesis.pdf

thesis.pdf: main.tex frontmatter.tex bibliography.bib $(chapters) $(configs)
	$(latexcmd) main.tex < /dev/null

clean:
	latexmk -c -jobname=thesis main.tex

clean-all:
	latexmk -C -jobname=thesis main.tex
