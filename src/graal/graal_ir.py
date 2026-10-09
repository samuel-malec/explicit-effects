"""Representation of Graal IR structures alongside the points-to information needed for analyis."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Op:
    kind: str
    node: int
    bci: int
    field: str | None = None
    obj: int | None = None
    value: int | None = None
    target: str | None = None
    callees: tuple[str, ...] = ()
    flow: str | None = None
    exception_edge: bool = False

    @property
    def resolved(self) -> bool:
        return self.kind != "invoke" or self.flow == "ok"

    def same_location(self, other: "Op") -> bool:
        return self.field == other.field and self.obj == other.obj


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
    exception_edge: bool = False 
    phi: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class Edge:
    to: int
    label: str | None # true/false, normal/exception edge


@dataclass(frozen=True)
class Block:
    id: int
    preds: tuple[int, ...]
    ops: tuple[Op, ...]
    succs: tuple[Edge, ...]
    exit: str | None  # "return", "unwind", "deopt", ...
    end: dict  # how the block ends: {"node": "IfNode", "bci": 2, "cond": "IsNullNode"}
    nodes: tuple[Node, ...] = ()


@dataclass(frozen=True)
class Graph:
    name: str
    descriptor: str
    unsupported: tuple[str, ...]
    entry: int
    blocks: dict[int, Block]
    values: dict[int, str]
    static: bool = False

    @property
    def supported(self) -> bool:
        return not self.unsupported

    def describe(self, value: int | None) -> str:
        if value is None:
            return "static"
        return self.values.get(value, f"#{value}")


def _op(raw: dict) -> Op:
    return Op(
        kind=raw["kind"],
        node=raw["node"],
        bci=raw["bci"],
        field=raw.get("field"),
        obj=raw.get("object"),
        value=raw.get("value"),
        target=raw.get("target"),
        callees=tuple(raw.get("callees", ())),
        flow=raw.get("flow"),
        exception_edge=raw.get("exception_edge", False),
    )


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
        exception_edge=raw.get("exception_edge", False),
        phi=tuple((e["block"], e["value"]) for e in raw.get("from", ())),
    )


def _graph(raw: dict) -> Graph:
    blocks = {}
    for b in raw.get("blocks", ()):
        blocks[b["id"]] = Block(
            id=b["id"],
            preds=tuple(b["preds"]),
            ops=tuple(_op(o) for o in b["ops"]),
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
        values={int(k): v for k, v in raw.get("values", {}).items()},
        static=raw.get("static", False),
    )
