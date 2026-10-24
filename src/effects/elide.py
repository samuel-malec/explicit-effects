"""Which monitor sites can go and which volatile accesses can be ordinary: those whose objects only this
thread reaches, and that nothing waits or notifies on, for the monitors.

Usage:
    uv run python -m effects.elide graal-native/out/locks-kills/export.json -o locks.txt

A monitor enter or exit takes a lock to order this thread with the others that take it. When no other
thread can reach any object the site may lock (thread escape, under the assumptions the export was made
with), nothing is ordered and the site can be removed from the code. Two things keep a site:

* the object is waited or notified on, or asked about with `Thread.holdsLock` (the facts' `waits`): those
  need the monitor held, and throw without it, so a site stays if any object it may lock is such an object,
  or if some wait or notify has an object the analysis can't name;
* the virtual machine's own code (`com.oracle.svm`): the assumption that its state is read only by it makes
  its objects look thread-local, which is for the program's sake, not a fact about its queues. Its waits are
  not counted either (JNI's `MonitorExit` asks about any object it is given).

A volatile read or write of a field is the same: it orders this thread with the others that access the
field, and when no other thread reaches any object it may be on, there is none. Waits don't matter to it.

The answer is one line for each site, `method:bci` and `enter` or `exit` after a tab, with the method as
the export names it; for a volatile access `plain-read` or `plain-write` and the field after another tab.
The graph phase removes a lock only when every enter and exit of that lock is listed.
"""

import argparse
from pathlib import Path

from graal.graal_import import PointsToFacts, load_facts

from .signatures import synchronizes_on

VM = "com.oracle.svm."


def waited_on(facts: PointsToFacts) -> tuple[set[str], bool]:
    """The objects some call waits or notifies on, or asks the monitor of, and whether some such call is
    on objects the analysis can't name."""
    objects: set[str] = set()
    unnamed = False
    for method, e in facts.methods.items():
        if method.startswith(VM):
            continue
        for receivers in e.get("waits", {}).values():
            if receivers is None:
                unnamed = True
            else:
                objects.update(receivers)
    return objects, unnamed


def elidable(facts: PointsToFacts) -> dict[str, str]:
    """The sites to change, `method:bci` -> `enter` or `exit` for a monitor to remove, `plain-read` or
    `plain-write` for a volatile access of a field to make an ordinary one (the field after a tab)."""
    waited, unnamed = waited_on(facts)
    sites: dict[str, str] = {}
    for method, e in facts.methods.items():
        if method.startswith(VM):
            continue
        for label, receivers in e.get("locks", {}).items():
            if receivers is None or not receivers or synchronizes_on(facts, receivers):
                continue
            bci = label.rsplit(" at bci ", 1)[1]
            if label.startswith("volatile "):
                # volatile read of F at bci N: nothing orders this thread with another through a field only it reaches.
                kind = "plain-read" if label.startswith("volatile read of ") else "plain-write"
                field = label.split(" of ", 1)[1].rsplit(" at bci ", 1)[0]
                sites[f"{method}:{bci}"] = f"{kind}\t{field}"
            elif not unnamed and not any(r in waited for r in receivers):
                kind = "enter" if label.startswith("MonitorEnterNode") else "exit" if label.startswith("MonitorExitNode") else None
                if kind is not None:
                    sites[f"{method}:{bci}"] = kind
    return sites


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    sites = elidable(load_facts(args.export))
    args.output.write_text("".join(f"{site}\t{kind}\n" for site, kind in sorted(sites.items())))
    monitors = sum(1 for kind in sites.values() if kind in ("enter", "exit"))
    print(f"{monitors} monitor sites to remove, {len(sites) - monitors} volatile accesses to make ordinary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
