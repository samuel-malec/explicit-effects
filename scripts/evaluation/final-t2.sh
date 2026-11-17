#!/usr/bin/env bash
# The final run T2 (17 Nov 2026; the user: "run the final evaluation with the stock arm", scope "builds + size of all, run time on 3"):
# one tool + fork pair, three arms: `stock` (the same builder, the feature off), `graal` (the feature on, nothing narrowed) and `fields`
# (every call narrowed to what its callees write, the kill sets worked out in the image builder: -H:SideEffectAnalysisKillSets=build).
# No model of concurrency (THREAD_ESCAPE=off). One build at a time, the arms taking turns inside a round, rounds one after the other.
#
#   phase threeprograms  AWFY (4 rounds, -O3 with trivial inlining), PetClinic (3), javac (3): build time, peak RSS, size, then run time
#                        with the machine quiet (programs/awfy/time.py, petclinic_load.py, time_javac.py), the first graal image twice (A/A)
#   phase renaissance    the 15 benchmarks, 3 rounds of stock, graal and fields at -O3, build time, peak RSS and size only
#   phase barista        the 11 applications, 3 rounds of stock, graal and fields, build time, peak RSS and size only
#
# Results: ~/eval/final-t2/ (log, tables, summary.txt, done); the builds of the three programs are in graal-native/out/{awfy-t2-*,
# petclinic-t2r*,javac-cost-*}, those of Renaissance and Barista in graal-native/out/final-t2/<suite>/<program>-r<k>/<arm>/. The javac
# builds of 14 Nov (option 2) are moved to out/option2-javac/ first, because cost-javac.sh names its builds without a tag.
# Run on pontos04 alone, from ~/explicit-effects.
export JAVA_HOME=$HOME/.mx/jdks/labsjdk-ce-latest-jvmci-25.4-b23_amd64
export PATH=$JAVA_HOME/bin:$HOME/mx:$HOME/.local/bin:$PATH
export THREAD_ESCAPE=off
unset KILL_SETS  # the scripts' default, build
RESULTS=${RESULTS:-$HOME/eval/final-t2}
mkdir -p "$RESULTS"
source "$HOME/explicit-effects/graal-native/env.sh"
set +e +u
source "$HERE/provenance.sh"
source "$SCRIPTS/frameworks/bundle.sh"
cd "$HERE" || exit 1
uv sync -q --project "$REPO"

stamp() { echo "== $(date -Is) $*"; }
wait_quiet() {  # the timings are of a machine with nothing else running
    while [[ $(cut -d. -f1 /proc/loadavg) -ge 2 ]]; do sleep 15; done
    echo "machine quiet at $(date +%T), load $(cut -d' ' -f1-3 /proc/loadavg)"
}
fail() { stamp "FAILED: $*"; exit 1; }

stamp "start; tool $(sed -n 2p "$REPO/.synced-from"); fork $(sed -n 2p "$G/.synced-from")"
stamp "builder home: $(readlink -f "$GRAALVM")"
stamp "THREAD_ESCAPE=$THREAD_ESCAPE KILL_SETS=${KILL_SETS:-<unset: build>}"
wait_quiet

only=${ONLY_PHASES:-threeprograms renaissance barista}

# ---------------------------------------------------------------- AWFY, PetClinic, javac
if [[ " $only " == *" threeprograms "* ]]; then
    stamp "AWFY: ${AWFY_BUILDS:-4} rounds"
    for n in $(seq 1 "${AWFY_BUILDS:-4}"); do
        ONLY="graal fields" TAG="t2-$n" EXTRA="-O3 -H:+AOTTrivialInline" ./run.sh Awfy > "out/awfy-t2-$n.log" 2>&1 || { tail -30 "out/awfy-t2-$n.log"; fail "AWFY round $n graal/fields"; }
        grep -E "built in|FAILED|rror" "out/awfy-t2-$n.log"
        ONLY=graal TAG="t2-stock$n" EXTRA="-O3 -H:+AOTTrivialInline -H:-SideEffectAnalysis" ./run.sh Awfy > "out/awfy-t2-stock$n.log" 2>&1 || { tail -30 "out/awfy-t2-stock$n.log"; fail "AWFY round $n stock"; }
        grep -E "built in|FAILED|rror" "out/awfy-t2-stock$n.log"
    done
    n=${AWFY_BUILDS:-4}
    wait_quiet
    images=(--image "graal-1=out/awfy-t2-1/graal/awfy-t2-1" --image "graal-1-again=out/awfy-t2-1/graal/awfy-t2-1")
    for k in $(seq 2 "$n"); do images+=(--image "graal-$k=out/awfy-t2-$k/graal/awfy-t2-$k"); done
    for k in $(seq 1 "$n"); do images+=(--image "fields-$k=out/awfy-t2-$k/fields/awfy-t2-$k"); done
    for k in $(seq 1 "$n"); do images+=(--image "stock-$k=out/awfy-t2-stock$k/graal/awfy-t2-stock$k"); done
    stamp "AWFY run time (the first graal image twice is the noise)"
    taskset -c 4-7 uv run --project "$REPO" python "$REPO/programs/awfy/time.py" "${images[@]}" --runs 5 2> /dev/null | tee "$RESULTS/awfy-time.txt"
    counts=()
    for k in $(seq 1 "$n"); do counts+=("out/awfy-t2-$k/graal/counts.txt" "out/awfy-t2-$k/fields/counts.txt"); done
    stamp "AWFY loads left"
    uv run --project "$REPO" python "$SCRIPTS/evaluation/counts.py" "${counts[@]}" | tee "$RESULTS/awfy-counts.txt"

    PETCLINIC=${PETCLINIC:-$HOME/eval/petclinic}
    NIB=$(ls "$PETCLINIC"/app/*.nib)
    stamp "PetClinic: ${PETCLINIC_ROUNDS:-3} rounds"
    for r in $(seq 1 "${PETCLINIC_ROUNDS:-3}"); do
        TAG=t2r$r "$SCRIPTS/frameworks/petclinic.sh" graal fields || fail "PetClinic round $r"
        build_plain "$NIB" "$HERE/out/petclinic-t2r$r/plain" --enable-monitoring=jmxserver -H:ConfigurationFileDirectories="$SCRIPTS/frameworks/petclinic" || fail "PetClinic round $r plain"
    done
    p=$HERE/out
    images=(--image "graal-1=$p/petclinic-t2r1/graal/image" --image "graal-1-again=$p/petclinic-t2r1/graal/image")
    for k in $(seq 2 "${PETCLINIC_ROUNDS:-3}"); do images+=(--image "graal-$k=$p/petclinic-t2r$k/graal/image"); done
    for k in $(seq 1 "${PETCLINIC_ROUNDS:-3}"); do images+=(--image "fields-$k=$p/petclinic-t2r$k/fields/image"); done
    for k in $(seq 1 "${PETCLINIC_ROUNDS:-3}"); do images+=(--image "stock-$k=$p/petclinic-t2r$k/plain/image"); done
    wait_quiet
    stamp "PetClinic under load (the first graal image twice is the noise)"
    python3 "$SCRIPTS/frameworks/petclinic_load.py" "${images[@]}" --runs 5 --seconds 30 --warmup 15 --clients 16 | tee "$RESULTS/petclinic-load.txt"

    o=$HERE/out
    rounds=${JAVAC_ROUNDS:-3}
    mkdir -p "$o/option2-javac"
    for d in "$o"/javac-cost-graal-r* "$o"/javac-cost-fields-r* "$o"/javac-cost-stock-r*; do  # the builds of 14 Nov: moved, not deleted
        [[ -d $d ]] && mv "$d" "$o/option2-javac/"
    done
    stamp "javac: $rounds rounds of graal and fields (cost-javac.sh), then $rounds stock builds"
    REPEATS=$rounds CONFIGS="graal fields" "$SCRIPTS/evaluation/cost-javac.sh" || fail "cost-javac.sh"
    for k in $(seq 1 "$rounds"); do
        dir=$o/javac-cost-stock-r$k
        rm -rf "$dir" && mkdir -p "$dir/stock"
        start=$SECONDS
        mx -p "$G/substratevm" javac-image > "$dir/stock.log" 2>&1 || { tail -30 "$dir/stock.log"; fail "javac stock round $k"; }
        image=$(grep -oE '/[^ ]*/javac \(executable' "$dir/stock.log" | cut -d' ' -f1)
        cp "$image" "$dir/stock/javac"
        echo "javac-cost-stock-r$k: built in $((SECONDS - start)) s"
    done
    stamp "loads left in javac's methods"
    uv run --project "$REPO" python "$SCRIPTS/evaluation/counts.py" "$o/javac-cost-graal-r1/graal/counts.txt" "$o/javac-cost-fields-r1/fields/counts.txt" | tee "$RESULTS/javac-counts.txt"
    rm -rf "$o/javac-aa-copy" && mkdir -p "$o/javac-aa-copy/graal" && cp "$o/javac-cost-graal-r1/graal/javac" "$o/javac-aa-copy/graal/javac"
    builds=("$o"/javac-cost-graal-r{1..3} "$o/javac-aa-copy" "$o"/javac-cost-fields-r{1..3} "$o"/javac-cost-stock-r{1..3})
    [[ $rounds == 3 ]] || builds=()
    if [[ ${#builds[@]} -gt 0 ]]; then
        wait_quiet
        stamp "time javac takes to compile AWFY's sources (the A/A copy is the first image again)"
        taskset -c 4-7 uv run --project "$REPO" python "$SCRIPTS/evaluation/time_javac.py" "${builds[@]}" --runs 10 | tee "$RESULTS/javac-time.txt"
    fi
fi

# ---------------------------------------------------------------- Renaissance and Barista: builds only
suite_builds() {  # suite, program, bundle, rounds, options for native-image
    local suite=$1 name=$2 nib=$3 rounds=$4 dir config r
    shift 4
    [[ -f $nib ]] || { echo "$suite/$name: MISSING $nib"; return; }
    for r in $(seq 1 "$rounds"); do
        for config in graal fields stock; do
            dir="$HERE/out/final-t2/$suite/$name-r$r/$config"
            echo -n "$suite/$name r$r $config: "
            if [[ $config == stock ]]; then
                build_plain "$nib" "$dir" "$@"
            else
                build_bundle "$config" "$nib" "$dir" "$@"
            fi
        done
    done
}

if [[ " $only " == *" renaissance "* ]]; then
    RENAISSANCE=${RENAISSANCE:-$HOME/eval/renaissance}
    stamp "Renaissance: ${RENAISSANCE_ROUNDS:-3} rounds of stock, graal and fields at -O3"
    for benchmark in ${RENAISSANCE_ONLY:-rx-scrabble scala-kmeans scrabble scala-doku dotty finagle-http future-genetic mnemonics par-mnemonics philosophers reactors scala-stm-bench7 akka-uct finagle-chirper fj-kmeans}; do
        wait_quiet > /dev/null
        suite_builds renaissance "$benchmark" "$RENAISSANCE/$benchmark/$benchmark.nib" "${RENAISSANCE_ROUNDS:-3}" -O3
    done
fi

if [[ " $only " == *" barista "* ]]; then
    BARISTA=${BARISTA:-$HOME/eval/barista}
    stamp "Barista: ${BARISTA_ROUNDS:-3} rounds of stock, graal and fields"
    for app in ${BARISTA_ONLY:-vanilla-hello-world vertx-hello-world micronaut-hello-world micronaut-shopcart micronaut-similarity helidon-hello-world dropwizard-hello-world play-scala-hello-world ktor-hello-world spring-hello-world spring-petclinic}; do
        wait_quiet > /dev/null
        suite_builds barista "$app" "$BARISTA/$app/$app.nib" "${BARISTA_ROUNDS:-3}"
    done
fi

stamp "summary"
python3 "$SCRIPTS/evaluation/summarize_builds.py" "$HERE/out" | tee "$RESULTS/summary.txt"
stamp "done"
touch "$RESULTS/done"
