"""What the unresolved calls are: the calls the analysis found no target for, sorted by why, by what is called and by where.

Usage:
    uv run python -m diagnostics.unresolved graal-native/out/awfy-eval/fields/export.json
    uv run python -m diagnostics.unresolved export.json --program deltablue,havlak --top 20

An export lists, for each method, its unresolved calls as `<target> at bci <n> (<why>)`: the target is the method the bytecode
names, or `<indirect>` where there is none (a call through a function pointer, reflection); the reason is `no flow` (the analysis
never made a flow for the call, so it was not reached or is code it cannot see), `disabled` (the flow exists and a predicate turned
it off) or `no callees` (the flow is on and found no method to call). Each of them makes the method kill everything.

The answer counts the calls and the methods that have one, by reason, by what is called, and by the part of the image that contains
the call (the program, the Scala library, the JDK, the VM and the compiler), for every method and for the program's methods that
still kill everything with the three layers (identity hash, class initialization, synchronization) left out, which are the methods
on which only an unresolved call, an unnamed call or an effect behind them remains.
"""

import argparse
import re
from collections import Counter
from pathlib import Path

from effects.kills import opaque
from effects.signatures import callees_of
from graal.graal_import import PointsToFacts, load_facts

from .blockers import in_program
from .ceiling import LAYERS

#: `java.lang.Object.equals(Ljava/lang/Object;)Z at bci 4 (no callees)`, or `<indirect> at bci -6 (no flow)`
ENTRY = re.compile(r"(?P<target><indirect>|\S+) at bci (?P<bci>-?\d+) \((?P<why>[^)]+)\)")

#: Where a class lies, by the start of its name, first match wins.
PARTS = (
    ("java.lang.invoke.", "JDK: method handles"),
    ("java.lang.reflect.", "JDK: reflection"),
    ("jdk.internal.reflect.", "JDK: reflection"),
    ("java.", "JDK"),
    ("javax.", "JDK"),
    ("jdk.graal.", "VM and compiler"),
    ("jdk.", "JDK"),
    ("sun.", "JDK"),
    ("com.sun.", "JDK"),
    ("com.oracle.", "VM and compiler"),
    ("org.graalvm.", "VM and compiler"),
    ("scala.", "Scala library"),
)


def part(method: str, program: list[str] | None = None) -> str:
    """The part of the image a method belongs to: the program's own, or the platform's by package."""
    for prefix, name in PARTS:
        if method.startswith(prefix):
            return name
    return "program" if in_program(method, program or []) else "other"


def target_kind(target: str) -> str:
    """What the call names: no method at all, or the class's part and whether it is a constructor, an `invoke`, a lambda."""
    if target == "<indirect>":
        return "no target method (function pointer, reflection)"
    name = target.split("(", 1)[0]
    owner, _, method = name.rpartition(".")
    if method == "<init>":
        return f"constructor, {part(owner)}"
    if method in ("invoke", "invokeExact", "invokeBasic", "linkToStatic", "linkToVirtual", "linkToSpecial", "linkToInterface"):
        return "method handle or reflective invoke"
    return f"method, {part(owner)}"


def entries(facts: PointsToFacts, methods) -> list[tuple[str, str, str, str]]:
    """(containing method, target, bci, reason) for every unresolved call of the methods."""
    found = []
    for m in methods:
        for text in facts.methods[m].get("unresolved", ()):
            if parsed := ENTRY.fullmatch(text):
                found.append((m, parsed["target"], parsed["bci"], parsed["why"]))
            else:
                found.append((m, text, "?", "unparsed"))
    return found


def table(title: str, found: list[tuple[str, str, str, str]], key, top: int | None = None) -> None:
    calls: Counter[str] = Counter()
    methods: dict[str, set[str]] = {}
    for e in found:
        k = key(*e)
        calls[k] += 1
        methods.setdefault(k, set()).add(e[0])
    print(f"{title}\n  {'calls':>6} {'methods':>7}  what")
    for k, n in calls.most_common(top):
        print(f"  {n:>6} {len(methods[k]):>7}  {k}")


def report(label: str, facts: PointsToFacts, methods: list[str], top: int) -> None:
    found = entries(facts, methods)
    have = {e[0] for e in found}
    print(f"\n== {label}: {len(methods)} methods, {len(found)} unresolved calls in {len(have)} of them")
    if not found:
        return
    table("by reason", found, lambda m, t, b, why: why)
    table("by what is called", found, lambda m, t, b, why: target_kind(t))
    table("by what is called and why", found, lambda m, t, b, why: f"{target_kind(t)}; {why}")
    table("by the part of the image that contains the call", found, lambda m, t, b, why: part(m))
    table(f"the {top} targets called most", found, lambda m, t, b, why: t, top)
    table(f"the {top} classes that contain most of them", found, lambda m, t, b, why: m.split("(", 1)[0].rpartition(".")[0], top)


def report_without_facts(label: str, facts: PointsToFacts, methods: list[str], top: int) -> None:
    found = calls_without_facts(facts, methods)
    have = {e[0] for e in found}
    callees = {e[1] for e in found}
    print(f"\n== {label}, calls of methods without facts: {len(found)} calls of {len(callees)} methods in {len(have)} of {len(methods)} methods")
    if not found:
        return
    table("by what is called", found, lambda m, c, b, why: target_kind(c))
    table("by the part of the image that contains the call", found, lambda m, c, b, why: part(m))
    table(f"the {top} methods called most", found, lambda m, c, b, why: c, top)
    table(f"the {top} classes called most", found, lambda m, c, b, why: c.split("(", 1)[0].rpartition(".")[0], top)


def calls_without_facts(facts: PointsToFacts, methods) -> list[tuple[str, str, str, str]]:
    """(containing method, callee, '', reason) for each call of a method the export has no facts for."""
    return [(m, c, "", "no facts") for m in methods for c in facts.methods[m].get("callees", ()) if c not in facts.methods]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("--assumptions", help="the thread-escape assumptions to read, from an export made with all of them")
    parser.add_argument("--program", default="", help="comma-separated method prefixes that are the program (default: outside the platform's packages)")
    parser.add_argument("--top", type=int, default=15, help="how many targets and classes to list")
    args = parser.parse_args()
    facts = load_facts(args.export, args.assumptions)
    prefixes = [p for p in args.program.split(",") if p]
    every = list(facts.methods)
    mine = [m for m in every if in_program(m, prefixes)]
    left = opaque(facts, LAYERS, callees_of(facts))
    behind = [m for m in mine if m in left]
    print(f"{len(every)} methods, {len(mine)} in the program; with {', '.join(LAYERS)} left out, {len(behind)} of the program's methods still kill everything")
    have = sum(1 for m in behind if facts.methods[m].get("unresolved"))
    print(f"of those {have} have an unresolved call themselves")
    report("every method", facts, every, args.top)
    report("the program's methods", facts, mine, args.top)
    report("the program's methods that still kill everything with the three layers left out", facts, behind, args.top)
    report_without_facts("every method", facts, every, args.top)
    report_without_facts("the program's methods that still kill everything with the three layers left out", facts, behind, args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
