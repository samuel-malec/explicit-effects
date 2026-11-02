"""Control flow and loops, image against image: what Graal leaves of the branches, and which loads left a loop.

Usage:
    uv run python scripts/evaluation/control_flow.py graal-native/out/awfy-ctl/{graal,kills}
    uv run python scripts/evaluation/control_flow.py graal-native/out/awfy-ctl/{graal,kills} --methods 10

Each image directory holds control.txt (for every method the image compiled: blocks, control-flow edges, ifs, switches,
loops, calls with an exception edge, deoptimizations, counted at the end of the low tier) and sites.txt (every field load
and store left, with whether it is in a loop and the inlining it came through). The images need to have been built
with -H:+TrackNodeSourcePosition, or the sites cannot be told apart. The first image is the one the others are compared
with.

A load that is in a loop in the first image and outside it in the other, at the same place, is counted as having left the loop:
it was hoisted, or the loop was peeled and a copy of it is outside; the two cannot be told apart from the counts. A load
that is in a loop in the first image and nowhere in the other is gone: forwarded, merged with another, or folded away.
"""

import argparse
from collections import Counter
from pathlib import Path

COLUMNS = ("blocks", "edges", "ifs", "switches", "loops", "exception calls", "deopts")


def control(image: Path) -> dict[str, tuple[int, ...]]:
    rows = {}
    for line in (image / "control.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            method, *numbers = line.split("\t")
            rows[method] = tuple(int(n) for n in numbers)
    return rows


def sites(image: Path) -> tuple[dict[tuple[str, str, str, str], Counter], bool]:
    """(method, load or store, field, inlining) -> how many in a loop (`loop`) and not (`flat`); whether positions were kept."""
    found: dict[tuple[str, str, str, str], Counter] = {}
    positioned = True
    for line in (image / "sites.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            method, kind, where, field, position = line.split("\t")
            positioned = positioned and position != "-"
            found.setdefault((method, kind, field, position), Counter())[where] += 1
    return found, positioned


def moves(base: dict, other: dict, kind: str) -> dict[str, int]:
    """How the loads (or stores) in loops of `base` fare in `other`, place by place."""
    left_and_outside = left_and_gone = entered = 0
    in_loops = outside = 0
    for key in base.keys() | other.keys():
        if key[1] != kind:
            continue
        before, after = base.get(key, Counter()), other.get(key, Counter())
        in_loop, flat = after["loop"] - before["loop"], after["flat"] - before["flat"]
        in_loops += in_loop
        outside += flat
        if in_loop < 0:
            hoisted = min(-in_loop, max(flat, 0))
            left_and_outside += hoisted
            left_and_gone += -in_loop - hoisted
        else:
            entered += in_loop
    return {"in loops": in_loops, "outside loops": outside, "left a loop, now outside": left_and_outside,
            "left a loop, gone": left_and_gone, "entered a loop": entered}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("images", nargs="+", type=Path, help="image directories (graal-native/out/<name>/<mode>); the first is the base")
    parser.add_argument("--methods", type=int, default=8, help="how many methods with the largest change in control-flow edges to list")
    args = parser.parse_args()

    flows = [control(image) for image in args.images]
    print(f"{'image':36} {'methods':>7} " + " ".join(f"{c:>15}" for c in COLUMNS))
    for image, rows in zip(args.images, flows):
        totals = [sum(row[i] for row in rows.values()) for i in range(len(COLUMNS))]
        print(f"{'/'.join(image.parts[-2:]):36} {len(rows):>7} " + " ".join(f"{t:>15}" for t in totals))
    base = flows[0]
    for image, rows in zip(args.images[1:], flows[1:]):
        common = base.keys() & rows.keys()
        changed = sorted(((rows[m][1] - base[m][1], m) for m in common if rows[m] != base[m]), key=lambda c: -abs(c[0]))
        print(f"\n{'/'.join(image.parts[-2:])} against {'/'.join(args.images[0].parts[-2:])}: {len(common)} methods in both "
              f"({len(base.keys() - rows.keys())} only in the first, {len(rows.keys() - base.keys())} only in this one), {len(changed)} with different control flow")
        for edges, method in changed[: args.methods]:
            before, after = base[method], rows[method]
            print(f"  edges {edges:+d}  " + ", ".join(f"{c} {b}->{a}" for c, b, a in zip(COLUMNS, before, after) if a != b) + f"  {method[:80]}")

    placed = [sites(image) for image in args.images]
    if not all(positioned for _, positioned in placed):
        print("\nthe images were built without -H:+TrackNodeSourcePosition: the places of the loads are not told apart, so the moves below are not meaningful")
    for kind in ("load", "store"):
        print(f"\n{kind}s")
        for image, (found, _) in zip(args.images[1:], placed[1:]):
            result = moves(placed[0][0], found, kind)
            print(f"  {'/'.join(image.parts[-2:])}: " + ", ".join(f"{name} {value:+d}" if name in ("in loops", "outside loops") else f"{name} {value}" for name, value in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
