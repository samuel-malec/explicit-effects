#!/usr/bin/env bash
# Compile the Are We Fast Yet benchmarks, from the are-we-fast-yet submodule,
# and the driver that runs them all, into a directory (default: classes/).
#
#   ./build.sh [out]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUITE="$(dirname "$(dirname "$HERE")")/are-we-fast-yet/benchmarks/Java/src"
OUT=${1:-$HERE/classes}

if [[ ! -d "$SUITE" ]]; then
    echo "error: no benchmarks at $SUITE (git submodule update --init)" >&2
    exit 1
fi
rm -rf "$OUT"
mkdir -p "$OUT"
javac -nowarn -d "$OUT" $(find "$SUITE" -name '*.java') "$HERE/Awfy.java"
