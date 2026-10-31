#!/usr/bin/env bash
# What thread escape says of the example programs of graal-export/examples/sharing, as
# Native Image's own analysis sees them: each example built as an image with the feature, once
# per analysis (insens, allocsens, _1obj, _2obj1h), all the sets of assumptions read from one
# analysis. Builds go side by side; the table is thread_escape.py's.
#
#   ./thread-escape.sh                                   # every example, three analyses
#   ANALYSES="insens _1obj" ./thread-escape.sh PublishedByStatic LocalInLocalObject
#   JOBS=16 OUT=/tmp/x ./thread-escape.sh
#   EXTRA="-J-Dsideeffects.explainSharing=Item" ./thread-escape.sh      # more native-image options
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

ANALYSES=${ANALYSES:-"insens allocsens _1obj"}
OUT=${OUT:-$HERE/out/thread-escape}
JOBS=${JOBS:-8}
mkdir -p "$OUT"
if [[ $# -gt 0 ]]; then
    NAMES=("$@")
else
    mapfile -t NAMES < <(cd "$EXPORT_DIR/examples/sharing" && ls Published*.java LocalIn*.java | sed 's/\.java$//')
fi

one() {  # example, analysis
    local name=$1 analysis=$2
    local dir="$OUT/$name.$analysis" flags=()
    [[ $analysis != insens ]] && flags=("-H:AnalysisContextSensitivity=$analysis")
    rm -rf "$dir" && mkdir -p "$dir/classes"
    "$GRAALVM/bin/javac" -d "$dir/classes" "$EXPORT_DIR/examples/sharing/$name.java" || return 1
    if ! "$GRAALVM/bin/native-image" -J-Dsideeffects.assumptionLayers=1 -H:+TrackInputFlows -J--upgrade-module-path="$COMPILER" -cp "$dir/classes" -EHOME -EPATH \
            -H:+UnlockExperimentalVMOptions -H:+SideEffectAnalysis -H:SideEffectAnalysisOutput="$dir/out" -H:SideEffectAnalysisProgram="sharing.$name" \
            -H:SideEffectAnalysisTool="$REPO" -H:SideEffectAnalysisUv="$(command -v uv)" -H:-AOTTrivialInline "${flags[@]}" ${EXTRA:-} \
            "sharing.$name" -o "$dir/image" > "$dir/build.log" 2>&1; then
        echo "$name, $analysis: build FAILED, see $dir/build.log" >&2
        return 1
    fi
    echo "$name, $analysis: built"
}
export -f one
export OUT GRAALVM COMPILER REPO EXPORT_DIR EXTRA
for name in "${NAMES[@]}"; do
    for analysis in $ANALYSES; do echo "$name $analysis"; done
done | xargs -P "$JOBS" -L 1 bash -c 'one "$@"' _ | sort
uv run --project "$REPO" python "$HERE/thread_escape.py" "$OUT" "${NAMES[@]}"
