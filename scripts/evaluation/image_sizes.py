"""The size of the images of graal and fields: what Native Image prints at the end of every build, per program over the rounds.

Usage:
    uv run python scripts/evaluation/image_sizes.py graal-native/out
    uv run python scripts/evaluation/image_sizes.py graal-native/out --only 'javac|petclinic' --builds sizes-builds.tsv

The builds are the ones of reproduce.sh: out/awfy-cost-<config>-r<k>/ (cost.sh), out/javac-cost-<config>-r<k>/ (cost-javac.sh),
out/petclinic-r<k>/<config>/, out/barista/<app>-r<k>/<config>/ (petclinic.sh and barista.sh with TAG=r<k>),
out/renaissance/<benchmark>-r<k>/<config>/ (renaissance.sh), and
out/awfy-<setting>-t<k>/ (the inliner stage, one directory holding both images; the builds with source positions, awfy-<setting>
without a round, are left out: their images carry the positions). Builds from before `kills` was renamed `fields` are read as
fields where a program has no build under the new name.

The sizes are the lines of the build's log (code area with its compilation units, image heap with its objects, other data, the
total image and file size; two decimals of MiB, and the file size moves in steps of 64 KiB, the alignment of the image's
segments). The size of the executable in bytes comes from stat, either of the file where it is still on disk or of a list made
on the machine that built it (--executables, lines of `find -printf '%s %p\n'` below out/); it is compared with the log's file size
and shown in a table of its own. A difference between the configurations counts when their ranges over the rounds do not overlap,
as for the build times; with one round of each there is no range. The day, tool and fork of each build are those of its
provenance.txt. Nothing is built or run here.
"""

import argparse
import os
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

UNIT = {"B": 1, "KiB": 1 << 10, "MiB": 1 << 20, "GiB": 1 << 30}
AMOUNT = r"([\d.]+)\s?(KiB|MiB|GiB|B)"
CODE = re.compile(rf"^\s*{AMOUNT} \(\s*[\d.]+%\) for code area:\s+([\d,]+) compilation units")
HEAP = re.compile(rf"^\s*{AMOUNT} \(\s*[\d.]+%\) for image heap:\s+([\d,]+) objects")
OTHER = re.compile(rf"^\s*{AMOUNT} \(\s*[\d.]+%\) for other data")
TOTAL = re.compile(rf"^\s*{AMOUNT} in total image size, {AMOUNT} in total file size")
COMMIT = re.compile(r"^\s+commit: ([0-9a-f]{7,40})", re.M)
CONFIGS = ("graal", "fields")
OLD_NAMES = {"kills": "fields"}


@dataclass(frozen=True)
class Sizes:
    code: int
    units: int
    heap: int
    objects: int
    other: int
    image: int
    file: int


@dataclass
class Build:
    group: str
    program: str
    config: str
    directory: Path
    sizes: Sizes | None
    executable: int | None  # the executable's size from stat, if it is still there
    day: str
    tool: str
    fork: str


def amount(value: str, unit: str) -> int:
    return round(float(value) * UNIT[unit])


def read_sizes(log: Path) -> Sizes | None:
    """The sizes in a build's log, or None if it lacks them (the build failed)."""
    found: dict[str, tuple[int, ...]] = {}
    for line in log.read_text(errors="replace").splitlines():
        if m := CODE.match(line):
            found["code"] = (amount(m[1], m[2]), int(m[3].replace(",", "")))
        elif m := HEAP.match(line):
            found["heap"] = (amount(m[1], m[2]), int(m[3].replace(",", "")))
        elif m := OTHER.match(line):
            found["other"] = (amount(m[1], m[2]),)
        elif m := TOTAL.match(line):
            found["total"] = (amount(m[1], m[2]), amount(m[3], m[4]))
    if len(found) < 4:
        return None
    return Sizes(found["code"][0], found["code"][1], found["heap"][0], found["heap"][1], found["other"][0], found["total"][0], found["total"][1])


def provenance(path: Path) -> tuple[str, str, str]:
    """The day, the tool's commit and the fork's commit a build was made from."""
    if not path.exists():
        return "?", "?", "?"
    text = path.read_text(errors="replace")
    day = re.search(r"^recorded: (\d{4}-\d\d-\d\d)", text, re.M)
    commits = COMMIT.findall(text)
    return (day[1] if day else "?", commits[0][:7] if commits else "?", commits[1][:11] if len(commits) > 1 else "?")


def executable_size(directory: Path, listed: dict[Path, int]) -> int | None:
    """The size of the image a build left in directory (a link called image, or its largest executable without a suffix), from
    the file or, if it is not here, from the list."""
    if directory in listed:
        return listed[directory]
    if (directory / "image").exists():
        return (directory / "image").resolve().stat().st_size
    if not directory.is_dir():
        return None
    sizes = [p.stat().st_size for p in directory.iterdir() if p.is_file() and os.access(p, os.X_OK) and not p.suffix]
    return max(sizes, default=None)


def read_listed(path: Path | None, out: Path) -> dict[Path, int]:
    """Directory -> the size of its largest executable, from lines of `size path` (paths below out/, as find prints them)."""
    listed: dict[Path, int] = {}
    for line in path.read_text().splitlines() if path else []:
        size, name = line.split(maxsplit=1)
        directory = out / Path(name).parent
        listed[directory] = max(int(size), listed.get(directory, 0))
    return listed


def discover(out: Path, listed: dict[Path, int]) -> list[Build]:
    builds: list[Build] = []

    def add(group: str, program: str, config: str, log: Path, images: Path, record: Path) -> None:
        if config in CONFIGS or config in OLD_NAMES:
            builds.append(Build(group, program, config, log.parent, read_sizes(log) if log.exists() else None, executable_size(images, listed), *provenance(record)))

    for d in sorted(out.glob("awfy-cost-*-r*")):
        config = d.name.removeprefix("awfy-cost-").rsplit("-r", 1)[0]
        add("AWFY, the rounds of cost.sh", "awfy", config, d / f"{config}.log", d / config, d / "provenance.txt")
    for d in sorted(out.glob("javac-cost-*-r*")):
        config = d.name.removeprefix("javac-cost-").rsplit("-r", 1)[0]
        add("javac, PetClinic and the Barista applications", "javac", config, d / f"{config}.log", d / config, d / "provenance.txt")
    for d in sorted(out.glob("petclinic-r*/*")):
        add("javac, PetClinic and the Barista applications", "petclinic", d.name, d / "build.log", d, d / "provenance.txt")
    for d in sorted((out / "barista").glob("*-r*/*")):
        add("javac, PetClinic and the Barista applications", d.parent.name.rsplit("-r", 1)[0], d.name, d / "build.log", d, d / "provenance.txt")
    for d in sorted((out / "renaissance").glob("*-r*/*")):
        add("Renaissance", d.parent.name.rsplit("-r", 1)[0], d.name, d / "build.log", d, d / "provenance.txt")
    for d in sorted(out.glob("awfy-*-t[0-9]*")):
        setting = re.sub(r"-t\d+$", "", d.name.removeprefix("awfy-"))
        for config in CONFIGS:
            add("AWFY under the inliner's settings (timing builds)", f"awfy {setting}", config, d / f"{config}.log", d / config, d / "provenance.txt")
    return builds


def by_program(builds: list[Build]) -> dict[str, dict[str, dict[str, list[Build]]]]:
    """Group -> program -> configuration -> builds. `kills` counts as fields where the program has no build called fields."""
    grouped: dict[str, dict[str, dict[str, list[Build]]]] = {}
    for b in builds:
        grouped.setdefault(b.group, {}).setdefault(b.program, {c: [] for c in (*CONFIGS, *OLD_NAMES)})[b.config].append(b)
    for programs in grouped.values():
        for configs in programs.values():
            old = configs.pop("kills")
            if not configs["fields"]:
                configs["fields"] = old
    return grouped


def mib(values: list[float]) -> str:
    values = [v / UNIT["MiB"] for v in values]
    return f"{statistics.median(values):.2f}" + (f" ({min(values):.2f}–{max(values):.2f})" if len(values) > 1 else "")


def delta(graal: list[int], fields: list[int], unit: str = "KiB") -> str:
    d = statistics.median(fields) - statistics.median(graal)
    return f"{d / UNIT[unit]:+,.0f} {unit} ({100 * d / statistics.median(graal):+.1f}%)"


def counts(graal: list[int], fields: list[int]) -> str:
    g, f = statistics.median(graal), statistics.median(fields)
    varies = len(set(graal)) > 1 or len(set(fields)) > 1
    return f"{g:,.0f} = {f:,.0f}" if g == f and not varies else f"{g:,.0f} → {f:,.0f}" + (" (varies)" if varies else "")


def apart(graal: list[int], fields: list[int]) -> str:
    if len(graal) < 2 or len(fields) < 2:
        return "one round"
    return "apart" if max(graal) < min(fields) or max(fields) < min(graal) else "overlap"


def report(grouped: dict[str, dict[str, dict[str, list[Build]]]], only: re.Pattern[str] | None) -> None:
    for group, programs in grouped.items():
        shown = {p: c for p, c in programs.items() if not only or only.search(p)}
        if not shown:
            continue
        rows, disk, parts, unreadable, sources = [], [], [], [], set()
        for program, configs in shown.items():
            ok = {c: [b.sizes for b in bs if b.sizes] for c, bs in configs.items()}
            unreadable += [f"{b.directory} ({b.config})" for bs in configs.values() for b in bs if not b.sizes]
            sources |= {(b.day, b.tool, b.fork) for bs in configs.values() for b in bs if b.sizes}
            if not ok["graal"] or not ok["fields"]:
                rows.append((program, f"{len(ok['graal'])}/{len(ok['fields'])}", "-", "-", "no pair of builds", ""))
                continue
            g, f = [s.file for s in ok["graal"]], [s.file for s in ok["fields"]]
            rows.append((program, f"{len(g)}/{len(f)}", mib(g), mib(f), delta(g, f), apart(g, f)))
            on_disk = {c: [b.executable for b in configs[c] if b.sizes and b.executable is not None] for c in CONFIGS}
            if on_disk["graal"] and on_disk["fields"]:
                eg, ef = on_disk["graal"], on_disk["fields"]
                disk.append((program, f"{len(eg)}/{len(ef)}", f"{statistics.median(eg):,.0f}", f"{statistics.median(ef):,.0f}",
                             f"{statistics.median(ef) - statistics.median(eg):+,.0f} B ({100 * (statistics.median(ef) - statistics.median(eg)) / statistics.median(eg):+.2f}%)",
                             f"{min(eg):,}–{max(eg):,}" if len(set(eg)) > 1 else "all equal", f"{min(ef):,}–{max(ef):,}" if len(set(ef)) > 1 else "all equal", apart(eg, ef)))
            parts.append((program, delta([s.code for s in ok["graal"]], [s.code for s in ok["fields"]]),
                          counts([s.units for s in ok["graal"]], [s.units for s in ok["fields"]]),
                          delta([s.heap for s in ok["graal"]], [s.heap for s in ok["fields"]]),
                          counts([s.objects for s in ok["graal"]], [s.objects for s in ok["fields"]]),
                          delta([s.other for s in ok["graal"]], [s.other for s in ok["fields"]])))
        print(f"== {group}")
        print("made from (day, tool, fork): " + "; ".join(" ".join(s) for s in sorted(sources)))
        print("\nthe file (MiB, median and range over the rounds)")
        table(("program", "rounds g/f", "graal", "fields", "fields − graal", "ranges"), rows)
        if disk:
            print("\nthe executable (bytes from stat, median over the rounds)")
            table(("program", "rounds g/f", "graal", "fields", "fields − graal", "graal rounds", "fields rounds", "ranges"), disk)
        print("\nits parts (median over the rounds)")
        table(("program", "code area", "compilation units", "image heap", "objects", "other data"), parts)
        if unreadable:
            print("\nno sizes in the log of: " + ", ".join(unreadable))
        print()


def table(header: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
    widths = [max(len(str(r[i])) for r in (header, *rows)) for i in range(len(header))]
    for r in (header, *rows):
        print("  ".join(str(c).ljust(widths[i]) if i == 0 else str(c).rjust(widths[i]) for i, c in enumerate(r)))


def check_executables(builds: list[Build]) -> None:
    """Compare the log's file size with the executable's, where the size is known. The log rounds to two decimals of its unit, and the
    file may carry a few bytes after the last segment."""
    checked, off = 0, []
    for b in builds:
        if b.sizes and b.executable is not None:
            checked += 1
            unit = UNIT["MiB"] if b.sizes.file >= UNIT["MiB"] else UNIT["KiB"]
            if abs(b.executable - b.sizes.file) > 0.006 * unit:
                off.append(f"{b.directory} ({b.config}): log {b.sizes.file}, stat {b.executable}")
    print(f"executables on disk compared with their logs: {checked}, differing by more than the rounding: {len(off)}")
    for line in off:
        print("  " + line)


def write_builds(builds: list[Build], out: Path, path: Path) -> None:
    header = ["group", "program", "config", "directory", "day", "tool", "fork", "code", "units", "heap", "objects", "other", "image", "file", "stat"]
    lines = ["\t".join(header)]
    for b in builds:
        s = b.sizes
        numbers = [s.code, s.units, s.heap, s.objects, s.other, s.image, s.file] if s else [""] * 7
        lines.append("\t".join(str(x) for x in [b.group, b.program, b.config, b.directory.relative_to(out), b.day, b.tool, b.fork, *numbers, b.executable if b.executable is not None else ""]))
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path, help="graal-native/out")
    parser.add_argument("--only", type=re.compile, help="only the programs whose name matches this regular expression")
    parser.add_argument("--executables", type=Path, help="sizes of the executables the builds left, `size path` lines made on the builder's machine")
    parser.add_argument("--builds", type=Path, help="write a line for every build (its sizes and provenance) to this file")
    args = parser.parse_args()
    builds = discover(args.out, read_listed(args.executables, args.out))
    report(by_program(builds), args.only)
    check_executables(builds)
    if args.builds:
        write_builds(builds, args.out, args.builds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
