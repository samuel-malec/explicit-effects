#!/usr/bin/env bash
# Why an object is shared, as Native Image's own analysis has it: one image build with the feature and
# thread escape's explanation switched on, printing the chain of reasons for each object whose name
# matches the regular expression, how the root methods were registered, and a count of the reasons at
# the root of every chain. For tracing an answer that is not the one expected.
#
#   ./explain-sharing.sh <classes dir> <program prefix> <main class> <regex> [native-image options…]
#   ./explain-sharing.sh /tmp/x/classes sharing.LocalInLocalObject sharing.LocalInLocalObject 'LocalInLocalObject\$Item' \
#       -H:AnalysisContextSensitivity=allocsens -H:+TrackInputFlows \
#       -H:SideEffectAnalysisAssumptions=thread-confined,vm-fields,vm-code,handler-references,entry-points
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
CLASSES=${1:?usage: explain-sharing.sh <classes dir> <program prefix> <main class> <regex> [options]}
PROGRAM=$2; MAIN=$3; REGEX=$4
shift 4
D=$(mktemp -d)
"$GRAALVM/bin/native-image" -J-Dsideeffects.explainSharing="$REGEX" -J--upgrade-module-path="$COMPILER" -cp "$CLASSES" -EHOME -EPATH \
    -H:+UnlockExperimentalVMOptions -H:+SideEffectAnalysis -H:SideEffectAnalysisOutput="$D/out" -H:SideEffectAnalysisProgram="$PROGRAM" \
    -H:SideEffectAnalysisTool="$REPO" -H:SideEffectAnalysisUv="$(command -v uv)" -H:-AOTTrivialInline "$@" "$MAIN" -o "$D/img" 2>&1 | grep -a -A14 "^THREADESCAPE"
echo "output in $D/out"
