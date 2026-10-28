# Export the corpus programs (graal-export/corpus/) with Native Image's points-to
# analysis, refresh the test fixtures from them, and run the checks.
#
#   make              refresh test/data, then run the checks
#   make export       export every corpus program to graal-export/out/<name>.json
#   make translate    translate every export to graal-export/out/<name>.ct
#   make native       the round trip: Native Image with the kills our tool computes
#   make awfy         Are We Fast Yet as a whole program: its two exports
#   make driver       the same for the native-image driver, from the graal tree
#   make native-awfy  its round trip, every image timed
#   make awfy-layouts why the narrowed images ran slower: counters across method alignments
#   make test-data    refresh test/data/examples.json, signatures.json and aliasing.json
#   make check        run the checks (uv run pytest)
#   make suite        export the examples (graal-export/examples/), one program per example,
#                     and check each still shows what its comment says
#
# An export is redone when its program, the launcher or the exporter changes:
# the exporter, PointsToExport, is in the graal tree's pointsto.jar. After
# rebuilding other parts of the graal tree, force it with make -B. GRAAL_HOME is
# passed on to graal-export/env.sh. Each export's analysis report is saved next to it, in
# graal-export/out/<name>.txt.
#
# The analysis names objects by type. graal-export/out/<name>.allocsens.json
# is the same export with an allocation-site-sensitive heap
# (-H:AnalysisContextSensitivity=allocsens), which tells apart objects of one
# class allocated in different places: what the object partitions use.
#
# make native builds each compared program's native image three times: as
# Graal compiles it, with the kills effects.kills computes from the image's
# own analysis, and with each field access in its partition of the objects too.
# It runs them against the JVM, and checks that a wrong kill and a wrong
# partition show. It needs the graal tree built with mx: its builder has
# SideEffectAnalysisFeature (-H:+SideEffectAnalysis), its compiler kill sets on
# invokes and partitions on field locations.
#
# A translation has one heap token; make translate PARTITION=field writes
# <name>.field.ct, with a token per field and array kind. PARTITION=object
# and PARTITION=object-field write a token per set of objects, and per field
# of one, from the allocation-site export.

EXPORT := graal-export
OUT := $(EXPORT)/out
NATIVE_DIR := graal-native
NATIVE := $(NATIVE_DIR)/out
# The graal tree the scripts use, as graal-export/env.sh picks it.
GRAAL := $(or $(GRAAL_HOME),$(if $(wildcard graal/substratevm/mxbuild/dists/standalone-pointsto.jar),$(CURDIR)/graal,/home/xmalec/graal))
EXPORTER := $(addprefix $(EXPORT)/,StandalonePointsToExport.java build.sh run-dump.sh env.sh exports.args) $(GRAAL)/substratevm/mxbuild/dists/pointsto.jar
TRANSLATOR := $(wildcard src/*/*.py) src/cthu/graal.ct
CORPUS := $(basename $(notdir $(wildcard $(EXPORT)/corpus/*.java)))
FIXTURES := examples signatures aliasing
COMPARED := Examples Signatures Aliasing

lower = $(shell echo '$(1)' | tr '[:upper:]' '[:lower:]')
EXPORTS := $(foreach e,$(CORPUS),$(OUT)/$(call lower,$(e)).json)

PARTITION ?= none
CT := $(if $(filter none,$(PARTITION)),,.$(PARTITION)).ct
SOURCE := $(if $(filter object%,$(PARTITION)),.allocsens)

.PHONY: all export translate native awfy native-awfy awfy-layouts driver test-data check suite
# build.sh recompiles the one classes/ directory that every export analyses.
.NOTPARALLEL:
.DELETE_ON_ERROR:

all: test-data check

export: $(EXPORTS)

translate: $(EXPORTS:.json=$(CT))

# Each run checks the image's output against the JVM's. The controls must
# print something else: one claims that countInto writes nothing, and one that two
# references in forwardPastAliasControl never meet.
native:
	$(foreach e,$(COMPARED),$(NATIVE_DIR)/run.sh $(e) &&) true
	@out=$$(LIE='Examples.countInto(LExamples$$Counter;LExamples$$Link;)V' $(NATIVE_DIR)/run.sh Examples) && echo "$$out" && echo "$$out" | grep -q 'instead of'
	@out=$$(SPLIT='Aliasing.forwardPastAliasControl(LAliasing$$Counter;LAliasing$$Counter;)I' $(NATIVE_DIR)/run.sh Aliasing) && echo "$$out" && echo "$$out" | grep -q 'instead of'

# Are We Fast Yet, from the are-we-fast-yet submodule, run by programs/awfy's
# driver. The analysis runs without its predicates: they take a native without
# an implementation, such as System.nanoTime, for a call that never returns,
# and the standalone analyzer has no implementation of any.
AWFY := programs/awfy
AWFY_SOURCES := $(AWFY)/Awfy.java $(AWFY)/build.sh $(wildcard are-we-fast-yet/benchmarks/Java/src/*.java are-we-fast-yet/benchmarks/Java/src/*/*.java)

awfy: $(OUT)/awfy.json $(OUT)/awfy.allocsens.json

native-awfy:
	$(NATIVE_DIR)/run.sh Awfy
	ALLOCSENS=1 $(NATIVE_DIR)/run.sh Awfy
	uv run python $(AWFY)/time.py $(NATIVE)/awfy
	uv run python $(AWFY)/time.py $(NATIVE)/awfy-allocsens

# Step 6: graal and kills with the symbols perf needs, as built by default (awfy-sym,
# methods at multiples of 32 bytes) and with methods at multiples of 16, 64 and 128 bytes,
# and two kills images that narrow CD's methods not at all, or only RedBlackTree.remove.
# Then CD's counters in each, and graal against kills for every benchmark across the
# alignments. See programs/awfy/layouts.py.
awfy-layouts:
	ONLY="graal kills" TAG=sym EXTRA=-H:-DeleteLocalSymbols $(NATIVE_DIR)/run.sh Awfy
	for a in 16 64 128; do \
		ONLY="graal kills" TAG=a$$a EXTRA="-H:-DeleteLocalSymbols -H:CodeAlignment=$$a" $(NATIVE_DIR)/run.sh Awfy; done
	ONLY=kills TAG=skipcd EXTRA="-H:-DeleteLocalSymbols -H:SideEffectAnalysisSkipMethods=cd." $(NATIVE_DIR)/run.sh Awfy
	ONLY=kills TAG=onlyremove EXTRA="-H:-DeleteLocalSymbols -H:SideEffectAnalysisOnlyMethods=cd.RedBlackTree.remove" $(NATIVE_DIR)/run.sh Awfy
	uv run python $(AWFY)/counters.py CD $(NATIVE)/awfy-sym $(NATIVE)/awfy-skipcd $(NATIVE)/awfy-onlyremove $(NATIVE)/awfy-a64 --runs 5
	uv run python $(AWFY)/layouts.py $(NATIVE)/awfy-a16 $(NATIVE)/awfy-sym $(NATIVE)/awfy-a64 $(NATIVE)/awfy-a128 --runs 3

$(OUT)/awfy.json: $(AWFY_SOURCES) $(EXPORTER)
	$(AWFY)/build.sh
	cd $(EXPORT) && ./build.sh corpus/Examples.java > /dev/null
	cd $(EXPORT) && TARGET_CP=$(CURDIR)/$(AWFY)/classes DUMP_IR=out/awfy.json ./run-dump.sh Awfy -H:-UsePredicates > out/awfy.txt

$(OUT)/awfy.allocsens.json: $(AWFY_SOURCES) $(EXPORTER)
	$(AWFY)/build.sh
	cd $(EXPORT) && ./build.sh corpus/Examples.java > /dev/null
	cd $(EXPORT) && TARGET_CP=$(CURDIR)/$(AWFY)/classes DUMP_IR=out/awfy.allocsens.json \
		./run-dump.sh Awfy -H:AnalysisContextSensitivity=allocsens > out/awfy.allocsens.txt

# The native-image driver, from the graal tree the scripts use: its own package
# is the program. It needs the builder's jar too, for ExitStatus and
# NativeImageGeneratorRunner, or the analysis reaches 17 of its methods.
DRIVER_CP := $(subst $(eval) ,:,$(addprefix $(GRAAL)/substratevm/mxbuild/dists/,svm-driver.jar svm.jar native-image-base.jar svm-shared.jar) \
	$(addprefix $(GRAAL)/sdk/mxbuild/dists/,nativeimage.jar collections.jar graal-sdk.jar word.jar))
DRIVER := TARGET_CP=$(DRIVER_CP) DUMP_FILTER=com.oracle.svm.driver

driver: $(OUT)/driver.json $(OUT)/driver.allocsens.json

$(OUT)/driver.json: $(EXPORTER)
	cd $(EXPORT) && ./build.sh corpus/Examples.java > /dev/null
	cd $(EXPORT) && $(DRIVER) DUMP_IR=out/driver.json ./run-dump.sh com.oracle.svm.driver.NativeImage -H:-UsePredicates > out/driver.txt

$(OUT)/driver.allocsens.json: $(EXPORTER)
	cd $(EXPORT) && ./build.sh corpus/Examples.java > /dev/null
	cd $(EXPORT) && $(DRIVER) DUMP_IR=out/driver.allocsens.json \
		./run-dump.sh com.oracle.svm.driver.NativeImage -H:AnalysisContextSensitivity=allocsens > out/driver.allocsens.txt

test-data: $(FIXTURES:%=test/data/%.json)

check:
	uv run pytest

# graal-export/suite re-exports only the examples whose source changed.
suite:
	$(EXPORT)/suite
	uv run pytest test/export_check/check_suite.py

# The object partitions' fixture needs allocation sites. Its main prints
# nothing, which keeps the export small.
test/data/aliasing.json: $(OUT)/aliasing.allocsens.json
	cp $< $@

test/data/%.json: $(OUT)/%.json
	cp $< $@

$(OUT)/%$(CT): $(OUT)/%$(SOURCE).json $(TRANSLATOR)
	uv run graal2ct $< --partition $(PARTITION) -o $@

# out/examples.json from corpus/Examples.java, analysed from its main, and
# out/examples.allocsens.json with allocation sites.
define export_rule
$(OUT)/$(call lower,$(1)).json: $(EXPORT)/corpus/$(1).java $(EXPORTER)
	cd $(EXPORT) && ./build.sh corpus/$(1).java > /dev/null
	cd $(EXPORT) && mkdir -p out && DUMP_IR=out/$(call lower,$(1)).json ./run-dump.sh $(1) > out/$(call lower,$(1)).txt
	@tail -n 1 $(OUT)/$(call lower,$(1)).txt

$(OUT)/$(call lower,$(1)).allocsens.json: $(EXPORT)/corpus/$(1).java $(EXPORTER)
	cd $(EXPORT) && ./build.sh corpus/$(1).java > /dev/null
	cd $(EXPORT) && mkdir -p out && DUMP_IR=out/$(call lower,$(1)).allocsens.json \
		./run-dump.sh $(1) -H:AnalysisContextSensitivity=allocsens > out/$(call lower,$(1)).allocsens.txt
	@tail -n 1 $(OUT)/$(call lower,$(1)).allocsens.txt
endef
$(foreach e,$(CORPUS),$(eval $(call export_rule,$(e))))
