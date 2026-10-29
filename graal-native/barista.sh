#!/usr/bin/env bash
# An application of the Barista benchmark suite (github.com/barista-benchmarks/barista, release 0.6.6), built with the side-effect
# analysis, one image per configuration, into out/barista/<app>/<config>/. Barista builds the application's Native Image bundle
# (benchmarks/<app>/target/<app>-<version>.nib, made on the laptop with `./build <app>`, which only writes the bundle: `--bundle-create=…,dry-run`);
# this applies it with the builder of the graal tree.
#
#   graal-native/barista.sh vanilla-hello-world graal locks lockscutoff
#   TAG=why EXTRA="-J-Dsideeffects.explainSharing=Http1xServerConnection" graal-native/barista.sh vertx-hello-world lockscutoff
#
# TAG puts the output in out/barista/<app>-<TAG>/, EXTRA gives native-image more options (as in run.sh).
# The configurations are in bundle.sh. The assets are in $BARISTA (default ~/eval/barista): <app>/<app>.nib and <app>/workloads/
# (the app's directory in the suite).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
source "$HERE/provenance.sh"
source "$HERE/bundle.sh"
set +e
BARISTA=${BARISTA:-$HOME/eval/barista}
[[ $# -gt 1 ]] || { echo "usage: barista.sh <app> <graal|kills|locks|graalflagscutoff|lockscutoff|ceiling>…" >&2; exit 2; }
APP=$1
shift
NIB="$BARISTA/$APP/$APP.nib"
[[ -f $NIB ]] || { echo "error: missing $NIB" >&2; exit 1; }
OUT="$HERE/out/barista/$APP${TAG:+-$TAG}"
mkdir -p "$OUT"
read -r -a EXTRA_OPTIONS <<< "${EXTRA:-}"

for config in "$@"; do
    build_bundle "$config" "$NIB" "$OUT/$config" "${EXTRA_OPTIONS[@]}"
done
