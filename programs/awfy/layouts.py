"""How the kills images compare with graal's when only the placement of code changes.

Usage:
    uv run python programs/awfy/layouts.py graal-native/out/awfy-a16 graal-native/out/awfy-sym \\
        graal-native/out/awfy-a64 graal-native/out/awfy-a128 [--runs 3] [--benchmarks CD,DeltaBlue]

Each directory holds a graal and a kills image, built alike except for the alignment
of compiled methods (-H:CodeAlignment, named in the directory as -a16; a directory
without one is built with the default, 32 bytes on AMD64). Every image runs every
benchmark under perf stat, as counters.py does, the images taking turns. For each
benchmark the table gives:
- kills against graal in cycles, in each layout, and the mean over the layouts;
- how far graal's own cycles move between layouts: what placement alone does;
- kills against graal in instructions, loads and stores, the mean over the layouts.
"""

import argparse
import re
import statistics
import sys
from pathlib import Path

from counters import count

BENCHMARKS = ("Bounce", "CD", "DeltaBlue", "Havlak", "Json", "List", "Mandelbrot", "NBody",
              "Permute", "Queens", "Richards", "Sieve", "Storage", "Towers")


def alignment(out: Path) -> str:
    found = re.search(r"-a(\d+)$", out.name)
    return found.group(1) if found else "32"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path, nargs="+", help="graal-native/out/<name> directories, one per layout")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--benchmarks", default=",".join(BENCHMARKS))
    parser.add_argument("--cpu", type=int, default=4)
    args = parser.parse_args()

    benchmarks = args.benchmarks.split(",")
    layouts = {alignment(out): out for out in args.out}
    seen: dict[tuple[str, str, str], list[dict[str, float]]] = {}
    for run in range(args.runs):
        for benchmark in benchmarks:
            for layout, out in layouts.items():
                for mode in ("graal", "kills"):
                    seen.setdefault((benchmark, layout, mode), []).append(
                        count(out / mode / out.name, benchmark, args.iterations, args.cpu))
        print(f"run {run + 1} of {args.runs} done", file=sys.stderr)

    def mean(benchmark: str, layout: str, mode: str, counter: str) -> float:
        return statistics.mean(r[counter] for r in seen[(benchmark, layout, mode)])

    print(f"kills against graal in cycles per method alignment (bytes), {args.iterations} iterations, mean of {args.runs} runs")
    print(f"{'benchmark':11}" + "".join(f" {layout:>7}" for layout in layouts) + f" {'mean':>7} {'graal moves':>12}"
          + "".join(f" {k:>13}" for k in ("instructions", "loads", "stores")))
    for benchmark in benchmarks:
        ratios = [mean(benchmark, layout, "kills", "cycles") / mean(benchmark, layout, "graal", "cycles") - 1 for layout in layouts]
        graal = [mean(benchmark, layout, "graal", "cycles") for layout in layouts]
        others = [statistics.mean(mean(benchmark, layout, "kills", k) / mean(benchmark, layout, "graal", k) - 1 for layout in layouts)
                  for k in ("instructions", "loads", "stores")]
        print(f"{benchmark:11}" + "".join(f" {r:>+7.1%}" for r in ratios) + f" {statistics.mean(ratios):>+7.1%}"
              + f" {max(graal) / min(graal) - 1:>12.1%}" + "".join(f" {o:>+13.2%}" for o in others))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
