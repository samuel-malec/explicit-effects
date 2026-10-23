"""What the side-effect analysis cost in the builds cost.sh made: per configuration, the median and the
range over its rounds of the whole build, Native Image's analysis and compile stages, peak RSS, and
each step of ours (timings.txt), and the difference to graal on the same points-to analysis.

Usage:
    uv run python graal-native/cost.py graal-native/out awfy

Our export and tool run in Native Image's afterAnalysis, so their time is part of its analysis stage
("[2/8] Performing analysis"); the phases run in the compile stage ("[6/8] Compiling methods").
"""

import argparse
import re
import statistics
from pathlib import Path

STAGE = re.compile(r"^\[(\d)/8\] .*?\(\s*([\d.]+)s @")
TOTAL = re.compile(r"Finished generating '.*' in (?:(\d+)m )?([\d.]+)s\.")
RSS = re.compile(r"Peak RSS: ([\d.]+)GiB")
CONFIGS = (("graal", ""), ("kills", ""), ("graal", "-allocsens"), ("objects", "-allocsens"), ("decisions", "-allocsens"))
STEPS = ("export", "effects.kills", "rules.decisions", "apply")


def build(log: Path) -> dict[str, float]:
    """The total, analysis and compile times and peak RSS of one native-image build."""
    seen: dict[str, float] = {}
    for line in log.read_text().splitlines():
        if m := STAGE.match(line):
            seen[{"2": "analysis", "6": "compile"}.get(m.group(1), f"stage {m.group(1)}")] = float(m.group(2))
        elif m := TOTAL.search(line):
            seen["total"] = 60 * int(m.group(1) or 0) + float(m.group(2))
        elif m := RSS.search(line):
            seen["rss GiB"] = float(m.group(1))
    return seen


def steps(timings: Path) -> dict[str, float]:
    """Seconds per step of ours, from timings.txt."""
    if not timings.exists():
        return {}
    rows = (line.split("\t") for line in timings.read_text().splitlines() if line and not line.startswith("#"))
    return {name: float(seconds) for name, seconds, _ in rows}


def cell(values: list[float]) -> str:
    if not values:
        return "-"
    return f"{statistics.median(values):.1f}" + (f" ({min(values):.1f}–{max(values):.1f})" if len(values) > 1 else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path, help="graal-native/out")
    parser.add_argument("program", help="the program's name as run.sh lowercases it: awfy, examples")
    args = parser.parse_args()

    rows = {}
    for config, analysis in CONFIGS:
        runs = sorted(args.out.glob(f"{args.program}{analysis}-cost-{config}-r*"))
        builds = [build(run / f"{config}.log") for run in runs]
        ours = [steps(run / config / "timings.txt") for run in runs]
        rows[(config, analysis)] = (builds, ours)

    columns = ("total", "analysis", "compile", "rss GiB")
    print(f"{args.program}: median (min–max) over rounds, seconds")
    print(f"{'configuration':24} {'rounds':>6} " + " ".join(f"{c:>18}" for c in columns) + "  " + " ".join(f"{s:>16}" for s in STEPS))
    for (config, analysis), (builds, ours) in rows.items():
        name = config + (" (allocsens)" if analysis else "")
        print(f"{name:24} {len(builds):>6} " + " ".join(f"{cell([b[c] for b in builds if c in b]):>18}" for c in columns)
              + "  " + " ".join(f"{cell([o[s] for o in ours if s in o]):>16}" for s in STEPS))

    print("\nadded to graal on the same analysis (difference of medians):")
    for (config, analysis), (builds, _) in rows.items():
        if config == "graal" or not builds:
            continue
        base, _ = rows[("graal", analysis)]
        if not base:
            continue
        name = config + (" (allocsens)" if analysis else "")
        added = []
        for c in ("total", "analysis", "compile"):
            mine, theirs = statistics.median(b[c] for b in builds), statistics.median(b[c] for b in base)
            added.append(f"{c} {mine - theirs:+.1f} s ({100 * (mine - theirs) / theirs:+.0f}%)")
        print(f"  {name:24} " + ", ".join(added))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
