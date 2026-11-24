"""The most loads that more precise kill sets could remove, next to what `fields` removes: the loads Graal leaves in the program's methods in the
image whose calls kill nothing (`-H:SideEffectAnalysisKillSets=none`, never sound), in the `fields` image and in the `graal` image of the same program.

Usage:
    uv run python scripts/evaluation/upper_bound.py awfy=out/awfy-t2-1/graal/counts.txt,out/awfy-t2-1/fields/counts.txt,out/awfy-ub-none/fields/counts.txt \\
        petclinic=out/petclinic-t2r1/graal/counts.txt,out/petclinic-t2r1/fields/counts.txt,out/petclinic-ub-none/fields/counts.txt

Each argument is a name and the counts.txt of the three images, `graal`, `fields` and `none`, in that order. The table has one row per program:
the loads (and those in loops) of each image, the change of `fields` and of `none` against `graal`, and the share of the bound that `fields` reaches
(its removed loads over those the bound removes). If `none` leaves about as many loads as `fields`, no more precise analysis can pay on the program;
if far fewer, there is headroom. The images of `none` are never run: the bound is only counted.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from counts import Counts, read, total


def change(base: int, now: int) -> str:
    return f"{now:,} ({100 * (now - base) / base:+.1f}%)" if base else f"{now:,}"


def row(name: str, graal: Counts, fields: Counts, none: Counts) -> str:
    removed_by_bound = graal.loads - none.loads
    share = f"{100 * (graal.loads - fields.loads) / removed_by_bound:.0f}%" if removed_by_bound > 0 else "-"
    return (f"{name:22} {graal.loads:>9,} {change(graal.loads, fields.loads):>18} {change(graal.loads, none.loads):>18} {share:>7}   "
            f"{graal.loop_loads:>7,} {fields.loop_loads:>7,} {none.loop_loads:>7,}   {graal.calls:>8,} {fields.calls:>8,} {none.calls:>8,}")


def common(graal: dict[str, Counts], fields: dict[str, Counts], none: dict[str, Counts]) -> tuple[Counts, Counts, Counts, int]:
    """The three images' totals over the methods all three compile: an image that inlines differently compiles other methods, and a total over
    all of them would then compare different sets."""
    names = set(graal) & set(fields) & set(none)
    return (total({m: graal[m] for m in names}), total({m: fields[m] for m in names}), total({m: none[m] for m in names}), len(names))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("programs", nargs="+", metavar="NAME=GRAAL,FIELDS,NONE", help="a name and the counts.txt of the three images")
    args = parser.parse_args()
    print("every method an image compiles")
    print(f"{'program':22} {'graal':>9} {'fields, loads':>18} {'none, loads':>18} {'share':>7}   {'in loops: graal':>7} {'fields':>7} {'none':>7}   {'calls: graal':>8} {'fields':>8} {'none':>8}")
    rows = []
    for spec in args.programs:
        name, _, paths = spec.partition("=")
        files = paths.split(",")
        if len(files) != 3:
            parser.error(f"{spec}: three counts.txt expected, graal, fields and none")
        graal, fields, none = (read(Path(f)) for f in files)
        rows.append((name, graal, fields, none))
        print(row(name, total(graal), total(fields), total(none)))
    print("\nthe methods all three images compile")
    print(f"{'program':22} {'methods':>8}   {'graal':>9} {'fields, loads':>18} {'none, loads':>18} {'share':>7}   {'in loops: graal':>7} {'fields':>7} {'none':>7}")
    for name, graal, fields, none in rows:
        g, f, n, count = common(graal, fields, none)
        removed_by_bound = g.loads - n.loads
        share = f"{100 * (g.loads - f.loads) / removed_by_bound:.0f}%" if removed_by_bound > 0 else "-"
        print(f"{name:22} {count:>8}   {g.loads:>9,} {change(g.loads, f.loads):>18} {change(g.loads, n.loads):>18} {share:>7}   {g.loop_loads:>7,} {f.loop_loads:>7,} {n.loop_loads:>7,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
