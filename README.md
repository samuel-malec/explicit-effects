# explicit-effects

## Overview 
This repository presents a prototype implementation of a side-effect analysis using explicit values in a Static Single Use IR.
To get a brief introduction to the problem, check out Graal Memory Model: https://samuel-malec.github.io/blog/2026/09/27/graal-memory/intro,
and https://samuel-malec.github.io/blog/2026/08/17/side-effect-analysis/intro.

## Repository Structure
```
src/
├── graal-export/    # Exports Graal IR and points-to facts from Native Image's standalone analysis
├── src/graal/       # Load the Graal export
├── src/cthu/        # Implementation of Graal dialect in Cthulhu
├── src/graal2ct/    # Graal IR -> Cthulhu compilation pipeline
├── test/            # Examples and test suite

## Running Examples

```bash
cd graal-export && ./build.sh examples/TokenExamples.java && \
    DUMP_IR=out/token-examples.json ./run-dump.sh TokenExamples && cd ..
PYTHONPATH=src python3 -m graal2ct graal-export/out/token-examples.json --method resetCounter
PYTHONPATH=src python3 test/check_graal2ct.py
```

