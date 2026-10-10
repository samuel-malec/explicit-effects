"""Compare the resulting IR obtained directly from Graal opposed to what our rules left out

Usage (or make compare):
    ./graal-probe/run.sh Examples Signatures Aliasing > graal-export/out/probe.txt
    uv run python -m rules.compare graal-export/out/{examples,signatures,aliasing}.allocsens.json \\
        --probe graal-export/out/probe.txt

The exports should have allocation sites (-H:AnalysisContextSensitivity=allocsens),
or the object partitions only tell objects apart by type.
"""

import argparse
import re
from collections import Counter
from pathlib import Path

from effects.signatures import PARTITIONERS, analyse, no_analysis
from graal.graal_import import load
from graal2ct.translate import Translation, structure_name

from . import memory

HEADER = re.compile(r"([\w$]+\.[\w$<>]+)\((.*)\)")
ROW = re.compile(r"\s+(bytecode|inlining|no inline|graal|kills|objects|decisions)\s+calls \d+\s+writes (.+?)\s+reads (.+)")
SIMPLE = {"Z": "boolean", "B": "byte", "C": "char", "S": "short", "I": "int", "J": "long", "F": "float", "D": "double"}
COLUMNS = ("bytecode", "Graal", "Graal+inl", "export", "one heap", "per field", "objects", "obj+field")
OURS = ("none", "field", "object", "object-field")
#: Native Image as Graal compiles it, with our kills, with object partitions too, and
#: with our dead stores removed as well, next to the JIT and the rules.
NATIVE = ("Graal", "NI", "NI+kills", "NI+objs", "NI+dead", "per field", "obj+field")
MODES = ("graal", "kills", "objects", "decisions")


def read_native(out: Path) -> dict[str, dict[str, tuple[Counter, Counter]]]:
    """Method → graal, kills, objects, decisions → (writes, reads): what
    graal-native's builds of each program left, as Graal compiles it, with our
    kills, with object partitions too, and with our dead stores removed."""
    methods: dict[str, dict[str, tuple[Counter, Counter]]] = {}
    for counts in sorted(out.glob("*/*/counts.txt")):
        if not counts.parent.parent.name.endswith(("-lie", "-split", "-dead", "-allocsens")):  # controls and variants
            for method, modes in read_probe(counts.read_text()).items():
                methods.setdefault(method, {}).update(modes)
    return {m: modes for m, modes in methods.items() if set(MODES) <= modes.keys()}


def read_probe(text: str) -> dict[str, dict[str, tuple[Counter, Counter]]]:
    """Method → bytecode, no inline, inlining → (writes, reads) by field; the
    accesses in a loop are counted again under `field(loop)`."""
    methods: dict[str, dict[str, tuple[Counter, Counter]]] = {}
    method = None
    for line in text.splitlines():
        if header := HEADER.fullmatch(line):
            method = f"{header.group(1)}({header.group(2)})"
            methods[method] = {}
        elif (row := ROW.fullmatch(line)) and method:
            methods[method][row.group(1)] = (_counts(row.group(2)), _counts(row.group(3)))
    return methods


def _counts(items: str) -> Counter:
    counts: Counter = Counter()
    for item in items.split() if items != "-" else ():
        name, _, n = item.partition("×")
        counts[name.removesuffix("(loop)")] += int(n or 1)
        if name.endswith("(loop)"):
            counts[name] += int(n or 1)
    return counts


def probe_name(name: str, descriptor: str) -> str:
    """Examples.deadStoreBothArms + (LExamples$Counter;Z)V → Examples.deadStoreBothArms(Counter, boolean)"""
    params, i = [], 1
    while descriptor[i] != ")":
        dims = 0
        while descriptor[i] == "[":
            dims, i = dims + 1, i + 1
        if descriptor[i] == "L":
            end = descriptor.index(";", i)
            simple, i = re.split(r"[/$]", descriptor[i + 1:end])[-1], end + 1
        else:
            simple, i = SIMPLE[descriptor[i]], i + 1
        params.append(simple + "[]" * dims)
    return f"{name}({', '.join(params)})"


def accesses(program, in_loops: bool = False) -> dict[str, tuple[int, int]]:
    """Structure → (stores, loads) left in it, or only those in its loops."""
    counts = {}
    for s in program.structures:
        kept = looping(s) if in_loops else {lam.name for lam in s.lambdas}
        kinds = Counter(m.group(1) for lam in s.lambdas if lam.name in kept for i in lam.body
                        if i.type == "heap" and (m := memory.ACCESS.fullmatch(i.op)))
        counts[s.name] = (kinds["set"], kinds["get"])
    return counts


def looping(s) -> set[str]:
    """The λs on a loop: those that jump or branch, through others of the
    method's λs, back to themselves. A call of the method itself isn't a loop."""
    refs = {lam.name: {i.op for i in lam.body if i.type == s.name and i.op != "run"} for lam in s.lambdas}
    found = set()
    for start in refs:
        seen, work = set(), list(refs[start])
        while work:
            name = work.pop()
            if name == start:
                found.add(start)
                break
            if name not in seen:
                seen.add(name)
                work.extend(refs.get(name, ()))
    return found


Row = tuple[str, list[tuple[int, int] | None], list[tuple[int, int] | None], list | None, list | None]


def compare(export: Path, graal: dict, native: dict | None = None) -> list[Row]:
    """(method, what each column leaves, what it leaves in loops, and the
    same next to Native Image if it was built) per method."""
    facts, graphs = load(export)
    left, looped = {}, {}
    for partition in OURS:
        effects = no_analysis() if partition == "none" else analyse(facts, PARTITIONERS[partition](facts))
        program = Translation(graphs, effects).translate(sorted(graphs))
        left.setdefault("export", accesses(program))
        looped.setdefault("export", accesses(program, in_loops=True))
        memory.apply(program)
        left[partition], looped[partition] = accesses(program), accesses(program, in_loops=True)

    rows = []
    for key, graph in sorted(graphs.items()):
        name = probe_name(graph.name, graph.descriptor)
        modes = graal.get(name)
        if not modes or not sum(modes["bytecode"][0].values()) + sum(modes["bytecode"][1].values()):
            continue
        writes, reads = ({f for f in c if not f.endswith("(loop)")} for c in modes["bytecode"])

        def graal_left(mode: str, loop: str = "") -> tuple[int, int]:
            w, r = modes[mode]
            return sum(w[f + loop] for f in writes), sum(r[f + loop] for f in reads)

        s = structure_name(key)
        ours = ("export", *OURS)
        built = (native or {}).get(name)

        def native_left(loop: str = "") -> list | None:
            if not built:
                return None
            images = [tuple(sum(c[f + loop] for f in fields) for c, fields in zip(built[mode], (writes, reads)))
                      for mode in MODES]
            rules = looped if loop else left
            return [graal_left("no inline", loop), *images, rules["field"].get(s), rules["object-field"].get(s)]

        rows.append((name, [*(graal_left(m) for m in ("bytecode", "no inline", "inlining")), *(left[c].get(s) for c in ours)],
                     [*(graal_left(m, "(loop)") for m in ("bytecode", "no inline", "inlining")),
                      *(looped[c].get(s) for c in ours)], native_left(), native_left("(loop)")))
    return rows


def table(title: str, rows: list[tuple[str, list[tuple[int, int] | None]]], width: int, columns=COLUMNS) -> None:
    print(f"{title:{width}}  " + "  ".join(f"{c:>9}" for c in columns))
    for name, cells in rows:
        print(f"{name:{width}}  " + "  ".join(f"{f'{c[0]}/{c[1]}' if c else 'refused':>9}" for c in cells))
    translated = [cells for _, cells in rows if all(cells)]
    totals = [f"{sum(c[i][0] for c in translated)}/{sum(c[i][1] for c in translated)}" for i in range(len(columns))]
    print(f"{f'total, {len(translated)} methods translated':{width}}  " + "  ".join(f"{t:>9}" for t in totals))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("exports", type=Path, nargs="+")
    parser.add_argument("--probe", type=Path, required=True, help="graal-probe's output")
    parser.add_argument("--native", type=Path, help="graal-native's out directory, to set Native Image next to them")
    args = parser.parse_args()

    graal = read_probe(args.probe.read_text())
    native = read_native(args.native) if args.native else None
    rows = [row for export in args.exports for row in compare(export, graal, native)]
    width = max(len(name) for name, *_ in rows)
    table("stores/loads left", [(name, cells) for name, cells, *_ in rows], width)
    print()
    table("stores/loads in loops", [(name, cells) for name, _, cells, *_ in rows
                                    if any(c and sum(c) for c in cells)], width)
    if native:
        print()
        table("native image: stores/loads left", [(name, cells) for name, *_, cells, _ in rows if cells], width, NATIVE)
        print()
        table("native image: in loops", [(name, cells) for name, *_, cells in rows if cells and any(c and sum(c) for c in cells)],
              width, NATIVE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
