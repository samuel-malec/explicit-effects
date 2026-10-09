# explicit-effects

## Overview 
This repository presents a prototype implementation of a side-effect analysis using explicit values in a Static Single Use IR.
To get a brief introduction to the problem, check out Graal Memory Model: https://samuel-malec.github.io/blog/2026/09/27/graal-memory/intro, and https://samuel-malec.github.io/blog/2026/08/17/side-effect-analysis/intro.

## Repository Structure
```
src/
├── graal-export/    # Exports Graal IR and points-to facts from Native Image's standalone analysis
├── graal-probe/     # Measures what Graal does to the examples' memory operations
├── src/graal/       # Load the Graal export
├── src/cthu/        # Implementation of Graal dialect in Cthulhu
├── src/effects/     # Heap partitions and method signatures: which partitions each method may touch
├── src/graal2ct/    # Graal IR -> Cthulhu compilation pipeline
├── src/rules/       # Rules on the token form: load forwarding, dead stores, and the comparison with Graal (see its README)
├── test/            # Examples and test suite
```

## Setup

The Python side is a [uv](https://docs.astral.sh/uv/) project with no runtime dependencies:
`uv sync` creates `.venv/` with the packages under `src/` and pytest, and `uv run` works from anywhere in the repository.

## Running Examples

```bash
cd graal-export && ./build.sh examples/Examples.java && \
    DUMP_IR=out/examples.json ./run-dump.sh Examples && cd ..
uv run graal2ct graal-export/out/examples.json --method forwardAcrossWritingCall
uv run graal2ct graal-export/out/examples.json --partition field
uv run graal2ct graal-export/out/examples.json --partition field --rules
uv run pytest
./graal-probe/run.sh
```

The Makefile chains these: `make` re-exports `Examples` and `Signatures` when their source or the exporter changed, copies them to `test/data/` and runs the checks.
`make export` exports every example to `graal-export/out/<name>.json`, with the analysis report in `<name>.txt`.
`make translate` translates every export to `<name>.ct` with one heap token, and `make translate PARTITION=field` to `<name>.field.ct` with a token per field.
`make compare` prints, per method of `Examples` and `Signatures`, the field stores and loads Graal leaves (from `graal-probe`) next to those the rules leave.
After rebuilding the graal tree, force the exports with `make -B`.
