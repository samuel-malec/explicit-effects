"""What each method, or anything it calls, may write: the kill set of a call to it, for Graal.

Usage:
    uv run python -m effects.kills graal-native/out/loadstoreelimination.json -o graal-native/out/loadstoreelimination.kills
    uv run python -m effects.kills graal-native/out/aliasing.json -o kills.txt \\
        --partition object-field --accesses accesses.txt
    uv run python -m effects.kills export.json -o ceiling.kills --ignore all
"""

import argparse
import re
import sys
from collections.abc import Collection
from pathlib import Path

from graal.graal_import import PointsToFacts, load_facts

from .signatures import (PARTITIONERS, REST, accesses, callees_of, close_over_callees, program_partition, reaching,
                         synchronizing)

ANY = "any"  # the kill set of a call that may write anything
INIT = "init"  # in a kill set: the call may allocate

#: Effects whose kill can be left out, to measure what more precise kill sets could give Graal. Never sound, so
#: never for an image whose output matters. Each maps to the kinds of node that are that effect among a method's
#: unknown effects, or to None when it isn't one kind of node (`blocks` handles those). The first three are what
#: most opaque methods reach first; every method still opaque without them reaches each of the others, so only
#: leaving all of them out shows the most the kill sets could do.
IGNORABLE: dict[str, tuple[str, ...] | None] = {
    "identity-hash": ("SubstrateIdentityHashCodeNode",),
    "class-initialization": ("EnsureClassInitializedNode",),
    "synchronization": None,  # every acquire and release
    "unresolved-calls": None,  # a call the analysis could not resolve
    "calls-without-facts": None,  # a call of a method the export has no facts for
    "other-effects": None,  # every other unknown effect: native transitions, raw writes, snippets, ...
}
NAMED_NODES = {node for nodes in IGNORABLE.values() if nodes for node in nodes}


def node_kind(text: str) -> str:
    """The node kind of an unknown effect's text, without its position or address: `EnsureClassInitializedNode`."""
    return re.split(r" at | \(|:", text, maxsplit=1)[0].strip()


def blocks(facts: PointsToFacts, method: dict, ignore: Collection[str] = ()) -> bool:
    """Whether the method by itself makes its kill set everything: an unknown effect (any of them, not just the
    first), synchronization that may order this thread with another, an unresolved call, or a call to a method
    without facts. The effects named in `ignore` don't count."""
    ignored = {node for name in ignore for node in (IGNORABLE[name] or ())}
    for text in method.get("unknown", ()):
        node = node_kind(text)
        counts = node not in ignored if node in NAMED_NODES else "other-effects" not in ignore
        if counts:
            return True
    synchronizes = synchronizing(facts, method, "acquires") or synchronizing(facts, method, "releases")
    if "synchronization" not in ignore and synchronizes:
        return True
    if "unresolved-calls" not in ignore and method.get("unresolved"):
        return True
    return "calls-without-facts" not in ignore and any(c not in facts.methods for c in method.get("callees", ()))


def kills(facts: PointsToFacts, partition: str = "field", ignore: Collection[str] = ()) -> dict[str, str | tuple[str, ...]]:
    """Each method's kill set: the partitions it, or anything it may call, may write. A partition that is all of
    a field goes by the field's name; the set also has `init` if the method allocates, and the VM's own
    locations it writes. It is `any` if the method reaches something the facts can't describe, or
    synchronization that may order this thread with another. A lock or volatile field that only this thread
    reaches orders nothing, and kills nothing.

    A release kills everything too, though it writes nothing itself: if the call killed nothing of a location,
    Graal could move a load of it from before the call to after it, where it may read what another thread
    wrote after seeing the release. A kill set can't stop loads moving below a call without stopping them
    moving above it as well.

    `ignore` (names from IGNORABLE) leaves those effects' kills out: a measurement, never sound."""
    if invalid := set(ignore) - IGNORABLE.keys():
        raise ValueError(f"cannot ignore {sorted(invalid)}: only {sorted(IGNORABLE)}")
    part = program_partition(facts, PARTITIONERS[partition](facts))
    rest = part(REST)
    methods = facts.methods
    written: dict[str, set[str]] = {}
    for m, e in methods.items():
        # A write outside the program's partitions (a platform field's) goes by the field's own name.
        own = {field if (p := part(field, receivers)) == rest else p
               for kind, field, receivers in accesses(e) if kind == "write"}
        written[m] = own | set(e.get("vmWrites", ())) | ({INIT} if e.get("allocates") else set())

    callees = callees_of(facts)
    kill_everything = reaching(callees, {m: m for m, e in methods.items() if blocks(facts, e, ignore)})
    # A method that reaches something unknown kills everything, whatever it writes. Every other method only
    # calls methods like itself, so only those need their callees' writes: on javac's export a third of the
    # methods, and a tenth of the time.
    close_over_callees({m: cs for m, cs in callees.items() if m not in kill_everything}, written)
    return {m: ANY if m in kill_everything else tuple(sorted(written[m])) for m in sorted(methods)}


def partitioned(facts: PointsToFacts, partition: str) -> dict[tuple[str, str], str]:
    """(position, field) → partition, for each access the export gives a position. It pairs the export's
    accesses with `accesses(e)`, which lists them first and in the same order."""
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
    parser.add_argument("--assumptions", help="the thread-escape assumptions to read, from an export made with all of them")
    parser.add_argument("--accesses", type=Path, help="where to write each access's partition")
    parser.add_argument("--ignore", default="", help="measurement only, never sound: leave out the kill of these effects (comma-separated: "
                        + ", ".join(IGNORABLE) + "; all: every one), to see the most that precise kill sets could give Graal")
    args = parser.parse_args()
    ignore = [name for name in args.ignore.split(",") if name]
    if ignore == ["all"]:
        ignore = list(IGNORABLE)
    if invalid := set(ignore) - IGNORABLE.keys():
        parser.error(f"cannot ignore {sorted(invalid)}: only {sorted(IGNORABLE)}")
    if ignore:
        print(f"warning: the kill of {', '.join(ignore)} is left out: these kill sets are an upper bound, not sound", file=sys.stderr)

    facts = load_facts(args.export, args.assumptions)
    written = kills(facts, args.partition, ignore)
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
