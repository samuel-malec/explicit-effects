#!/usr/bin/env bash
# Compile the round trip feature
#   ./build.sh            # classes/
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

rm -rf "$HERE/classes"
mkdir -p "$HERE/classes"
"$GRAALVM/bin/javac" -d "$HERE/classes" -cp "$BUILDER" \
    --upgrade-module-path="$COMPILER" --add-modules=jdk.graal.compiler,jdk.internal.vm.ci \
    @"$EXPORTER/exports.args" "${JVMCI_EXPORTS[@]}" \
    "$HERE/EffectsFeature.java" "$EXPORTER/ReadWriteExport.java" "$EXPORTER/GraphExport.java"
echo "built the feature in $HERE/classes"
