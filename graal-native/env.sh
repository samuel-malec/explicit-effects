#!/usr/bin/env bash
# What run.sh needs. graal-export/env.sh picks the graal tree (GRAAL_HOME, or
# the graal submodule once built); GRAALVM_HOME is the GraalVM built from it,
# with mx build in its substratevm: its image builder carries the side-effect
# analysis (SideEffectAnalysisFeature) and the exporter (PointsToExport).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../graal-export/env.sh"
set -euo pipefail
EXPORT_DIR="$HERE"  # graal-export, whose corpus run.sh builds
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
SCRIPTS="$REPO/scripts"  # the helpers; nothing in this directory uses them
GRAALVM=${GRAALVM_HOME:-$G/sdk/latest_graalvm_home}
# The compiler with kill sets on invokes: built in the graal tree with
# `mx build --dependencies GRAAL`, and put in place of the GraalVM's own.
COMPILER="$G/compiler/mxbuild/dists/graal.jar"

for file in "$GRAALVM/bin/native-image" "$COMPILER"; do
    if [[ ! -e "$file" ]]; then
        echo "error: missing $file" >&2
        exit 1
    fi
done
