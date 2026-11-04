"""Native Image's stages in builds of graal and fields, and what fields adds to each: the build time by stage.

Usage:
    uv run python scripts/evaluation/stage_times.py graal-native/out/awfy-base-t1 graal-native/out/awfy-base-t2
    uv run python scripts/evaluation/stage_times.py graal-native/out/awfy-base-t{1,2,3} --steps

Each directory is one run.sh build pair and holds graal.log and fields.log (the builder's output, whose [n/8] lines give the
stages). The median over the directories is shown for each configuration, and fields against graal. The total is the log's
"Finished generating", the stages the seconds the builder prints for each; other is what the stages do not account for.
--steps adds our own steps of the fields builds (timings.txt: facts, report, write, tool, apply).
"""

import argparse
import re
import statistics
from pathlib import Path

STAGES = ["init", "analysis", "universe", "parsing", "inlining", "compile", "layout", "image"]


def parse(log: Path) -> dict[str, float] | None:
    text = log.read_text(errors="replace")
    stages = re.findall(r"^\[(\d)/8\].*\((\d+\.\d)s @", text, re.M)
    finished = re.search(r"Finished generating .* in (?:(\d+)m )?(\d+(?:\.\d+)?)s", text)
    if len(stages) != 8 or not finished:
        return None
    found = {name: float(seconds) for name, (_, seconds) in zip(STAGES, stages)}
    found["total"] = int(finished.group(1) or 0) * 60 + float(finished.group(2))
    found["other"] = found["total"] - sum(found[n] for n in STAGES)
    return found


def steps(path: Path) -> dict[str, float]:
    found: dict[str, float] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            parts = line.split("\t")
            if not line.startswith("#") and len(parts) >= 2:
                found[parts[0]] = float(parts[1])
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--steps", action="store_true", help="also our steps in the fields builds")
    args = parser.parse_args()
    columns = STAGES + ["other", "total"]
    rows = {}
    for config in ("graal", "fields"):
        parsed = [parse(d / f"{config}.log") for d in args.directories]
        failed = sum(p is None for p in parsed)
        good = [p for p in parsed if p]
        rows[config] = [statistics.median(p[c] for p in good) for c in columns] if good else None
        print(f"{config}: {len(good)} builds" + (f", {failed} failed" if failed else "") + ("; totals " + ", ".join(f"{p['total']:.1f}" for p in good) if good else ""))
    if rows["graal"] and rows["fields"]:
        print(f"{'':12}" + "".join(f"{c:>10}" for c in columns))
        for name in ("graal", "fields"):
            print(f"{name:12}" + "".join(f"{v:10.1f}" for v in rows[name]))
        print(f"{'fields-graal':12}" + "".join(f"{f - g:+10.1f}" for g, f in zip(rows["graal"], rows["fields"])))
    if args.steps:
        measured = [steps(d / "fields" / "timings.txt") for d in args.directories]
        names = ["export: facts", "export: report", "export: write", "effects.kills", "apply"]
        print("our steps (fields, median s): " + "  ".join(f"{n} {statistics.median([m.get(n, 0.0) for m in measured]):.2f}" for n in names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
