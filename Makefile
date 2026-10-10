# Export the examples with Native Image's points-to analysis, refresh the test
# fixtures from them, and run the checks.
#
#   make              refresh test/data, then run the checks
#   make export       export every example to graal-export/out/<name>.json
#   make translate    translate every export to graal-export/out/<name>.ct
#   make compare      the stores and loads the rules leave next to what Graal leaves
#   make native       the round trip: Native Image with the kills our tool computes
#   make awfy         Are We Fast Yet as a whole program: coverage, opacity, the rules
#   make driver       the same for the native-image driver, from the graal tree
#   make native-awfy  its round trip, every image timed
#   make test-data    refresh test/data/examples.json, signatures.json and aliasing.json
#   make check        run the checks (uv run pytest)
#
# An export is redone when its example or the exporter changes; after
# rebuilding the graal tree, force it with make -B. GRAAL_HOME is passed on to
# graal-export/env.sh. Each export's analysis report is saved next to it, in
# graal-export/out/<name>.txt.
#
# The analysis names objects by type. graal-export/out/<name>.allocsens.json
# is the same export with an allocation-site-sensitive heap
# (-H:AnalysisContextSensitivity=allocsens), which tells apart objects of one
# class allocated in different places: what the object partitions use.
#
# make native builds each compared program's native image four times: as
# Graal compiles it, with the kills effects.kills computes from the image's
# own analysis, with each field access in its partition of the objects too,
# and with the stores our rules find dead in Java removed as well. It runs
# them against the JVM, and checks that a wrong kill, a wrong partition and a
# wrong dead store show: see graal-native/README.md. It needs graal.jar rebuilt in
# the graal tree with kill sets on invokes and partitions on field locations.
# make compare then sets the images next to the rest.
#
# A translation has one heap token; make translate PARTITION=field writes
# <name>.field.ct, with a token per field and array kind. PARTITION=object
# and PARTITION=object-field write a token per set of objects, and per field
# of one, from the allocation-site export.

EXPORT := graal-export
OUT := $(EXPORT)/out
NATIVE_DIR := graal-native
NATIVE := $(NATIVE_DIR)/out
EXPORTER := $(addprefix $(EXPORT)/,ReadWriteExport.java GraphExport.java build.sh run-dump.sh env.sh exports.args)
TRANSLATOR := $(wildcard src/*/*.py) src/cthu/graal.ct
EXAMPLES := $(basename $(notdir $(wildcard $(EXPORT)/examples/*.java)))
FIXTURES := examples signatures aliasing
COMPARED := Examples Signatures Aliasing

lower = $(shell echo '$(1)' | tr '[:upper:]' '[:lower:]')
EXPORTS := $(foreach e,$(EXAMPLES),$(OUT)/$(call lower,$(e)).json)

PARTITION ?= none
CT := $(if $(filter none,$(PARTITION)),,.$(PARTITION)).ct
SOURCE := $(if $(filter object%,$(PARTITION)),.allocsens)

.PHONY: all export translate compare native awfy native-awfy driver test-data check
# build.sh recompiles the one classes/ directory that every export analyses.
.NOTPARALLEL:
.DELETE_ON_ERROR:

all: test-data check

export: $(EXPORTS)

translate: $(EXPORTS:.json=$(CT))

compare: $(OUT)/probe.txt $(foreach e,$(COMPARED),$(OUT)/$(call lower,$(e)).allocsens.json)
	uv run python -m rules.compare $(filter %.json,$^) --probe $< $(if $(wildcard $(NATIVE)/*/kills/counts.txt),--native $(NATIVE))

# Each run checks the image's output against the JVM's. The controls must
# print something else: one claims that countInto writes nothing, one that two
# references in forwardPastAliasControl never meet, and one that a store in
# forwardAcrossMerge, which is read, is dead.
native:
	$(NATIVE_DIR)/build.sh
	$(foreach e,$(COMPARED),$(NATIVE_DIR)/run.sh $(e) &&) true
	@out=$$(LIE='Examples.countInto(LExamples$$Counter;LExamples$$Link;)V' $(NATIVE_DIR)/run.sh Examples) && echo "$$out" && echo "$$out" | grep -q 'instead of'
	@out=$$(SPLIT='Aliasing.forwardPastAliasControl(LAliasing$$Counter;LAliasing$$Counter;)I' $(NATIVE_DIR)/run.sh Aliasing) && echo "$$out" && echo "$$out" | grep -q 'instead of'
	@out=$$(DEAD='Examples.forwardAcrossMerge(LExamples$$Counter;LExamples$$Link;Z)I:21' $(NATIVE_DIR)/run.sh Examples) && echo "$$out" && echo "$$out" | grep -q 'instead of'

# Are We Fast Yet, from the are-we-fast-yet submodule, run by programs/awfy's
# driver. The analysis runs without its predicates: they take a native without
# an implementation, such as System.nanoTime, for a call that never returns,
# and the standalone analyzer has no implementation of any.
AWFY := programs/awfy
AWFY_SOURCES := $(AWFY)/Awfy.java $(AWFY)/build.sh $(wildcard are-we-fast-yet/benchmarks/Java/src/*.java are-we-fast-yet/benchmarks/Java/src/*/*.java)

awfy: $(OUT)/awfy.json $(OUT)/awfy.allocsens.json
	uv run python -m rules.report $^ --native $(wildcard $(NATIVE)/awfy $(NATIVE)/awfy-allocsens)

native-awfy:
	$(NATIVE_DIR)/build.sh
	$(NATIVE_DIR)/run.sh Awfy
	ALLOCSENS=1 $(NATIVE_DIR)/run.sh Awfy
	uv run python $(AWFY)/time.py $(NATIVE)/awfy
	uv run python $(AWFY)/time.py $(NATIVE)/awfy-allocsens

$(OUT)/awfy.json: $(AWFY_SOURCES) $(EXPORTER)
	$(AWFY)/build.sh
	cd $(EXPORT) && ./build.sh examples/Examples.java > /dev/null
	cd $(EXPORT) && TARGET_CP=$(CURDIR)/$(AWFY)/classes DUMP_IR=out/awfy.json ./run-dump.sh Awfy -H:-UsePredicates > out/awfy.txt

$(OUT)/awfy.allocsens.json: $(AWFY_SOURCES) $(EXPORTER)
	$(AWFY)/build.sh
	cd $(EXPORT) && ./build.sh examples/Examples.java > /dev/null
	cd $(EXPORT) && TARGET_CP=$(CURDIR)/$(AWFY)/classes DUMP_IR=out/awfy.allocsens.json \
		./run-dump.sh Awfy -H:AnalysisContextSensitivity=allocsens > out/awfy.allocsens.txt

# The native-image driver, from the graal tree the scripts use: its own package
# is the program. It needs the builder's jar too, for ExitStatus and
# NativeImageGeneratorRunner, or the analysis reaches 17 of its methods.
GRAAL := $(or $(GRAAL_HOME),$(if $(wildcard graal/substratevm/mxbuild/dists/standalone-pointsto.jar),$(CURDIR)/graal,/home/xmalec/graal))
DRIVER_CP := $(subst $(eval) ,:,$(addprefix $(GRAAL)/substratevm/mxbuild/dists/,svm-driver.jar svm.jar native-image-base.jar svm-shared.jar) \
	$(addprefix $(GRAAL)/sdk/mxbuild/dists/,nativeimage.jar collections.jar graal-sdk.jar word.jar))
DRIVER := TARGET_CP=$(DRIVER_CP) DUMP_FILTER=com.oracle.svm.driver

driver: $(OUT)/driver.json $(OUT)/driver.allocsens.json
	uv run python -m rules.report $^

$(OUT)/driver.json: $(EXPORTER)
	cd $(EXPORT) && ./build.sh examples/Examples.java > /dev/null
	cd $(EXPORT) && $(DRIVER) DUMP_IR=out/driver.json ./run-dump.sh com.oracle.svm.driver.NativeImage -H:-UsePredicates > out/driver.txt

$(OUT)/driver.allocsens.json: $(EXPORTER)
	cd $(EXPORT) && ./build.sh examples/Examples.java > /dev/null
	cd $(EXPORT) && $(DRIVER) DUMP_IR=out/driver.allocsens.json \
		./run-dump.sh com.oracle.svm.driver.NativeImage -H:AnalysisContextSensitivity=allocsens > out/driver.allocsens.txt

# What Graal leaves of each method's field accesses, from its own test harness.
$(OUT)/probe.txt: graal-probe/MemoryProbe.java graal-probe/run.sh $(COMPARED:%=$(EXPORT)/examples/%.java)
	./graal-probe/run.sh $(COMPARED) > $@

test-data: $(FIXTURES:%=test/data/%.json)

check:
	uv run pytest

# The object partitions' fixture needs allocation sites. Its main prints
# nothing, which keeps the export small.
test/data/aliasing.json: $(OUT)/aliasing.allocsens.json
	cp $< $@

test/data/%.json: $(OUT)/%.json
	cp $< $@

$(OUT)/%$(CT): $(OUT)/%$(SOURCE).json $(TRANSLATOR)
	uv run graal2ct $< --partition $(PARTITION) -o $@

# out/examples.json from examples/Examples.java, analysed from its main, and
# out/examples.allocsens.json with allocation sites.
define export_rule
$(OUT)/$(call lower,$(1)).json: $(EXPORT)/examples/$(1).java $(EXPORTER)
	cd $(EXPORT) && ./build.sh examples/$(1).java > /dev/null
	cd $(EXPORT) && mkdir -p out && DUMP_IR=out/$(call lower,$(1)).json ./run-dump.sh $(1) > out/$(call lower,$(1)).txt
	@tail -n 1 $(OUT)/$(call lower,$(1)).txt

$(OUT)/$(call lower,$(1)).allocsens.json: $(EXPORT)/examples/$(1).java $(EXPORTER)
	cd $(EXPORT) && ./build.sh examples/$(1).java > /dev/null
	cd $(EXPORT) && mkdir -p out && DUMP_IR=out/$(call lower,$(1)).allocsens.json \
		./run-dump.sh $(1) -H:AnalysisContextSensitivity=allocsens > out/$(call lower,$(1)).allocsens.txt
	@tail -n 1 $(OUT)/$(call lower,$(1)).allocsens.txt
endef
$(foreach e,$(EXAMPLES),$(eval $(call export_rule,$(e))))
