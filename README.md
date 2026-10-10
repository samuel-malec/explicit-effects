# explicit-effects

## Overview 
This repository presents a prototype implementation of a side-effect analysis using explicit values in a Static Single Use IR.
To get a brief introduction to the problem, check out Graal Memory Model: https://samuel-malec.github.io/blog/2026/09/27/graal-memory/intro, and https://samuel-malec.github.io/blog/2026/08/17/side-effect-analysis/intro.

## Repository Structure
```
src/
├── graal-export/    # Exports Graal IR and points-to facts from Native Image's standalone analysis
├── graal-probe/     # Measures what Graal does to the examples' memory operations
├── graal-native/    # The round trip: Native Image compiles with the kills our tool computes (see its README)
├── programs/        # Whole programs: Are We Fast Yet and the native-image driver (see its README)
├── graal/           # Submodule: the Graal tree, with kill sets on invokes and partitions on field locations
├── are-we-fast-yet/ # Submodule: the Are We Fast Yet benchmarks
├── src/graal/       # Load the Graal export
├── src/cthu/        # Implementation of Graal dialect in Cthulhu
├── src/effects/     # Heap partitions and method signatures: which partitions each method may touch (see its README)
├── src/graal2ct/    # Graal IR -> Cthulhu compilation pipeline
├── src/rules/       # Rules on the token form: load forwarding, dead stores, and the comparison with Graal (see its README)
├── test/            # Examples and test suite
```

## Setup

The Python side is a [uv](https://docs.astral.sh/uv/) project with no runtime dependencies:
`uv sync` creates `.venv/` with the packages under `src/` and pytest, and `uv run` works from anywhere in the repository.

The Graal tree is a submodule, `graal/`: the `side-effect-analysis` branch of [samuel-malec/graal](https://github.com/samuel-malec/graal), which adds kill sets to invokes and partitions to field locations (`graal-native/README.md`).
Clone with `git clone --recurse-submodules`, or run `git submodule update --init` after cloning, and build it as any Graal tree:

```bash
cd graal/substratevm && JAVA_HOME=~/.mx/jdks/labsjdk-ce-latest-jvmci-25.4-b23_amd64 mx build
```

The scripts use the submodule once it is built; until then, and whenever `GRAAL_HOME` is set, they use that tree instead.

## Running Examples

```bash
cd graal-export && ./build.sh examples/Examples.java && \
    DUMP_IR=out/examples.json ./run-dump.sh Examples && cd ..
uv run graal2ct graal-export/out/examples.json --method forwardAcrossWritingCall
uv run graal2ct graal-export/out/examples.json --partition field
uv run graal2ct graal-export/out/examples.json --partition field --rules
uv run graal2ct graal-export/out/aliasing.allocsens.json --partition object-field --rules
uv run pytest
./graal-probe/run.sh
```

The Makefile chains these: `make` re-exports `Examples` and `Signatures` when their source or the exporter changed, copies them to `test/data/` and runs the checks.
`make export` exports every example to `graal-export/out/<name>.json`, with the analysis report in `<name>.txt`.
`make translate` translates every export to `<name>.ct` with one heap token, and `make translate PARTITION=field` to `<name>.field.ct` with a token per field.
`PARTITION=object` and `PARTITION=object-field` give a token per set of objects the points-to analysis tells apart, and per field of one; they read `<name>.allocsens.json`, exported with allocation sites.
`make compare` prints, per method of `Examples`, `Signatures` and `Aliasing`, the field stores and loads Graal leaves (from `graal-probe`) next to those the rules leave under each partitioning.
`make native` builds each of them as a native image four times: as Graal compiles it, with the calls narrowed to what our tool says their callees may write, with each field access in its partition of the objects too, and with the stores our rules find dead in Java removed as well. It checks each against the JVM; `make compare` then shows the images too.
It needs the graal tree's `graal.jar` rebuilt with kill sets on invokes and partitions on field locations (`graal-native/README.md`).
`make awfy` and `make driver` run the export and the rules on whole programs, and `make native-awfy` the round trip on Are We Fast Yet, timed (`programs/README.md`).
After rebuilding the graal tree, force the exports with `make -B`.
