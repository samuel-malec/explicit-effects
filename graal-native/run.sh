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
#   ONLY=locks ./run.sh LockShapes      # the image that also removes the locks on objects only one thread
#                              # reaches; LIE_LOCKS='LocksShared.add(I)V' ONLY=locks ./run.sh LocksShared is the
#                              # control: the program shares that lock, so it must go wrong
#   ONLY="graal kills" TAG=sym EXTRA="-H:-DeleteLocalSymbols" ./run.sh Awfy
#                              # only some of the images, into out/awfy-sym/, with more
#                              # native-image options: here, the symbols perf needs
#
# A fourth image (decisions) also removes the stores our rules find dead in Java. A fifth,
# graal-dse, only with ONLY, has Graal remove dead stores itself after inlining instead.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

EXAMPLE=${1:?usage: run.sh <a class of graal-export/corpus, or a program of programs/>}
PROGRAM="$REPO/programs/$(echo "$EXAMPLE" | tr '[:upper:]' '[:lower:]')"
NAME=$(echo "$EXAMPLE" | tr '[:upper:]' '[:lower:]')${LIE:+-lie}${LIE_LOCKS:+-lie}${SPLIT:+-split}${DEAD:+-dead}${ALLOCSENS:+-allocsens}${TAG:+-$TAG}
OUT="$HERE/out/$NAME"
MAIN=$EXAMPLE
SOURCES=("$EXPORT_DIR/corpus/$EXAMPLE.java")
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
if [[ -n "${ONLY:-}" ]]; then
    read -r -a MODES <<< "$ONLY"
fi
read -r -a EXTRA_OPTIONS <<< "${EXTRA:-}"

rm -rf "$OUT"
mkdir -p "$OUT/classes"
if [[ -x "$PROGRAM/build.sh" ]]; then
    "$PROGRAM/build.sh" "$OUT/classes"
else
    "$GRAALVM/bin/javac" -d "$OUT/classes" "${SOURCES[@]}"
fi
# What a program prints and how it exits: Signatures, for one, ends in an exception. A run
# that takes longer than RUN_TIMEOUT seconds (default 300) is stopped and exits with 124: a
# wrong optimization can make a loop endless.
run() {
    local status=0
    timeout "${RUN_TIMEOUT:-300}" "$@" 2> /dev/null || status=$?
    echo "exit $status"
}
run "$GRAALVM/bin/java" -cp "$OUT/classes" "$MAIN" > "$OUT/jvm.txt"

for mode in "${MODES[@]}"; do
    mkdir -p "$OUT/$mode"
    narrow=$([[ $mode == graal || $mode == locks ]] && echo - || echo +)
    # Object partitions need the analysis to tell objects apart by where they were
    # allocated, and the compiled graphs to keep where each access is.
    OBJECTS=()
    if [[ -n "${ALLOCSENS:-}" && ( $mode == graal || $mode == kills ) ]]; then
        OBJECTS=(-H:AnalysisContextSensitivity=allocsens)
    fi
    if [[ $mode == objects || $mode == decisions ]]; then
        OBJECTS=(-H:AnalysisContextSensitivity=allocsens -H:+TrackNodeSourcePosition -H:SideEffectAnalysisPartition=object-field
                 ${SPLIT:+"-H:SideEffectAnalysisClaimNoAliasing=$SPLIT"})
    fi
    if [[ $mode == decisions ]]; then
        OBJECTS+=(-H:+SideEffectAnalysisRemoveDeadStores ${DEAD:+"-H:SideEffectAnalysisClaimDeadStore=$DEAD"})
    fi
    # Not one of the four images by default (ONLY="locks"): the monitors on objects only one thread reaches
    # are removed, and nothing else changes. The analysis tells objects apart by allocation site and keeps
    # the inputs of its flows, and thread escape makes the assumptions the export names; with LIE_LOCKS=<method key>
    # the control claims that method's monitors are thread-local, which a program that shares them must not survive.
    if [[ $mode == locks ]]; then
        OBJECTS=(-H:AnalysisContextSensitivity=allocsens -H:+TrackNodeSourcePosition -H:+TrackInputFlows -H:SideEffectAnalysisLabel=locks
                 -H:+SideEffectAnalysisElideLocks -H:SideEffectAnalysisAssumptions="${ASSUMPTIONS:-vm-code,entry-points}"
                 ${LIE_LOCKS:+"-H:SideEffectAnalysisClaimLocksLocal=$LIE_LOCKS"})
    fi
    # Not one of the four images by default (ONLY="... graal-dse"): Graal's own dead-store
    # elimination, OverwrittenStoreEliminationPhase, after inlining, with the same partitions as
    # the decisions image, instead of the tool's decisions.
    if [[ $mode == graal-dse ]]; then
        OBJECTS=(-H:AnalysisContextSensitivity=allocsens -H:+TrackNodeSourcePosition -H:SideEffectAnalysisPartition=object-field
                 -H:+SideEffectAnalysisEliminateOverwrittenStores)
    fi
    start=$(date +%s)
    # The side-effect analysis is a feature of the graal tree's image builder
    # (SideEffectAnalysisFeature), switched on and configured with these options.
    if ! "$GRAALVM/bin/native-image" \
            -J--upgrade-module-path="$COMPILER" \
            -cp "$OUT/classes" -EHOME -EPATH \
            -H:+UnlockExperimentalVMOptions -H:+SideEffectAnalysis \
            -H:SideEffectAnalysisOutput="$OUT/$mode" -H:SideEffectAnalysisProgram="$SCOPE" -H:${narrow}SideEffectAnalysisNarrowCalls \
            -H:SideEffectAnalysisTool="$REPO" -H:SideEffectAnalysisUv="$(command -v uv)" \
            ${LIE:+"-H:SideEffectAnalysisClaimWritesNothing=$LIE"} "${OBJECTS[@]}" \
            -H:-AOTTrivialInline "${EXTRA_OPTIONS[@]}" \
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
