"""Print the facts of an export as text: for each of the program's methods, what it
reads, writes and calls, and each of its field and array accesses with the objects
it may touch.

Usage:
    uv run python -m graal.facts graal-export/out/suite/objects.ForwardPastMaybeAlias.allocsens.json
    uv run python -m graal.facts graal-export/out/suite/forwarding.AcrossCall.json --method demo
    uv run python -m graal.facts graal-export/out/suite/objects.ForwardPastOtherObject.allocsens.json --all --method Byte

An access's objects are its receivers, as the points-to analysis names them: by
type, or with allocation sites by where they were allocated (Counter@main:0 is
the Counter allocated at bci 0 of main). These are what the partitioner reads.
"""

import argparse
import re
import sys
from pathlib import Path

from .graal_import import load

# Effects the facts can't name one by one, as the export lists them.
EFFECTS = ("unknown", "acquires", "releases", "unresolved", "unknownReads", "vmWrites", "dead")


def short_method(key: str) -> str:
    """forwarding.AcrossCall.length(Lforwarding/AcrossCall$Link;)I → AcrossCall.length"""
    return ".".join(key.split("(")[0].split(".")[-2:])


def short_field(field: str) -> str:
    """forwarding.AcrossCall$Counter.value → AcrossCall$Counter.value; int[] stays int[]."""
    return ".".join(field.split(".")[-2:])


def short_object(name: str) -> str:
    """objects.X$Counter@objects.X.main([Ljava/lang/String;)V:0 → Counter@main:0, and so for
    each call site an inlined allocation went through."""
    kind, _, site = name.partition("@")
    if kind.endswith(".<statics>"):  # a static field's pseudo-object: its class
        return ".".join(kind.split(".")[-2:])
    kind = re.split(r"[.$]", kind)[-1]
    if not site:
        return kind
    sites = []
    for at in site.split(" in "):
        method, _, bci = at.rpartition(":")
        sites.append(f"{method.split('(')[0].split('.')[-1]}:{bci}" if method else at)
    return f"{kind}@{' in '.join(sites)}"


def receivers(objects: list[str] | None) -> str:
    if objects is None:
        return "objects unknown"
    if not objects:
        return "no object (always null)"
    return ", ".join(short_object(o) for o in objects)


def show(key: str, facts: dict) -> str:
    lines = [key]
    for label, kind in (("reads", "reads"), ("writes", "writes")):
        if facts.get(kind):
            lines.append(f"    {label:<8}{', '.join(short_field(f) for f in facts[kind])}")
    if facts.get("callees"):
        lines.append(f"    {'calls':<8}{', '.join(short_method(c) for c in facts['callees'])}")
    if facts.get("allocates"):
        lines.append("    allocates")
    locks = facts.get("locks", {})
    for kind in EFFECTS:
        for what in facts.get(kind, ()):
            on = f"   on {receivers(locks[what])}" if what in locks else ""
            lines.append(f"    {kind:<7} {what}{on}")
    for access in facts.get("accesses", ()):
        at = (access.get("at") or "").rpartition(":")[2]
        lines.append(f"    {access['kind']:<6}{short_field(access['field']):<30} through {receivers(access['receivers'])}"
                     + (f"   at bci {at}" if at else ""))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("--method", default="", help="only methods whose name contains this")
    parser.add_argument("--all", action="store_true", help="also the methods outside the program, such as the JDK's")
    args = parser.parse_args()

    facts, graphs = load(args.export)
    program = {g.name + g.descriptor for g in graphs.values()}
    shown = [show(key, facts.methods[key]) for key in sorted(facts.methods)
             if (args.all or key in program) and args.method in key]
    if not shown:
        print(f"no method of {args.export} contains {args.method!r}", file=sys.stderr)
        return 1
    print("\n\n".join(shown))
    if not args.all:
        print(f"\n{len(shown)} of the program's methods; {len(facts.methods)} methods have facts (--all for the rest)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
