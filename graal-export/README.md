# Graal Export

## Overview

Runs Native Image's points-to analysis and dumps, per method, which fields it reads and which it writes
It runs on the standalone points-to analyzer `com.oracle.graal.pointsto.standalone`.

## Example Usage

```bash
./build.sh examples/Examples.java [ more.java ... ]
DUMP_IR=out/examples.json ./run-dump.sh Examples
```

## Output
Each method is exported as a json dictionary, which consists of the necessary information
for further analysis, such as its name and descriptors and most importantly it's control flow graph
obtained by Graal's API that yields a valid schedule corresponding to the sea of nodes representation.
Each basic block has its predecessors, successors and individual Graal IR nodes that comprise it.
