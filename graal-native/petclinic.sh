#!/usr/bin/env bash
# Spring PetClinic, the Native Image bundle that Graal's benchmark suite ships (spring-petclinic-3.0.1-SNAPSHOT.nib, made in 2023),
# built with the side-effect analysis, one image per configuration, into out/petclinic/<config>/. The bundle is applied with this
# builder; two things it needs that the 2023 builder did not: JMX support (--enable-monitoring=jmxserver) and four registrations
# for reflection (petclinic/reachability-metadata.json, found by petclinic/add-missing-registrations.py: build, run, read what the
# image says it lacks). Every configuration gets both, so the images differ only in what the analysis does.
#
#   graal-native/petclinic.sh graal kills                          # default analysis
#   graal-native/petclinic.sh graalflagscutoff lockscutoff         # allocation sites, cutoff 100: locks removed or not
#
#   graal        the feature on, nothing narrowed: the baseline
#   kills        every call narrowed to what its callees write
#   ceiling      kills with the kill of everything the facts cannot name left out (unsound: an upper bound); does not
#                finish on petclinic: effects.kills was stopped after an hour at 226 GB (nearly every one of the 164,600
#                methods then has a list of tens of thousands of partitions), so it is not built by default
#   graalflagscutoff, lockscutoff   allocation sites, the saturation cutoff at 100, the inputs of the flows and the source positions kept;
#                lockscutoff also removes the locks and makes the volatile accesses ordinary that thread escape proves local
#
# The assets are in $PETCLINIC (default ~/eval/petclinic: app/*.nib, workloads/, wrk/, copied from ~/.mx/cache on the laptop).
# petclinic_load.py then starts the images and measures them under load.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
source "$HERE/provenance.sh"
set +e
PETCLINIC=${PETCLINIC:-$HOME/eval/petclinic}
NIB=$(ls "$PETCLINIC"/app/*.nib)
OUT="$HERE/out/petclinic"
mkdir -p "$OUT"
[[ $# -gt 0 ]] || { echo "usage: petclinic.sh <graal|kills|graalflagscutoff|lockscutoff|ceiling>…" >&2; exit 2; }

build() {  # configuration
    local config=$1 dir="$OUT/$1" flags=() mode=kills
    local allocsens=(-H:AnalysisContextSensitivity=allocsens -H:+TrackNodeSourcePosition -H:+TrackInputFlows -H:TypeFlowSaturationCutoff=100)
    case $config in
        graal)             mode=graal; flags=(-H:-SideEffectAnalysisNarrowCalls) ;;
        kills)             flags=() ;;
        ceiling)           flags=(-H:SideEffectAnalysisIgnoreEffects=all) ;;
        graalflagscutoff)  mode=graal; flags=(-H:-SideEffectAnalysisNarrowCalls "${allocsens[@]}") ;;
        lockscutoff)       mode=locks; flags=(-H:-SideEffectAnalysisNarrowCalls "${allocsens[@]}" -H:SideEffectAnalysisLabel=locks
                                              -H:+SideEffectAnalysisElideLocks -H:SideEffectAnalysisAssumptions=vm-code,entry-points
                                              -H:DeadlockWatchdogInterval=120) ;;  # the tool runs for longer than the default ten minutes
        *) echo "unknown configuration $config" >&2; return 1 ;;
    esac
    rm -rf "$dir" && mkdir -p "$dir/$mode"
    provenance "$dir"
    cp "$NIB" "$dir/app.nib"
    local start=$SECONDS
    ( cd "$dir" && "$GRAALVM/bin/native-image" -J--upgrade-module-path="$COMPILER" -EHOME -EPATH \
        --enable-monitoring=jmxserver -H:ConfigurationFileDirectories="$HERE/petclinic" \
        -H:+UnlockExperimentalVMOptions -H:+SideEffectAnalysis -H:SideEffectAnalysisOutput="$dir/$mode" \
        -H:SideEffectAnalysisTool="$REPO" -H:SideEffectAnalysisUv="$(command -v uv)" "${flags[@]}" \
        --bundle-apply=app.nib > "$dir/build.log" 2>&1 )
    local status=$?
    echo "$config: exit $status, built in $((SECONDS - start)) s, $(grep -o 'executable, [0-9.]*MiB' "$dir/build.log" | head -1), $(grep -h 'locks removed' "$dir/$mode/timings.txt" 2> /dev/null | head -1)"
    ln -sfn "$dir/app.output/default/spring-petclinic" "$dir/image"
    return $status
}

# One after the other: builds side by side slow each other down (five at once took 4 to 53 minutes), so their times mean nothing
for config in "$@"; do
    build "$config"
done
