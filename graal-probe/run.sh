#!/usr/bin/env bash
# Measure what Graal does to the examples' memory operations, with the graal
# tree's own test harness (GraalCompilerTest), without mx.
#
#   ./run.sh                          # Examples
#   ./run.sh Examples                 # chosen classes from ../graal-export/examples
#   GRAAL_HOME=/path/to/graal ./run.sh
PROBE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# G, UPGRADE_MP, MODULE_PATH, ADD_MODULES and EXPORTS: the same module and JVMCI
# arrangement graal-export runs the analysis with.
source "$PROBE/../graal-export/env.sh"

EXAMPLES=("$@")
if [[ ${#EXAMPLES[@]} -eq 0 ]]; then
    EXAMPLES=(Examples)
fi

JUNIT=$(find "$HOME/.mx/cache" -path "*/JUNIT_*/junit.jar" 2>/dev/null | head -1)
HAMCREST=$(find "$HOME/.mx/cache" -path "*/HAMCREST_*/hamcrest.jar" 2>/dev/null | head -1)
if [[ -z "$JUNIT" || -z "$HAMCREST" ]]; then
    echo "error: junit.jar or hamcrest.jar not found under ~/.mx/cache" >&2
    exit 1
fi
for jar in graal-test.jar graal-test-runtime.jar; do
    if [[ ! -f "$G/compiler/mxbuild/dists/$jar" ]]; then
        echo "error: missing $G/compiler/mxbuild/dists/$jar -- build the compiler's tests in the graal tree" >&2
        exit 1
    fi
done

CP="$G/compiler/mxbuild/dists/graal-test.jar"
CP="$CP:$G/compiler/mxbuild/dists/graal-test-runtime.jar"
CP="$CP:$G/sdk/mxbuild/dists/collections.jar"
CP="$CP:$G/sdk/mxbuild/dists/nativeimage.jar"
CP="$CP:$G/sdk/mxbuild/dists/word.jar"
CP="$CP:$JUNIT:$HAMCREST:$PROBE/classes"

# Rebuilt every run: stale classes would report numbers from an older probe.
rm -rf "$PROBE/classes"
mkdir -p "$PROBE/classes"

# Every jdk.graal.compiler package exported to the unnamed module, and opened
# for running, the way mx unittest sets up the test classpath. Regenerated
# every run, so a rebuilt graal tree cannot leave the list stale.
python3 - "$G/compiler/mxbuild/dists/graal.jar" "$PROBE/classes" <<'PY'
import os, sys, zipfile
jar, out = sys.argv[1], sys.argv[2]
packages = sorted({os.path.dirname(n).replace("/", ".") for n in zipfile.ZipFile(jar).namelist()
                   if n.endswith(".class") and not n.startswith("META-INF") and "/" in n})
exports = [f"--add-exports=jdk.graal.compiler/{p}=ALL-UNNAMED" for p in packages]
opens = [f"--add-opens=jdk.graal.compiler/{p}=ALL-UNNAMED" for p in packages]
open(os.path.join(out, "compile.args"), "w").write("\n".join(exports) + "\n")
open(os.path.join(out, "runtime.args"), "w").write("\n".join(exports + opens) + "\n")
PY

SOURCES=("$PROBE"/*.java)
for name in "${EXAMPLES[@]}"; do
    SOURCES+=("$PROBE/../graal-export/examples/$name.java")
done
if ! javac -nowarn -cp "$CP" @"$PROBE/classes/compile.args" "${EXPORTS[@]}" \
        --upgrade-module-path="$UPGRADE_MP" --module-path="$MODULE_PATH" \
        --add-modules="$ADD_MODULES,jdk.graal.compiler" \
        -d "$PROBE/classes" "${SOURCES[@]}"; then
    echo "error: compiling the probe failed -- not running" >&2
    exit 1
fi

LIST=$(IFS=,; echo "${EXAMPLES[*]}")
exec java -XX:+UnlockExperimentalVMOptions -XX:+EnableJVMCI \
    --upgrade-module-path="$UPGRADE_MP" --module-path="$MODULE_PATH" \
    --add-modules="$ADD_MODULES" "${EXPORTS[@]}" @"$PROBE/classes/runtime.args" \
    -Dprobe.examples="$LIST" -cp "$CP" \
    org.junit.runner.JUnitCore probe.MemoryProbe
