#!/usr/bin/env bash
# One Native Image bundle per Renaissance benchmark, made by mx: its agent run (the reflection and resource configuration) and an image
# build by the GraalVM of the fork's build, with --bundle-create so that the build arguments, the standalone jar and the agent's files
# are written to <benchmark>.nib. Our builder applies the bundles afterwards (bundle.sh), as for the Barista and PetClinic bundles.
# The GraalVM home must hold libnative-image-agent.so, which mx skips unless asked: the build and this call both pass
# --native-images=lib:native-image-agent (the home's name depends on it).
# Run on pontos04:  renaissance-bundles.sh scrabble akka-uct dotty
export JAVA_HOME=$HOME/.mx/jdks/labsjdk-ce-latest-jvmci-25.4-b23_amd64
export PATH=$JAVA_HOME/bin:$HOME/mx:$HOME/.local/bin:$PATH
OUT=$HOME/eval/renaissance
VERSION=0.16.0
for b in "$@"; do
    rm -rf "$OUT/$b" && mkdir -p "$OUT/$b"
    started=$(date +%s)
    (cd "$HOME/graal/substratevm" && mx --native-images=lib:native-image-agent benchmark "renaissance-native-image:$b" --bench-suite-version=$VERSION -- \
        --jvm=native-image --jvm-config=default \
        -Dnative-image.benchmark.stages=agent,image \
        "-Dnative-image.benchmark.extra-image-build-argument=--bundle-create=$OUT/$b/$b.nib") > "$OUT/$b/mx.log" 2>&1
    status=$?
    echo "$(date +%T) $b: mx exit $status after $(( $(date +%s) - started )) s, bundle $(ls -la "$OUT/$b/$b.nib" 2>/dev/null | awk '{print $5}') bytes"
done
