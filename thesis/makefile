latexcmd = latexmk -shell-escape -pdf
chapters = $(wildcard chapters/*.tex)
deps = thesis.tex $(chapters)

.PHONY: all pvc clean clean-all

all: thesis.pdf

thesis.pdf: $(deps)
	$(latexcmd) $< < /dev/null

pvc: $(deps)
	-$(latexcmd) -pvc $< < /dev/null

clean:
	latexmk -c thesis.pdf

clean-all:
	latexmk -C thesis.pdf
