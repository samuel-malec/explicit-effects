"""What the side-effect analysis cost in the builds cost.sh made: per configuration, the median and the
range over its rounds of the whole build, Native Image's analysis and compile stages, peak RSS, and
each step of ours (timings.txt), and the difference to graal on the same points-to analysis.

Usage:
    uv run python scripts/evaluation/cost.py graal-native/out awfy

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
# (label, the tag in the build's name, the mode it was run in (the directory of its output), the analysis' suffix,
# the label of the configuration it adds to). The baseline of a configuration has the same analysis and flags.
CONFIGS = (
    ("graal", "graal", "graal", "", None),
    ("graal + inputs", "graalinputs", "graal", "", "graal"),
    ("kills", "kills", "kills", "", "graal"),
    ("kills + escape", "killsescape", "kills", "", "graal + inputs"),
    ("graal (allocsens)", "graal", "graal", "-allocsens", None),
    ("graal + flags (allocsens)", "graalflags", "graal", "-allocsens", "graal (allocsens)"),
    ("objects (allocsens)", "objects", "objects", "-allocsens", "graal (allocsens)"),
    ("locks (allocsens)", "locks", "locks", "-allocsens", "graal + flags (allocsens)"),
    # javac only: the saturation cutoff at 100 (F65), and locks removed on top of it
    ("graal + cutoff (allocsens)", "graalcutoff", "graal", "-allocsens", "graal (allocsens)"),
    ("graal + flags + cutoff (allocsens)", "graalflagscutoff", "graal", "-allocsens", "graal + cutoff (allocsens)"),
    ("locks + cutoff (allocsens)", "lockscutoff", "locks", "-allocsens", "graal + flags + cutoff (allocsens)"),
)
STEPS = ("export", "export: thread escape", "effects.kills", "effects.elide", "apply", "elide locks")


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
    for label, tag, mode, analysis, base in CONFIGS:
        runs = sorted(args.out.glob(f"{args.program}{analysis}-cost-{tag}-r*"))
        builds = [build(run / f"{mode}.log") for run in runs]
        ours = [steps(run / mode / "timings.txt") for run in runs]
        rows[label] = (builds, ours, base)

    columns = ("total", "analysis", "compile", "rss GiB")
    print(f"{args.program}: median (min–max) over rounds, seconds")
    print(f"{'configuration':28} {'rounds':>6} " + " ".join(f"{c:>18}" for c in columns))
    for label, (builds, _, _) in rows.items():
        if builds:
            print(f"{label:28} {len(builds):>6} " + " ".join(f"{cell([b[c] for b in builds if c in b]):>18}" for c in columns))
    print("\nour steps inside the build (seconds, median over rounds; part of the analysis stage, except apply and elide locks, which are in the compile stage and summed over the compiler's threads):")
    print(f"{'configuration':28} " + " ".join(f"{s:>22}" for s in STEPS))
    for label, (builds, ours, _) in rows.items():
        if builds and any(ours):
            print(f"{label:28} " + " ".join(f"{cell([o[s] for o in ours if s in o]):>22}" for s in STEPS))

    print("\nadded to the configuration it builds on (difference of medians):")
    for label, (builds, _, base) in rows.items():
        if base is None or not builds or not rows[base][0]:
            continue
        added = []
        for c in ("total", "analysis", "compile"):
            mine, theirs = statistics.median(b[c] for b in builds), statistics.median(b[c] for b in rows[base][0])
            added.append(f"{c} {mine - theirs:+.1f} s ({100 * (mine - theirs) / theirs:+.0f}%)")
        print(f"  {label:28} on {base:26} " + ", ".join(added))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
