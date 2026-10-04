"""Graal IR → Cthulhu transformation

Each method becomes a structure, and each of its basic blocks a λ.
Each basic bloc k of a method becomes a λ.
As of now the entire memory modeling is condensed into one linear value of type `heap`.
( TODO: how to model exceptions ? -> Right now create a phony cthu instruction which acts as an expcetion,
"""

from itertools import count

from cthu.ir import Instr, Lambda, Program, Structure, function_type
from cthu.ssu import linearize
from graal.graal_ir import Block, Edge, Graph, Node

ARITHMETIC = {
    "Add": "add", "Sub": "sub", "Mul": "mul", "SignedDiv": "div", "SignedRem": "rem",
    "And": "and", "Or": "or", "Xor": "xor",
    "LeftShift": "shl", "RightShift": "shr", "UnsignedRightShift": "ushr",
}

UNARY = {"Negate": "neg", "Not": "not"}

COMPARISON = {
    "IntegerEquals": "eq?", "IntegerLessThan": "lt?", "IntegerBelow": "ult?",
    "ObjectEquals": "eq?", "PointerEquals": "eq?",
}

ALIASES = {"Pi", "ValueProxy"}

ENDS = {"If", "Return", "Unwind"}

CALLS = {"Invoke", "InvokeWithException"}

_DESCRIPTOR = {"Z": "int", "B": "int", "C": "int", "S": "int", "I": "int", "J": "long", "F": "float", "D": "double"}


class Unsupported(Exception):
    """The method contains something the translation does not handle yet."""


def structure_name(method: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in method)


def parameter_types(descriptor: str, static: bool) -> list[str]:
    types = [] if static else ["ref"]
    i = 1

    while descriptor[i] != ")":
        if descriptor[i] in "L[":
            while descriptor[i] == "[":
                i += 1
            if descriptor[i] == "L":
                i = descriptor.index(";", i)
            types.append("ref")
        else:
            types.append(_DESCRIPTOR[descriptor[i]])
        i += 1

    return types


def return_type(descriptor: str) -> str | None:
    result = descriptor[descriptor.index(")") + 1:]
    if result == "V":
        return None
    return "ref" if result[0] in "L[" else _DESCRIPTOR[result]


class Translation:
    
    def __init__(self, graphs: dict[str, Graph]):
        self.graphs = graphs
        # A call names its callee by name and descriptor, which tells overloads apart.
        self.keys = {graph.name + graph.descriptor: key for key, graph in graphs.items()}
        self.program = Program()
        self.refused: dict[str, str] = {}

    def translate(self, keys: list[str]) -> Program:
        for key in keys:
            graph = self.graphs[key]

            if "no graph" in graph.unsupported:
                self.refused[key] = "no graph (native or abstract)"
                continue

            method = MethodTranslation(self, graph, structure_name(key))
            
            try:
                structure = method.structure()
            except Unsupported as e:
                self.refused[key] = str(e)
                continue
            
            self.program.structures.append(structure)
            
            for external in method.externals:
                if external not in self.program.externals:
                    self.program.externals.append(external)
        
        return self.program

    def callee_structure(self, method: str) -> tuple[str, bool]:
        key = self.keys.get(method)
        return structure_name(key or method), key is None


class MethodTranslation:
    def __init__(self, translation: Translation, graph: Graph, name: str):
        self.t = translation
        self.g = graph
        self.name = name
        self.nodes = {n.id: n for b in graph.blocks.values() for n in b.nodes}
        self.alias = {n.id: n.inputs[0] for n in self.nodes.values() if n.op in ALIASES}
        self.params = parameter_types(graph.descriptor, graph.static)
        result = return_type(graph.descriptor)
        self.outs = ([("r", result)] if result else []) + [("hout", "heap")]
        self.out_types = [t for _, t in self.outs]
        self.externals: list[str] = []
        self.frames: dict[str, Lambda] = {}

    def value(self, node_id: int) -> int:
        while node_id in self.alias:
            node_id = self.alias[node_id]
        return node_id

    def ref(self, node_id: int) -> str:
        node = self.nodes[self.value(node_id)]
        return f"p{node.index}" if node.op == "Parameter" else f"v{node.id}"

    def type_of(self, node_id: int) -> str:
        return _type(self.nodes[self.value(node_id)])

    def successors(self, block: Block) -> list[Edge]:
        return [e for e in block.succs if e.label != "exception"]

    def _analyse(self) -> None:
        blocks = self.g.blocks

        # A block is doomed if every path from it throws or depotimizes
        doomed = {b.id for b in blocks.values() if b.exit is not None and b.exit != "return"}
        changed = True

        while changed:
            changed = False
            for b in blocks.values():
                succ = self.successors(b)
                if b.id not in doomed and succ and all(e.to in doomed for e in succ):
                    doomed.add(b.id)
                    changed = True
        self.doomed = doomed

        # Find reachable blocks along normal edges
        reached, work = {self.g.entry}, [self.g.entry]
        while work:
            b = blocks[work.pop()]
            if b.id in doomed:
                continue

            for e in self.successors(b):
                if e.to not in reached:
                    reached.add(e.to)
                    work.append(e.to)

        self.order = [b for b in blocks if b in reached]  # Keep the rpo order of blocks 

        # Find which values must come to a block from a different block
        defs, uses = {}, {}
        for b in self.order:
            defs[b], uses[b] = self._defs_and_uses(blocks[b])

        live = {b: set() for b in self.order}
        changed = True

        while changed:
            changed = False
            for b in reversed(self.order):
                if b in doomed:
                    continue
                out = set()
 
                for e in self.successors(blocks[b]):
                    out |= live[e.to] - self._phis(e.to)
                new = uses[b] | (out - defs[b])

                if new != live[b]:
                    live[b] = new
                    changed = True

        # Determine the node ids of parameters the blocks (their respective lambdas) receive
        self.param_ids: dict[int, list[int]] = {}
        for b in self.order:
            block = blocks[b]
            if b not in doomed and block.end.get("node") == "IfNode":
                true, false = self._branches(block)
                union = sorted(live[true] | live[false])
                self.param_ids[true] = self.param_ids[false] = union

        for b in self.order:
            if b != self.g.entry and b not in self.param_ids:
                phis = [n.id for n in blocks[b].nodes if n.op == "ValuePhi"]
                self.param_ids[b] = phis + sorted(live[b] - set(phis))

    def _defs_and_uses(self, block: Block) -> tuple[set[int], set[int]]:
        defs, uses = set(), set()
        for n in block.nodes:
            if n.op == "ValuePhi":
                defs.add(n.id)
                continue
            
            if n.op in ALIASES:
                continue
            
            for i in (*n.inputs, *n.args):
                v = self.value(i)
                if v not in defs:
                    uses.add(v)
            
            if n.type != "void" and n.op not in ENDS:
                defs.add(n.id)

        for e in self.successors(block):  # the phi values this block passes on
            for n in self.g.blocks[e.to].nodes:
                if n.op == "ValuePhi":
                    v = self.value(dict(n.phi)[block.id])
                    if v not in defs:
                        uses.add(v)

        return defs, uses

    def _phis(self, block_id: int) -> set[int]:
        return {n.id for n in self.g.blocks[block_id].nodes if n.op == "ValuePhi"}

    def _branches(self, block: Block) -> tuple[int, int]:
        labels = {e.label: e.to for e in self.successors(block)}
        return labels["true"], labels["false"]

    def structure(self) -> Structure:
        self._analyse()
        structure = Structure(self.name, note=self.g.name)

        for b in self.order:
            lam = self._trap(b) if b in self.doomed else self._block(b)
            structure.lambdas.append(lam)

        structure.lambdas.extend(self.frames.values())
        for lam in structure.lambdas:
            linearize(lam)

        return structure

    def _lambda_name(self, block_id: int) -> str:
        return "run" if block_id == self.g.entry else f"b{block_id}"

    def _lambda_params(self, block_id: int) -> list[tuple[str, str]]:
        if block_id == self.g.entry:
            return [(f"p{i}", t) for i, t in enumerate(self.params)] + [("h", "heap")]
        return [(self.ref(i), self.type_of(i)) for i in self.param_ids[block_id]] + [("h", "heap")]

    def _trap(self, block_id: int) -> Lambda:
        lam = Lambda(self._lambda_name(block_id), self._lambda_params(block_id), list(self.outs),
                     note="traps: every path from here throws")

        lam.body.append(Instr("heap", "trap", ["h"]))

        for name, t in self.outs:
            lam.body.append(Instr(t, "bot", [], [name], [t]))
        return lam

    def _block(self, block_id: int) -> Lambda:
        block = self.g.blocks[block_id]
        lam = Lambda(self._lambda_name(block_id), self._lambda_params(block_id), list(self.outs))
        self.body, self.heap, self.heaps = lam.body, "h", count(1)

        for n in block.nodes:
            self._node(n)

        self._end(block)
        return lam

    def _emit(self, type_: str, op: str, ins: list[str], outs: list[str], out_types: list[str], note: str = "") -> None:
        self.body.append(Instr(type_, op, ins, outs, out_types, note))

    def _next_heap(self) -> str:
        return f"h{next(self.heaps)}"

    def _node(self, n: Node) -> None:
        op, v, t = n.op, f"v{n.id}", _type(n)
        if op in ("Parameter", "ValuePhi") or op in ALIASES or op in ENDS:
            return

        if op == "Constant":
            if t in ("int", "long"):
                self._emit(t, "cons_" + n.value.replace("-", "m"), [], [v], [t])
            elif t == "ref" and n.value == "null":
                self._emit("ref", "null", [], [v], ["ref"])
            else:
                raise Unsupported(f"constant {n.value}")
        elif op in ARITHMETIC:
            self._emit(t, ARITHMETIC[op], [self.ref(i) for i in n.inputs], [v], [t])
        elif op in UNARY:
            self._emit(t, UNARY[op], [self.ref(n.inputs[0])], [v], [t])
        elif op in COMPARISON:
            self._emit(self.type_of(n.inputs[0]), COMPARISON[op], [self.ref(i) for i in n.inputs], [v], ["bool"])
        elif op == "IsNull":
            self._emit("ref", "nil?", [self.ref(n.inputs[0])], [v], ["bool"])
        elif op == "LogicNegation":
            self._emit("bool", "not", [self.ref(n.inputs[0])], [v], ["bool"])
        elif op == "Conditional":
            cond, yes, no = (self.ref(i) for i in n.inputs)
            self._emit("bool", "not", [cond], [f"{v}_not"], ["bool"])
            self._emit(t, "opt", [cond, yes], [f"{v}_yes"], [t])
            self._emit(t, "opt", [f"{v}_not", no], [f"{v}_no"], [t])
            self._emit(t, "join", [f"{v}_yes", f"{v}_no"], [v], [t])
        elif op == "ArrayLength":
            self._emit("ref", "length", [self.ref(n.inputs[0])], [v], ["int"])
        elif op in ("LoadField", "StoreField"):
            self._field(n)
        elif op == "NewInstance":
            h = self._next_heap()
            k = self.t.program.class_index(n.cls)
            self._emit("heap", f"new_{k}", [self.heap], [v, h], ["ref", "heap"], note=n.cls)
            self.heap = h
        elif op in CALLS:
            self._call(n)
        elif op in ("BytecodeException", "ExceptionObject"):
            raise Unsupported("exception handler (a caught exception)")
        elif op in ("CommitAllocation", "VirtualInstance", "AllocatedObject"):
            raise Unsupported("allocation after escape analysis")
        else:
            raise Unsupported(op)

    def _field(self, n: Node) -> None:
        value = _type(n) if n.op == "LoadField" else self.type_of(n.inputs[-1])
        k = self.t.program.field_index(n.field, value)
        h = self._next_heap()
        static = "static" if (n.op == "LoadField" and not n.inputs) or (n.op == "StoreField" and len(n.inputs) == 1) else ""
        ins = [self.heap, *(self.ref(i) for i in n.inputs)]

        if n.op == "LoadField":
            self._emit("heap", f"get{static}_{k}", ins, [f"v{n.id}", h], [_type(n), "heap"], note=n.field)
        else:
            self._emit("heap", f"set{static}_{k}", ins, [h], ["heap"], note=n.field)
        self.heap = h

    def _call(self, n: Node) -> None:
        if len(n.callees) > 1:
            raise Unsupported(f"call to {n.target} with {len(n.callees)} targets")
        callee = n.callees[0] if n.callees else n.target
        structure, external = self.t.callee_structure(callee)

        if external and callee not in self.externals:
            self.externals.append(callee)

        result = None if n.type == "void" else _type(n)
        arg_types = [self.type_of(a) for a in n.args]
        ftype = function_type(arg_types + ["heap"], ([result] if result else []) + ["heap"])
        h = self._next_heap()
        outs = ([f"v{n.id}"] if result else []) + [h]
        self._emit(structure, "run", [], [f"k{n.id}"], [ftype])

        self._emit(ftype, "call", [f"k{n.id}", *(self.ref(a) for a in n.args), self.heap], outs,
                   ([result] if result else []) + ["heap"], note=callee)
        self.heap = h

    def _end(self, block: Block) -> None:
        succ = self.successors(block)
        if block.end.get("node") == "IfNode":
            if_node = next(n for n in block.nodes if n.op == "If")
            true, false = self._branches(block)
            self._branch(if_node.inputs[0], true, false)

        elif block.exit == "return":
            ret = next(n for n in block.nodes if n.op == "Return")
            if ret.inputs:
                self._emit(self.outs[0][1], "move", [self.ref(ret.inputs[0])], ["r"], [self.outs[0][1]])
            self._emit("heap", "move", [self.heap], ["hout"], ["heap"])

        elif len(succ) == 1:
            self._jump(block.id, succ[0].to)
        else:
            raise Unsupported(f"block ending in {block.end.get('node')}")

    def _jump(self, src: int, dst: int) -> None:
        phis = {n.id: dict(n.phi) for n in self.g.blocks[dst].nodes if n.op == "ValuePhi"}
        args = [self.ref(phis[i][src]) if i in phis else self.ref(i) for i in self.param_ids[dst]]
        ftype = function_type([t for _, t in self._lambda_params(dst)], self.out_types)
        self._emit(self.name, self._lambda_name(dst), [], [f"k{dst}"], [ftype])
        self._emit(ftype, "call", [f"k{dst}", *args, self.heap], [n for n, _ in self.outs], self.out_types)

    def _branch(self, cond: int, true: int, false: int) -> None:
        params = self._lambda_params(true)
        ftype = function_type([t for _, t in params], self.out_types)
        frame = self._frame(ftype, params)
        c = self.ref(cond)
        self._emit(self.name, self._lambda_name(true), [], ["kt"], [ftype])
        self._emit(self.name, self._lambda_name(false), [], ["kf"], [ftype])
        self._emit(self.name, frame.name, [], ["frame"], ["frame"])
        self._emit("bool", "not", [c], ["cn"], ["bool"])
        self._emit(ftype, "opt", [c, "kt"], ["at"], [ftype])
        self._emit(ftype, "opt", ["cn", "kf"], ["af"], [ftype])
        self._emit(ftype, "join", ["at", "af", "frame"], ["k"], [ftype])
        args = [self.ref(i) for i in self.param_ids[true]]
        self._emit(ftype, "call", ["k", *args, self.heap], [n for n, _ in self.outs], self.out_types)

    def _frame(self, ftype: str, params: list[tuple[str, str]]) -> Lambda:
        if ftype in self.frames:
            return self.frames[ftype]

        xs = [(f"x{i}", t) for i, (_, t) in enumerate(params[:-1])]
        lam = Lambda(f"frame_{len(self.frames)}", [("A", ftype), ("B", ftype), *xs, ("h", "heap")], list(self.outs))
        lam.body.append(Instr("heap", "fork", ["h"], ["h_a", "h_b"], ["heap", "heap"]))
        outs_a = [f"{name}_a" for name, _ in self.outs]
        outs_b = [f"{name}_b" for name, _ in self.outs]
        lam.body.append(Instr(ftype, "call", ["A", *(x for x, _ in xs), "h_a"], outs_a, self.out_types))
        lam.body.append(Instr(ftype, "call", ["B", *(x for x, _ in xs), "h_b"], outs_b, self.out_types))

        for (name, t), a, b in zip(self.outs, outs_a, outs_b):
            lam.body.append(Instr(t, "join", [a, b], [name], [t]))

        self.frames[ftype] = lam
        return lam


def _type(n: Node) -> str:
    return "bool" if n.type == "cond" else n.type
