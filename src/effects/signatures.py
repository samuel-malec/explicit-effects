"""Which partitions of memory each method may read and write.

    A partition is a set of memory locations, and a program's partitions are
    disjoint: every location is in exactly one, so operations on two
    partitions never touch the same memory.

    - `heap`: all of memory as one partition.
    - `field`: one partition per field and per array element kind. Two fields
      are different memory whatever the objects, so Java's type system alone
      makes them disjoint.
    - `object`: disjoint sets of objects from the points-to facts, with all
      their fields. Two objects share a partition when one access may touch
      both: union-find over the objects each access's receiver may point to.
    - `object-field`: the same for each field on its own, so a partition is one
      field of a set of objects: disjoint as both `field` and `object` are.

    How finely the facts tell objects apart is the analysis's choice: by type
    by default, by allocation site with -H:AnalysisContextSensitivity=allocsens.
"""

from dataclasses import dataclass
from typing import Callable, Protocol

from graal.graal_import import PointsToFacts

#: The objects an access's receiver may point to, as the export names them:
#: `Examples$Counter` by type, `Examples$Counter@Examples.main([Ljava/lang/String;)V:9`
#: by allocation site. None when the analysis can't say.
Receivers = frozenset[str] | None


class Partitioner(Protocol):
    """A field, `Examples$Counter.value`, or an array kind, `int[]`, and the
    objects an access may touch, to the access's partition."""

    def __call__(self, field: str, receivers: Receivers = None, /) -> str: ...


#: Memory that no field of the program names: the platform's fields, and
#: whatever an opaque method may touch.
REST = "*"

#: The pseudo-objects of an access whose receiver the analysis can't say
#: anything about, and of one whose receiver is always null, which touches nothing.
UNKNOWN, NOTHING = "?", "null"


def one_heap(field: str, receivers: Receivers = None) -> str:
    """All of memory as one partition."""
    return "heap"


def by_field(field: str, receivers: Receivers = None) -> str:
    """One partition per field and per array element kind."""
    return field


def by_object(facts: PointsToFacts) -> Partitioner:
    """Disjoint sets of objects, with all their fields."""
    return _by_objects(facts, per_field=False)


def by_object_field(facts: PointsToFacts) -> Partitioner:
    """Disjoint sets of objects, for each field on its own."""
    return _by_objects(facts, per_field=True)


#: The partitionings by name, each made from the facts.
PARTITIONERS: dict[str, Callable[[PointsToFacts], Partitioner]] = {
    "heap": lambda facts: one_heap,
    "field": lambda facts: by_field,
    "object": by_object,
    "object-field": by_object_field,
}


def accesses(method: dict) -> list[tuple[str, str, Receivers]]:
    """A method's field and array accesses: read or write, the field, and the
    objects it may touch. A field the method reads or writes with no access
    listed, as in a method outside the program, may touch any object."""
    listed = [(a["kind"], a["field"], None if a["receivers"] is None else frozenset(a["receivers"]))
              for a in method.get("accesses", ())]
    covered = {(kind, field) for kind, field, _ in listed}
    return listed + [(kind, field, None) for kind in ("read", "write") for field in method.get(kind + "s", ())
                     if (kind, field) not in covered]


def _by_objects(facts: PointsToFacts, per_field: bool) -> Partitioner:
    program = facts.fields.keys()
    parent: dict = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def elements(field: str, receivers: Receivers) -> list:
        """What an access joins: (field, object) per field, otherwise the object."""
        if not receivers:
            pseudo = UNKNOWN if receivers is None else NOTHING
            return [(field, pseudo) if per_field else (pseudo, field)]
        return [(field, o) if per_field else o for o in sorted(receivers)]

    def join(a, b) -> None:
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        parent[find(a)] = find(b)

    known: dict[str, set[str]] = {}  # the objects the listed accesses of a field may touch
    unknown: set[str] = set()  # fields some access may touch on objects the analysis can't name
    for method in facts.methods.values():
        for _, field, receivers in accesses(method):
            if field in program or field.endswith("[]"):
                touched = elements(field, receivers)
                for element in touched:
                    join(touched[0], element)
                if receivers is None:
                    unknown.add(field)
                else:
                    known.setdefault(field, set()).update(receivers)

    # An access the analysis can't say anything about may touch any object
    # with the field, so it joins every object another access of it may touch.
    for field in unknown:
        for o in known.get(field, ()):
            join(elements(field, None)[0], elements(field, frozenset({o}))[0])

    classes: dict = {}
    for element in parent:
        classes.setdefault(find(element), []).append(element)
    names = _names(classes, per_field)

    def partition(field: str, receivers: Receivers = None, /) -> str:
        if field == REST:
            return REST
        touched = elements(field, receivers)
        roots = {find(e) for e in touched if e in parent}
        if len(roots) != 1 or any(e not in parent for e in touched):
            raise ValueError(f"{field} through {sorted(receivers or ())} is in no one partition of the facts")
        return names[roots.pop()]

    return partition


def _names(classes: dict, per_field: bool) -> dict:
    """A name per class. Per field: the field itself when it has one class,
    otherwise the field and where the class's first object was allocated,
    `Examples$Counter.value@main:9`. Per object: the first object,
    `Examples$Counter@main:9`."""
    def label(members: list) -> str:
        found = sorted(o for o in ([m[1] for m in members] if per_field else [m for m in members if isinstance(m, str)])
                       if o not in (UNKNOWN, NOTHING))
        if not found:  # only the field's unknown or null receivers
            field, pseudo = members[0] if per_field else reversed(members[0])
            return pseudo if per_field else f"{field}@{pseudo}"
        kind, site = _site(found[0])
        return (site or kind) if per_field else f"{kind}@{site}" if site else kind

    count: dict[str, int] = {}
    for members in classes.values():
        if per_field:
            count[members[0][0]] = count.get(members[0][0], 0) + 1

    names, used = {}, set()
    for root, members in sorted(classes.items(), key=lambda item: sorted(map(str, item[1]))):
        name = label(members)
        if per_field:
            field = members[0][0]
            name = field if count[field] == 1 else f"{field}@{name}"
        unique, k = name, 2
        while unique in used:
            unique, k = f"{name}#{k}", k + 1
        names[root] = unique
        used.add(unique)
    return names


def _site(obj: str) -> tuple[str, str]:
    """The type and a short allocation site: `Examples$Counter@Examples.main([Ljava/lang/String;)V:9`
    is `Examples$Counter` at `main:9`; an object named by its type has no site."""
    kind, _, site = obj.partition("@")
    if site and site != "constant":
        method, _, bci = site.split(" in ")[0].rpartition(":")
        site = method.split("(")[0].rsplit(".", 1)[-1] + ":" + bci
    return kind, site


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

    def part(field: str, receivers: Receivers = None) -> str:
        return partition(field, receivers) if field in program or field.endswith("[]") else partition(REST)

    methods = facts.methods
    touched = {m: accesses(e) for m, e in methods.items()}
    reads = {m: {part(f, r) for kind, f, r in touched[m] if kind == "read"} for m in methods}
    writes = {m: {part(f, r) for kind, f, r in touched[m] if kind == "write"} | ({part(REST)} if e.get("allocates") else set())
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
