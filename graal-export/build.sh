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
if ! javac -XDstringConcat=inline ${JAVAC_CP:+-cp "$JAVAC_CP"} -d "$HERE/classes" "${SOURCES[@]}"; then
    echo "error: compiling the target failed -- not continuing" >&2
    echo "       if it imports a library, put the jar on JAVAC_CP here and on TARGET_CP for run-dump.sh" >&2
    exit 1
fi
if ! javac -cp "$CP" @"$HERE/jvmci.args" -d "$HERE" "$HERE/DumpEffects.java"; then
    echo "error: compiling DumpEffects.java failed" >&2
    exit 1
fi

echo "built driver + analysis target in classes/:"
find "$HERE/classes" -name "*.class" | sed "s|$HERE/classes/|  |"
