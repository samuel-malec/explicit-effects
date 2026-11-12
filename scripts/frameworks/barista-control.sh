#!/usr/bin/env bash
# The control for a Barista application whose image does not start or whose build fails: the same bundle applied by the same builder with the
# feature (graal: loaded, nothing narrowed, THREAD_ESCAPE=off as in the no-model run) and without it (plain: build_plain of bundle.sh), into
# out/barista-control/<app>-r1/<config>/, the layout barista_run.py reads with --builds and --configs.
#
#   scripts/frameworks/barista-control.sh spring-hello-world dropwizard-hello-world
#   python3 scripts/frameworks/barista_run.py --builds graal-native/out/barista-control --configs graal,plain --rounds 1 --apps spring-hello-world
#
# The builder is the one of the graal tree now, which need not be the one of the builds the control is for: both arms are built here, so the pair
# differs in the feature only. The assets are in $BARISTA (default ~/eval/barista), as for barista.sh.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../graal-native/env.sh"
source "$HERE/provenance.sh"
source "$SCRIPTS/frameworks/bundle.sh"
set +e
BARISTA=${BARISTA:-$HOME/eval/barista}

for app in "$@"; do
    nib="$BARISTA/$app/$app.nib"
    [[ -f $nib ]] || { echo "error: missing $nib" >&2; continue; }
    out="$HERE/out/barista-control/$app-r1"
    echo "$(date +%T) $app"
    THREAD_ESCAPE=off build_bundle graal "$nib" "$out/graal"
    build_plain "$nib" "$out/plain"
done
echo "$(date +%T) done"
