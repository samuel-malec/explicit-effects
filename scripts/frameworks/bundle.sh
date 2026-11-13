# Applying a Native Image bundle (.nib) with the side-effect analysis, one image per configuration. Sourced by petclinic.sh and
# barista.sh, after env.sh and provenance.sh:
#
#   build_bundle <configuration> <bundle.nib> <output directory> [native-image options the bundle needs]
#
# builds <output directory>/app.output/default/<executable>, links it as <output directory>/image, and prints one line: the
# exit status, the build time, the size, and (for the locks configurations) what was removed. The analysis' own files
# (export, kill sets, timings, counts) are in <output directory>/<mode>/.
#
#   build_plain <bundle.nib> <output directory> [native-image options the bundle needs]
#
# the same bundle applied by the same builder without the feature: the control that tells whether a failing build or image is ours.
#
#   graal        the feature on, nothing narrowed: the baseline
#   fields       every call narrowed to what its callees write
#   ceiling      fields, with the kill of everything the facts cannot name left out (unsound: an upper bound)
#   locks        locks removed and volatile accesses made ordinary where thread escape proves the object local, default analysis
#   graalflagscutoff, lockscutoff   allocation sites, the saturation cutoff at 100, the inputs of the flows and the source positions
#                kept; lockscutoff also removes the locks and makes the volatile accesses ordinary that thread escape proves local
#
# THREAD_ESCAPE=off adds -H:-SideEffectAnalysisThreadEscape to every configuration and refuses locks and lockscutoff.
#
# KILL_SETS says where fields works out the kill sets: build (the default; the image builder does it from the same facts), tool (the
# explicit-effects tool on the export, as before) or both (the builder does it and the tool too, and the build stops if any method's
# kill set differs). The other configurations keep the fork's default, tool: ceiling leaves effects out and the builder does not,
# and the rest narrow no calls.

# Sets `mode` (the analysis' output directory) and `flags` for a configuration; the caller declares both local.
configure() {
    local allocsens=(-H:AnalysisContextSensitivity=allocsens -H:+TrackNodeSourcePosition -H:+TrackInputFlows -H:TypeFlowSaturationCutoff=100)
    local locks=(-H:-SideEffectAnalysisNarrowCalls -H:SideEffectAnalysisLabel=locks -H:+SideEffectAnalysisElideLocks -H:SideEffectAnalysisAssumptions=vm-code,entry-points)
    mode=fields
    case $1 in
        graal)             mode=graal; flags=(-H:-SideEffectAnalysisNarrowCalls) ;;
        fields)            flags=(-H:SideEffectAnalysisKillSets="${KILL_SETS:-build}") ;;
        ceiling)           flags=(-H:SideEffectAnalysisIgnoreEffects=all) ;;
        graalflagscutoff)  mode=graal; flags=(-H:-SideEffectAnalysisNarrowCalls "${allocsens[@]}") ;;
        locks)             mode=locks; flags=("${locks[@]}") ;;
        lockscutoff)       mode=locks; flags=("${locks[@]}" "${allocsens[@]}"
                                              -H:DeadlockWatchdogInterval=120) ;;  # the tool runs for longer than the default ten minutes
        *) echo "unknown configuration $1 (graal, fields, ceiling, locks, graalflagscutoff, lockscutoff)" >&2; return 1 ;;
    esac
    # THREAD_ESCAPE=off: no model of concurrency anywhere (as in graal-native/run.sh), so nothing that removes a lock or reads thread escape
    if [[ ${THREAD_ESCAPE:-on} == off ]]; then
        if [[ $mode == locks ]]; then
            echo "error: configuration $1 removes locks, which needs thread escape (THREAD_ESCAPE=off)" >&2
            return 1
        fi
        flags+=(-H:-SideEffectAnalysisThreadEscape)
    fi
}

build_bundle() {  # configuration, bundle, directory, options for native-image
    local config=$1 nib=$2 dir=$3 mode flags=()
    shift 3
    configure "$config" || return 1
    rm -rf "$dir" && mkdir -p "$dir/$mode"
    provenance "$dir"
    cp "$nib" "$dir/app.nib"
    local start=$SECONDS
    ( cd "$dir" && "$GRAALVM/bin/native-image" -J--upgrade-module-path="$COMPILER" -EHOME -EPATH "$@" \
        -H:+UnlockExperimentalVMOptions -H:+SideEffectAnalysis -H:SideEffectAnalysisOutput="$dir/$mode" \
        -H:SideEffectAnalysisTool="$REPO" -H:SideEffectAnalysisUv="$(command -v uv)" "${flags[@]}" \
        --bundle-apply=app.nib > "$dir/build.log" 2>&1 )
    local status=$?
    echo "$config: exit $status, built in $((SECONDS - start)) s, $(grep -o 'executable, [0-9.]*MiB' "$dir/build.log" | head -1), $(grep -h 'locks removed' "$dir/$mode/timings.txt" 2> /dev/null | head -1)"
    local executable
    executable=$(find "$dir/app.output/default" -maxdepth 1 -type f -executable ! -name '*.so' ! -name '*.debug' 2> /dev/null | head -1)
    [[ -z $executable ]] || ln -sfn "$executable" "$dir/image"
    return $status
}

build_plain() {  # bundle, directory, options for native-image
    local nib=$1 dir=$2
    shift 2
    rm -rf "$dir" && mkdir -p "$dir"
    provenance "$dir"
    cp "$nib" "$dir/app.nib"
    local start=$SECONDS
    ( cd "$dir" && "$GRAALVM/bin/native-image" -J--upgrade-module-path="$COMPILER" -EHOME -EPATH "$@" --bundle-apply=app.nib > "$dir/build.log" 2>&1 )
    local status=$?
    echo "plain: exit $status, built in $((SECONDS - start)) s, $(grep -o 'executable, [0-9.]*MiB' "$dir/build.log" | head -1)"
    local executable
    executable=$(find "$dir/app.output/default" -maxdepth 1 -type f -executable ! -name '*.so' ! -name '*.debug' 2> /dev/null | head -1)
    [[ -z $executable ]] || ln -sfn "$executable" "$dir/image"
    return $status
}
