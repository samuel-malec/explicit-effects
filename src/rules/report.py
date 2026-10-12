"""What the translation and the rules make of a whole program.

Usage:
    uv run python -m rules.report graal-export/out/awfy.json graal-export/out/awfy.allocsens.json

Takes an export, and optionally the same program exported with allocation
sites for the object partitions, and prints:
- how many of the program's methods translate, and why the others don't;
- how many touch everything, and which effects make them;
- the field stores and loads in the translated methods, and what the rules
  leave of them under each partitioning.

"""

import argparse
import re
from collections import Counter
from pathlib import Path

from effects.signatures import PARTITIONERS, REST, analyse, no_analysis
from graal.graal_import import load
from graal2ct.translate import Translation, structure_name

from . import memory
from .compare import MODES, accesses, looping, probe_name, read_probe

# A refusal's reason
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

    print(f"\n{'partitioning':14} {'partitions':>10} {'export':>9} {'rules':>9}")
    for partition in ("none", "field", "object", "object-field"):
        source = export if not partition.startswith("object") else allocsens
        if source is None:
            continue

        f, g = load(source)
        effects = no_analysis() if partition == "none" else analyse(f, PARTITIONERS[partition](f))
        translated = Translation(g, effects).translate(sorted(g))
        before = "/".join(str(sum(n[i] for n in accesses(translated).values())) for i in (0, 1))
        memory.apply(translated)
        left = "/".join(str(sum(n[i] for n in accesses(translated).values())) for i in (0, 1))
        partitions = len([p for p in effects.partitions if p != effects.partition(REST)])
        print(f"{partition:14} {partitions:>10} {before:>9} {left:>9}")


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


def side_by_side(export: Path, allocsens: Path, images: list[Path]) -> None:
    """The token form next to Native Image, method by method: the field stores and loads
    the export has, what our rules leave of them, and what each image leaves of them."""
    ours: dict[str, dict[str, tuple[int, int]]] = {}
    names: dict[str, str] = {}
    for column, path, partition in (("per field", export, "field"), ("obj+field", allocsens, "object-field")):
        facts, graphs = load(path)
        program = Translation(graphs, analyse(facts, PARTITIONERS[partition](facts))).translate(sorted(graphs))
        if column == "per field":
            ours["export"], ours["export in loops"] = accesses(program), accesses(program, in_loops=True)
        
        memory.apply(program)
        ours[column], ours[column + " in loops"] = accesses(program), accesses(program, in_loops=True)
        
        for key, graph in graphs.items():  # as the images name a method: no package
            simple = graph.name.rsplit(".", 1)
            names[structure_name(key)] = probe_name(simple[0].rsplit(".", 1)[-1] + "." + simple[1], graph.descriptor)
    
    built: dict[str, dict[str, tuple[Counter, Counter]]] = {}
    
    for out in images:
        for mode in MODES:
            if (out / mode / "counts.txt").exists():
                for method, modes in read_probe((out / mode / "counts.txt").read_text()).items():
                    built.setdefault(method, {}).update(modes)
    
    columns = ("export", "per field", "obj+field", *MODES)
    rows = []
    
    for structure, name in sorted(names.items(), key=lambda kv: kv[1]):
        cells = [ours[c].get(structure) for c in columns[:3]]
        if None in cells or not all(m in built.get(name, {}) for m in MODES):
            continue
        for loops in ("", " in loops"):
            mine = [ours[c + loops][structure] for c in columns[:3]]
            theirs = [tuple(sum(n for f, n in c.items() if f.endswith("(loop)") == bool(loops)) for c in built[name][m]) for m in MODES]
            rows.append((name, loops, mine + theirs))
    for loops in ("", " in loops"):
        chosen = [cells for _, l, cells in rows if l == loops]
        print(f"\n{len(chosen)} methods translated and compiled, field stores/loads{loops}:")
        print("  " + "  ".join(f"{c:>10}" for c in columns))
        print("  " + "  ".join(f"{sum(c[i][0] for c in chosen)}/{sum(c[i][1] for c in chosen):<6}".rjust(10) for i in range(len(columns))))
    print("\nwhere our rules and the kills image differ, all accesses:")
    for name, loops, cells in rows:
        if not loops and cells[1] != cells[4]:
            print(f"  {name:70} " + "  ".join(f"{c[0]}/{c[1]}" for c in cells))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("allocsens", type=Path, nargs="?", help="the same program, exported with allocation sites")
    parser.add_argument("--native", type=Path, nargs="*", default=[], help="graal-native's builds of the program")
    parser.add_argument("--side", type=Path, nargs="*", default=[],
                        help="graal-native's builds whose exports were translated, to set the rules next to the images")
    args = parser.parse_args()
    if args.side:
        side_by_side(args.export, args.allocsens, args.side)
        return 0
    report(args.export, args.allocsens)
    for out in args.native:
        native(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
