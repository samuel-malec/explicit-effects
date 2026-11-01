#!/usr/bin/env bash
# The gate before any load measurement of a Barista application: build graal, kills, locks and lockscutoff one after the other,
# then say what keeps every lock and volatile site of the two locks exports (why_no_locks.py). barista.sh says where the bundles are.
#
#   scripts/frameworks/barista-gate.sh helidon-hello-world micronaut-shopcart
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../graal-native/env.sh"
set +e
for app in "$@"; do
    echo "$(date +%T) start $app"
    "$SCRIPTS/frameworks/barista.sh" "$app" graal kills locks lockscutoff
    for config in locks lockscutoff; do
        echo "== why no lock is removable in $app, $config"
        uv run --project "$REPO" python "$SCRIPTS/sharing/why_no_locks.py" "$HERE/out/barista/$app/$config/locks/export.json"
    done
    echo "$(date +%T) end $app"
done
