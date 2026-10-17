#!/bin/bash
# ./dump.sh forwarding.ForwardedByGraal [--allocsens]
# Builds the provided Java program and creates json export and igv dump for further analysis.

CLASS="$1"

if [[ -z "$CLASS" ]]; then
    echo "Usage: $0 <class> [--allocsens]"
    exit 1
fi

if [[ "$2" == "--allocsens" ]]; then
    DUMP_IR="out/${CLASS}.allocsens.json" \
    ./run-dump.sh "$CLASS" \
        -H:AnalysisContextSensitivity=allocsens \
        -H:Dump=:2 \
        -H:MethodFilter="${CLASS##*.}.demo" \
        -H:DumpPath="$PWD/out/igv"
else
    DUMP_IR="out/${CLASS}.json" \
    ./run-dump.sh "$CLASS" \
        -H:Dump=:2 \
        -H:MethodFilter="${CLASS##*.}.demo" \
        -H:DumpPath="$PWD/out/igv"
fi