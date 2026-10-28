"""What each method, or anything it calls, may write: the kill set of a call to it, for Graal.

Usage:
    uv run python -m effects.kills graal-native/out/examples.json -o graal-native/out/examples.kills
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

from .signatures import PARTITIONERS, REST, accesses, callees_of, close_over_callees, program_partition, reaching, synchronizing

ANY = "any"
INIT = "init"

#: The effects whose kill can be left out for a measurement, and what each is in the facts: the kinds of node that
#: are an unknown effect (None: not a node, see `blocks`). With them left out the kill sets are an upper bound
#: of what Graal could be told, to see what making them precise could give. Never sound, so never for a build
#: whose output is to be kept. The first three are the effects the notes found in front of most opaque methods;
#: behind them are the others, each reached by all the methods that remain, so only the last (everything the
#: facts cannot name) tells the most the kill sets could do.
IGNORABLE: dict[str, tuple[str, ...] | None] = {
    "identity-hash": ("SubstrateIdentityHashCodeNode",),
    "class-initialization": ("EnsureClassInitializedNode",),
    "synchronization": None,  # every acquire and release
    "unresolved-calls": None,  # a call the analysis could not resolve
    "calls-without-facts": None,  # a call of a method the export has no facts for
    "other-effects": None,  # every other unknown effect: native transitions, raw writes, snippets, ...
}
NAMED = {node for nodes in IGNORABLE.values() if nodes for node in nodes}


def kind(text: str) -> str:
    """A fact's text without its position and the node's address: `EnsureClassInitializedNode`."""
    return re.split(r" at | \(|:", text, maxsplit=1)[0].strip()


def blocks(facts: PointsToFacts, method: dict, ignore: Collection[str] = ()) -> bool:
    """Whether the method itself has what makes its kill set everything: an effect the facts can't name
    (every one of them, not only the first), synchronization that may order this thread with another, a call
    that is unresolved, or a call of a method without facts. What `ignore` names does not count."""
    ignored = {node for name in ignore for node in (IGNORABLE[name] or ())}
    for text in method.get("unknown", ()):
        if kind(text) not in ignored and not ("other-effects" in ignore and kind(text) not in NAMED):
            return True
    if "synchronization" not in ignore and (synchronizing(facts, method, "acquires") or synchronizing(facts, method, "releases")):
        return True
    if "unresolved-calls" not in ignore and method.get("unresolved"):
        return True
    return "calls-without-facts" not in ignore and any(c not in facts.methods for c in method.get("callees", ()))


def kills(facts: PointsToFacts, partition: str = "field", ignore: Collection[str] = ()) -> dict[str, str | tuple[str, ...]]:
    """Method → the partitions it may write, a field's own name where the
    partition is all of the field, `init` if it allocates, and the VM's state it
    writes; `any` if it reaches something the facts can't say anything about, or
    synchronization that may order this thread with another. A lock or a volatile
    field only this thread reaches (`synchronizing`) orders it with no one, and kills
    nothing.

    A release kills everything too, although it writes only its own writes: Graal
    would let a load before a call that kills nothing of its location float below
    the call, where it may read what another thread wrote after the release saw
    it. A kill set can't stop loads below the call without stopping those above.

    `ignore` (names of `IGNORABLE`) leaves the kill of those effects out: a measurement of what precise
    kill sets could give, never sound."""
    if unknown := set(ignore) - IGNORABLE.keys():
        raise ValueError(f"cannot ignore {sorted(unknown)}: only {sorted(IGNORABLE)}")
    part = program_partition(facts, PARTITIONERS[partition](facts))
    rest = part(REST)
    methods = facts.methods
    written: dict[str, set[str]] = {}
    for m, e in methods.items():
        own = {field if part(field, receivers) == rest else part(field, receivers)
               for kind, field, receivers in accesses(e) if kind == "write"}
        written[m] = own | set(e.get("vmWrites", ())) | ({INIT} if e.get("allocates") else set())

    callees = callees_of(facts)
    unknown = reaching(callees, {m: m for m, e in methods.items() if blocks(facts, e, ignore)})
    # A method that reaches something unknown kills everything, whatever it writes. Every other one
    # calls only methods like itself, so only they need what their callees write: on javac's export,
    # a third of the methods, and a tenth of the time.
    close_over_callees({m: cs for m, cs in callees.items() if m not in unknown}, written)
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
    parser.add_argument("--assumptions", help="the thread-escape assumptions to read, from an export made with all of them")
    parser.add_argument("--accesses", type=Path, help="where to write each access's partition")
    parser.add_argument("--ignore", default="", help="measurement only, never sound: leave out the kill of these effects (comma-separated: "
                        + ", ".join(IGNORABLE) + "; all: every one), to see the most that precise kill sets could give Graal")
    args = parser.parse_args()
    ignore = [name for name in args.ignore.split(",") if name]
    if ignore == ["all"]:
        ignore = list(IGNORABLE)
    if unknown := set(ignore) - IGNORABLE.keys():
        parser.error(f"cannot ignore {sorted(unknown)}: only {sorted(IGNORABLE)}")
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
