"""Why a locks export lists no site: every monitor and volatile site of the export, by what keeps it.

    uv run python scripts/sharing/why_no_locks.py graal-native/out/petclinic/lockscutoff/locks/export.json

Uses the decision code of effects.elide, so the counts are what the tool saw. A control is the same run on an
export that lists sites (javac with cutoff 100: 66)."""
import collections
import sys
from pathlib import Path

from effects.elide import VM, waited_on
from effects.signatures import synchronizes_on
from graal.graal_import import load_facts

facts = load_facts(Path(sys.argv[1]))
waited, unnamed = waited_on(facts)
shared = facts.shared
print(f"{len(facts.methods)} methods, {len(shared) if shared is not None else None} shared objects, "
      f"a wait on objects the analysis can't name: {unnamed}, {len(waited)} waited-on objects")
count: collections.Counter = collections.Counter()
alone: collections.Counter = collections.Counter()  # shared receiver that is the only shared one of a site
for method, e in facts.methods.items():
    where = "vm" if method.startswith(VM) else "other"
    for label, receivers in e.get("locks", {}).items():
        kind = "volatile" if label.startswith("volatile ") else "monitor"
        if receivers is None:
            why = "receivers not named"
        elif not receivers:
            why = "no receivers"
        elif synchronizes_on(facts, receivers):
            why = "a shared object among the receivers"
            blockers = [o for o in receivers if shared is not None and o in shared]
            if len(blockers) == 1:
                alone[blockers[0]] += 1
        elif kind == "monitor" and (unnamed or any(r in waited for r in receivers)):
            why = "waited on"
        else:
            why = "can be removed"
        count[(where, kind, why)] += 1
for key, n in sorted(count.items()):
    print(f"{n:8}  {key[0]:6} {key[1]:9} {key[2]}")
print(f"\n{sum(alone.values())} sites have exactly one shared object among their receivers, {len(alone)} different objects; "
      f"those named java.lang.Object or an array: {sum(n for o, n in alone.items() if o == 'java.lang.Object' or o.endswith('[]'))}")
print("shared objects that alone keep the most sites:")
for obj, n in alone.most_common(15):
    print(f"{n:8}  {obj}")
