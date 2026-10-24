"""Why the methods of a program kill everything: the first thing each reaches that the facts can't
bound, and how many methods the program has behind each.

Usage:
    uv run python -m effects.blockers graal-native/out/awfy-eval-o3/kills/export.json
    uv run python -m effects.blockers export.json --program deltablue,havlak --synchronization none

A method kills everything (`effects.kills`) when it, or a method it calls, has an effect or a call
the facts can't name, or synchronization that may order this thread with another. The answer says
which, for the program's methods: synchronization on objects only this thread reaches counts as
nothing (`--synchronization all` counts it, as the kill sets did before they knew thread escape).
"""

import argparse
import re
from collections import Counter
from pathlib import Path

from graal.graal_import import PointsToFacts, load_facts

from .kills import ANY, kills
from .signatures import callees_of, synchronizes_on, synchronizing

# Packages that are not the program under analysis, as the export treats them by default.
PLATFORM = ("java.", "javax.", "jdk.", "sun.", "com.sun.", "com.oracle.", "org.graalvm.", "org.ietf.",
            "org.jcp.", "org.w3c.", "org.xml.")


def in_program(method: str, prefixes: list[str]) -> bool:
    if prefixes:
        return "*" in prefixes or any(method.startswith(p) for p in prefixes)
    return not method.startswith(PLATFORM)


def kind(text: str) -> str:
    """A fact's text without its position and the node's address: `EnsureClassInitializedNode`."""
    return re.split(r" at | \(|:", text, maxsplit=1)[0].strip()


def direct_cause(facts: PointsToFacts, method: str, sync: str) -> str | None:
    """What the method itself has that makes it kill everything, most telling first; None if it has none."""
    e = facts.methods[method]
    missing = [c for c in e.get("callees", ()) if c not in facts.methods]
    if e.get("unresolved"):
        return "unresolved call"
    if missing:
        return "call to a method without facts"
    for kind_ in ("acquires", "releases"):
        found = e.get(kind_) if sync == "all" else synchronizing(facts, e, kind_) if sync == "shared" else []
        if found:
            return f"{kind_[:-1]}: {kind(found[0])}"
    if e.get("unknown"):
        return kind(e["unknown"][0])
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
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("--assumptions", help="the set of thread-escape assumptions to read from an export made with all of them: none, thread-confined, "
                        "thread-confined, thread-confined,vm-fields, ... up to thread-confined,vm-fields,vm-code,handler-references,entry-points")
    parser.add_argument("--program", default="", help="comma-separated class-name prefixes, * for every method; default: outside the platform's packages")
    parser.add_argument("--synchronization", choices=["shared", "all", "none"], default="shared",
                        help="which synchronization blocks: that on objects another thread may reach (what the kill sets do), "
                             "all of it (before they knew thread escape), or none (what a kill set that named exactly the "
                             "partitions another thread may touch could free at most)")
    args = parser.parse_args()
    facts = load_facts(args.export, args.assumptions)
    program = [p for p in args.program.split(",") if p]
    answers = kills(facts)
    methods = [m for m in facts.methods if in_program(m, program)]
    counts = blockers(facts, program, args.synchronization)
    killing = [m for m in methods if answers[m] == ANY]
    print(f"{len(methods)} program methods; synchronization that blocks: {args.synchronization}; "
          f"{sum(counts.values())} have a cause" + (f" ({len(killing)} kill everything)" if args.synchronization == "shared" else ""))
    for cause, n in counts.most_common():
        print(f"  {n:5d}  {cause}")
    sites = lock_sites(facts, program)
    print(f"{sum(sites.values())} monitor and volatile sites in the program's methods: "
          + ", ".join(f"{n} {what}" for what, n in sites.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
