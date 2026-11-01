"""How long each javac image cost-javac.sh built takes to compile the same sources: Are We Fast Yet's
benchmarks, as a realistic workload. The images take turns run by run, so that the machine's drift
touches them alike. One measurement is --repeat compiles in a row (a native javac compiles them in
about 0.1 s); the table shows the median wall time per compile and each image against the first.

Usage:
    taskset -c 4-7 uv run python scripts/evaluation/time_javac.py graal-native/out/javac-cost-graal-r1 \\
        graal-native/out/javac-cost-kills-r1 --runs 10

Each argument is a build directory of cost-javac.sh, holding <config>/javac.
"""

import argparse
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCES = sorted(str(p) for p in (REPO / "are-we-fast-yet/benchmarks/Java/src").rglob("*.java"))


def system(jdk: Path) -> list[str]:
    """How the image finds the JDK's classes, as Graal's gate runs it."""
    return ["-Djava.home=", "--system", "none", "-p", str(jdk / "jmods")] if (jdk / "jmods").is_dir() else ["--system", str(jdk)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("builds", type=Path, nargs="+", help="build directories of cost-javac.sh")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--repeat", type=int, default=5, help="compiles per measurement")
    parser.add_argument("--jdk", type=Path, default=Path.home() / ".mx/jdks/labsjdk-ce-latest-jvmci-25.4-b23_amd64")
    args = parser.parse_args()

    images = {}
    for build in args.builds:
        config = next(p.name for p in build.iterdir() if p.is_dir() and (p / "javac").exists())
        images[build.name] = build / config / "javac"
    times: dict[str, list[float]] = {name: [] for name in images}
    for run in range(args.runs + 1):
        for name, image in images.items():
            with tempfile.TemporaryDirectory() as out:
                start = time.perf_counter()
                for _ in range(args.repeat):
                    subprocess.run([str(image), "-proc:none", *system(args.jdk), "-d", out, *SOURCES], check=True, capture_output=True)
                if run > 0:  # the first run of each warms the file cache
                    times[name].append((time.perf_counter() - start) / args.repeat)
        print(f"run {run} of {args.runs} done", file=sys.stderr)

    base = statistics.median(next(iter(times.values())))
    print(f"{len(SOURCES)} files, {args.runs} runs of {args.repeat} compiles each; median s per compile, against {next(iter(times))}")
    for name, values in times.items():
        median = statistics.median(values)
        print(f"  {name:32} {median:7.3f}  ({min(values):.3f}–{max(values):.3f})  {100 * (median - base) / base:+.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
