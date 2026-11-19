"""Why the methods of a program kill everything: the first thing each reaches that the analysis can't
bound, and how many of the program's methods are behind each.

Usage:
    uv run python -m diagnostics.blockers graal-native/out/awfy-eval-o3/fields/export.json
    uv run python -m diagnostics.blockers export.json --program deltablue,havlak --synchronization none
    uv run python -m diagnostics.blockers export.json --roots 25

A method kills everything (`effects.kills`) when it, or a method it calls, has an effect or a call
the analysis can't name, or synchronization that may order this thread with another. The answer says
which, for the program's methods. Synchronization on objects only this thread reaches doesn't count
(`--synchronization all` counts it, ignoring thread escape).
"""

import argparse
from collections import Counter
from pathlib import Path

from effects.kills import node_kind, opaque
from effects.signatures import callees_of, synchronizes_on, synchronizing
from graal.graal_import import PointsToFacts, load_facts

# Packages that are not the program under analysis, as the export treats them by default.
PLATFORM = ("java.", "javax.", "jdk.", "sun.", "com.sun.", "com.oracle.", "org.graalvm.", "org.ietf.",
            "org.jcp.", "org.w3c.", "org.xml.")


def in_program(method: str, prefixes: list[str]) -> bool:
    """Whether the method is the program's: under one of the prefixes (`*` for any), or without prefixes, outside
    the platform's packages."""
    if prefixes:
        return "*" in prefixes or any(method.startswith(p) for p in prefixes)
    return not method.startswith(PLATFORM)


def direct_cause(facts: PointsToFacts, method: str, sync: str) -> str | None:
    """What the method itself has that makes it kill everything, most telling first; None if it has none."""
    e = facts.methods[method]
    missing = [c for c in e.get("callees", ()) if c not in facts.methods]
    if e.get("unresolved"):
        return "unresolved call"
    if missing:
        return "call to a method without facts"
    for kind in ("acquires", "releases"):
        found = e.get(kind) if sync == "all" else synchronizing(facts, e, kind) if sync == "shared" else []
        if found:
            return f"{kind[:-1]}: {node_kind(found[0])}"
    if e.get("unknown"):
        return node_kind(e["unknown"][0])
    return None


def blockers(facts: PointsToFacts, program: list[str], sync: str = "shared") -> Counter[str]:
    """For each program method that kills everything, the direct cause of the nearest method on a call path
    to something that has one. A method that has a cause itself counts under it."""
    callers: dict[str, list[str]] = {}
    for m, cs in callees_of(facts).items():
        for c in cs:
            callers.setdefault(c, []).append(m)
    # Nearest cause by a breadth-first walk from the methods that have one up to their callers.
    nearest: dict[str, tuple[str, bool]] = {}
    frontier = []
    for m in facts.methods:
        cause = direct_cause(facts, m, sync)
        if cause:
            nearest[m] = (cause, True)
            frontier.append(m)
    while frontier:
        reached = []
        for x in frontier:
            for caller in callers.get(x, ()):
                if caller not in nearest:
                    nearest[caller] = (nearest[x][0], False)
                    reached.append(caller)
        frontier = reached
    result: Counter[str] = Counter()
    for m, (cause, direct) in nearest.items():
        if in_program(m, program):
            result[cause + ("" if direct else " (through callees)")] += 1
    return result


def nearest_through(facts: PointsToFacts, program: list[str], sync: str = "shared", top: int = 25) -> tuple[int, list[tuple[str, int, int, str]], list[tuple[str, int, int, str]]]:
    """The methods the program's opaque methods become opaque through, as (method, program methods that call it directly,
    program methods that come first to it, its own cause), most first, in two rankings; and how many program methods are
    opaque.

    Each opaque method has a distance to the nearest method that has a cause itself (an unresolved call, a native
    transition, a lock, a class initialization): its roots are those at that distance on the paths of that length, and its gateways
    the first method outside the program on those paths. A program method counts once under each of its roots and gateways, so
    where paths tie the counts add up to more than the methods; a program method with a cause of its own is its own root and
    has no gateway. The share of a method that is only reached after others is not counted: it would be 'every opaque method'
    for the few roots that all calls end in."""
    killing = opaque(facts)
    callees = callees_of(facts)
    callers: dict[str, list[str]] = {}
    for m, cs in callees.items():
        for c in cs:
            callers.setdefault(c, []).append(m)
    causes = {m: direct_cause(facts, m, sync) for m in killing}
    dist = {m: 0 for m, why in causes.items() if why}
    layer = list(dist)
    while layer:
        reached = []
        for x in layer:
            for caller in callers.get(x, ()):
                if caller in killing and caller not in dist:
                    dist[caller] = dist[x] + 1
                    reached.append(caller)
        layer = reached
    nearest_roots: dict[str, frozenset[str]] = {}
    gateways: dict[str, frozenset[str]] = {}
    for m in sorted(dist, key=dist.__getitem__):
        outside = not in_program(m, program)
        if dist[m] == 0:
            nearest_roots[m], gateways[m] = frozenset({m}), frozenset({m}) if outside else frozenset()
            continue
        roots_of: set[str] = set()
        gateways_of: set[str] = set()
        for c in callees[m]:
            if dist.get(c) == dist[m] - 1:
                roots_of |= nearest_roots[c]
                gateways_of |= gateways[c]
        nearest_roots[m] = frozenset(roots_of)
        gateways[m] = frozenset({m}) if outside else frozenset(gateways_of)
    mine = [m for m in dist if in_program(m, program)]
    first_roots = Counter(r for m in mine for r in nearest_roots[m])
    first_gateways = Counter(g for m in mine for g in gateways[m])

    def direct(m: str) -> int:
        return sum(1 for c in callers.get(m, ()) if c in killing and in_program(c, program))

    def rows(counter: Counter[str]) -> list[tuple[str, int, int, str]]:
        ranked = sorted(counter, key=lambda m: (-counter[m], m))[:top]
        return [(m, direct(m), counter[m], causes[m] or "through callees") for m in ranked]

    return len(mine), rows(first_gateways), rows(first_roots)


def lock_sites(facts: PointsToFacts, program: list[str]) -> Counter[str]:
    """The program's monitor and volatile sites by what thread escape says of their receivers: lock elision and
    ordinary volatile accesses need every receiver of a site thread-local."""
    sites: Counter[str] = Counter()
    for m, e in facts.methods.items():
        if not in_program(m, program):
            continue
        for s, receivers in e.get("locks", {}).items():
            if receivers is None:
                sites["receivers unnamed"] += 1
            elif synchronizes_on(facts, receivers):
                sites["some receiver shared"] += 1
            else:
                sites["every receiver thread-local"] += 1
    return sites


def main() -> int:
    """Print how many of the program's methods each cause keeps opaque, then its monitor and volatile sites."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("--assumptions", help="the set of thread-escape assumptions to read from an export made with all of them: none, "
                        "thread-confined, thread-confined,vm-fields, ... up to thread-confined,vm-fields,vm-code,handler-references,entry-points")
    parser.add_argument("--program", default="", help="comma-separated class-name prefixes, * for every method; default: outside the platform's packages")
    parser.add_argument("--synchronization", choices=["shared", "all", "none"], default="shared",
                        help="which synchronization blocks: that on objects another thread may reach (what the kill sets do), "
                             "all of it (ignoring thread escape), or none (what a kill set that named exactly the "
                             "partitions another thread may touch could free at most)")
    parser.add_argument("--roots", type=int, default=0, metavar="N",
                        help="also list the N methods the program's opaque methods become opaque through: the gateways into the platform and "
                             "the methods that have a cause themselves, by how many program methods come first to them")
    args = parser.parse_args()
    facts = load_facts(args.export, args.assumptions)
    program = [p for p in args.program.split(",") if p]
    answers = opaque(facts)
    methods = [m for m in facts.methods if in_program(m, program)]
    counts = blockers(facts, program, args.synchronization)
    killing = [m for m in methods if m in answers]
    print(f"{len(methods)} program methods; synchronization that blocks: {args.synchronization}; "
          f"{sum(counts.values())} have a cause" + (f" ({len(killing)} kill everything)" if args.synchronization == "shared" else ""))
    for cause, n in counts.most_common():
        print(f"  {n:5d}  {cause}")
    sites = lock_sites(facts, program)
    print(f"{sum(sites.values())} monitor and volatile sites in the program's methods: "
          + ", ".join(f"{n} {what}" for what, n in sites.most_common()))
    if args.roots:
        opaque_program, gateways, causes = nearest_through(facts, program, args.synchronization, args.roots)
        print(f"{opaque_program} program methods kill everything; first = program methods that come first to a method (each counted under every one it ties with)")
        for title, rows in (("gateways: the first method outside the program on the way to a cause", gateways),
                            ("roots: the methods with a cause of their own that program methods come nearest to", causes)):
            print(f"{title}\n  {'first':>6} {'direct':>6}  method (cause)")
            for method, direct, first, why in rows:
                print(f"  {first:>6} {direct:>6}  {method} ({why})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
