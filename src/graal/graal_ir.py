"""Representation of Graal IR structures alongside the points-to information needed for analysis."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Node:
    id: int
    op: str
    type: str
    inputs: tuple[int, ...] = ()
    bci: int = -1
    index: int | None = None
    value: str | None = None
    field: str | None = None
    cls: str | None = None
    args: tuple[int, ...] = ()
    target: str | None = None
    callees: tuple[str, ...] = ()
    flow: str | None = None
    phi: tuple[tuple[int, int], ...] = ()
    receivers: tuple[str, ...] | None = None  # what a field or array access may touch, None when unknown
    at: str | None = None  # where a field or array access is: method, bci, and the calls it was inlined through
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
    to: int
    label: str | None  # true/false, normal/exception edge


@dataclass(frozen=True)
class Block:
    id: int
    succs: tuple[Edge, ...]
    exit: str | None  # "return", "unwind", "deopt", ...
    end: dict  # how the block ends, {"node": "IfNode", "bci": 2, "cond": "IsNullNode"}
    nodes: tuple[Node, ...] = ()


@dataclass(frozen=True)
class Graph:
    name: str
    descriptor: str
    unsupported: tuple[str, ...]
    entry: int
    blocks: dict[int, Block]
    static: bool = False


def _node(raw: dict) -> Node:
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
        receivers=tuple(raw["receivers"]) if raw.get("receivers") is not None else None,
        at=raw.get("at"),
        ordered=raw.get("ordered", False),
        kind=raw.get("kind"),
        fields=tuple(raw.get("fields", ())),
        length=raw.get("length"),
        objects=tuple(raw.get("objects", ())),
        entries=tuple(raw.get("values", ())),
        locked=raw.get("locked", False),
        virtual=raw.get("object") if isinstance(raw.get("object"), int) else None,
        constant=raw.get("object") if isinstance(raw.get("object"), str) else None,
        negated=tuple(raw.get("negated", ())),
    )


def parse_graph(raw: dict) -> Graph:
    """A method's graph, as graal-export writes it."""
    blocks = {}
    for b in raw.get("blocks", ()):
        blocks[b["id"]] = Block(
            id=b["id"],
            succs=tuple(Edge(e["to"], e["label"]) for e in b["succs"]),
            exit=b["exit"],
            end=b.get("end", {}),
            nodes=tuple(_node(n) for n in b.get("nodes", ())),
        )
    return Graph(
        name=raw["name"],
        descriptor=raw["descriptor"],
        unsupported=tuple(raw["unsupported"]),
        entry=raw.get("entry", 0),
        blocks=blocks,
        static=raw.get("static", False),
    )
