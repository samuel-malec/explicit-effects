"""What each method may write, as Graal's memory kills: the answer of the round trip.

Usage:
    uv run python -m effects.kills graal-native/out/examples.json -o graal-native/out/examples.kills
    uv run python -m effects.kills graal-native/out/aliasing.json -o kills.txt \\
        --partition object-field --accesses accesses.txt

Writes one line per method the facts know: its name and descriptor, and
what it, or anything it calls, may write. That is either `any`, or the
partitions it writes, comma-separated, possibly none. A method may write `any`
when its signature touches everything, or when it writes the rest of memory,
which no field of the program names: a platform field or an allocation.

With the default `--partition field` the partitions are fields and array
kinds, which are Graal's own memory locations. With `object-field` they are
fields of sets of objects, `Aliasing$Counter.value@main:199`, and
`--accesses` writes the partition of each access the facts list, by where it
is: the position, the field, and the partition. Graal can then
give each access to a field that location instead.
"""

import argparse
import json
import sys
from pathlib import Path

from graal.graal_import import PointsToFacts

from .signatures import PARTITIONERS, REST, accesses, analyse

ANY = "any"


def kills(facts: PointsToFacts, partition: str = "field") -> dict[str, str | tuple[str, ...]]:
    """Method → `any`, or the partitions it may write."""
    effects = analyse(facts, PARTITIONERS[partition](facts))
    return {m: ANY if s.opaque or effects.partition(REST) in s.writes else tuple(sorted(s.writes))
            for m, s in sorted(effects.signatures.items())}


def partitioned(facts: PointsToFacts, partition: str) -> dict[tuple[str, str], str]:
    """(position, field) → partition, for each access the facts list where it is."""
    part = analyse(facts, PARTITIONERS[partition](facts)).partition
    return {(a["at"], a["field"]): part(field, receivers)
            for e in facts.methods.values()
            for a, (_, field, receivers) in zip(e.get("accesses", ()), accesses(e))
            if a.get("at")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("export", type=Path, help="facts or graphs exported by graal-export")
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument("--partition", choices=["field", "object-field"], default="field")
    parser.add_argument("--accesses", type=Path, help="where to write each access's partition")
    args = parser.parse_args()

    data = json.loads(args.export.read_text())
    facts = PointsToFacts(data.get("methods", {}), data.get("fields", {}))
    written = kills(facts, args.partition)
    args.out.write_text("".join(f"{m}\t{w if w == ANY else ','.join(w)}\n" for m, w in written.items()))
    narrowed = [w for w in written.values() if w != ANY]
    print(f"{len(written)} methods: {len(narrowed)} narrowed, {sum(1 for w in narrowed if not w)} of them writing nothing",
          file=sys.stderr)
    if args.accesses:
        located = partitioned(facts, args.partition)
        args.accesses.write_text("".join(f"{at}\t{field}\t{p}\n" for (at, field), p in sorted(located.items())))
        print(f"{len(located)} accesses in {len(set(located.values()))} partitions", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
