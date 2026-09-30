#!/usr/bin/env bash
# Dump per-method field read/write sets from Native Image's points-to analysis.
#
#   ./run-dump.sh                        # entry class Demo
#   ./run-dump.sh my.pkg.Main            # your own entry class
#   ./run-dump.sh my.pkg.Main -H:...     # plus extra analyzer options
#
# Env:
#   GRAAL_HOME   graal checkout (default /home/xmalec/graal)
#   TARGET_CP    classes to analyse (default ./classes)
#   DUMP_FILTER  report only classes under this prefix (default: everything
#                that isn't a JDK/Graal platform class)
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

ENTRY=Demo
if [[ $# -gt 0 && "$1" != -* ]]; then
    ENTRY="$1"
    shift
fi

exec java \
  -XX:+UnlockExperimentalVMOptions -XX:+EnableJVMCI \
  -Dcom.oracle.graal.pointsto.standalone.vmaccess.name=host \
  -Ddump.filter="${DUMP_FILTER:-}" \
  -Ddump.json="${DUMP_JSON:-}" \
  --upgrade-module-path="$UPGRADE_MP" \
  --module-path="$MODULE_PATH" \
  --add-modules="$ADD_MODULES" \
  "${EXPORTS[@]}" @"$HERE/exports.args" \
  -cp "$CP:$HERE" \
  DumpEffects \
  "$ENTRY" \
  -H:StandaloneAnalysisTargetAppCP="${TARGET_CP:-$HERE/classes}" \
  -H:StandaloneAnalysisReportsPath="$HERE/out" \
  "$@"
