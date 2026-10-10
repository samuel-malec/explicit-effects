"""How long each image of the round trip runs each Are We Fast Yet benchmark.

Usage:
    uv run python programs/awfy/time.py graal-native/out/awfy [--runs 5] [--iterations 20]

Runs every image graal-native built (graal, kills, objects, decisions), the
images taking turns run by run so that the machine's drift touches them
alike. Each run measures each benchmark --iterations times at the size the
suite benchmarks with. The first iteration of a run is left out, and the
table shows the median of the rest, in ms, and each image's against graal's.
"""

import argparse
import statistics
import subprocess
import sys
from pathlib import Path

MODES = ("graal", "kills", "objects", "decisions")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path, help="graal-native/out/<name>")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()

    images = {mode: args.out / mode / args.out.name for mode in MODES if (args.out / mode).is_dir()}
    times: dict[str, dict[str, list[float]]] = {mode: {} for mode in images}
    for run in range(args.runs):
        for mode, image in images.items():
            done = subprocess.run([str(image), str(args.iterations), "timing"], capture_output=True, text=True, check=True)
            seen: set[str] = set()
            for line in done.stderr.splitlines():
                name, value = line.split()
                if name in seen:  # the first iteration warms the caches
                    times[mode].setdefault(name, []).append(int(value.removesuffix("us")) / 1000)
                seen.add(name)
        print(f"run {run + 1} of {args.runs} done", file=sys.stderr)

    print(f"{'benchmark':12} {'graal ms':>9}" + "".join(f" {mode:>10}" for mode in list(images)[1:]))
    total = {mode: 0.0 for mode in images}
    for name in times["graal"]:
        median = {mode: statistics.median(times[mode][name]) for mode in images}
        for mode in images:
            total[mode] += median[mode]
        print(f"{name:12} {median['graal']:>9.2f}" + "".join(f" {median[m] / median['graal'] - 1:>+10.1%}" for m in list(images)[1:]))
    print(f"{'total':12} {total['graal']:>9.2f}" + "".join(f" {total[m] / total['graal'] - 1:>+10.1%}" for m in list(images)[1:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
