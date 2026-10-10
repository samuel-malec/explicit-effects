#!/usr/bin/env bash
# What build.sh and run.sh share. graal-export/env.sh picks the graal tree
# (GRAAL_HOME, or the graal submodule once built); GRAALVM_HOME is the GraalVM
# built from it.
# graal-export's environment: the JVMCI exports, and the standalone analyzer,
# which the exporter's main needs to compile but never runs in a build.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../graal-export/env.sh"
set -euo pipefail
EXPORTER="$HERE"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
GRAALVM=${GRAALVM_HOME:-$G/sdk/latest_graalvm_home}
# The compiler with kill sets on invokes: built in the graal tree with
# `mx build --dependencies GRAAL`, and put in place of the GraalVM's own.
COMPILER="$G/compiler/mxbuild/dists/graal.jar"
BUILDER=$(ls "$GRAALVM"/lib/svm/builder/*.jar | tr '\n' ':')$G/substratevm/mxbuild/dists/standalone-pointsto.jar

for file in "$GRAALVM/bin/native-image" "$COMPILER"; do
    if [[ ! -e "$file" ]]; then
        echo "error: missing $file" >&2
        exit 1
    fi
done

JVMCI_EXPORTS=("${EXPORTS[@]}")
# What the feature and the exporter use of the builder, for the image's class path.
BUILDER_EXPORTS=()
for package in com.oracle.svm.core.feature com.oracle.svm.hosted com.oracle.svm.hosted.meta; do
    BUILDER_EXPORTS+=("--add-exports=org.graalvm.nativeimage.builder/$package=ALL-UNNAMED")
done
for package in com.oracle.graal.pointsto com.oracle.graal.pointsto.flow com.oracle.graal.pointsto.flow.context.object \
        com.oracle.graal.pointsto.meta com.oracle.graal.pointsto.phases com.oracle.graal.pointsto.typestate; do
    BUILDER_EXPORTS+=("--add-exports=org.graalvm.nativeimage.pointsto/$package=ALL-UNNAMED")
done
