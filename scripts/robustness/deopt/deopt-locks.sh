#!/usr/bin/env bash
# Lock removal and deoptimization. DeoptimizedLocks is deoptimized while it holds a lock on an object only
# one thread reaches, twice: its code from the image, which the stress test (-H:+DeoptimizeAll) deoptimizes
# inside the locked region, and the same method compiled while the program runs, whose compiled code is
# invalidated by a call inside the region. The frame goes on in the version of the method that the image
# was built with for deoptimization, which must release the lock. Three images:
#
#   graal      no analysis: both are right (the image code goes on, the thread does not hold the lock afterwards)
#   guarded    the lock removal on, with the method's monitors claimed thread-local (the control of
#              -H:SideEffectAnalysisClaimLocksLocal: the analysis of an image that includes the compiler
#              proves no lock local); the image can deoptimize, so it keeps them, and both are right
#   unguarded  the same with -H:+SideEffectAnalysisClaimNoDeoptimization: the monitors are removed from the
#              image's code and the version it resumes in releases a lock nobody took: the image stops with
#              "Unexpected exception in MonitorSupport.monitorExit" (IllegalMonitorStateException), exit 134
#
#   ./deopt-locks.sh                 # all three, into out/deopt-locks/
#   MODES="graal guarded" ./deopt-locks.sh
#
# Each prints the number of deoptimizations the run did (-H:+ProfileDeoptimization): a run with none proves
# nothing. The analysis tells objects apart by type only: Native Image's runtime compilation does not build
# with the allocation-site analysis (AnalysisError in CallSiteSensitiveMethodTypeFlow.setAsStubFlow).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../../../graal-native/env.sh"
source "$HERE/provenance.sh"
set +e

OUT="$HERE/out/deopt-locks"
rm -rf "$OUT"
mkdir -p "$OUT/classes"
provenance "$OUT"
BUILDER="$GRAALVM/lib/svm/builder"
SDK="$G/sdk/mxbuild/dists"
"$GRAALVM/bin/javac" --add-modules jdk.internal.vm.ci --add-exports jdk.internal.vm.ci/jdk.vm.ci.code=ALL-UNNAMED \
    --add-exports jdk.internal.vm.ci/jdk.vm.ci.meta=ALL-UNNAMED \
    -cp "$BUILDER/svm.jar:$BUILDER/svm-shared.jar:$BUILDER/pointsto.jar:$BUILDER/native-image-base.jar:$SDK/nativeimage.jar:$SDK/word.jar:$SDK/collections.jar:$COMPILER" \
    -d "$OUT/classes" "$DIR/DeoptimizedLocks.java" || exit 1

failed=0
for mode in ${MODES:-graal guarded unguarded}; do
    mkdir -p "$OUT/$mode"
    ANALYSIS=()
    expected_image=ok
    expected_compiled=false
    if [[ $mode != graal ]]; then
        ANALYSIS=(-H:+SideEffectAnalysis -H:SideEffectAnalysisOutput="$OUT/$mode" -H:SideEffectAnalysisProgram=DeoptimizedLocks
                  -H:SideEffectAnalysisTool="$REPO" -H:SideEffectAnalysisUv="$(command -v uv)" -H:-SideEffectAnalysisNarrowCalls
                  -H:+TrackNodeSourcePosition -H:+TrackInputFlows -H:SideEffectAnalysisLabel=locks
                  -H:+SideEffectAnalysisElideLocks -H:SideEffectAnalysisAssumptions=vm-code,entry-points
                  '-H:SideEffectAnalysisClaimLocksLocal=DeoptimizedLocks.run()LDeoptimizedLocks$Cell;')
        if [[ $mode == unguarded ]]; then
            ANALYSIS+=(-H:+SideEffectAnalysisClaimNoDeoptimization)
            expected_image="a fatal error in MonitorSupport.monitorExit"
            expected_compiled="-"
        fi
    fi
    start=$(date +%s)
    if ! "$GRAALVM/bin/native-image" -J--upgrade-module-path="$COMPILER" -cp "$OUT/classes" -EHOME -EPATH \
            --add-exports=org.graalvm.nativeimage.shared/com.oracle.svm.shared.util=ALL-UNNAMED \
            --initialize-at-build-time=DeoptimizedLocks \
            '--features=DeoptimizedLocks$RegisterMethodsFeature' \
            -H:+UnlockExperimentalVMOptions -H:+ProfileDeoptimization -H:+DeoptimizeAll -H:-AOTTrivialInline "${ANALYSIS[@]}" \
            DeoptimizedLocks -o "$OUT/$mode/deopt-locks" > "$OUT/$mode.log" 2>&1; then
        tail -40 "$OUT/$mode.log"
        echo "$mode: the build failed"
        failed=1
        continue
    fi
    timeout 300 "$OUT/$mode/deopt-locks" > "$OUT/$mode/output.txt" 2> "$OUT/$mode/errors.txt"
    status=$?
    image=$(sed -n 's/^image code deoptimized in the region: //p' "$OUT/$mode/output.txt")
    compiled=$(sed -n 's/^compiled code .* holds the lock after the method returned: //p' "$OUT/$mode/output.txt")
    deopts=$(sed -n 's/^ *Number of deoptimizations: *\([0-9]*\).*/\1/p' "$OUT/$mode/errors.txt" | tail -n 1)
    removed=$(sed -n 's/^# locks removed: \([0-9]*\),.*/\1/p' "$OUT/$mode/timings.txt" 2> /dev/null)
    kept=$(sed -n 's/^# locks kept because the image can deoptimize: \([0-9]*\).*/\1/p' "$OUT/$mode/timings.txt" 2> /dev/null)
    if [[ $mode == unguarded ]]; then
        # The image stops before it can print: the fatal error in the version the frame resumed in is the evidence.
        image=$(grep -q "^Fatal error: Unexpected exception in MonitorSupport.monitorExit" "$OUT/$mode/errors.txt" && echo "$expected_image")
        compiled=-
        deopts=-
        verdict=$([[ $image == "$expected_image" && $status -ne 0 ]] && echo "as expected" || echo "NOT AS EXPECTED")
    else
        verdict=$([[ $image == "$expected_image" && $compiled == "$expected_compiled" && ${deopts:-0} -gt 1 ]] && echo "as expected" || echo "NOT AS EXPECTED")
    fi
    [[ $verdict == "as expected" ]] || failed=1
    echo "$mode: built in $(( $(date +%s) - start )) s, exit $status, deoptimizations ${deopts:-?}, locks removed ${removed:--}, kept ${kept:--}; image code: ${image:-?} (expected $expected_image); compiled code holds the lock afterwards: ${compiled:-?} (expected $expected_compiled): $verdict"
done
exit $failed
