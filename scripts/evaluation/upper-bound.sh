#!/usr/bin/env bash
# What keeps methods opaque on large programs, and the most loads that more precise kill sets could remove.
#
#   phase exports  one build of PetClinic and of three Renaissance benchmarks (default scrabble, scala-doku, philosophers) with the tool's kill sets
#                  (-H:SideEffectAnalysisKillSets=tool), only for the export.json they leave: out/upper-bound/<program>/tool/fields/export.json
#   phase none     one build of AWFY (-O3, trivial inlining), PetClinic and the 15 Renaissance benchmarks (-O3) with every call killing only the VM's
#                  state (-H:SideEffectAnalysisKillSets=none: an upper bound, never sound; the images are never run, only their counts.txt is read):
#                  out/upper-bound/<program>/none/fields/counts.txt
#   phase analyze  on each export diagnostics.ceiling (what each effect left out frees, and what one effect alone still holds), diagnostics.unresolved
#                  (the unresolved calls and the calls of methods without facts, sorted) and diagnostics.blockers --roots (the methods the program's
#                  methods become opaque through), and upper_bound.py: loads of `graal`, `fields` (the final run's builds, out/awfy-t2-1, out/petclinic-t2r1,
#                  out/final-t2/renaissance/<b>-r1) and `none`. Reads only; nothing is built.
#
# Results: ~/eval/upper-bound/ (log, one file per program and analysis, table.txt, done). No model of concurrency (THREAD_ESCAPE=off), as the final run.
# Run on pontos04 alone, from ~/explicit-effects, with the fork whose builder has the `none` mode.
#   ONLY_PHASES="none analyze" scripts/evaluation/upper-bound.sh        # which phases; EXPORT_BENCHMARKS and NONE_BENCHMARKS choose the Renaissance ones
export JAVA_HOME=$HOME/.mx/jdks/labsjdk-ce-latest-jvmci-25.4-b23_amd64
export PATH=$JAVA_HOME/bin:$HOME/mx:$HOME/.local/bin:$PATH
export THREAD_ESCAPE=off
unset KILL_SETS
RESULTS=${RESULTS:-$HOME/eval/upper-bound}
mkdir -p "$RESULTS"
source "$HOME/explicit-effects/graal-native/env.sh"
set +e +u
source "$HERE/provenance.sh"
source "$SCRIPTS/frameworks/bundle.sh"
cd "$HERE" || exit 1
uv sync -q --project "$REPO"

stamp() { echo "== $(date -Is) $*"; }
wait_quiet() {
    while [[ $(cut -d. -f1 /proc/loadavg) -ge 2 ]]; do sleep 15; done
    echo "machine quiet at $(date +%T), load $(cut -d' ' -f1-3 /proc/loadavg)"
}

stamp "start; tool $(sed -n 2p "$REPO/.synced-from"); fork $(sed -n 2p "$G/.synced-from")"
stamp "builder home: $(readlink -f "$GRAALVM")"
wait_quiet

only=${ONLY_PHASES:-exports none analyze}
UB=$HERE/out/upper-bound
PETCLINIC=${PETCLINIC:-$HOME/eval/petclinic}
RENAISSANCE=${RENAISSANCE:-$HOME/eval/renaissance}
PETCLINIC_OPTIONS=(--enable-monitoring=jmxserver -H:ConfigurationFileDirectories="$SCRIPTS/frameworks/petclinic")
ALL_RENAISSANCE="rx-scrabble scala-kmeans scrabble scala-doku dotty finagle-http future-genetic mnemonics par-mnemonics philosophers reactors scala-stm-bench7 akka-uct finagle-chirper fj-kmeans"
EXPORT_BENCHMARKS=${EXPORT_BENCHMARKS:-scrabble scala-doku philosophers}
NONE_BENCHMARKS=${NONE_BENCHMARKS:-$ALL_RENAISSANCE}

if [[ " $only " == *" exports "* ]]; then
    stamp "exports: PetClinic and $EXPORT_BENCHMARKS with the tool's kill sets"
    echo -n "petclinic tool: "
    KILL_SETS=tool build_bundle fields "$(ls "$PETCLINIC"/app/*.nib)" "$UB/petclinic/tool" "${PETCLINIC_OPTIONS[@]}"
    for b in $EXPORT_BENCHMARKS; do
        wait_quiet > /dev/null
        echo -n "$b tool: "
        KILL_SETS=tool build_bundle fields "$RENAISSANCE/$b/$b.nib" "$UB/$b/tool" -O3
    done
fi

if [[ " $only " == *" none "* ]]; then
    stamp "none: every call kills only the VM's state (an upper bound, not sound; counts only)"
    ONLY=fields TAG=ub-none KILL_SETS=none EXTRA="-O3 -H:+AOTTrivialInline" ./run.sh Awfy > "$RESULTS/awfy-none.log" 2>&1
    grep -E "built in|FAILED|rror" "$RESULTS/awfy-none.log"
    wait_quiet > /dev/null
    echo -n "petclinic none: "
    KILL_SETS=none build_bundle fields "$(ls "$PETCLINIC"/app/*.nib)" "$UB/petclinic/none" "${PETCLINIC_OPTIONS[@]}"
    for b in $NONE_BENCHMARKS; do
        wait_quiet > /dev/null
        echo -n "$b none: "
        KILL_SETS=none build_bundle fields "$RENAISSANCE/$b/$b.nib" "$UB/$b/none" -O3
    done
fi

if [[ " $only " == *" analyze "* ]]; then
    stamp "analyze"
    run() { uv run --project "$REPO" python "$@"; }
    for dir in "$UB"/*/tool; do
        name=$(basename "$(dirname "$dir")")
        export_json=$dir/fields/export.json
        [[ -f $export_json ]] || { echo "$name: no export"; continue; }
        run -m diagnostics.ceiling "$export_json" > "$RESULTS/$name-ceiling.txt" 2>&1
        run -m diagnostics.unresolved "$export_json" --top 20 > "$RESULTS/$name-unresolved.txt" 2>&1
        run -m diagnostics.blockers "$export_json" --roots 25 > "$RESULTS/$name-blockers.txt" 2>&1
        echo "$name: $(head -1 "$RESULTS/$name-ceiling.txt")"
    done
    specs=("awfy=out/awfy-t2-1/graal/counts.txt,out/awfy-t2-1/fields/counts.txt,out/awfy-ub-none/fields/counts.txt")
    if [[ -f $UB/petclinic/none/fields/counts.txt ]]; then
        specs+=("petclinic=out/petclinic-t2r1/graal/graal/counts.txt,out/petclinic-t2r1/fields/fields/counts.txt,$UB/petclinic/none/fields/counts.txt")
    fi
    for b in $ALL_RENAISSANCE; do
        [[ -f $UB/$b/none/fields/counts.txt ]] || continue
        specs+=("$b=out/final-t2/renaissance/$b-r1/graal/graal/counts.txt,out/final-t2/renaissance/$b-r1/fields/fields/counts.txt,$UB/$b/none/fields/counts.txt")
    done
    run "$SCRIPTS/evaluation/upper_bound.py" "${specs[@]}" | tee "$RESULTS/table.txt"
fi

stamp "done"
touch "$RESULTS/done"
