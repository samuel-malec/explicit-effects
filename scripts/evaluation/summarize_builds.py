"""Build time, peak resident set and image size of the builds of final-t2.sh, per program and arm, from the lines Native Image prints
at the end of each build: "Finished generating 'x' in 1m 23.4s.", "Peak RSS: 5.25GiB", "(executable, 7.81MiB)".

Usage:
    python3 scripts/evaluation/summarize_builds.py graal-native/out

Arms: stock (the same builder, the feature off), graal (the feature on, nothing narrowed), fields (calls narrowed). An arm differs from another when
the ranges of its builds do not overlap. Programs: AWFY at -O3, PetClinic and javac (tags t2), then the Renaissance benchmarks and the Barista
applications (out/final-t2/<suite>/<program>-r<k>/<arm>/build.log), with a line per suite over its programs. A build whose log lacks one of the
three lines is listed as failed. Nothing is built or run here.
"""

import re
import statistics
import sys
from pathlib import Path

PROGRAMS = {
    "AWFY at -O3": {
        "graal": "awfy-t2-{k}/graal.log",
        "fields": "awfy-t2-{k}/fields.log",
        "stock": "awfy-t2-stock{k}/graal.log",
    },
    "PetClinic": {
        "graal": "petclinic-t2r{k}/graal/build.log",
        "fields": "petclinic-t2r{k}/fields/build.log",
        "stock": "petclinic-t2r{k}/plain/build.log",
    },
    "javac": {
        "graal": "javac-cost-graal-r{k}/graal.log",
        "fields": "javac-cost-fields-r{k}/fields.log",
        "stock": "javac-cost-stock-r{k}/stock.log",
    },
}
SUITES = ("renaissance", "barista")
ARMS = ("stock", "graal", "fields")
PAIRS = (("graal", "fields"), ("stock", "graal"), ("stock", "fields"))  # b against a
METRICS = (("build", "s"), ("RSS", "rss"), ("size", "mib"))
UNIT = {"KiB": 1 / 1024, "MiB": 1.0, "GiB": 1024.0, "KB": 1 / 1024, "MB": 1.0, "GB": 1024.0}


def seconds(text: str) -> float:
    total = 0.0
    for number, unit in re.findall(r"([\d.]+)([hms])", text):
        total += float(number) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


def read(log: Path) -> dict[str, float] | None:
    if not log.exists():
        return None
    text = log.read_text(errors="replace")
    time = re.search(r"Finished generating '[^']*' in ([^\n]*?)\.\n", text)
    rss = re.search(r"Peak RSS: ([\d.]+)(GiB|MiB)", text)
    size = re.search(r"\((?:executable|shared library), ([\d.]+)(KiB|MiB|GiB|KB|MB|GB)\)", text)
    if not (time and rss and size):
        return None
    return {"s": seconds(time[1]), "rss": float(rss[1]) * UNIT[rss[2]] / 1024, "mib": float(size[1]) * UNIT[size[2]]}


def span(values: list[float], digits: int = 1) -> str:
    return f"{statistics.median(values):.{digits}f} ({min(values):.{digits}f}–{max(values):.{digits}f})"


def change(a: list[float], b: list[float]) -> tuple[float, bool]:
    """b against a: the change in the medians in per cent, and whether the ranges are apart."""
    return 100 * (statistics.median(b) - statistics.median(a)) / statistics.median(a), min(a) > max(b) or min(b) > max(a)


def versus(a: list[float], b: list[float]) -> str:
    c, apart = change(a, b)
    return f"{c:+.1f}%{' (apart)' if apart else ' (ranges overlap)'}"


def collect(out: Path) -> dict[str, dict[str, dict[str, list[dict[str, float]]]]]:
    """Suite -> program -> arm -> the builds that finished, by round; failed ones are counted under 'failed'."""
    found: dict[str, dict[str, dict[str, list]]] = {"three": {}}
    for program, arms in PROGRAMS.items():
        found["three"][program] = {arm: [] for arm in ARMS} | {"failed": []}
        for arm, pattern in arms.items():
            for k in range(1, 10):
                path = out / pattern.format(k=k)
                if path.exists():
                    values = read(path)
                    (found["three"][program][arm] if values else found["three"][program]["failed"]).append(values or f"{arm} r{k}")
    for suite in SUITES:
        found[suite] = {}
        for directory in sorted((out / "final-t2" / suite).glob("*-r*/*")):
            if directory.name not in ARMS:
                continue
            program = directory.parent.name.rsplit("-r", 1)[0]
            entry = found[suite].setdefault(program, {arm: [] for arm in ARMS} | {"failed": []})
            values = read(directory / "build.log")
            (entry[directory.name] if values else entry["failed"]).append(values or f"{directory.parent.name.rsplit('-', 1)[1]} {directory.name}")
    return found


def table(name: str, arms: dict[str, list]) -> None:
    print(f"== {name}")
    for arm in ARMS:
        if arms[arm]:
            print(f"  {arm:7} builds: " + ", ".join(f"{b['s']:.1f} s / {b['rss']:.2f} GiB / {b['mib']:.2f} MiB" for b in arms[arm]))
    if arms["failed"]:
        print(f"  FAILED: {', '.join(arms['failed'])}")
    print(f"  {'':7} {'builds':>6}  {'total build, s':>22}  {'peak RSS, GiB':>20}  {'executable, MiB':>22}")
    for arm in ARMS:
        if arms[arm]:
            builds = arms[arm]
            print(f"  {arm:7} {len(builds):>6}  {span([b['s'] for b in builds]):>22}  {span([b['rss'] for b in builds], 2):>20}  {span([b['mib'] for b in builds], 2):>22}")
    for a, b in PAIRS:
        if arms[a] and arms[b]:
            print(f"  {b} against {a}: " + "; ".join(f"{label} {versus([x[key] for x in arms[a]], [x[key] for x in arms[b]])}" for label, key in METRICS))
    print()


def suite_line(name: str, programs: dict[str, dict[str, list]]) -> None:
    """Over the programs of a suite: the median and mean of each program's change in the medians, and how many are apart."""
    print(f"== {name}: {len(programs)} programs")
    for a, b in PAIRS:
        rows = {label: [change([x[key] for x in p[a]], [x[key] for x in p[b]]) for p in programs.values() if p[a] and p[b]] for label, key in METRICS}
        count = len(rows["build"])
        if not count:
            continue
        parts = []
        for label, _ in METRICS:
            values = [c for c, _ in rows[label]]
            parts.append(f"{label} median {statistics.median(values):+.1f}% mean {statistics.fmean(values):+.1f}% range {min(values):+.1f}..{max(values):+.1f}% apart in {sum(1 for _, apart in rows[label] if apart)} of {count}")
        print(f"  {b} against {a} ({count} programs): " + "; ".join(parts))
    print()


def main() -> int:
    out = Path(sys.argv[1])
    found = collect(out)
    for program, arms in found["three"].items():
        if any(arms[arm] for arm in ARMS) or arms["failed"]:
            table(program, arms)
    for suite in SUITES:
        if found[suite]:
            suite_line(suite.capitalize(), found[suite])
            for program, arms in found[suite].items():
                table(f"{suite}/{program}", arms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
