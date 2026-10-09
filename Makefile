# Export the examples with Native Image's points-to analysis, refresh the test
# fixtures from them, and run the checks.
#
#   make              refresh test/data, then run the checks
#   make export       export every example to graal-export/out/<name>.json
#   make translate    translate every export to graal-export/out/<name>.ct
#   make compare      the stores and loads the rules leave next to what Graal leaves
#   make test-data    refresh test/data/examples.json and signatures.json
#   make check        run the checks (uv run pytest)
#
# An export is redone when its example or the exporter changes; after
# rebuilding the graal tree, force it with make -B. GRAAL_HOME is passed on to
# graal-export/env.sh. Each export's analysis report is saved next to it, in
# graal-export/out/<name>.txt.
#
# A translation has one heap token; make translate PARTITION=field writes
# <name>.field.ct, with a token per field and array kind.

EXPORT := graal-export
OUT := $(EXPORT)/out
EXPORTER := $(addprefix $(EXPORT)/,ReadWriteExport.java GraphExport.java build.sh run-dump.sh env.sh exports.args)
TRANSLATOR := $(wildcard src/*/*.py) src/cthu/graal.ct
EXAMPLES := $(basename $(notdir $(wildcard $(EXPORT)/examples/*.java)))
FIXTURES := examples signatures

lower = $(shell echo '$(1)' | tr '[:upper:]' '[:lower:]')
EXPORTS := $(foreach e,$(EXAMPLES),$(OUT)/$(call lower,$(e)).json)

PARTITION ?= none
CT := $(if $(filter none,$(PARTITION)),,.$(PARTITION)).ct

.PHONY: all export translate compare test-data check
# build.sh recompiles the one classes/ directory that every export analyses.
.NOTPARALLEL:
.DELETE_ON_ERROR:

all: test-data check

export: $(EXPORTS)

translate: $(EXPORTS:.json=$(CT))

compare: $(OUT)/probe.txt $(OUT)/examples.json $(OUT)/signatures.json
	uv run python -m rules.compare $(OUT)/examples.json $(OUT)/signatures.json --probe $<

# What Graal leaves of each method's field accesses, from its own test harness.
$(OUT)/probe.txt: graal-probe/MemoryProbe.java graal-probe/run.sh $(EXPORT)/examples/Examples.java $(EXPORT)/examples/Signatures.java
	./graal-probe/run.sh Examples Signatures > $@

test-data: $(FIXTURES:%=test/data/%.json)

check:
	uv run pytest

test/data/%.json: $(OUT)/%.json
	cp $< $@

$(OUT)/%$(CT): $(OUT)/%.json $(TRANSLATOR)
	uv run graal2ct $< --partition $(PARTITION) -o $@

# out/examples.json from examples/Examples.java, analysed from its main.
define export_rule
$(OUT)/$(call lower,$(1)).json: $(EXPORT)/examples/$(1).java $(EXPORTER)
	cd $(EXPORT) && ./build.sh examples/$(1).java > /dev/null
	cd $(EXPORT) && mkdir -p out && DUMP_IR=out/$(call lower,$(1)).json ./run-dump.sh $(1) > out/$(call lower,$(1)).txt
	@tail -n 1 $(OUT)/$(call lower,$(1)).txt
endef
$(foreach e,$(EXAMPLES),$(eval $(call export_rule,$(e))))
