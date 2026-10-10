# Graal Export

## Overview

Runs Native Image's points-to analysis and dumps Graal IR and points-to analysis information for furhter analysis. 
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

Each field and array access, on its node in the graph and in the `accesses` of
the program's methods' facts, lists the objects its receiver may point to
(`receivers`), or null when the analysis can't say. By default the analysis
names objects by type, `Examples$Counter`. With allocation sites it names them
by where they were allocated, `Examples$Counter@Examples.main([Ljava/lang/String;)V:0`:

```bash
DUMP_IR=out/examples.allocsens.json ./run-dump.sh Examples -H:AnalysisContextSensitivity=allocsens
```

That also switches off the analysis's primitive tracking and predicates, which
makes far more of the JDK reachable from a program that prints; see
[`src/effects/README.md`](../src/effects/README.md).
