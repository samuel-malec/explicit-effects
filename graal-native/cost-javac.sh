#!/usr/bin/env bash
# What the side-effect analysis costs on a large program: javac, the JDK's com.sun.tools.javac.Main,
# as `mx javac-image` builds it (37,854 reachable methods). Each configuration is built REPEATS
# times, one build at a time, the configurations taking turns. Each image compiles the corpus's
# Examples.java, whose classes must print what the JDK's own javac's classes print. Builds go to
# out/javac[-allocsens]-cost-<config>-r<k>/, as cost.sh's do, so that cost.py reads them.
#
#   ./cost-javac.sh                                   # 3 rounds of graal and kills
#   REPEATS=1 CONFIGS="graal kills objects" ./cost-javac.sh
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
    local config=$1 round=$2 analysis="" flags=()
    case $config in
        graal)          flags=(-H:-SideEffectAnalysisNarrowCalls) ;;
        kills)          flags=() ;;
        graal-allocsens) flags=(-H:-SideEffectAnalysisNarrowCalls -H:AnalysisContextSensitivity=allocsens); analysis=-allocsens; config=graal ;;
        objects)        flags=(-H:AnalysisContextSensitivity=allocsens -H:+TrackNodeSourcePosition -H:SideEffectAnalysisPartition=object-field); analysis=-allocsens ;;
        *) echo "unknown configuration $config" >&2; exit 1 ;;
    esac
    local dir="$HERE/out/javac$analysis-cost-$config-r$round"
    rm -rf "$dir" && mkdir -p "$dir/$config"
    local start=$SECONDS
    if ! mx -p "$G/substratevm" javac-image -H:+UnlockExperimentalVMOptions -H:+SideEffectAnalysis \
            -H:SideEffectAnalysisTool="$REPO" -H:SideEffectAnalysisUv="$(command -v uv)" \
            -H:SideEffectAnalysisProgram=com.sun.tools.javac -H:SideEffectAnalysisOutput="$dir/$config" \
            "${flags[@]}" > "$dir/$config.log" 2>&1; then
        tail -30 "$dir/$config.log"
        exit 1
    fi
    # mx puts the image in its own build directory, whatever the output path: keep a copy.
    local image
    image=$(grep -oE '/[^ ]*/javac \(executable' "$dir/$config.log" | cut -d' ' -f1)
    cp "$image" "$dir/$config/javac"
    local same="compiles Examples as the JDK's javac does"
    mkdir -p "$dir/$config/classes"
    if ! "$dir/$config/javac" -proc:none "${SYSTEM[@]}" -d "$dir/$config/classes" "$EXAMPLES" > "$dir/$config/javac.txt" 2>&1; then
        same="FAILED to compile Examples: $(head -c 300 "$dir/$config/javac.txt")"
    elif ! "$JDK/bin/java" -cp "$dir/$config/classes" Examples 2>&1 | cmp -s - "$REFERENCE/output.txt"; then
        same="compiled Examples DIFFERENTLY: its classes print something else"
    fi
    echo "javac$analysis-cost-$config-r$round: built in $((SECONDS - start)) s, $same"
}

for round in $(seq 1 "$REPEATS"); do
    for config in "${CONFIGS[@]}"; do
        build "$config" "$round"
    done
done
uv run --project "$REPO" python "$HERE/cost.py" "$HERE/out" javac
