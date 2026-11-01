#!/usr/bin/env bash
# AWFY at -O3 with trivial inlining (as a user builds it), `graal` and `kills`, built several times and timed together.
#
# Builds of one configuration differ in speed by more than runs of one binary (petclinic: 6% for `graal`, 38% for `kills` with
# identical kill sets; code placement moved Permute by 8%). The run-time claims of the AWFY comparison (Queens -26%, total neutral)
# were measured on one build of each configuration; this repeats the builds and says how many of them agree.
#
#   scripts/evaluation/awfy-repeat.sh [builds=4] [runs=5]
#
# Builds one after the other into out/awfy-repeat<n>/{graal,kills}/ (log out/awfy-repeat<n>.log), then waits until the machine is
# quiet and times all images pinned to cpus 4-7: the first build's `graal` twice (A/A, the noise of one binary), then every build's
# `graal` and `kills` in turn, run by run (programs/awfy/time.py). The table, with each image against the first, is
# out/awfy-repeat-time.txt; counts.py's loads left per build are out/awfy-repeat-counts.txt.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../graal-native/env.sh"
export PATH="$GRAALVM/bin:$PATH"  # programs/awfy/build.sh compiles with the javac on the path
BUILDS=${1:-4}
RUNS=${2:-5}
cd "$HERE"
uv sync -q --project "$REPO"

for n in $(seq 1 "$BUILDS"); do
    ONLY="graal kills" TAG="repeat$n" EXTRA="-O3 -H:+AOTTrivialInline" ./run.sh Awfy > "out/awfy-repeat$n.log" 2>&1
    grep -E "built in|FAILED|rror" "out/awfy-repeat$n.log"
done

# the machine must be quiet for the timings: nothing else of ours, nothing of others
while [[ $(cut -d. -f1 /proc/loadavg) -ge 2 ]]; do sleep 15; done
echo "machine quiet at $(date +%T), load $(cut -d' ' -f1-3 /proc/loadavg)"

images=(--image "graal-1=out/awfy-repeat1/graal/awfy-repeat1" --image "graal-1-again=out/awfy-repeat1/graal/awfy-repeat1")
for n in $(seq 2 "$BUILDS"); do
    images+=(--image "graal-$n=out/awfy-repeat$n/graal/awfy-repeat$n")
done
for n in $(seq 1 "$BUILDS"); do
    images+=(--image "kills-$n=out/awfy-repeat$n/kills/awfy-repeat$n")
done
taskset -c 4-7 uv run --project "$REPO" python "$REPO/programs/awfy/time.py" "${images[@]}" --runs "$RUNS" 2> /dev/null | tee out/awfy-repeat-time.txt

counts=()
for n in $(seq 1 "$BUILDS"); do
    counts+=("out/awfy-repeat$n/graal/counts.txt" "out/awfy-repeat$n/kills/counts.txt")
done
uv run --project "$REPO" python "$SCRIPTS/evaluation/counts.py" "${counts[@]}" | tee out/awfy-repeat-counts.txt
