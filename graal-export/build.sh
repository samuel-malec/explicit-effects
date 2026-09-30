#!/usr/bin/env bash
#   ./build.sh                     # compiles Demo.java (the two examples)
#   ./build.sh path/to/My.java ...  # compiles your own program instead
#
# JAVAC_CP adds a compile classpath for the target, e.g.
#   JAVAC_CP=$G/sdk/mxbuild/dists/collections.jar ./build.sh Bench.java
#
# Sources land in classes/, which is what run-dump.sh analyses.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

SOURCES=("$@")
if [[ ${#SOURCES[@]} -eq 0 ]]; then
    SOURCES=("$HERE/Demo.java")
fi

rm -rf "$HERE/classes"
javac ${JAVAC_CP:+-cp "$JAVAC_CP"} -d "$HERE/classes" "${SOURCES[@]}"
javac -cp "$CP" @"$HERE/jvmci.args" -d "$HERE" "$HERE/DumpEffects.java"

echo "built driver + analysis target in classes/:"
find "$HERE/classes" -name "*.class" | sed "s|$HERE/classes/|  |"
