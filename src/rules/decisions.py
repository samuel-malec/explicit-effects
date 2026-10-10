"""Which stores Graal may remove: the dead stores the rules find, in Java.

Usage:
    uv run python -m rules.decisions graal-native/out/examples/decisions/export.json -o dead.txt

Translates the program's methods of an export and removes dead stores, after
the shape the rules need but without forwarding a load first, so that a store
is dead whatever Graal does with the loads. Only what is dead in Java goes:
nothing between a store and the store that overwrites it may throw, since an
exception leaving the method lets a caller read it.

Writes one line per dead store: where it is, a tab, and its field. A store the
rules copied counts only if every copy went.
"""

import argparse
import sys
from pathlib import Path

from effects.signatures import PARTITIONERS, analyse
from graal.graal_import import load
from graal2ct.translate import Translation

from . import memory


def dead_stores(export: Path, partition: str = "field") -> list[str]:
    """`position\\tfield` of each store that is dead in Java."""
    facts, graphs = load(export)
    program = Translation(graphs, analyse(facts, PARTITIONERS[partition](facts))).translate(sorted(graphs))
    done = memory.apply(program, forward=False, java=True)
    left = {f"{i.at}\t{i.note}" for s in program.structures for lam in s.lambdas for i in lam.body
            if (m := memory.ACCESS.fullmatch(i.op)) and m.group(1) == "set" and i.at}
    return sorted(set(done.dead) - left)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("export", type=Path, help="facts and graphs exported by graal-export")
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument("--partition", choices=["field", "object-field"], default="field")
    args = parser.parse_args()

    dead = dead_stores(args.export, args.partition)
    args.out.write_text("".join(f"{line}\n" for line in dead))
    print(f"{len(dead)} dead store(s), in Java", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
