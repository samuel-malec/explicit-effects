"""What each method, or anything it calls, may write: the kill set of a call to it, for Graal.

Usage:
    uv run python -m effects.kills graal-native/out/examples.json -o graal-native/out/examples.kills
    uv run python -m effects.kills graal-native/out/aliasing.json -o kills.txt \\
        --partition object-field --accesses accesses.txt
"""

import argparse
import sys
from pathlib import Path

from graal.graal_import import PointsToFacts, load_facts

from .signatures import PARTITIONERS, REST, accesses, callees_of, close_over_callees, program_partition, reaching

ANY = "any"
INIT = "init"


def kills(facts: PointsToFacts, partition: str = "field") -> dict[str, str | tuple[str, ...]]:
    """Method → the partitions it may write, a field's own name where the
    partition is all of the field, `init` if it allocates, and the VM's state it
    writes; `any` if it reaches something the facts can't say anything about."""
    part = program_partition(facts, PARTITIONERS[partition](facts))
    rest = part(REST)
    methods = facts.methods
    written: dict[str, set[str]] = {}
    for m, e in methods.items():
        own = {field if part(field, receivers) == rest else part(field, receivers)
               for kind, field, receivers in accesses(e) if kind == "write"}
        written[m] = own | set(e.get("vmWrites", ())) | ({INIT} if e.get("allocates") else set())

    callees = callees_of(facts)
    unknown = reaching(callees, {m: m for m, e in methods.items()
                                 if e.get("unknown") or e.get("unresolved") or any(c not in methods for c in callees[m])})
    close_over_callees(callees, written)
    return {m: ANY if m in unknown else tuple(sorted(written[m])) for m in sorted(methods)}


def partitioned(facts: PointsToFacts, partition: str) -> dict[tuple[str, str], str]:
    """(position, field) → partition, for each access the facts list where it is."""
    part = program_partition(facts, PARTITIONERS[partition](facts))
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

    facts = load_facts(args.export)
    written = kills(facts, args.partition)
    args.out.write_text("".join(f"{m}\t{w if w == ANY else ','.join(w)}\n" for m, w in written.items()))
    narrowed = [w for w in written.values() if w != ANY]
    print(
        f"{len(written)} methods: {len(narrowed)} narrowed, {sum(1 for w in narrowed if not w)} of them writing nothing",
        file=sys.stderr)
    if args.accesses:
        located = partitioned(facts, args.partition)
        args.accesses.write_text("".join(f"{at}\t{field}\t{p}\n" for (at, field), p in sorted(located.items())))
        print(f"{len(located)} accesses in {len(set(located.values()))} partitions", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
