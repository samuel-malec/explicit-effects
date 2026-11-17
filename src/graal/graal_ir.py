"""One method's Graal IR as graal-export writes it, read into frozen dataclasses.

A graph is the method after the points-to analysis, scheduled: its blocks in the export's order, each block's
nodes in the order the schedule runs them, a merge's phis and a loop exit's proxies first. `parse_graph` keeps
what the export says, under another name where the JSON key is a Python keyword or means two things:

    in                          inputs
    class                       cls
    from: [{block, value}]      phi: ((block, value), ...)
    values (CommitAllocation)   entries   (a graph's own `values` is something else)
    object, an int              virtual   (AllocatedObject: the virtual object it is)
    object, a string            constant  (Constant: which object it is)

Lists become tuples, and a key a node lacks gets the field's default. `receivers: null` stays None, "the
analysis can't say", which is not `()`, "no object". Nothing reads the blocks' `preds` and `ops`, the nodes'
`at` and `exception_edge` or the graph's `values`, so they are left out. The facts are in graal_import.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Node:
    id: int  # Graal's id of the node, unique in the graph
    op: str  # Graal's node class without "Node": StoreField, InvokeWithException, ValuePhi
    type: str  # int, long, float, double, ref, cond (a condition) or void (no value)
    inputs: tuple[int, ...] = ()  # the values and conditions it uses
    bci: int = -1  # where it is in the method's bytecode; negative when nowhere, -1 when the export gives none (phis)
    index: int | None = None  # a Parameter's position, 0 the receiver of an instance method
    value: str | None = None  # a Constant's value as text: 5, null, Ljava/lang/Object;
    field: str | None = None  # a field access's field: forwarding.AcrossCall$Counter.value
    cls: str | None = None  # the class a NewInstance makes, an InstanceOf tests or a VirtualInstance is
    args: tuple[int, ...] = ()  # an invoke's arguments, the receiver first if there is one
    target: str | None = None  # the method an invoke names, with its descriptor
    callees: tuple[str, ...] = ()  # the methods the analysis linked to the invoke
    flow: str | None = None  # the invoke's flow in the analysis: ok, no-callees, disabled or missing
    phi: tuple[tuple[int, int], ...] = ()  # a ValuePhi's value from each predecessor: (block, value)
    # The objects a field or array access may touch, a monitor may lock, or an AllocatedObject may be;
    # None when the analysis can't say, which is not () (none).
    receivers: tuple[str, ...] | None = None
    ordered: bool = False  # a volatile field access: a load acquires, a store releases
    kind: str | None = None  # an array access's or allocation's element kind: int[], Object[]
    fields: tuple[str, ...] = ()  # an object escape analysis made virtual: its fields, in order
    length: int | None = None  # an array escape analysis made virtual: its length
    objects: tuple[int, ...] = ()  # the virtual objects a CommitAllocation makes
    entries: tuple[int | None, ...] = ()  # their fields' or elements' values, object by object
    locked: bool = False  # whether any of them is locked as it is made
    virtual: int | None = None  # the virtual object an AllocatedObject is
    constant: str | None = None  # an object constant, told apart from others of its type
    negated: tuple[bool, ...] = ()  # which inputs a ShortCircuitOr negates


@dataclass(frozen=True)
class Edge:
    to: int  # the block it goes to
    label: str | None  # true or false after an If, normal or exception after a call that may throw, else None


@dataclass(frozen=True)
class Block:
    id: int
    succs: tuple[Edge, ...]
    # How the method leaves at the block's end: return, unwind (it throws), deopt, or the last node's class
    # for another way; None when the block goes on to another.
    exit: str | None
    end: dict  # the block's last node: {"node": "IfNode", "bci": 2, "cond": "IsNullNode"}
    nodes: tuple[Node, ...] = ()


@dataclass(frozen=True)
class Graph:
    name: str  # class and method: forwarding.AcrossCall.demo
    descriptor: str  # parameter and return types: (Lforwarding/AcrossCall$Counter;Lforwarding/AcrossCall$Link;)I
    unsupported: tuple[str, ...]  # why the exporter refused the method, () if it didn't
    entry: int  # the block the method starts in
    blocks: dict[int, Block]  # by id, in the export's order
    static: bool = False  # no receiver among the parameters


def _node(raw: dict) -> Node:
    receivers = raw.get("receivers")
    obj = raw.get("object")
    return Node(
        id=raw["id"],
        op=raw["op"],
        type=raw["type"],
        inputs=tuple(raw.get("in", ())),
        bci=raw.get("bci", -1),
        index=raw.get("index"),
        value=raw.get("value"),
        field=raw.get("field"),
        cls=raw.get("class"),
        args=tuple(raw.get("args", ())),
        target=raw.get("target"),
        callees=tuple(raw.get("callees", ())),
        flow=raw.get("flow"),
        phi=tuple((e["block"], e["value"]) for e in raw.get("from", ())),
        receivers=None if receivers is None else tuple(receivers),
        ordered=raw.get("ordered", False),
        kind=raw.get("kind"),
        fields=tuple(raw.get("fields", ())),
        length=raw.get("length"),
        objects=tuple(raw.get("objects", ())),
        entries=tuple(raw.get("values", ())),
        locked=raw.get("locked", False),
        virtual=obj if isinstance(obj, int) else None,
        constant=obj if isinstance(obj, str) else None,
        negated=tuple(raw.get("negated", ())),
    )


def _block(raw: dict) -> Block:
    return Block(
        id=raw["id"],
        succs=tuple(Edge(e["to"], e["label"]) for e in raw["succs"]),
        exit=raw["exit"],
        end=raw.get("end", {}),
        nodes=tuple(_node(n) for n in raw.get("nodes", ())),
    )


def parse_graph(raw: dict) -> Graph:
    """A method's graph, as graal-export writes it. A method the exporter has no graph of (`unsupported` says
    `no graph`, or `no graph after the analysis (…)`) has no blocks, and its entry is 0."""
    return Graph(
        name=raw["name"],
        descriptor=raw["descriptor"],
        unsupported=tuple(raw["unsupported"]),
        entry=raw.get("entry", 0),
        blocks={b["id"]: _block(b) for b in raw.get("blocks", ())},
        static=raw.get("static", False),
    )
