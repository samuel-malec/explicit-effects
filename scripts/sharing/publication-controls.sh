#!/usr/bin/env bash
# Controls for the publication examples: thread escape with one kind of site left out, which must make
# the examples that kind publishes come out local. Prints which are, for each kind left out.
#
#   ./publication-controls.sh                      # needs graal-export/suite to have been run
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../graal-export/env.sh"
EXAMPLES=(PublishedByStatic PublishedByField PublishedByArray PublishedByArrayCopy PublishedByAtomic PublishedByQueue PublishedByMap)
OUT=${OUT:-$(mktemp -d)}
for leave in static field array copy; do
    mkdir -p "$OUT/$leave"
    for example in "${EXAMPLES[@]}"; do
        JAVA_TOOL_OPTIONS="-Dsideeffects.controlLeaveOut=$leave" TARGET_CP="$HERE/out/suite/classes" DUMP_IR="$OUT/$leave/$example.json" \
            "$HERE/run-dump.sh" "sharing.$example" -H:AnalysisContextSensitivity=allocsens > /dev/null 2>&1
    done
done
uv run --project "$(dirname "$HERE")" python - "$OUT" "${EXAMPLES[@]}" <<'PY'
import sys
from pathlib import Path
from graal.graal_import import load_facts
from diagnostics.publication import item_shared
out, examples = Path(sys.argv[1]), sys.argv[2:]
print(f"{'left out':10}" + "".join(f"{e.replace('PublishedBy', ''):>12}" for e in examples))
for leave in ("static", "field", "array", "copy"):
    print(f"{leave:10}" + "".join(f"{item_shared(load_facts(out / leave / (e + '.json')), e):>12}" for e in examples))
PY
