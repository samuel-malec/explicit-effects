#!/usr/bin/env bash
# Native Image's own JUnit tests (com.oracle.svm.test) with the locks thread escape proves removable gone and
# the volatile accesses it proves ordinary made so, in every method of every test image: the robustness run
# for lock elision. About an hour on pontos04. Graal's assertions stay on.
#
# Two limits, found 24 Oct: the default analysis is used because Native Image's allocsens analysis breaks JmxTest by
# itself (it dies at startup, `Unsupported protocol: rmi`, with or without the feature); and the tool lists no site to
# remove in the images built so far ("0 monitor sites to remove"), so the run shows that the feature and the phase
# build and run under assertions, not that an elision is right. The round trips of the corpus and AWFY do that.
#
#   ./svm-test-locks.sh [output directory, default ~/eval/svm-test-locks]
set -uo pipefail
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
EVAL=${1:-$HOME/eval/svm-test-locks}
mkdir -p "$EVAL"
echo "=== start $(date +%T)"
mx -p "$HOME/graal/substratevm" native-unittest com.oracle.svm.test --build-args -J-ea -J-esa -H:+UnlockExperimentalVMOptions \
    -H:+SideEffectAnalysis -H:SideEffectAnalysisTool="$REPO" -H:SideEffectAnalysisProgram=com.oracle.svm.test \
    -H:SideEffectAnalysisOutput="$EVAL/out" -H:-SideEffectAnalysisNarrowCalls -H:+SideEffectAnalysisElideLocks \
    -H:SideEffectAnalysisLabel=locks -H:SideEffectAnalysisAssumptions=vm-code,entry-points \
    -H:+TrackNodeSourcePosition -H:+TrackInputFlows > "$EVAL/svm-test.log" 2>&1
echo "exit $?"
grep -E "Finished generating|Failed generating|^OK \(|FAILURES|Tests run:" "$EVAL/svm-test.log" | sed 's/ in [0-9].*//; s/ after .*//' | sort | uniq -c
grep -E "^[0-9]+\) " "$EVAL/svm-test.log" | head -20
echo "=== done $(date +%T)"
