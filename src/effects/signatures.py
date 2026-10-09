"""Which partitions of memory each method may read and write.

A partitioning is sound when it is disjoint, every location in exactly one
partition, and the signatures are complete, every operation carrying the token
of every partition it may touch.

Partitions: one per field of the program, named by its declaring class, which
two different fields never share whatever the objects; one per array element
kind, from the export; and the rest of memory, which holds the platform's
fields and whatever no field names. `heap` puts all of them in one.

A method's signature is the partitions its own accesses touch, plus whatever
its callees touch, to a fixpoint over the points-to call graph. Effects only
grow and there are finitely many partitions, so the iteration ends; it needs
more than one pass because of recursion. An allocation touches the rest of
memory.

A method touches everything, every partition, when it or anything it calls
has a callee without facts (a native, a lambda), a call the analysis did not
resolve, or a memory effect the facts can't name (a monitor, a volatile
access, a fence, an unsafe access). Unknown effects are never assumed absent.
"""

from dataclasses import dataclass
from typing import Callable

from graal.graal_import import PointsToFacts

#: A field, `Examples$Counter.value`, or an array kind, `int[]`, to its partition.
Partitioner = Callable[[str], str]

#: Memory that no field of the program names: the platform's fields, and
#: whatever an opaque method may touch.
REST = "*"


def one_heap(field: str) -> str:
    """All of memory as one partition."""
    return "heap"


def by_field(field: str) -> str:
    """One partition per field and per array element kind."""
    return field


PARTITIONERS: dict[str, Partitioner] = {"heap": one_heap, "field": by_field}


@dataclass(frozen=True)
class Signature:
    reads: frozenset[str]
    writes: frozenset[str]
    opaque: bool = False  # may touch anything
    why: str = ""  # what makes it opaque: the effect at the root of it


@dataclass
class Effects:
    partition: Partitioner
    signatures: dict[str, Signature]  # by method: name and descriptor
    partitions: tuple[str, ...]  # every partition of the program, the rest of memory included

    def tokens(self, method: str) -> tuple[str, ...]:
        """The partitions a method needs a token for, in a fixed order: all of
        them for a method without a signature or an opaque one."""
        signature = self.signatures.get(method)
        if signature is None or signature.opaque:
            return self.partitions
        return tuple(sorted(signature.reads | signature.writes))


def no_analysis() -> Effects:
    """No signatures: every method threads all of memory as one token."""
    return Effects(one_heap, {}, ("heap",))


def analyse(facts: PointsToFacts, partition: Partitioner) -> Effects:
    program = facts.fields.keys()  # the fields of the classes under analysis

    def part(field: str) -> str:
        return partition(field if field in program or field.endswith("[]") else REST)

    methods = facts.methods
    reads = {m: {part(f) for f in e.get("reads", ())} for m, e in methods.items()}
    writes = {m: {part(f) for f in e.get("writes", ())} | ({part(REST)} if e.get("allocates") else set())
              for m, e in methods.items()}
    callees = {m: set(e.get("callees", ())) for m, e in methods.items()}

    changed = True
    while changed:
        changed = False
        for m in methods:
            r, w = set(reads[m]), set(writes[m])
            for callee in callees[m]:
                r |= reads.get(callee, set())
                w |= writes.get(callee, set())
            if r != reads[m] or w != writes[m]:
                reads[m], writes[m] = r, w
                changed = True

    # What makes a method touch everything, and every method that reaches it too.
    why: dict[str, str] = {}
    for m, e in methods.items():
        missing = sorted(c for c in callees[m] if c not in methods)
        if missing:
            why[m] = f"{missing[0]} has no facts"
        elif e.get("unresolved"):
            why[m] = f"{m}: unresolved call to {e['unresolved'][0]}"
        elif e.get("unknown"):
            why[m] = f"{m}: {e['unknown'][0]}"
    callers: dict[str, set[str]] = {}
    for m, cs in callees.items():
        for callee in cs:
            callers.setdefault(callee, set()).add(m)
    work = list(why)
    while work:
        callee = work.pop()
        for caller in callers.get(callee, ()):
            if caller not in why:
                why[caller] = why[callee]
                work.append(caller)

    everything = {p for m in methods for p in reads[m] | writes[m]} | {part(REST)}
    signatures = {m: Signature(frozenset(reads[m]), frozenset(writes[m]), m in why, why.get(m, "")) for m in methods}
    return Effects(part, signatures, tuple(sorted(everything)))
