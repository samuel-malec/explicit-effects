"""Whether an example's item is shared where the program uses it (graal-export/examples/concurrency,
Published* and LocalIn*): the objects its accesses to the item's field may be on, as the analysis
names them, are shared if any of them is. The analysis names an object by where it was allocated, or
by its type alone, which stands for any object of the type."""

from graal.graal_import import PointsToFacts


def item_shared(facts: PointsToFacts, example: str) -> str:
    """`shared`, `local`, or `unused` if the program has no access to the item's field."""
    field = f"concurrency.{example}$Item.value"
    receivers = [a["receivers"] for method, e in facts.methods.items() if method.startswith(f"concurrency.{example}.")
                 for a in e.get("accesses", ()) if a["field"] == field]
    if not receivers:
        return "unused"
    shared = facts.shared or frozenset()
    return "shared" if any(r is None or any(o in shared for o in r) for r in receivers) else "local"
