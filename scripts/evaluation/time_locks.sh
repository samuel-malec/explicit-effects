#!/usr/bin/env bash
# What removing the locks and making the volatile accesses ordinary is worth at run time: a program of the
# corpus with a Run<Name> main that prints the best time of each shape on the error stream (LockShapes,
# VolatileShapes), built as the image Graal makes (graal) and as the image that removes what thread escape
# says can go (locks), each run REPS times, taking turns, pinned to four cores. Time on pontos04 only.
#
#   ./time_locks.sh LockShapes
#   REPS=9 ./time_locks.sh VolatileShapes
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../graal-native/env.sh"

PROGRAM=${1:?usage: time_locks.sh <LockShapes|VolatileShapes>}
REPS=${REPS:-7}
NAME=$(echo "$PROGRAM" | tr '[:upper:]' '[:lower:]')-time
EXTRA="-O3 -H:+AOTTrivialInline" ONLY="graal locks" TAG=time "$HERE/run.sh" "$PROGRAM" || exit 1
OUT="$HERE/out/$NAME"
declare -A TIMES
for r in $(seq 1 "$REPS"); do
    for mode in graal locks; do
        TIMES[$mode]+="$(taskset -c 4-7 "$OUT/$mode/$NAME" 2>&1 > /dev/null | tail -1)"$'\n'
    done
done
for mode in graal locks; do
    printf '%s' "${TIMES[$mode]}" > "$OUT/$mode/times.txt"
done
uv run --project "$REPO" python - "$OUT" <<'PY'
import re
import sys
from pathlib import Path

out = Path(sys.argv[1])
best = {}
for mode in ("graal", "locks"):
    for line in (out / mode / "times.txt").read_text().splitlines():
        shapes = dict((name, float(ms)) for name, ms in re.findall(r"(\w+) ([0-9.]+)", line.split(":", 1)[1]))
        for name, ms in shapes.items():
            best[mode, name] = min(best.get((mode, name), ms), ms)
names = sorted({name for _, name in best})
print(f"{'shape':10}{'graal ms':>12}{'locks ms':>12}{'locks/graal':>14}")
for name in names:
    g, l = best["graal", name], best["locks", name]
    print(f"{name:10}{g:12.3f}{l:12.3f}{l / g:14.2f}")
PY
