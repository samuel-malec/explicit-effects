"""Compare the resulting IR obtained directly from Graal opposed to what our rules left out

Usage:
    ./graal-probe/run.sh Examples Signatures > graal-export/out/probe.txt
    uv run python -m rules.compare graal-export/out/examples.json graal-export/out/signatures.json \\
        --probe graal-export/out/probe.txt
"""

import argparse
import re
from collections import Counter
from pathlib import Path

from effects.signatures import analyse, by_field, no_analysis
from graal.graal_import import load
from graal2ct.translate import Translation, structure_name

from . import memory

HEADER = re.compile(r"(\w+\.\w+)\((.*)\)")
ROW = re.compile(r"\s+(bytecode|inlining|no inline)\s+calls \d+\s+writes (.+?)\s+reads (.+)")
SIMPLE = {"Z": "boolean", "B": "byte", "C": "char", "S": "short", "I": "int", "J": "long", "F": "float", "D": "double"}
COLUMNS = ("bytecode", "Graal", "Graal+inl", "export", "one heap", "per field")


def read_probe(text: str) -> dict[str, dict[str, tuple[Counter, Counter]]]:
    """Method → bytecode, no inline, inlining → (writes, reads) by field."""
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


def accesses(program) -> dict[str, tuple[int, int]]:
    """Structure → (stores, loads) left in it."""
    counts = {}
    for s in program.structures:
        kinds = Counter(m.group(1) for lam in s.lambdas for i in lam.body
                        if i.type == "heap" and (m := memory.ACCESS.fullmatch(i.op)))
        counts[s.name] = (kinds["set"], kinds["get"])
    return counts


def compare(export: Path, graal: dict) -> list[tuple[str, list[tuple[int, int] | None]]]:
    facts, graphs = load(export)
    left = {}
    for partition in ("none", "field"):
        effects = no_analysis() if partition == "none" else analyse(facts, by_field)
        program = Translation(graphs, effects).translate(sorted(graphs))
        left.setdefault("export", accesses(program))
        memory.apply(program)
        left[partition] = accesses(program)

    rows = []
    for key, graph in sorted(graphs.items()):
        name = probe_name(graph.name, graph.descriptor)
        modes = graal.get(name)
        if not modes or not sum(modes["bytecode"][0].values()) + sum(modes["bytecode"][1].values()):
            continue
        writes, reads = (set(c) for c in modes["bytecode"])

        def graal_left(mode: str) -> tuple[int, int]:
            w, r = modes[mode]
            return sum(w[f] for f in writes), sum(r[f] for f in reads)

        s = structure_name(key)
        rows.append((name, [graal_left("bytecode"), graal_left("no inline"), graal_left("inlining"),
                            *(left[column].get(s) for column in ("export", "none", "field"))]))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("exports", type=Path, nargs="+")
    parser.add_argument("--probe", type=Path, required=True, help="graal-probe's output")
    args = parser.parse_args()

    graal = read_probe(args.probe.read_text())
    rows = [row for export in args.exports for row in compare(export, graal)]
    width = max(len(name) for name, _ in rows)
    print(f"{'stores/loads left':{width}}  " + "  ".join(f"{c:>9}" for c in COLUMNS))
    for name, cells in rows:
        print(f"{name:{width}}  " + "  ".join(f"{f'{c[0]}/{c[1]}' if c else 'refused':>9}" for c in cells))

    translated = [cells for _, cells in rows if all(cells)]
    totals = [f"{sum(c[i][0] for c in translated)}/{sum(c[i][1] for c in translated)}" for i in range(len(COLUMNS))]
    print(f"{f'total, {len(translated)} methods translated':{width}}  " + "  ".join(f"{t:>9}" for t in totals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
