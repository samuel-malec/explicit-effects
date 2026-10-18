# Graal Export

## Overview

Runs Native Image's points-to analysis and dumps Graal IR and points-to analysis information for furhter analysis. 
It runs on the standalone points-to analyzer `com.oracle.graal.pointsto.standalone`.
The exporter itself, `PointsToExport`, is part of the graal tree's points-to analysis
(`substratevm/src/com.oracle.graal.pointsto/src/com/oracle/graal/pointsto/export/`), so that
native-image builds can use it too; this directory has its standalone launcher,
`StandalonePointsToExport`. After changing the exporter, rebuild the graal tree with `mx build`.

## Example Usage

```bash
./build.sh examples/conversion/Class.java && DUMP_IR=out/conversion.Class.json ./run-dump.sh conversion.Class
```

## Output
Each method is exported as a json dictionary, which consists of the necessary information
for further analysis, such as its name and descriptors and most importantly it's control flow graph
obtained by Graal's API that yields a valid schedule corresponding to the sea of nodes representation. 

## Seeing the exported graph in IGV

Add Graal's dump options, with a method filter of the form `Class.method`:

```bash
TARGET_CP=out/suite/classes DUMP_IR=out/nullcheck.json \
    ./run-dump.sh conversion.NullCheck -H:Dump=:1 -H:MethodFilter=NullCheck.demo -H:DumpPath=$PWD/out/igv
```

Each method gets three files in `out/igv/`: `PointsToAnalysisMethod:<id>[…].bgv`,
`…_1.bgv` and `…_2.bgv`. They are the analysis's decode, the exporter's decode for
the facts, and the exporter's decode for the graph. The last one ends with the graph
titled **Exported to JSON**: exactly what the JSON holds, with its schedule. Its node
ids are the JSON's ids, which `uv run python -m graal.show` prints. Open it in IGV
(`mx igv`, then File → Open). `-H:Dump=:2` adds a graph after each cleanup phase.


## Printing the allocation sites
By default the analysis names objects by type, `Examples$Counter`.
With allocation sites it names them by where they were allocated,
`Examples$Counter@Examples.main([Ljava/lang/String;)V:0`:

```bash
DUMP_IR=out/examples.allocsens.json ./run-dump.sh Examples -H:AnalysisContextSensitivity=allocsens
```

That also switches off the analysis's primitive tracking and predicates, which
makes far more of the JDK reachable from a program that prints; see
[`src/effects/README.md`](../src/effects/README.md).

Each method's facts also say what it does to memory beyond its field and array
accesses, by what Graal says each node does: `allocates`; `vmWrites`, the VM's
own locations it writes, such as `vm:identityHashCode`; `unknownReads`, nodes
that may read any location; `unknown`, nodes that may write anything (no
location, or synchronization); `unresolved`, calls without a target; and,
exported from a native-image build, `dead`, calls the image's own analysis
proves it never makes.
