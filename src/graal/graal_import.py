"""Read an export of graal-export or of the image builder.

`load_facts` reads only the facts, which every export has: all the kill sets and the lock decisions need.
`load` also reads the graphs, which only an export made with them has (`DUMP_IR`, or
`-H:+SideEffectAnalysisExportGraphs` in the image builder): for the translation and the printers."""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .graal_ir import Graph, parse_graph


@dataclass
class PointsToFacts:
    """The facts as the exporter writes them, in plain dicts."""
    methods: dict[str, dict] = field(default_factory=dict)  # by method: its reads, writes, calls and effects
    fields: dict[str, dict] = field(default_factory=dict)  # the program's own fields: whether each is read and written
    shared: frozenset[str] | None = None  # the objects another thread may reach, None when the export doesn't say


def load_facts(path: str | Path, assumptions: str | None = None) -> PointsToFacts:
    """The facts of an export, with graphs or without. `assumptions` names one set of thread-escape
    assumptions, if the export was made with all of them (`none`, `thread-confined`,
    `thread-confined,vm-fields`, ...): the shared objects are then those under that set."""
    return _facts(json.loads(Path(path).read_text()), assumptions)


def _facts(data: dict, assumptions: str | None = None) -> PointsToFacts:
    if assumptions is not None:
        shared = frozenset(data["sharedObjectsByAssumptions"][assumptions])
    elif "sharedObjects" in data:
        shared = frozenset(data["sharedObjects"])
    else:
        shared = None
    return PointsToFacts(data.get("methods", {}), data.get("fields", {}), shared)


def load(path: str | Path) -> tuple[PointsToFacts, dict[str, Graph]]:
    """The facts and the graphs of an export made with graphs. A graph goes by its method's name,
    `forwarding.AcrossCall.demo`, or by name and descriptor where two graphs of the export have the
    same name (an overload, a bridge): `Examples.countInto(LExamples$Counter;LExamples$Link;)V`."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- generate it with:\n"
            "  cd graal-export && ./build.sh corpus/LoadStoreElimination.java && "
            "DUMP_IR=out/loadstoreelimination.json ./run-dump.sh LoadStoreElimination"
        )

    data = json.loads(path.read_text())

    if "graphs" not in data:
        raise ValueError(f"{path} has no graphs - it was written with DUMP_JSON, not DUMP_IR")

    graphs = [parse_graph(g) for g in data["graphs"]]
    counts = Counter(g.name for g in graphs)
    keyed = {(g.name if counts[g.name] == 1 else g.name + g.descriptor): g for g in graphs}
    return _facts(data), keyed
