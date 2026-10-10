"""What the translation and the rules make of a whole program.

Usage:
    uv run python -m rules.report graal-export/out/awfy.json graal-export/out/awfy.allocsens.json

Takes an export, and optionally the same program exported with allocation
sites for the object partitions, and prints:
- how many of the program's methods translate, and why the others don't;
- how many touch everything, and which effects make them;
- the field stores and loads in the translated methods, and what the rules
  leave of them under each partitioning, with dead stores the trap model's and
  Java's.

With --native, also what Native Image leaves of the program's methods in
each image graal-native built of it (graal-native/out/<name>/).
"""

import argparse
import re
from collections import Counter
from pathlib import Path

from effects.signatures import PARTITIONERS, REST, analyse, no_analysis
from graal.graal_import import load
from graal2ct.translate import Translation

from . import memory
from .compare import MODES, accesses, read_probe

#: A refusal's reason, by what it starts with.
REASONS = [
    (r"allocation after escape analysis", "allocation after escape analysis"),
    (r"call to .* with \d+ targets", "a call with several targets"),
    (r"(Load|Store)IndexedNode|AccessIndexed", "an array element access"),
    (r"exception handler", "a caught exception"),
    (r"Monitor(Enter|Exit)Node", "a monitor"),
    (r"ordered \(volatile\)", "a volatile access"),
    (r"no graph", "no graph (native or abstract)"),
    (r"constant ", "a constant other than an int or null"),
]


def reason(why: str) -> str:
    return next((name for pattern, name in REASONS if re.search(pattern, why)), why.split(" at bci")[0])


def report(export: Path, allocsens: Path | None) -> None:
    facts, graphs = load(export)
    program = sorted(graphs)
    translation = Translation(graphs, no_analysis())
    translation.translate(program)
    refused = Counter(reason(why) for why in translation.refused.values())
    print(f"{len(program)} methods of the program, {len(program) - len(translation.refused)} translated")
    for why, n in refused.most_common():
        print(f"  {n:5}  refused: {why}")

    effects = analyse(facts, PARTITIONERS["field"](facts))
    keys = {g.name + g.descriptor for g in graphs.values()}
    opaque = Counter(effects.signatures[k].why.split(": ", 1)[-1] for k in keys if k in effects.signatures and effects.signatures[k].opaque)
    print(f"\n{sum(opaque.values())} of them touch everything, because they reach")
    for why, n in opaque.most_common(8):
        print(f"  {n:5}  {why}")

    print(f"\n{'partitioning':14} {'partitions':>10} {'export':>9} {'trap model':>11} {'Java':>9}")
    for partition in ("none", "field", "object", "object-field"):
        source = export if not partition.startswith("object") else allocsens
        if source is None:
            continue
        f, g = load(source)
        effects = no_analysis() if partition == "none" else analyse(f, PARTITIONERS[partition](f))
        before = left = java = None
        for mode in ("export", "trap", "java"):
            translated = Translation(g, effects).translate(sorted(g))
            if mode != "export":
                memory.apply(translated, java=mode == "java")
            stores, loads = (sum(n[i] for n in accesses(translated).values()) for i in (0, 1))
            before, left, java = (f"{stores}/{loads}", left, java) if mode == "export" else \
                (before, f"{stores}/{loads}", java) if mode == "trap" else (before, left, f"{stores}/{loads}")
        partitions = len([p for p in effects.partitions if p != effects.partition(REST)])
        print(f"{partition:14} {partitions:>10} {before:>9} {left:>11} {java:>9}")


def native(out: Path) -> None:
    """What each image of graal-native's round trip left of the program's methods."""
    print(f"\n{out.name}: {'stores':>7} {'(loops)':>7} {'loads':>6} {'(loops)':>7} {'calls':>6}   calls narrowed to nothing/one/several,"
          f" fields partitioned, dead stores removed")
    for mode in MODES:
        counts = out / mode / "counts.txt"
        if not counts.exists():
            continue
        text = counts.read_text()
        total = Counter()
        for writes, reads in (modes[mode] for modes in read_probe(text).values()):
            for what, counted in (("stores", writes), ("loads", reads)):
                for f, n in counted.items():  # an access in a loop is counted under field(loop) alone
                    total[what] += n
                    total[what + " in loops"] += n if f.endswith("(loop)") else 0
        calls = sum(int(n) for n in re.findall(r"^\s+\w+\s+calls (\d+)", text, re.M))
        kills = [line.split(" kills ")[1] for line in text.splitlines() if re.match(r"\s{8}\S.* kills ", line)]
        narrowed = "/".join(str(n) for n in (sum(k == "nothing" for k in kills), sum(k != "nothing" and len(k.split()) == 1 for k in kills),
                                              sum(len(k.split()) > 1 for k in kills)))
        partitioned = len(re.findall(r"^\s{8}\S+ in @", text, re.M))
        dead = text.count("dead store to")
        print(f"{mode:{len(out.name) + 1}} {total['stores']:>7} {total['stores in loops']:>7} {total['loads']:>6} {total['loads in loops']:>7}"
              f" {calls:>6}   {narrowed}, {partitioned}, {dead}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("allocsens", type=Path, nargs="?", help="the same program, exported with allocation sites")
    parser.add_argument("--native", type=Path, nargs="*", default=[], help="graal-native's builds of the program")
    args = parser.parse_args()
    report(args.export, args.allocsens)
    for out in args.native:
        native(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
