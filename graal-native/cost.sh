#!/usr/bin/env bash
# What the side-effect analysis costs in a native-image build: each configuration of one program built
# REPEATS times, one build at a time, the configurations taking turns so that the machine's drift
# touches them alike. Builds as run.sh builds them, into out/<name>-cost-<config>-r<k>/.
#
#   ./cost.sh Awfy                      # 5 rounds, -O3 with trivial inlining: a user's build
#   REPEATS=3 EXTRA="" ./cost.sh Examples
#
# A round builds, on the default analysis: graal; graal with the analysis keeping the inputs of its flows
# (graalinputs, what thread escape needs: the baseline of killsescape); kills; and kills with thread escape
# as the elision uses it (killsescape: inputs kept, assumptions vm-code,entry-points). Then with allocation
# sites (ALLOCSENS=1): graal; graal with the inputs and source positions kept (graalflags, the baseline of
# locks); objects; locks (elision); decisions. Each configuration compares with the one it adds to on the same
# analysis and flags. cost.py then sets each build's stage times, peak RSS and timings.txt side by side.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

PROGRAM=${1:?usage: cost.sh <program, as run.sh takes it>}
REPEATS=${REPEATS:-5}
EXTRA=${EXTRA--O3 -H:+AOTTrivialInline}
export EXTRA
INPUTS="-H:+TrackInputFlows"
POSITIONS="-H:+TrackNodeSourcePosition"
ESCAPE="-H:SideEffectAnalysisAssumptions=vm-code,entry-points"

for round in $(seq 1 "$REPEATS"); do
    ONLY=graal TAG=cost-graal-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    EXTRA="$EXTRA $INPUTS" ONLY=graal TAG=cost-graalinputs-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    ONLY=kills TAG=cost-kills-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    EXTRA="$EXTRA $INPUTS $ESCAPE" ONLY=kills TAG=cost-killsescape-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    ALLOCSENS=1 ONLY=graal TAG=cost-graal-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    ALLOCSENS=1 EXTRA="$EXTRA $INPUTS $POSITIONS" ONLY=graal TAG=cost-graalflags-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    for config in objects locks decisions; do
        ALLOCSENS=1 ONLY=$config TAG=cost-$config-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    done
done
uv run --project "$REPO" python "$HERE/cost.py" "$HERE/out" "$(echo "$PROGRAM" | tr '[:upper:]' '[:lower:]')"
