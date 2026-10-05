#!/usr/bin/env bash
#./build.sh path/to/My.java
#DUMP_JSON=out/my.json ./run-dump.sh my.pkg.Main

# JAVAC_CP adds a compile classpath for the target, e.g.
#   JAVAC_CP=$G/sdk/mxbuild/dists/collections.jar ./build.sh path/to/My.java
#
# Sources land in classes/, which is what run-dump.sh analyses.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

SOURCES=("$@")
if [[ ${#SOURCES[@]} -eq 0 ]]; then
    SOURCES=("$HERE/examples/Examples.java")
fi

rm -rf "$HERE/classes"
if ! javac -XDstringConcat=inline ${JAVAC_CP:+-cp "$JAVAC_CP"} -d "$HERE/classes" "${SOURCES[@]}"; then
    echo "error: compiling the target failed -- not continuing" >&2
    echo "       if it imports a library, put the jar on JAVAC_CP here and on TARGET_CP for run-dump.sh" >&2
    exit 1
fi
# The driver is compiled with the module flags run-dump.sh runs it with, so it
# builds against the repo's jdk.graal.compiler rather than the JDK's own older
# copy: GraphExport uses the compiler's node classes directly.
if ! javac -cp "$CP" --upgrade-module-path="$UPGRADE_MP" --module-path="$MODULE_PATH" \
        --add-modules="$ADD_MODULES,jdk.graal.compiler,jdk.graal.compiler.options" \
        "${EXPORTS[@]}" @"$HERE/exports.args" \
        -d "$HERE" "$HERE/ReadWriteExport.java" "$HERE/GraphExport.java"; then
    echo "error: compiling the driver failed" >&2
    exit 1
fi

echo "built driver + analysis target in classes/:"
find "$HERE/classes" -name "*.class" | sed "s|$HERE/classes/|  |"
