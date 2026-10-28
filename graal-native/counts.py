"""What Graal leaves of the program's methods in each image, from the counts.txt of the builds: field loads, loads in loops,
field stores, calls, and where two images differ.

Usage:
    uv run python graal-native/counts.py graal-native/out/awfy-o3/{graal,kills}/counts.txt
    uv run python graal-native/counts.py graal-native/out/awfy-o3/{graal,kills}/counts.txt --diff --match Queens

Each counts.txt lists, for every method the image compiled, the calls, the stores (writes) and the loads (reads)
left in its graph: a field with `×n` is accessed n times, `(loop)` marks the accesses inside a loop. The table has
one row per file; the first is the one the others are compared with. With --diff, the methods whose numbers differ
between the first file and each other one are listed, the largest change first.
"""

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

#: A field with how often it is accessed and whether in a loop: `Variable.mark(loop)×4`, `Planner.currentMark`, `-`
ACCESS = re.compile(r"(?P<field>\S+?)(?P<loop>\(loop\))?(?:×(?P<times>\d+))?")
LINE = re.compile(r"\s+(?P<label>\S+)\s+calls (?P<calls>\d+)\s+writes (?P<writes>.*?)\s+reads (?P<reads>.*)")


@dataclass
class Counts:
    calls: int = 0
    stores: int = 0
    loop_stores: int = 0
    loads: int = 0
    loop_loads: int = 0

    def __add__(self, other: "Counts") -> "Counts":
        return Counts(*(a + b for a, b in zip(vars(self).values(), vars(other).values())))


def accesses(text: str) -> tuple[int, int]:
    """(all, in loops) of a list of accesses as counts.txt writes it."""
    total = loops = 0
    for token in text.split():
        if token == "-":
            continue
        m = ACCESS.fullmatch(token)
        assert m, token
        n = int(m["times"] or 1)
        total += n
        loops += n if m["loop"] else 0
    return total, loops


def read(path: Path) -> dict[str, Counts]:
    """Method → what is left of it. The methods are the unindented lines; a call's detail lines are indented deeper."""
    methods: dict[str, Counts] = {}
    name = None
    for line in path.read_text().splitlines():
        if line and not line[0].isspace():
            name = line
        elif (m := LINE.fullmatch(line)) and name is not None:
            stores, loop_stores = accesses(m["writes"])
            loads, loop_loads = accesses(m["reads"])
            methods[name] = Counts(int(m["calls"]), stores, loop_stores, loads, loop_loads)
    return methods


def total(methods: dict[str, Counts]) -> Counts:
    return sum(methods.values(), Counts())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("counts", type=Path, nargs="+", help="counts.txt of the images; the first is the baseline")
    parser.add_argument("--diff", action="store_true", help="list the methods whose numbers differ from the first file's")
    parser.add_argument("--match", default="", help="only methods whose name matches this regular expression")
    parser.add_argument("--top", type=int, default=15, help="at most this many methods per file with --diff")
    args = parser.parse_args()

    images = {path: read(path) for path in args.counts}
    for path, methods in images.items():
        if not methods:
            parser.error(f"{path} lists no method")
    pattern = re.compile(args.match)
    base_path = args.counts[0]
    base = total({m: c for m, c in images[base_path].items() if pattern.search(m)})
    print(f"{'image':46} {'methods':>7} {'loads':>7} {'in loops':>9} {'stores':>7} {'in loops':>9} {'calls':>6}")
    for path, methods in images.items():
        kept = {m: c for m, c in methods.items() if pattern.search(m)}
        t = total(kept)
        label = "/".join(path.parts[-3:-1])
        row = f"{label:46} {len(kept):>7} {t.loads:>7} {t.loop_loads:>9} {t.stores:>7} {t.loop_stores:>9} {t.calls:>6}"
        if path != base_path:
            row += f"   loads {t.loads - base.loads:+d} ({(t.loads - base.loads) / base.loads:+.1%}), in loops {t.loop_loads - base.loop_loads:+d}" if base.loads else ""
        print(row)
    if args.diff:
        for path in args.counts[1:]:
            before, after = images[base_path], images[path]
            rows = []
            for m in sorted(set(before) | set(after)):
                if not pattern.search(m):
                    continue
                a, b = before.get(m), after.get(m)
                if a != b:
                    rows.append((abs((b.loads if b else 0) - (a.loads if a else 0)) + abs((b.calls if b else 0) - (a.calls if a else 0)), m, a, b))
            print(f"\n{'/'.join(path.parts[-3:-1])} against {'/'.join(base_path.parts[-3:-1])}: {len(rows)} methods differ"
                  + (f", the {args.top} with the largest change:" if len(rows) > args.top else ":"))
            for _, m, a, b in sorted(rows, key=lambda r: -r[0])[:args.top]:
                def show(c: Counts | None) -> str:
                    return "not compiled" if c is None else f"loads {c.loads} ({c.loop_loads} in loops), stores {c.stores}, calls {c.calls}"
                print(f"  {m[:70]}\n      {show(a)}\n   -> {show(b)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
