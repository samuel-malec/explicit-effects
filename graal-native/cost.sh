#!/usr/bin/env bash
# What the side-effect analysis costs in a native-image build: each configuration of one program built
# REPEATS times, one build at a time, the configurations taking turns so that the machine's drift
# touches them alike. Builds as run.sh builds them, into out/<name>-cost-<config>-r<k>/.
#
#   ./cost.sh Awfy                      # 5 rounds, -O3 with trivial inlining: a user's build
#   REPEATS=3 EXTRA="" ./cost.sh Examples
#
# A round builds graal and kills on the default analysis, then graal, objects and decisions with
# allocation sites (ALLOCSENS=1), so that each configuration compares with graal on the same
# analysis. cost.py then sets each build's stage times, peak RSS and timings.txt side by side.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

PROGRAM=${1:?usage: cost.sh <program, as run.sh takes it>}
REPEATS=${REPEATS:-5}
EXTRA=${EXTRA--O3 -H:+AOTTrivialInline}
export EXTRA

for round in $(seq 1 "$REPEATS"); do
    for config in graal kills; do
        ONLY=$config TAG=cost-$config-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    done
    for config in graal objects decisions; do
        ALLOCSENS=1 ONLY=$config TAG=cost-$config-r$round "$HERE/run.sh" "$PROGRAM" || exit 1
    done
done
uv run --project "$REPO" python "$HERE/cost.py" "$HERE/out" "$(echo "$PROGRAM" | tr '[:upper:]' '[:lower:]')"
