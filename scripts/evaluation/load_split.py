"""Where the loads of a program are: in its controls, in methods that do not change, or in methods that lose loads.

Usage:
    uv run python scripts/evaluation/load_split.py graal-native/out/examples-repro/{graal,fields}/counts.txt

The program's designed examples come with controls: a method that must keep its loads because the call may write the field or the
reference may alias another (its name ends in `Control`). Counted with the rest, they make the percentage smaller than what the
facts do where they apply. The totals in the loads table count every method; this splits them. The first file is the baseline, the
second the image under test. The methods are those both files list, and the three groups add up to the totals counts.py prints.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from counts import read, total  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("baseline", type=Path, help="counts.txt of the image to compare with (graal)")
    parser.add_argument("image", type=Path, help="counts.txt of the image under test (fields)")
    args = parser.parse_args()

    before, after = read(args.baseline), read(args.image)
    groups: dict[str, list[tuple[int, int]]] = {"controls": [], "unchanged": [], "reduced": []}
    for method in before.keys() & after.keys():
        name = method.split("(")[0].rsplit(".", 1)[-1]
        old, new = before[method].loads, after[method].loads
        kind = "controls" if name.endswith("Control") else "unchanged" if old == new else "reduced"
        groups[kind].append((old, new))

    print(f"{'':12} {'methods':>7} {'before':>7} {'after':>7}")
    for kind, rows in groups.items():
        print(f"{kind:12} {len(rows):>7} {sum(o for o, _ in rows):>7} {sum(n for _, n in rows):>7}")
    everything = [row for rows in groups.values() for row in rows]
    old, new = sum(o for o, _ in everything), sum(n for _, n in everything)
    print(f"{'all':12} {len(everything):>7} {old:>7} {new:>7}   ({(new - old) / old:+.1%})" if old else "no loads")
    # the control of this script: the groups must add up to counts.py's totals over the methods both files list
    common = before.keys() & after.keys()
    assert old == total({m: before[m] for m in common}).loads and new == total({m: after[m] for m in common}).loads
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
