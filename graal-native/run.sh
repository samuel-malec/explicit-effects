#!/usr/bin/env bash
# The round trip on one example: build its native image as Graal compiles it
# (graal), with the kills our tool gives each call (kills), and with each
# access to a field in its partition of the objects too (objects), run them,
# and compare their output with the JVM's. What Graal leaves of the program's
# methods, with the calls narrowed and the fields partitioned in each, goes to
# out/<name>/<mode>/counts.txt.
#
#   ./run.sh Examples
#   ./run.sh Aliasing          # through RunAliasing, which prints what it computes
#   ./run.sh Awfy              # a whole program: programs/awfy/, built by its build.sh
#   LIE='Examples.countInto(LExamples$Counter;LExamples$Link;)V' ./run.sh Examples
#                              # the control: a wrong kill must show in the output
#   SPLIT='Aliasing.forwardPastAliasControl(LAliasing$Counter;LAliasing$Counter;)I' ./run.sh Aliasing
#                              # the same for partitions: different references never meet
#   DEAD='Examples.forwardAcrossMerge(LExamples$Counter;LExamples$Link;Z)I:21' ./run.sh Examples
#                              # the same for decisions: a store that is read claimed dead
#   ALLOCSENS=1 ./run.sh Awfy  # every image with allocation sites, so that the analysis is
#                              # the same in all four: out/awfy-allocsens/
#
# A fourth image (decisions) also removes the stores our rules find dead in Java.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

EXAMPLE=${1:?usage: run.sh <a class of graal-export/examples, or a program of programs/>}
PROGRAM="$REPO/programs/$(echo "$EXAMPLE" | tr '[:upper:]' '[:lower:]')"
NAME=$(echo "$EXAMPLE" | tr '[:upper:]' '[:lower:]')${LIE:+-lie}${SPLIT:+-split}${DEAD:+-dead}${ALLOCSENS:+-allocsens}
OUT="$HERE/out/$NAME"
MAIN=$EXAMPLE
SOURCES=("$EXPORTER/examples/$EXAMPLE.java")
if [[ -f "$HERE/Run$EXAMPLE.java" ]]; then
    MAIN=Run$EXAMPLE
    SOURCES+=("$HERE/Run$EXAMPLE.java")
fi
# A whole program is every class outside the platform's packages; an example is its classes.
SCOPE="$EXAMPLE,$MAIN"
if [[ -x "$PROGRAM/build.sh" ]]; then
    SOURCES=()
    SCOPE=""
fi
MODES=(graal kills objects decisions)
if [[ -n "${LIE:-}" ]]; then
    MODES=(kills)
elif [[ -n "${SPLIT:-}" ]]; then
    MODES=(objects)
elif [[ -n "${DEAD:-}" ]]; then
    MODES=(decisions)
fi

rm -rf "$OUT"
mkdir -p "$OUT/classes"
if [[ -x "$PROGRAM/build.sh" ]]; then
    "$PROGRAM/build.sh" "$OUT/classes"
else
    "$GRAALVM/bin/javac" -d "$OUT/classes" "${SOURCES[@]}"
fi
# What a program prints and how it exits: Signatures, for one, ends in an exception.
run() {
    local status=0
    "$@" 2> /dev/null || status=$?
    echo "exit $status"
}
run "$GRAALVM/bin/java" -cp "$OUT/classes" "$MAIN" > "$OUT/jvm.txt"

# The image's class path gets the JVMCI exports, but JVMCI is no root module of the image.
CI_EXPORTS=()
for flag in "${JVMCI_EXPORTS[@]}"; do
    [[ "$flag" == --add-exports=jdk.internal.vm.ci/* ]] && CI_EXPORTS+=("$flag")
done

for mode in "${MODES[@]}"; do
    mkdir -p "$OUT/$mode"
    narrow=$([[ $mode == graal ]] && echo false || echo true)
    # Object partitions need the analysis to tell objects apart by where they were
    # allocated, and the compiled graphs to keep where each access is.
    OBJECTS=()
    if [[ -n "${ALLOCSENS:-}" && ( $mode == graal || $mode == kills ) ]]; then
        OBJECTS=(-H:AnalysisContextSensitivity=allocsens)
    fi
    if [[ $mode == objects || $mode == decisions ]]; then
        OBJECTS=(-H:AnalysisContextSensitivity=allocsens -H:+TrackNodeSourcePosition -J-Deffects.partition=object-field
                 ${SPLIT:+"-J-Deffects.split=$SPLIT"})
    fi
    if [[ $mode == decisions ]]; then
        OBJECTS+=(-J-Deffects.decisions=true ${DEAD:+"-J-Deffects.dead=$DEAD"})
    fi
    start=$(date +%s)
    if ! "$GRAALVM/bin/native-image" \
            -J--upgrade-module-path="$COMPILER" \
            @"$EXPORTER/exports.args" "${CI_EXPORTS[@]}" "${BUILDER_EXPORTS[@]}" \
            -cp "$OUT/classes:$HERE/classes" --features=EffectsFeature -EHOME -EPATH \
            -J-Deffects.out="$OUT/$mode" -J-Deffects.program="$SCOPE" -J-Deffects.narrow=$narrow \
            -J-Deffects.tool="$REPO" -J-Deffects.uv="$(command -v uv)" ${LIE:+"-J-Deffects.lie=$LIE"} "${OBJECTS[@]}" \
            -H:+UnlockExperimentalVMOptions -H:-AOTTrivialInline \
            "$MAIN" -o "$OUT/$mode/$NAME" > "$OUT/$mode.log" 2>&1; then
        tail -40 "$OUT/$mode.log"
        exit 1
    fi
    run "$OUT/$mode/$NAME" > "$OUT/$mode/output.txt"
    if cmp -s "$OUT/jvm.txt" "$OUT/$mode/output.txt"; then
        same="prints what the JVM prints"
    else
        same="prints $(tr '\n' ' ' < "$OUT/$mode/output.txt")instead of the JVM's $(tr '\n' ' ' < "$OUT/jvm.txt")"
    fi
    echo "$NAME, $mode: built in $(( $(date +%s) - start )) s, $same"
done
