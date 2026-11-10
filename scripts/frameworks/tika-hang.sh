#!/usr/bin/env bash
# Is a hang of the build the feature's? Barista's quarkus-tika bundle hangs the builder in a class-initialization deadlock (threads inside the
# <clinit> of Apache POI's and XMLBeans' schema classes, initialized at build time, while the others wait on them). This applies the bundle again and
# again by the same builder with the feature (graal: loaded, nothing narrowed, THREAD_ESCAPE=off) and without it (plain), the two taking turns, with the
# build's watchdog set to one minute so that a hang costs two.
#
#   scripts/frameworks/tika-hang.sh [builds per arm, default 8]
#
# One line per build: what the log shows (built; a hang, with the number of <clinit> frames and blocked threads of its thread dump and the number of
# frames of the feature; the type of an image-heap error), the time, and the load when it started. Logs in out/tika-hang/<arm>-<n>/build.log; the bundle
# copy and the build's outputs are deleted after each build. The assets are in $BARISTA (default ~/eval/barista), as for barista.sh.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../graal-native/env.sh"
source "$HERE/provenance.sh"
source "$SCRIPTS/frameworks/bundle.sh"
set +e
BARISTA=${BARISTA:-$HOME/eval/barista}
N=${1:-8}
NIB="$BARISTA/quarkus-tika/quarkus-tika.nib"
OUT="$HERE/out/tika-hang"
WATCHDOG=(-H:DeadlockWatchdogInterval=1)
[[ -f $NIB ]] || { echo "error: missing $NIB" >&2; exit 1; }

classify() {  # log
    local log=$1
    if grep -q 'Finished generating' "$log"; then echo "built"
    elif grep -q 'watchdog detected no activity' "$log"; then
        echo "HANG: $(grep -c '<clinit>' "$log") <clinit> frames, $(grep -c 'in BLOCKED' "$log") blocked threads, $(grep -c -i 'SideEffectAnalysis.*java\|sideeffects\.' "$log") frames of the feature"
    elif grep -q 'was found in the image heap' "$log"; then echo "image-heap error: $(grep -m1 -o "object of type '[^']*'" "$log")"
    else echo "other: $(grep -m1 -i 'error\|exception' "$log" | cut -c1-100)"; fi
}

echo "$(date +%T) start, $N builds per arm, load $(cut -d' ' -f1 /proc/loadavg)"
for n in $(seq 1 "$N"); do
    for arm in plain graal; do
        dir="$OUT/$arm-$n"
        load=$(cut -d' ' -f1 /proc/loadavg)
        start=$SECONDS
        if [[ $arm == graal ]]; then
            THREAD_ESCAPE=off build_bundle graal "$NIB" "$dir" "${WATCHDOG[@]}" > /dev/null
        else
            build_plain "$NIB" "$dir" "${WATCHDOG[@]}" > /dev/null
        fi
        echo "$(date +%T) $arm $n: $(classify "$dir/build.log"), $((SECONDS - start)) s, load at start $load"
        rm -f "$dir/app.nib"
        rm -rf "$dir/app.output"
    done
done
echo "$(date +%T) done"
