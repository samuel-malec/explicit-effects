"""What the side-effect analysis cost on javac, PetClinic and the Barista applications, and what it left out of their code: per program,
the builds of `graal` and `fields` over their rounds (median and range of the build, Native Image's analysis and compile stages, peak
RSS), the increment, each step of ours, and the loads and calls left in the methods counts.txt lists.

Usage:
    uv run python scripts/evaluation/cost_programs.py graal-native/out

The builds are the ones of reproduce.sh's javac and frameworks stages: out/javac-cost-<config>-r<k>/ (cost-javac.sh),
out/petclinic-r<k>/<config>/, out/barista/<app>-r<k>/<config>/ (petclinic.sh and barista.sh with TAG=r<k>) and
out/renaissance/<benchmark>-r<k>/<config>/ (renaissance.sh). A build whose log lacks
"Finished generating" failed and is listed as such.
"""

import argparse
import importlib.util
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cost = load("cost")
counts = load("counts")

CONFIGS = ("graal", "fields")
STEPS = ("export", "effects.kills", "apply")


def rounds_of(out: Path) -> dict[str, dict[str, list[Path]]]:
    """Program -> configuration -> the build directories (the directory holding the build's log and its mode directory), by round."""
    programs: dict[str, dict[str, list[Path]]] = {}

    def add(program: str, config: str, directory: Path) -> None:
        programs.setdefault(program, {c: [] for c in CONFIGS})[config].append(directory)

    for directory in sorted(out.glob("javac-cost-*-r*")):
        config = directory.name.removeprefix("javac-cost-").rsplit("-r", 1)[0]
        if config in CONFIGS:
            add("javac", config, directory)
    for directory in sorted(out.glob("petclinic-r*/*")):
        if directory.name in CONFIGS and directory.is_dir():
            add("petclinic", directory.name, directory)
    for suite in ("barista", "renaissance"):
        for directory in sorted((out / suite).glob("*-r*/*")):
            app = directory.parent.name.rsplit("-r", 1)[0]
            if directory.name in CONFIGS and directory.is_dir():
                add(app, directory.name, directory)
    return programs


def log_of(directory: Path, config: str) -> Path:
    return directory / "build.log" if (directory / "build.log").exists() else directory / f"{config}.log"


def total_counts(directory: Path, config: str) -> counts.Counts | None:
    path = directory / config / "counts.txt"
    return counts.total(counts.read(path)) if path.exists() else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path, help="graal-native/out")
    args = parser.parse_args()

    print(f"{'program':26} {'rounds':>6} | {'graal total':>16} {'fields total':>16} {'increment':>18} | {'analysis +':>10} {'compile +':>10} | {'rss graal':>9} {'rss fields':>10}")
    details = []
    for program, by_config in rounds_of(args.out).items():
        builds = {c: [cost.build(log_of(d, c)) for d in dirs] for c, dirs in by_config.items()}
        failed = {c: sum("total" not in b for b in bs) for c, bs in builds.items()}
        ok = {c: [b for b in bs if "total" in b] for c, bs in builds.items()}
        if not ok["graal"] or not ok["fields"]:
            print(f"{program:26} {'-':>6} | failed builds: graal {failed['graal']} of {len(builds['graal'])}, fields {failed['fields']} of {len(builds['fields'])}")
            continue

        def med(c: str, key: str) -> float:
            return statistics.median(b[key] for b in ok[c] if key in b)

        total = {c: [b["total"] for b in ok[c]] for c in CONFIGS}
        added = med("fields", "total") - med("graal", "total")
        row = (f"{program:26} {len(ok['graal']):>3}/{len(ok['fields']):<2} | {cost.cell(total['graal']):>16} {cost.cell(total['fields']):>16} "
               f"{added:+8.1f} s ({100 * added / med('graal', 'total'):+5.1f}%) | "
               f"{med('fields', 'analysis') - med('graal', 'analysis'):+9.1f}s {med('fields', 'compile') - med('graal', 'compile'):+9.1f}s | "
               f"{med('graal', 'rss GiB'):>9.1f} {med('fields', 'rss GiB'):>10.1f}")
        print(row)
        mode_steps = [cost.steps(d / "fields" / "timings.txt") for d in by_config["fields"]]
        steps = "  ".join(f"{s} {cost.cell([m[s] for m in mode_steps if s in m])}" for s in STEPS)
        base = {c: [total_counts(d, c) for d in dirs] for c, dirs in by_config.items()}
        shown = []
        for c in CONFIGS:
            known = [t for t in base[c] if t]
            if known:
                loads = sorted({t.loads for t in known})
                calls = sorted({t.calls for t in known})
                shown.append(f"{c}: {'/'.join(map(str, loads))} loads ({known[0].loop_loads} in loops), {'/'.join(map(str, calls))} calls, {len(known)} counted")
        details.append(f"{program}: our steps (s, fields) {steps}\n    " + "; ".join(shown))
    print("\nour steps in the `fields` builds (seconds, median and range over rounds) and the loads and calls left (values over rounds, '/' if they differ):")
    print("\n".join(details))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
