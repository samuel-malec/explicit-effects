"""Hardware counters for one Are We Fast Yet benchmark, in each image graal-native built.

Usage:
    uv run python programs/awfy/counters.py CD graal-native/out/awfy-sym graal-native/out/awfy-a64 [--runs 3]

Runs every image under each directory (graal, kills, objects, decisions) on the one
benchmark, under `perf stat`, pinned to one CPU, the images taking turns run by run.
Prints the mean of each counter per image, and each image's cycles against the
first image's. Unlike run times, the counts don't depend on the clock frequency.

The events are AMD Zen 4's: instructions retired, loads and stores dispatched,
mispredicted branches, and misses in the op cache, where decoded instructions wait
by the 64-byte window of code they came from.
"""

import argparse
import statistics
import subprocess
import sys
from pathlib import Path

MODES = ("graal", "kills", "objects", "decisions")
EVENTS = {
    "cycles": "cycles",
    "instructions": "instructions",
    "loads": "ls_dispatch.ld_dispatch",
    "stores": "ls_dispatch.store_dispatch",
    "mispredicted": "ex_ret_brn_misp",
    "op-cache misses": "op_cache_hit_miss.op_cache_miss",
}


def count(image: Path, benchmark: str, iterations: int, cpu: int) -> dict[str, float]:
    done = subprocess.run(["taskset", "-c", str(cpu), "perf", "stat", "-x,", "-e", ",".join(EVENTS.values()),
                           str(image), str(iterations), "timing", benchmark], capture_output=True, text=True, check=True)
    counts = {}
    for line in done.stderr.splitlines():
        fields = line.split(",")
        if len(fields) > 2 and fields[2] in EVENTS.values() and fields[0].isdigit():
            counts[next(k for k, v in EVENTS.items() if v == fields[2])] = float(fields[0])
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("benchmark")
    parser.add_argument("out", type=Path, nargs="+", help="graal-native/out/<name> directories")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--cpu", type=int, default=4)
    args = parser.parse_args()

    images = {f"{out.name}/{mode}": out / mode / out.name for out in args.out for mode in MODES if (out / mode / out.name).exists()}
    seen: dict[str, list[dict[str, float]]] = {name: [] for name in images}
    for run in range(args.runs):
        for name, image in images.items():
            seen[name].append(count(image, args.benchmark, args.iterations, args.cpu))
        print(f"run {run + 1} of {args.runs} done", file=sys.stderr)

    print(f"{args.benchmark}, {args.iterations} iterations, mean of {args.runs} runs (cycles ±: standard deviation)")
    print(f"{'image':22} {'cycles':>14} {'±':>6} {'vs first':>9}" + "".join(f" {k:>15}" for k in list(EVENTS)[1:]))
    first = None
    for name, runs in seen.items():
        mean = {k: statistics.mean(r[k] for r in runs) for k in EVENTS if all(k in r for r in runs)}
        spread = statistics.stdev(r["cycles"] for r in runs) / mean["cycles"] if len(runs) > 1 else 0.0
        first = first or mean["cycles"]
        print(f"{name:22} {mean['cycles']:>14,.0f} {spread:>6.1%} {mean['cycles'] / first - 1:>+9.1%}"
              + "".join(f" {mean.get(k, float('nan')):>15,.0f}" for k in list(EVENTS)[1:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
