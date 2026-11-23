"""Which partitions of memory each method may read and write.

A partition is a set of memory locations; a program's partitions never overlap. Memory can be cut four ways:

- `heap`: all of memory is one partition.
- `field`: a partition per field and per array element kind. Java's types alone keep two fields apart.
- `object`: a partition per set of objects, with all their fields. Two objects share a partition when one
  access may touch both (union-find over the objects each access may touch).
- `object-field`: the same for each field separately, so a partition is one field of a set of objects.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Protocol

from graal.graal_import import PointsToFacts

# The objects an access may touch, as the export names them; None when the analysis can't say.
Receivers = frozenset[str] | None


class Partitioner(Protocol):
    """The partition of an access to `field` on `receivers`."""

    def __call__(self, field: str, receivers: Receivers = None, /) -> str: ...


# The rest of memory: what no field of the program covers.
REST = "*"

# Stand-in objects for an access whose objects the analysis can't name, and for one whose reference is
# always null, which touches nothing.
UNKNOWN, NOTHING = "?", "null"

# The stand-in object for a class's static fields, which every thread can reach.
STATICS = ".<statics>"


def shared_object(facts: PointsToFacts, o: str) -> bool:
    """Whether another thread may reach the object: one the analysis can't name, static fields, an object
    the export lists as shared, or any object when the export has no such list."""
    return facts.shared is None or o == UNKNOWN or o.endswith(STATICS) or o in facts.shared


def synchronizes_on(facts: PointsToFacts, objects: Receivers) -> bool:
    """Whether locking these objects, or a volatile access to them, may order this thread with another. It
    can't if no other thread reaches any of them."""
    return objects is None or any(o != NOTHING and shared_object(facts, o) for o in objects)


def synchronizing(facts: PointsToFacts, method: dict, kind: str) -> list[str]:
    """The method's own sites of `kind` ("acquires" or "releases") that may order this thread with another,
    leaving out locks and volatile fields that only this thread reaches."""
    locks = method.get("locks", {})
    return [s for s in method.get(kind, ()) if s not in locks or synchronizes_on(facts, locks[s])]


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
    """Disjoint sets of objects, for each field separately."""
    return _by_objects(facts, per_field=True)


PARTITIONERS: dict[str, Callable[[PointsToFacts], Partitioner]] = {
    "heap": lambda facts: one_heap,
    "field": lambda facts: by_field,
    "object": by_object,
    "object-field": by_object_field,
}


def accesses(method: dict) -> list[tuple[str, str, Receivers]]:
    """Every field or array a method may read or write, as (kind, field, receivers): first the accesses the
    export lists, in its order, then each read or write the list misses, with receivers None."""
    result = []
    for site in method.get("accesses", ()):
        receivers = None if site["receivers"] is None else frozenset(site["receivers"])
        result.append((site["kind"], site["field"], receivers))

    with_site = {(kind, field) for kind, field, _ in result}
    for kind, key in (("read", "reads"), ("write", "writes")):
        for field in method.get(key, ()):
            if (kind, field) not in with_site:
                result.append((kind, field, None))
    return result


def _in_program(field: str, program: Collection[str]) -> bool:
    """Whether the partitions cover the field: one of the program's own fields, or an array element kind."""
    return field in program or field.endswith("[]")


class _DisjointSets:
    """Union-find over any hashable elements."""

    def __init__(self) -> None:
        self.parent: dict = {}

    def __contains__(self, x) -> bool:
        return x in self.parent

    def find(self, x):
        parent = self.parent
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def join(self, a, b) -> None:
        self.parent.setdefault(a, a)
        self.parent.setdefault(b, b)
        self.parent[self.find(a)] = self.find(b)

    def classes(self) -> dict:
        """Each class by its root, with its members in the order they first joined."""
        classes: dict = {}
        for x in self.parent:
            classes.setdefault(self.find(x), []).append(x)
        return classes


def _by_objects(facts: PointsToFacts, per_field: bool) -> Partitioner:
    """Sets of objects that one access may touch together, or with `per_field` such sets for each field."""
    program = facts.fields.keys()
    sets = _DisjointSets()

    def elements(field: str, receivers: Receivers) -> list:
        """What an access joins: (field, object) per field, otherwise the object. Without a named object, a
        stand-in for the field's unknown objects or for null."""
        if not receivers:
            pseudo = UNKNOWN if receivers is None else NOTHING
            return [(field, pseudo) if per_field else (pseudo, field)]
        return [(field, o) if per_field else o for o in sorted(receivers)]

    known: dict[str, set[str]] = {}  # for each field, the objects its listed accesses name
    unknown: set[str] = set()  # the fields some access touches on objects the analysis can't name

    # 1. Each access joins everything it may touch.
    for method in facts.methods.values():
        for _, field, receivers in accesses(method):
            if _in_program(field, program):
                touched = elements(field, receivers)
                for element in touched:
                    sets.join(touched[0], element)
                if receivers is None:
                    unknown.add(field)
                else:
                    known.setdefault(field, set()).update(receivers)

    # 2. An access on objects the analysis can't name may touch any object with the field.
    for field in unknown:
        for o in known.get(field, ()):
            sets.join(elements(field, None)[0], elements(field, frozenset({o}))[0])

    # 3. An object named by its type alone, T, may be any object of exactly that type, so it is the same as
    #    one named by an allocation site, T@site, or as a constant, T@constant.
    for element in list(sets.parent):
        o = element[1] if per_field else element
        if isinstance(o, str) and "@" in o:
            summary = (element[0], o.split("@", 1)[0]) if per_field else o.split("@", 1)[0]
            if summary in sets:
                sets.join(summary, element)

    names = _names(sets.classes(), per_field)

    def partition(field: str, receivers: Receivers = None, /) -> str:
        if field == REST:
            return REST
        if receivers and field in unknown and not receivers <= known.get(field, set()):
            # An object no listed access of the field names, such as a new one: only the accesses on
            # objects the analysis can't name touch that field of it.
            receivers = None
        touched = elements(field, receivers)
        roots = {sets.find(e) for e in touched if e in sets}
        if len(roots) != 1 or any(e not in sets for e in touched):
            raise ValueError(f"{field} through {sorted(receivers or ())} is in no one partition of the facts")
        return names[roots.pop()]

    return partition


def _names(classes: dict, per_field: bool) -> dict:
    """A name for each class, by its root. Per field: the field alone if it has one class, otherwise the field
    and where the class's first object was allocated, `LoadStoreElimination$Counter.value@main:9`. Per object:
    the first object, `LoadStoreElimination$Counter@main:9`. A name already taken gets #2, #3, ..."""

    def label(members: list) -> str:
        if per_field:
            objects = [o for _, o in members]
        else:
            objects = [m for m in members if isinstance(m, str)]
        named = sorted(o for o in objects if o not in (UNKNOWN, NOTHING))

        if not named:  # only stand-ins: the field's unknown objects or null
            field, pseudo = members[0] if per_field else reversed(members[0])
            return pseudo if per_field else f"{field}@{pseudo}"

        kind, site = _site(named[0])
        if per_field:
            return site or kind
        return f"{kind}@{site}" if site else kind

    classes_of_field: dict[str, int] = {}
    for members in classes.values():
        if per_field:
            field, _ = members[0]
            classes_of_field[field] = classes_of_field.get(field, 0) + 1

    names, used = {}, set()
    for root, members in sorted(classes.items(), key=lambda item: sorted(map(str, item[1]))):
        name = label(members)
        if per_field:
            field, _ = members[0]
            name = field if classes_of_field[field] == 1 else f"{field}@{name}"

        unique, k = name, 2
        while unique in used:
            unique, k = f"{name}#{k}", k + 1

        names[root] = unique
        used.add(unique)

    return names


def _site(name: str) -> tuple[str, str]:
    """An object's type and short allocation site: `LoadStoreElimination$Counter@LoadStoreElimination.main([Ljava/lang/String;)V:9`
    gives `LoadStoreElimination$Counter` and `main:9`. An object named by its type alone has no site."""
    kind, _, site = name.partition("@")
    if site and site != "constant":
        method, _, bci = site.split(" in ")[0].rpartition(":")
        site = method.split("(")[0].rsplit(".", 1)[-1] + ":" + bci
    return kind, site


@dataclass(frozen=True)
class Signature:
    """What a method, with everything it may call, may read and write."""

    reads: frozenset[str]
    writes: frozenset[str]
    opaque: bool = False  # may touch anything: a call to it kills all memory
    why: str = ""  # the effect that makes it opaque
    releases: bool = False  # whether it, or a method it may call, releases


@dataclass
class Effects:
    """Each method's signature, and the partitions they are in terms of."""

    partition: Partitioner
    signatures: dict[str, Signature]  # by method key: name and descriptor
    partitions: tuple[str, ...]  # every partition of the program, REST included
    shared: frozenset[str] | None = None  # the partitions another thread may touch; all of them if not given
    facts: PointsToFacts | None = None  # which objects another thread may reach; without facts, any

    def __post_init__(self) -> None:
        if self.shared is None:
            self.shared = frozenset(self.partitions)

    def tokens(self, method: str) -> tuple[str, ...]:
        """The partitions a method needs a token for: all of them if it is opaque or has no signature."""
        signature = self.signatures.get(method)
        if signature is None or signature.opaque:
            return self.partitions
        return tuple(sorted(signature.reads | signature.writes))

    def synchronizes(self, objects: Receivers) -> bool:
        """Whether synchronizing on these objects may order this thread with another."""
        return self.facts is None or synchronizes_on(self.facts, objects)

    def keeps(self, method: str, partition: str) -> bool:
        """Whether a call to the method gives the partition's token back unchanged: the method may read the
        partition but writes none of it."""
        signature = self.signatures.get(method)
        return signature is not None and not signature.opaque and partition not in signature.writes


def no_analysis() -> Effects:
    """The baseline without an analysis: all of memory is one partition, and every method takes its token."""
    return Effects(one_heap, {}, ("heap",))


def callees_of(facts: PointsToFacts) -> dict[str, set[str]]:
    """Each method, and the methods it may call."""
    return {m: set(e.get("callees", ())) for m, e in facts.methods.items()}


def close_over_callees(callees: dict[str, set[str]], *sets: dict[str, set[str]]) -> None:
    """Add to each method's set, in each of `sets`, the sets of every method it may call, directly or not.
    Methods that call each other end with the same set. Changes `sets` in place."""
    for component in _components(callees):  # a component's callees are complete before it
        members = set(component)
        called = {c for m in component for c in callees[m] if c not in members}
        for per_method in sets:
            joined = set().union(*(per_method.get(m, ()) for m in component), *(per_method.get(c, ()) for c in called))
            for m in component:
                per_method[m] |= joined


def _components(callees: dict[str, set[str]]) -> list[list[str]]:
    """The call graph's strongly connected components (Tarjan's algorithm), each after every component it
    calls. Written without recursion, so that long call chains don't reach Python's recursion limit."""
    index: dict[str, int] = {}  # the order in which each method was first visited
    low: dict[str, int] = {}  # the lowest index the method reaches inside its component
    stack: list[str] = []  # visited methods whose component isn't finished
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(m: str) -> None:
        index[m] = low[m] = len(index)
        stack.append(m)
        on_stack.add(m)

    for root in callees:
        if root in index:
            continue
        visit(root)
        work = [(root, iter(callees[root]))]  # the current path, each method with the callees it has left
        while work:
            m, children = work[-1]
            for c in children:
                if c not in callees:  # outside the graph
                    continue
                if c not in index:  # visit it first, then come back to m
                    visit(c)
                    work.append((c, iter(callees[c])))
                    break
                if c in on_stack:
                    low[m] = min(low[m], index[c])
            else:  # every callee of m is done
                work.pop()
                if work:
                    caller, _ = work[-1]
                    low[caller] = min(low[caller], low[m])
                if low[m] == index[m]:  # m is its component's first method: the component is complete
                    component = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == m:
                            break
                    components.append(component)
    return components


def reaching(callees: dict[str, set[str]], roots: dict[str, str]) -> dict[str, str]:
    """The roots, and every method that may call one, directly or not, each with the value of a root it
    reaches (the first one found)."""
    callers: dict[str, set[str]] = {}
    for m, cs in callees.items():
        for callee in cs:
            callers.setdefault(callee, set()).add(m)

    found, work = dict(roots), list(roots)
    while work:
        callee = work.pop()
        for caller in callers.get(callee, ()):
            if caller not in found:
                found[caller] = found[callee]
                work.append(caller)
    return found


def program_partition(facts: PointsToFacts, partition: Partitioner) -> Partitioner:
    """`partition` for the program's own fields and for array kinds; any other field, the platform's, is in
    REST."""
    program = facts.fields.keys()

    def part(field: str, receivers: Receivers = None) -> str:
        return partition(field, receivers) if _in_program(field, program) else partition(REST)

    return part


def analyse(facts: PointsToFacts, partition: Partitioner) -> Effects:
    """Each method's signature: the partitions it, and everything it may call, may read and write."""
    part = program_partition(facts, partition)
    methods = facts.methods
    touched = {m: accesses(e) for m, e in methods.items()}
    reads = {m: {part(f, r) for kind, f, r in touched[m] if kind == "read"} for m in methods}
    writes = {m: {part(f, r) for kind, f, r in touched[m] if kind == "write"} | (
        {part(REST)} if e.get("allocates") else set())
              for m, e in methods.items()}
    callees = callees_of(facts)

    why = reaching(callees, _opaque_roots(methods, callees))
    shared = _shared_partitions(facts, part, touched)
    releasing = _synchronize(facts, shared, reads, writes)
    close_over_callees(callees, reads, writes)
    releases = reaching(callees, releasing)

    everything = {p for m in methods for p in reads[m] | writes[m]} | {part(REST)}
    signatures = {m: Signature(frozenset(reads[m]), frozenset(writes[m]), opaque=m in why, why=why.get(m, ""),
                               releases=m in releases and m not in why)
                  for m in methods}
    return Effects(part, signatures, tuple(sorted(everything)), frozenset(shared), facts)


def _opaque_roots(methods: dict[str, dict], callees: dict[str, set[str]]) -> dict[str, str]:
    """The methods that may touch anything by themselves, each with why: a callee without facts, a call the
    analysis couldn't resolve, an unknown effect, or a read of anything (which needs every token)."""
    why: dict[str, str] = {}
    for m, e in methods.items():
        missing = sorted(c for c in callees[m] if c not in methods)
        if missing:
            why[m] = f"{missing[0]} has no facts"
        elif e.get("unresolved"):
            why[m] = f"{m}: unresolved call to {e['unresolved'][0]}"
        elif e.get("unknown"):
            why[m] = f"{m}: {e['unknown'][0]}"
        elif e.get("unknownReads"):
            why[m] = f"{m}: {e['unknownReads'][0]}"
    return why


def _shared_partitions(facts: PointsToFacts, part: Partitioner,
                       touched: dict[str, list[tuple[str, str, Receivers]]]) -> set[str]:
    """The partitions another thread may touch: REST, and every partition an access reaches through an object
    another thread may reach, or through objects the analysis can't name."""
    shared = {part(REST)}
    for method_accesses in touched.values():
        for _, f, r in method_accesses:
            if r is None or any(shared_object(facts, o) for o in r):
                shared.add(part(f, r))
    return shared


def _synchronize(facts: PointsToFacts, shared: set[str], reads: dict[str, set[str]],
                 writes: dict[str, set[str]]) -> dict[str, str]:
    """Add each method's synchronization on objects another thread may reach to what it reads and writes, and
    give the methods that release. An acquire may show this thread other threads' writes, so it reads and
    writes every shared partition. A release may show them this thread's writes, so it reads every shared
    partition. Synchronization on an object only this thread reaches orders nothing and adds nothing."""
    releasing = {}
    for m, e in facts.methods.items():
        if synchronizing(facts, e, "acquires"):
            reads[m] |= shared
            writes[m] |= shared
        if synchronizing(facts, e, "releases"):
            reads[m] |= shared
            releasing[m] = m
    return releasing
