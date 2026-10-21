#!/usr/bin/env bash
# Build one example as a native image with the side-effect analysis.
#   ./run.sh [--field | --object-field | --graal] [--dump] path/to/Example.java
# --field (default) narrows calls and removes dead stores; --object-field also splits fields by
# allocation site; --graal applies nothing. --dump sends the graphs to IGV (start `mx igv`).
# Results go to $OUT/<class>/<variant> (default /tmp/side-effects): image, counts.txt, kills.txt.
set -euo pipefail

GRAAL=${GRAAL:-$HOME/graal}
TOOL=${TOOL:-$HOME/explicit-effects}
OUT=${OUT:-/tmp/side-effects}
export JAVA_HOME=${JAVA_HOME:-$HOME/.mx/jdks/labsjdk-ce-latest-jvmci-25.4-b23_amd64}

variant=field
dump=()
while [[ $# -gt 1 ]]; do
    case $1 in
        --field | --object-field | --graal) variant=${1#--} ;;
        --dump) dump=(-H:Dump=:2 -H:PrintGraph=Network) ;;
        *) echo "unknown flag: $1" >&2; exit 1 ;;
    esac
    shift
done
[[ $# -eq 1 && -f $1 ]] || { sed -n '2,6p' "$0" >&2; exit 1; }

source=$(realpath "$1")
name=$(basename "$source" .java)
package=$(sed -n 's/^package \([A-Za-z0-9_.]*\);.*/\1/p' "$source" | head -1)
main=${package:+$package.}$name
dir=$OUT/$main/$variant

case $variant in
    field)        flags=(-H:+TrackNodeSourcePosition -H:+SideEffectAnalysisRemoveDeadStores) ;;
    object-field) flags=(-H:+TrackNodeSourcePosition -H:+SideEffectAnalysisRemoveDeadStores
                         -H:AnalysisContextSensitivity=allocsens -H:SideEffectAnalysisPartition=object-field) ;;
    graal)        flags=(-H:-SideEffectAnalysisNarrowCalls) ;;
esac

rm -rf "$dir"
mkdir -p "$dir/classes"
"$JAVA_HOME/bin/javac" -d "$dir/classes" "$source"
mx -p "$GRAAL/substratevm" native-image -H:+UnlockExperimentalVMOptions -H:+SideEffectAnalysis \
    -H:SideEffectAnalysisTool="$TOOL" -H:-AOTTrivialInline -H:SideEffectAnalysisLabel="$variant" \
    -H:SideEffectAnalysisOutput="$dir" "${flags[@]}" "${dump[@]}" -H:MethodFilter="$name.*" \
    -cp "$dir/classes" -o "$dir/image" "$main"
