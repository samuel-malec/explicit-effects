#!/usr/bin/env bash
# A benchmark of the Renaissance suite (release 0.16.0, github.com/renaissance-benchmarks/renaissance), built with the side-effect
# analysis, one image per configuration and round, into out/renaissance/<benchmark>-r<round>/<config>/. The benchmark's Native Image
# bundle is made by renaissance-bundles.sh (mx runs the benchmark under the agent and builds an image with --bundle-create); this applies
# it with the builder of the graal tree, as barista.sh does, so that `graal` and `fields` differ only in our flags.
#
#   THREAD_ESCAPE=off scripts/frameworks/renaissance.sh scrabble akka-uct
#   THREAD_ESCAPE=off scripts/frameworks/renaissance.sh --rounds 1 --configs graal,fields,ceiling dotty
#   LEVEL= THREAD_ESCAPE=off scripts/frameworks/renaissance.sh scrabble        # the builder's default optimization level
#
# The images are built one at a time, in turns: for each benchmark graal r1, fields r1, graal r2, fields r2, ... The configurations
# are in bundle.sh. LEVEL is the optimization level (default -O3,
# the level of the AWFY runs); EXTRA gives native-image more options. The bundles are in $RENAISSANCE (default ~/eval/renaissance):
# <benchmark>/<benchmark>.nib.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../graal-native/env.sh"
source "$HERE/provenance.sh"
source "$SCRIPTS/frameworks/bundle.sh"
set +e
RENAISSANCE=${RENAISSANCE:-$HOME/eval/renaissance}
ROUNDS=1,2,3
CONFIGS=graal,fields
BENCHMARKS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --rounds) ROUNDS=$2; shift 2 ;;
        --configs) CONFIGS=$2; shift 2 ;;
        -*) echo "usage: renaissance.sh [--rounds 1,2,3] [--configs graal,fields] <benchmark>…" >&2; exit 2 ;;
        *) BENCHMARKS+=("$1"); shift ;;
    esac
done
[[ ${#BENCHMARKS[@]} -gt 0 ]] || { echo "usage: renaissance.sh [--rounds 1,2,3] [--configs graal,fields] <benchmark>…" >&2; exit 2; }
read -r -a EXTRA_OPTIONS <<< "${LEVEL--O3} ${EXTRA:-}"

for benchmark in "${BENCHMARKS[@]}"; do
    nib="$RENAISSANCE/$benchmark/$benchmark.nib"
    [[ -f $nib ]] || { echo "error: missing $nib" >&2; continue; }
    for round in ${ROUNDS//,/ }; do
        for config in ${CONFIGS//,/ }; do
            out="$HERE/out/renaissance/$benchmark-r$round/$config"
            echo -n "$benchmark r$round "
            build_bundle "$config" "$nib" "$out" "${EXTRA_OPTIONS[@]}"
        done
    done
done
