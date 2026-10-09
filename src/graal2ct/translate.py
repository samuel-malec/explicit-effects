"""Graal IR → Cthulhu transformation."""

import re
from itertools import count

from cthu.ir import Instr, Lambda, Program, Structure, function_type
from cthu.ssu import linearize
from effects.signatures import REST, Effects, no_analysis
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


def token_names(partitions: tuple[str, ...]) -> dict[str, str]:
    """A token name per partition: `h` for all of memory, `h_rest` for memory
    no field names, `h_int_arr` for an array kind, otherwise `h_` and the
    field's last name, `h_value`, qualified as far as it takes to tell them apart."""
    names = {p: "h" if p == "heap" else "h_rest" for p in partitions if p in ("heap", REST)}
    names |= {p: "h_" + p[:-2] + "_arr" for p in partitions if p.endswith("[]")}
    parts = {p: re.split(r"[.$]", p) for p in partitions if p not in names}
    
    for depth in range(1, max((len(s) for s in parts.values()), default=0) + 1):
        candidates = {p: "h_" + "_".join(s[-depth:]) for p, s in parts.items()}
        if len(set(candidates.values()) | set(names.values())) == len(candidates) + len(names):
            break
    
    for p, s in parts.items():
        names[p] = "".join(c if c.isalnum() else "_" for c in "h_" + "_".join(s[-depth:]))
    
    return names


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

    def __init__(self, graphs: dict[str, Graph], effects: Effects | None = None):
        self.graphs = graphs
        self.effects = effects or no_analysis()
        self.token_names = token_names(self.effects.partitions)
        # A call names its callee by name and descriptor, which tells overloads apart.
        self.keys = {graph.name + graph.descriptor: key for key, graph in graphs.items()}
        self.program = Program()
        self.refused: dict[str, str] = {}

    def translate(self, keys: list[str]) -> Program:
        calls: dict[str, str] = {}
        for key in keys:
            graph = self.graphs[key]

            if "no graph" in graph.unsupported:
                self.refused[key] = "no graph (native or abstract)"
                continue

            if graph.unsupported:
                self.refused[key] = "; ".join(graph.unsupported)
                continue

            method = MethodTranslation(self, graph, structure_name(key))
            
            try:
                structure = method.structure()
            except Unsupported as e:
                self.refused[key] = str(e)
                continue
            
            self.program.structures.append(structure)
            calls.update(method.calls)

        # Called but not defined here: outside the export, refused, or not selected.
        defined = {s.name for s in self.program.structures}
        for structure, method in calls.items():
            if structure not in defined:
                self.program.externals.setdefault(structure, method)
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
        # A constructor returns its receiver, now initialized, and every later
        # use of the object takes that: nothing can publish the object before
        # the constructor, and its final fields, are done.
        self.constructor = graph.name.endswith(".<init>")
        self.receiver = next((n.id for n in self.nodes.values() if n.op == "Parameter" and n.index == 0), None)
        if self.constructor:
            result = "ref"
        self.renamed: dict[int, str] = {}  # objects a constructor call has initialized, in the current λ
        self.token = {p: translation.token_names[p] for p in translation.effects.tokens(graph.name + graph.descriptor)}
        self.tokens = list(self.token.values())
        self.outs = ([("r", result)] if result else []) + [(f"{t}out", "heap") for t in self.tokens]
        self.out_types = [t for _, t in self.outs]
        self.calls: dict[str, str] = {}  # the structures this method calls, and the methods they stand for
        self.frames: dict[str, Lambda] = {}

    def value(self, node_id: int) -> int:
        while node_id in self.alias:
            node_id = self.alias[node_id]
        return node_id

    def ref(self, node_id: int) -> str:
        node = self.nodes[self.value(node_id)]
        if node.id in self.renamed:
            return self.renamed[node.id]
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

        for b in reached - doomed:
            if any(e.label == "exception" and e.to not in doomed for e in blocks[b].succs):
                raise Unsupported(f"exception handler (a caught exception) for bci {blocks[b].end.get('bci')}")

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

        if self.constructor and block.exit == "return" and self.receiver not in defs:
            uses.add(self.receiver)  # a constructor returns it

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
        if self.constructor and self.receiver is None:
            raise Unsupported("a constructor without its receiver")
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
        tokens = [(t, "heap") for t in self.tokens]
        if block_id == self.g.entry:
            return [(f"p{i}", t) for i, t in enumerate(self.params)] + tokens
        return [(self.ref(i), self.type_of(i)) for i in self.param_ids[block_id]] + tokens

    def _trap(self, block_id: int) -> Lambda:
        lam = Lambda(self._lambda_name(block_id), self._lambda_params(block_id), list(self.outs),
                     note="traps: every path from here throws")

        for t in self.tokens:
            lam.body.append(Instr("heap", "trap", [t]))

        for name, t in self.outs:
            lam.body.append(Instr(t, "bot", [], [name], [t]))
        return lam

    def _block(self, block_id: int) -> Lambda:
        block = self.g.blocks[block_id]
        self.renamed = {}
        lam = Lambda(self._lambda_name(block_id), self._lambda_params(block_id), list(self.outs))
        self.body = lam.body
        self.current = {t: t for t in self.tokens}  # each token's version so far in this λ
        self.versions = {t: count(1) for t in self.tokens}

        for n in block.nodes:
            self._node(n)

        self._end(block)
        return lam

    def _emit(self, type_: str, op: str, ins: list[str], outs: list[str], out_types: list[str], note: str = "") -> None:
        self.body.append(Instr(type_, op, ins, outs, out_types, note))

    def _advance(self, token: str) -> tuple[str, str]:
        """The token's current version, and its next, which becomes current."""
        before, after = self.current[token], f"{token}{next(self.versions[token])}"
        self.current[token] = after
        return before, after

    def _token_for(self, partition: str, what: str) -> str:
        if partition not in self.token:
            raise Unsupported(f"{what} touches {partition}, which the signature of {self.g.name} lacks")
        return self.token[partition]

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
            # An allocation takes the rest of memory.
            before, after = self._advance(self._token_for(self.t.effects.partition(REST), f"allocating {n.cls}"))
            k = self.t.program.class_index(n.cls)
            self._emit("heap", f"new_{k}", [before], [v, after], ["ref", "heap"], note=n.cls)
        elif op in CALLS:
            self._call(n)
        elif op in ("BytecodeException", "ExceptionObject"):
            raise Unsupported(f"exception handler (a caught exception) for bci {n.bci}")
        elif op in ("CommitAllocation", "VirtualInstance", "AllocatedObject"):
            raise Unsupported("allocation after escape analysis")
        elif op == "FinalFieldBarrier" and self.constructor:
            pass  # ordered by the receiver the constructor returns
        else:
            raise Unsupported(op)

    def _field(self, n: Node) -> None:
        value = _type(n) if n.op == "LoadField" else self.type_of(n.inputs[-1])
        k = self.t.program.field_index(n.field, value)
        before, after = self._advance(self._token_for(self.t.effects.partition(n.field), n.field))
        static = "static" if (n.op == "LoadField" and not n.inputs) or (n.op == "StoreField" and len(n.inputs) == 1) else ""
        ins = [before, *(self.ref(i) for i in n.inputs)]

        if n.op == "LoadField":
            self._emit("heap", f"get{static}_{k}", ins, [f"v{n.id}", after], [_type(n), "heap"], note=n.field)
        else:
            self._emit("heap", f"set{static}_{k}", ins, [after], ["heap"], note=n.field)

    def _call(self, n: Node) -> None:
        if len(n.callees) > 1:
            raise Unsupported(f"call to {n.target} with {len(n.callees)} targets")
        callee = n.callees[0] if n.callees else n.target
        structure, _ = self.t.callee_structure(callee)
        self.calls[structure] = callee

        # The callee gets the tokens of its own signature; a call the analysis
        # did not resolve gets all of them.
        partitions = self.t.effects.tokens(callee) if n.flow == "ok" else self.t.effects.partitions
        tokens = [self._token_for(p, f"the call to {callee}") for p in partitions]
        heaps = ["heap"] * len(tokens)
        constructs = ".<init>(" in callee  # gives back the object it initialized
        result = "ref" if constructs else None if n.type == "void" else _type(n)
        arg_types = [self.type_of(a) for a in n.args]
        ftype = function_type(arg_types + heaps, ([result] if result else []) + heaps)
        versions = [self._advance(t) for t in tokens]
        outs = ([f"v{n.id}"] if result else []) + [after for _, after in versions]
        self._emit(structure, "run", [], [f"k{n.id}"], [ftype])

        self._emit(ftype, "call", [f"k{n.id}", *(self.ref(a) for a in n.args), *(before for before, _ in versions)], outs,
                   ([result] if result else []) + heaps, note=callee)
        if constructs:
            self.renamed[self.value(n.args[0])] = f"v{n.id}"

    def _end(self, block: Block) -> None:
        succ = self.successors(block)
        if block.end.get("node") == "IfNode":
            if_node = next(n for n in block.nodes if n.op == "If")
            true, false = self._branches(block)
            self._branch(if_node.inputs[0], true, false)

        elif block.exit == "return":
            ret = next(n for n in block.nodes if n.op == "Return")
            if self.constructor:
                self._emit("ref", "move", [self.ref(self.receiver)], ["r"], ["ref"])
            elif ret.inputs:
                self._emit(self.outs[0][1], "move", [self.ref(ret.inputs[0])], ["r"], [self.outs[0][1]])
            for t in self.tokens:
                self._emit("heap", "move", [self.current[t]], [f"{t}out"], ["heap"])

        elif len(succ) == 1:
            self._jump(block.id, succ[0].to)
        else:
            raise Unsupported(f"block ending in {block.end.get('node')}")

    def _jump(self, src: int, dst: int) -> None:
        phis = {n.id: dict(n.phi) for n in self.g.blocks[dst].nodes if n.op == "ValuePhi"}
        args = [self.ref(phis[i][src]) if i in phis else self.ref(i) for i in self.param_ids[dst]]
        ftype = function_type([t for _, t in self._lambda_params(dst)], self.out_types)
        self._emit(self.name, self._lambda_name(dst), [], [f"k{dst}"], [ftype])
        self._emit(ftype, "call", [f"k{dst}", *args, *(self.current[t] for t in self.tokens)], [n for n, _ in self.outs], self.out_types)

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
        self._emit(ftype, "call", ["k", *args, *(self.current[t] for t in self.tokens)], [n for n, _ in self.outs], self.out_types)

    def _frame(self, ftype: str, params: list[tuple[str, str]]) -> Lambda:
        if ftype in self.frames:
            return self.frames[ftype]

        xs = [(f"x{i}", t) for i, (_, t) in enumerate(params[:len(params) - len(self.tokens)])]
        lam = Lambda(f"frame_{len(self.frames)}", [("A", ftype), ("B", ftype), *xs, *((t, "heap") for t in self.tokens)], list(self.outs))
        for t in self.tokens:
            lam.body.append(Instr("heap", "fork", [t], [f"{t}_a", f"{t}_b"], ["heap", "heap"]))
        outs_a = [f"{name}_a" for name, _ in self.outs]
        outs_b = [f"{name}_b" for name, _ in self.outs]
        lam.body.append(Instr(ftype, "call", ["A", *(x for x, _ in xs), *(f"{t}_a" for t in self.tokens)], outs_a, self.out_types))
        lam.body.append(Instr(ftype, "call", ["B", *(x for x, _ in xs), *(f"{t}_b" for t in self.tokens)], outs_b, self.out_types))

        for (name, t), a, b in zip(self.outs, outs_a, outs_b):
            lam.body.append(Instr(t, "join", [a, b], [name], [t]))

        self.frames[ftype] = lam
        return lam


def _type(n: Node) -> str:
    return "bool" if n.type == "cond" else n.type
