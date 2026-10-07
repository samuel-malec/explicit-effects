""" Import a json file which contains Graal IR annotated with points-to information """

import json
from dataclasses import dataclass, field
from pathlib import Path

from .graal_ir import Graph, _graph


@dataclass
class PointsToFacts:
    methods: dict[str, dict] = field(default_factory=dict) # What fields does a method read/write, keyed by name + descriptor
    fields: dict[str, dict] = field(default_factory=dict) # what fields are reachable (read/written)


def load(path: str | Path) -> tuple[PointsToFacts, dict[str, Graph]]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- generate it with:\n"
            "  cd graal-export && ./build.sh examples/Examples.java && "
            "DUMP_IR=out/examples.json ./run-dump.sh Examples"
        )

    data = json.loads(path.read_text())

    if "graphs" not in data:
        raise ValueError(f"{path} has no graphs - it was written with DUMP_JSON, not DUMP_IR")

    graphs = [_graph(g) for g in data["graphs"]]
    counts: dict[str, int] = {}

    for g in graphs:
        counts[g.name] = counts.get(g.name, 0) + 1

    keyed = {(g.name if counts[g.name] == 1 else g.name + g.descriptor): g for g in graphs}
    return PointsToFacts(data.get("methods", {}), data.get("fields", {})), keyed
