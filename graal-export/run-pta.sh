#!/usr/bin/env bash
# Run the analyzer's own main (reports only). See run-dump.sh for the useful one.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

exec java \
  -XX:+UnlockExperimentalVMOptions -XX:+EnableJVMCI \
  -Dcom.oracle.graal.pointsto.standalone.vmaccess.name=host \
  --upgrade-module-path="$UPGRADE_MP" \
  --module-path="$MODULE_PATH" \
  --add-modules="$ADD_MODULES" \
  "${EXPORTS[@]}" @"$HERE/exports.args" \
  -cp "$CP" \
  com.oracle.graal.pointsto.standalone.PointsToAnalyzer \
  Examples \
  -H:StandaloneAnalysisTargetAppCP="$HERE/classes" \
  -H:StandaloneAnalysisReportsPath="$HERE/out" \
  "$@"
