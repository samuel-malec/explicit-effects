"""How long each image of the round trip runs each Are We Fast Yet benchmark.

Usage:
    uv run python programs/awfy/time.py graal-native/out/awfy [--runs 5] [--iterations 20]
    uv run python programs/awfy/time.py --image graal=out/a/graal/a --image skip=out/b/kills/b --benchmark Permute

Runs every image graal-native built (graal, kills, ceiling, objects), the
images taking turns run by run so that the machine's drift touches them
alike. Each run measures each benchmark --iterations times at the size the
suite benchmarks with. The first iteration of a run is left out, and the
table shows the median of the rest, in ms, and each image's against the first one's. The images are the
ones of a directory, or those named with --image label=path (the first is the one the others are compared with);
--benchmark runs one benchmark only.
"""

import argparse
import statistics
import subprocess
import sys
from pathlib import Path

MODES = ("graal", "kills", "ceiling", "objects")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path, nargs="?", help="graal-native/out/<name>")
    parser.add_argument("--image", action="append", default=[], metavar="LABEL=PATH", help="an image to time; instead of a directory")
    parser.add_argument("--benchmark", help="only this benchmark")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()

    if args.image:
        images = {label: Path(path) for label, _, path in (item.partition("=") for item in args.image)}
    elif args.out:
        images = {mode: args.out / mode / args.out.name for mode in MODES if (args.out / mode).is_dir()}
    else:
        parser.error("name a directory or some --image")
    first = next(iter(images))
    times: dict[str, dict[str, list[float]]] = {mode: {} for mode in images}
    for run in range(args.runs):
        for mode, image in images.items():
            done = subprocess.run([str(image), str(args.iterations), "timing", *([args.benchmark] if args.benchmark else [])],
                                  capture_output=True, text=True, check=True)
            seen: set[str] = set()
            for line in done.stderr.splitlines():
                name, value = line.split()
                if name in seen:  # the first iteration warms the caches
                    times[mode].setdefault(name, []).append(int(value.removesuffix("us")) / 1000)
                seen.add(name)
        print(f"run {run + 1} of {args.runs} done", file=sys.stderr)

    print(f"{'benchmark':12} {first + ' ms':>9}" + "".join(f" {mode:>10}" for mode in list(images)[1:]))
    total = {mode: 0.0 for mode in images}
    for name in times[first]:
        median = {mode: statistics.median(times[mode][name]) for mode in images}
        for mode in images:
            total[mode] += median[mode]
        print(f"{name:12} {median[first]:>9.2f}" + "".join(f" {median[m] / median[first] - 1:>+10.1%}" for m in list(images)[1:]))
    print(f"{'total':12} {total[first]:>9.2f}" + "".join(f" {total[m] / total[first] - 1:>+10.1%}" for m in list(images)[1:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
