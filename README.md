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
├── src/graal2ct/    # Graal IR -> Cthulhu compilation pipeline
├── test/            # Examples and test suite
```

## Running Examples

```bash
cd graal-export && ./build.sh examples/Examples.java && \
    DUMP_IR=out/examples.json ./run-dump.sh Examples && cd ..
PYTHONPATH=src python3 -m graal2ct graal-export/out/examples.json --method forwardAcrossWritingCall
PYTHONPATH=src python3 test/export_check/check_graal2ct.py
./graal-probe/run.sh
```
