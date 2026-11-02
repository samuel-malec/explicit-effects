#!/usr/bin/env bash
# What the side-effect analysis costs in a native-image build: each configuration of one program built
# REPEATS times, one build at a time, the configurations taking turns so that the machine's drift
# touches them alike. Builds as run.sh builds them, into out/<name>-cost-<config>-r<k>/.
#
#   ./cost.sh Awfy                      # 5 rounds, -O3 with trivial inlining: a user's build
#   REPEATS=3 EXTRA="" ./cost.sh Examples
#
# A round builds, on the default analysis: graal; graal with the analysis keeping the inputs of its flows
# (graalinputs, what thread escape needs: the baseline of fieldsescape); fields; and fields with thread escape
# as the elision uses it (fieldsescape: inputs kept, assumptions vm-code,entry-points). Then with allocation
# sites (ALLOCSENS=1): graal; graal with the inputs and source positions kept (graalflags, the baseline of
# locks); objects; locks (elision). Each configuration compares with the one it adds to on the same
# analysis and flags. cost.py then sets each build's stage times, peak RSS and timings.txt side by side.
#
# THREAD_ESCAPE=off builds only what has no model of concurrency in it: graal, fields, and with allocation sites graal and
# objects, every image with -H:-SideEffectAnalysisThreadEscape (run.sh). fieldsescape, locks and their baselines are not built,
# and the ones an earlier run left in out/ are removed, so that cost.py does not set them next to these.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../graal-native/env.sh"

PROGRAM=${1:?usage: cost.sh <program, as run.sh takes it>}
REPEATS=${REPEATS:-5}
EXTRA=${EXTRA--O3 -H:+AOTTrivialInline}
export EXTRA
INPUTS="-H:+TrackInputFlows"
POSITIONS="-H:+TrackNodeSourcePosition"
ESCAPE="-H:SideEffectAnalysisAssumptions=vm-code,entry-points"

CONFIGS=(objects locks)
if [[ ${THREAD_ESCAPE:-on} == off ]]; then
    CONFIGS=(objects)
    name=$(echo "$PROGRAM" | tr '[:upper:]' '[:lower:]')
    rm -rf "$HERE/out/$name"-cost-{graalinputs,fieldsescape}-r* "$HERE/out/$name"-allocsens-cost-{graalflags,locks}-r*
fi

for round in $(seq 1 "$REPEATS"); do
    ONLY=graal TAG=cost-graal-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    [[ ${THREAD_ESCAPE:-on} == off ]] || EXTRA="$EXTRA $INPUTS" ONLY=graal TAG=cost-graalinputs-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    ONLY=fields TAG=cost-fields-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    [[ ${THREAD_ESCAPE:-on} == off ]] || EXTRA="$EXTRA $INPUTS $ESCAPE" ONLY=fields TAG=cost-fieldsescape-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    ALLOCSENS=1 ONLY=graal TAG=cost-graal-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    [[ ${THREAD_ESCAPE:-on} == off ]] || ALLOCSENS=1 EXTRA="$EXTRA $INPUTS $POSITIONS" ONLY=graal TAG=cost-graalflags-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    for config in "${CONFIGS[@]}"; do
        ALLOCSENS=1 ONLY=$config TAG=cost-$config-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    done
done
uv run --project "$REPO" python "$SCRIPTS/evaluation/cost.py" "$HERE/out" "$(echo "$PROGRAM" | tr '[:upper:]' '[:lower:]')"
