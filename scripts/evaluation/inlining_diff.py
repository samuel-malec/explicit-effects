"""What Graal inlined in builds of one program under different inliner settings: the inlined call sites against a reference build.

Usage:
    uv run python scripts/evaluation/inlining_diff.py graal-native/out/awfy-base graal-native/out/awfy-inl1000 graal-native/out/awfy-cgs50
    uv run python scripts/evaluation/inlining_diff.py out/awfy-base out/awfy-inl300 --watch 'Queens.placeQueen(int)' --watch 'Queens.queens()'

Each directory is one run.sh build with source positions and holds graal/shape.txt and graal/inlined.txt (--config fields reads the
fields image instead). The first directory is the reference. For each directory: the methods, the inlined call sites in all, the
methods whose inlining differs from the reference (the hash of their inlined call sites, over the methods both builds compiled), and,
for each watched method, the methods inlined directly into it. A setting that changes nothing shows 0 methods with other inlining.
"""

import argparse
import collections
import re
from pathlib import Path

DEFAULT_WATCH = ["Queens.placeQueen(int)", "Queens.queens()"]


def read_shapes(path: Path) -> dict[str, tuple[int, int, str]]:
    """method -> (nodes, inlined call sites, inlining hash)"""
    found = {}
    for line in path.read_text().splitlines():
        parts = line.split("\t")
        if line.startswith("#") or len(parts) < 8:
            continue
        found[parts[0]] = (int(parts[1]), int(parts[5]), parts[6])
    return found


def read_inlined(path: Path) -> dict[str, list[list[str]]]:
    """method -> the chains of its inlined call sites (callee, then the callers it was inlined into, innermost first)"""
    found: dict[str, list[list[str]]] = collections.defaultdict(list)
    for line in path.read_text().splitlines():
        parts = line.split("\t")
        if not line.startswith("#") and len(parts) == 2:
            found[parts[0]].append(parts[1].split(" < "))
    return found


def short(callee: str) -> str:
    return re.sub(r"\(.*", "", callee)


def direct(chains: list[list[str]]) -> str:
    """the methods inlined straight into the method (a chain of two: the callee and the call site in the method), with counts"""
    counts = collections.Counter(short(chain[0]) for chain in chains if len(chain) == 2)
    return ", ".join(f"{name}{'' if n == 1 else f' x{n}'}" for name, n in sorted(counts.items())) or "nothing"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--config", default="graal", help="the image whose files are read (graal or fields)")
    parser.add_argument("--watch", action="append", help=f"a method whose directly inlined methods are listed (default {DEFAULT_WATCH})")
    args = parser.parse_args()
    watch = args.watch or DEFAULT_WATCH
    builds = []
    for d in args.directories:
        shapes = read_shapes(d / args.config / "shape.txt")
        inlined = read_inlined(d / args.config / "inlined.txt")
        builds.append((d.name.removeprefix("awfy-"), shapes, inlined))
    reference = builds[0][1]
    print(f"{'setting':22}{'methods':>8}{'nodes':>9}{'inlined sites':>15}{'other inlining':>16}   " + "   ".join(f"inlined into {w}" for w in watch))
    for name, shapes, inlined in builds:
        common = [m for m in shapes if m in reference]
        other = sum(shapes[m][2] != reference[m][2] for m in common)
        sites = sum(s[1] for s in shapes.values())
        nodes = sum(s[0] for s in shapes.values())
        watched = "   ".join(f"{direct(inlined.get(w, []))}" if w in shapes else "(not compiled)" for w in watch)
        print(f"{name:22}{len(shapes):8}{nodes:9}{sites:15}{other:11} of {len(common):<4}{watched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
