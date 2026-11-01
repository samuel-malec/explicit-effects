"""Print the Graal IR of an export as text: blocks in order, each with its nodes
as the schedule has them and where it goes next.

Usage:
    uv run python -m diagnostics.show graal-export/out/suite/forwarding.AcrossCall.json --method demo

Each node is its id, its operation, its type, the ids of its inputs, and what
else the export says about it: a field, a constant, a call's targets, where a
phi's values come from.
"""

import argparse
import sys
from pathlib import Path

from graal.graal_import import load
from graal.graal_ir import Block, Graph, Node


def show(graph: Graph) -> str:
    lines = [f"{graph.name}{graph.descriptor}" + (f"   refused by the exporter: {'; '.join(graph.unsupported)}"
                                                  if graph.unsupported else "")]
    for block in graph.blocks.values():
        lines.append("")
        lines.append(f"block {block.id}" + (" (entry)" if block.id == graph.entry else "") + f" → {_successors(block)}")
        lines += [f"    {_node(n)}" for n in block.nodes]
    return "\n".join(lines)


def _successors(block: Block) -> str:
    if block.exit:
        return block.exit
    return ", ".join(f"{e.to}" + (f" ({e.label})" if e.label else "") for e in block.succs)


def _node(n: Node) -> str:
    inputs = " ".join(str(i) for i in (*n.inputs, *n.args))
    details = []
    if n.op == "Parameter":
        details.append(f"p{n.index}")
    if n.value is not None:
        details.append(n.value)
    if n.field:
        details.append(("volatile " if n.ordered else "") + n.field.rsplit("$", 1)[-1])
    if n.cls:
        details.append(n.cls.rsplit("$", 1)[-1])
    if n.kind:
        details.append(n.kind)
    if n.phi:
        details.append(", ".join(f"from block {b}: {v}" for b, v in n.phi))
    if n.callees or n.target:
        details.append(f"calls {', '.join(n.callees) or n.target}" + ("" if n.flow in (None, "ok") else f" ({n.flow})"))
    if n.receivers is not None:
        details.append(f"objects {', '.join(n.receivers) or 'none'}")
    if n.objects:
        details.append(f"makes {' '.join(map(str, n.objects))}, first values {' '.join(map(str, n.entries))}")
    return f"{n.id:4}  {n.op:22} {n.type:5} {inputs:12} {'  '.join(details)}".rstrip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("--method", default="", help="only methods whose name contains this")
    args = parser.parse_args()

    _, graphs = load(args.export)
    shown = [show(g) for key, g in sorted(graphs.items()) if args.method in key]
    if not shown:
        print(f"no method of {args.export} contains {args.method!r}", file=sys.stderr)
        return 1
    print("\n\n".join(shown))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
