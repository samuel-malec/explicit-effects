#!/usr/bin/env bash
# What the side-effect analysis costs on a large program: javac, the JDK's com.sun.tools.javac.Main,
# as `mx javac-image` builds it (37,854 reachable methods). Each configuration is built REPEATS
# times, one build at a time, the configurations taking turns. Each image compiles the corpus's
# Examples.java, whose classes must print what the JDK's own javac's classes print. Builds go to
# out/javac[-allocsens]-cost-<config>-r<k>/, as cost.sh's do, so that cost.py reads them.
#
#   ./cost-javac.sh                                   # 3 rounds of graal and kills
#   REPEATS=1 CONFIGS="graal kills objects" ./cost-javac.sh
#   CONFIGS="graal graalinputs kills killsescape graal-allocsens graalflags-allocsens objects locks" ./cost-javac.sh   # the full table
#
# graalinputs and graalflags-allocsens are graal with the flags thread escape needs (inputs of flows kept, source
# positions kept): the baselines of killsescape and locks, so that what the flags cost Native Image itself is not
# counted as ours.
#
# javac's classes are under com.sun., which isn't the program by default: the builds name them.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

REPEATS=${REPEATS:-3}
read -r -a CONFIGS <<< "${CONFIGS:-graal kills}"
JDK=${JAVA_HOME:-$HOME/.mx/jdks/labsjdk-ce-latest-jvmci-25.4-b23_amd64}
if [[ -d "$JDK/jmods" ]]; then
    SYSTEM=(-Djava.home= --system none -p "$JDK/jmods")  # as Graal's gate runs the image
else
    SYSTEM=(--system "$JDK")
fi
EXAMPLES="$EXPORT_DIR/corpus/Examples.java"
REFERENCE="$HERE/out/javac-reference"
rm -rf "$REFERENCE" && mkdir -p "$REFERENCE/classes"
"$JDK/bin/javac" -d "$REFERENCE/classes" "$EXAMPLES"
"$JDK/bin/java" -cp "$REFERENCE/classes" Examples > "$REFERENCE/output.txt" 2>&1

build() {  # configuration, round
    local config=$1 round=$2 analysis="" tag mode flags=()
    tag=$config; mode=$config
    local inputs=(-H:+TrackInputFlows) positions=(-H:+TrackNodeSourcePosition) escape=(-H:SideEffectAnalysisAssumptions=vm-code,entry-points)
    local allocsens=(-H:AnalysisContextSensitivity=allocsens)
    case $config in
        graal)          flags=(-H:-SideEffectAnalysisNarrowCalls) ;;
        graalinputs)    mode=graal; flags=(-H:-SideEffectAnalysisNarrowCalls "${inputs[@]}") ;;
        kills)          flags=() ;;
        killsescape)    mode=kills; flags=("${inputs[@]}" "${escape[@]}") ;;
        graal-allocsens) tag=graal; mode=graal; analysis=-allocsens; flags=(-H:-SideEffectAnalysisNarrowCalls "${allocsens[@]}") ;;
        graalflags-allocsens) tag=graalflags; mode=graal; analysis=-allocsens; flags=(-H:-SideEffectAnalysisNarrowCalls "${allocsens[@]}" "${inputs[@]}" "${positions[@]}") ;;
        objects)        analysis=-allocsens; flags=("${allocsens[@]}" "${positions[@]}" -H:SideEffectAnalysisPartition=object-field) ;;
        locks)          analysis=-allocsens; flags=(-H:-SideEffectAnalysisNarrowCalls "${allocsens[@]}" "${positions[@]}" "${inputs[@]}" -H:SideEffectAnalysisLabel=locks
                                                   -H:+SideEffectAnalysisElideLocks "${escape[@]}") ;;
        *) echo "unknown configuration $config" >&2; exit 1 ;;
    esac
    local dir="$HERE/out/javac$analysis-cost-$tag-r$round"
    rm -rf "$dir" && mkdir -p "$dir/$mode"
    local start=$SECONDS
    if ! mx -p "$G/substratevm" javac-image -H:+UnlockExperimentalVMOptions -H:+SideEffectAnalysis \
            -H:SideEffectAnalysisTool="$REPO" -H:SideEffectAnalysisUv="$(command -v uv)" \
            -H:SideEffectAnalysisProgram=com.sun.tools.javac -H:SideEffectAnalysisOutput="$dir/$mode" \
            "${flags[@]}" > "$dir/$mode.log" 2>&1; then
        tail -30 "$dir/$mode.log"
        exit 1
    fi
    # mx puts the image in its own build directory, whatever the output path: keep a copy.
    local image
    image=$(grep -oE '/[^ ]*/javac \(executable' "$dir/$mode.log" | cut -d' ' -f1)
    cp "$image" "$dir/$mode/javac"
    local same="compiles Examples as the JDK's javac does"
    mkdir -p "$dir/$mode/classes"
    if ! "$dir/$mode/javac" -proc:none "${SYSTEM[@]}" -d "$dir/$mode/classes" "$EXAMPLES" > "$dir/$mode/javac.txt" 2>&1; then
        same="FAILED to compile Examples: $(head -c 300 "$dir/$mode/javac.txt")"
    elif ! "$JDK/bin/java" -cp "$dir/$mode/classes" Examples 2>&1 | cmp -s - "$REFERENCE/output.txt"; then
        same="compiled Examples DIFFERENTLY: its classes print something else"
    fi
    echo "javac$analysis-cost-$tag-r$round: built in $((SECONDS - start)) s, $same"
}

for round in $(seq 1 "$REPEATS"); do
    for config in "${CONFIGS[@]}"; do
        build "$config" "$round"
    done
done
uv run --project "$REPO" python "$HERE/cost.py" "$HERE/out" javac
