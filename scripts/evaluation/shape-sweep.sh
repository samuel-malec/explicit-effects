#!/usr/bin/env bash
# AWFY built as graal and as fields under different inliner and unroller settings, each with source positions, so that
# shape_metrics.py can compare the two images of a setting: out/awfy-<setting>/{graal,fields}/. A build whose output differs
# from the JVM's is a failure, as in run.sh. Nothing here times anything; see awfy-repeat.sh for run time.
#
#   scripts/evaluation/shape-sweep.sh                    # every setting below
#   scripts/evaluation/shape-sweep.sh base nounroll      # some of them
#   LIST=1 scripts/evaluation/shape-sweep.sh             # only print the settings
#   FLAGS=1 scripts/evaluation/shape-sweep.sh nounroll   # the options of one setting (for timing builds, which keep no positions)
#   THREAD_ESCAPE=off ROUNDS=2 scripts/evaluation/shape-sweep.sh base   # builds awfy-base and awfy-base-2 (FIRST_ROUND=2 only the second)
#
# The settings are the levels of the optimization (-O), the inliner's switches and its limit for trivial methods, and the
# loop optimizations that duplicate code (full and partial unrolling, peeling). base is the configuration of the 2 November run: it
# turns trivial inlining on, which run.sh's default leaves off (notrivial is that default). -H:-AOTInline is deprecated and read by
# nothing, and so is -H:-InlineBeforeAnalysis (deprecated: no effect); -H:InlineBeforeAnalysisAllowedDepth (default 20) is the depth of the
# inlining before the analysis, which changes the graphs the analysis sees (depth 1 fails in Native Image itself, 5 and 10 build). -H:-AOTPriorityInline switches off Graal's main inliner (only
# -O2 and -O3 turn it on).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../graal-native/env.sh"

POSITIONS="-H:+TrackNodeSourcePosition"
UNROLL="-H:-FullUnroll -H:-PartialUnroll"
declare -A SETTINGS=(
    [base]="-O3 -H:+AOTTrivialInline"
    [nounroll]="-O3 -H:+AOTTrivialInline $UNROLL"
    [nopeel]="-O3 -H:+AOTTrivialInline $UNROLL -H:-LoopPeeling"
    [notrivial]="-O3 -H:-AOTTrivialInline"
    [trivial5]="-O3 -H:+AOTTrivialInline -H:MaxNodesInTrivialMethod=5"
    [nopriority]="-O3 -H:+AOTTrivialInline -H:-AOTPriorityInline"
    [iba5]="-O3 -H:+AOTTrivialInline -H:InlineBeforeAnalysisAllowedDepth=5"
    [O1]="-O1 -H:+AOTTrivialInline"
    [Os]="-Os -H:+AOTTrivialInline"
    [notrivial-nounroll]="-O3 -H:-AOTTrivialInline $UNROLL"
    [nopriority-nounroll]="-O3 -H:+AOTTrivialInline -H:-AOTPriorityInline $UNROLL"
    [Os-nounroll]="-Os -H:+AOTTrivialInline $UNROLL"
)
ORDER=(base nounroll nopeel notrivial trivial5 nopriority iba5 O1 Os notrivial-nounroll nopriority-nounroll Os-nounroll)

if [[ -n ${FLAGS:-} ]]; then  # FLAGS=1 shape-sweep.sh base: the native-image options of a setting, without the source positions
    echo "${SETTINGS[${1:?usage: FLAGS=1 shape-sweep.sh <setting>}]}"
    exit 0
fi
if [[ -n ${LIST:-} ]]; then
    for name in "${ORDER[@]}"; do printf '%-20s %s\n' "$name" "${SETTINGS[$name]}"; done
    exit 0
fi

CHOSEN=("$@")
[[ ${#CHOSEN[@]} -gt 0 ]] || CHOSEN=("${ORDER[@]}")
for name in "${CHOSEN[@]}"; do
    [[ -n ${SETTINGS[$name]:-} ]] || { echo "error: no setting called $name (LIST=1 lists them)" >&2; exit 2; }
done
for name in "${CHOSEN[@]}"; do
    for round in $(seq "${FIRST_ROUND:-1}" "${ROUNDS:-1}"); do
        tag=$name
        [[ $round -eq 1 ]] || tag=$name-$round
        EXTRA="${SETTINGS[$name]} $POSITIONS" ONLY="graal fields" TAG=$tag "$HERE/run.sh" Awfy
    done
done
