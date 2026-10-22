""" Graal IR → Cthulhu transformation. """

import re
from itertools import count

from cthu.ir import THROWS, TRAPS, Instr, Lambda, Program, Structure, frame_type, function_type
from cthu.ssu import linearize
from effects.signatures import REST, Effects, no_analysis
from graal.graal_ir import Block, Graph, Node

ARITHMETIC = {
    "Add": "add", "Sub": "sub", "Mul": "mul", "SignedDiv": "div", "SignedRem": "rem",
    "SignedFloatingIntegerDiv": "div", "SignedFloatingIntegerRem": "rem", "FloatDiv": "div", "FloatRem": "rem",
    "And": "and", "Or": "or", "Xor": "xor",
    "LeftShift": "shl", "RightShift": "shr", "UnsignedRightShift": "ushr",
    "Min": "min", "Max": "max",
}

UNARY = {"Negate": "neg", "Not": "not", "Abs": "abs", "Sqrt": "sqrt"}

COMPARISON = {
    "IntegerEquals": "eq?", "IntegerLessThan": "lt?", "IntegerBelow": "ult?",
    "ObjectEquals": "eq?", "PointerEquals": "eq?", "FloatEquals": "eq?", "FloatLessThan": "lt?",
}

CONVERSIONS = {"Narrow", "SignExtend", "ZeroExtend", "FloatConvert", "Reinterpret"}
NUMBERS = {"int", "long", "float", "double"}

# What escape analysis made virtual: described, and made by a CommitAllocation.
VIRTUAL = {"VirtualInstance", "VirtualArray", "VirtualBoxing"}

# Nodes that touch memory in a way the dialect has no operation for. Each becomes a call to
# an external that takes every token of the method: the method's signature covers the node.
OPAQUE = {"EnsureClassInitialized", "MarkStaticFinalFieldInitialized", "PureBox", "AllocatingBox", "CopyOf",
          "CopyOfRange",
          "ArrayEquals", "ArrayRegionEquals", "ArrayRegionEqualsWithMask", "ArrayCompareTo", "ArrayRegionCompareTo",
          "ArrayIndexOf", "VectorizedHashCode", "CalcStringAttributes", "StringLatin1Inflate",
          "ArrayCopyWithConversions",
          "UnaryMathIntrinsic", "ArrayCopy"}

ALIASES = {"Pi", "ValueProxy", "PublishWrites", "StateSplitProxy"}

ENDS = {"If", "Return", "Unwind"}

CALLS = {"Invoke", "InvokeWithException"}

CAUGHT = "ExceptionObject"

_DESCRIPTOR = {"Z": "int", "B": "int", "C": "int", "S": "int", "I": "int", "J": "long", "F": "float", "D": "double"}


class Unsupported(Exception):
    """The method contains something the translation does not handle yet."""


def structure_name(method: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in method)


def token_names(partitions: tuple[str, ...]) -> dict[str, str]:
    """A token name per heap partition"""
    names = {p: "h" if p == "heap" else "h_rest" for p in partitions if p in ("heap", REST)}
    names |= {p: "h_" + p[:-2] + "_arr" for p in partitions if p.endswith("[]")}
    parts = {p: re.split(r"[.$]", p) for p in partitions if p not in names}

    for depth in range(1, max((len(s) for s in parts.values()), default=0) + 1):
        candidates = {p: "h_" + "_".join(s[-depth:]) for p, s in parts.items()}
        if len(set(candidates.values()) | set(names.values())) == len(candidates) + len(names):
            break

    for p, s in parts.items():
        names[p] = "".join(c if c.isalnum() else "_" for c in ("h_" + "_".join(s[-depth:])).replace("[]", "_arr"))
        names[p] += "_" if names[p][-1].isdigit() else ""

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
        self.keys = {graph.name + graph.descriptor: key for key, graph in graphs.items()}
        self.program = Program()
        self.refused: dict[str, str] = {}  # each method refused, and why

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

    def callee_structure(self, method: str) -> str:
        return structure_name(self.keys.get(method) or method)


class MethodTranslation:
    def __init__(self, translation: Translation, graph: Graph, name: str):
        self.t = translation
        self.g = graph
        self.name = name
        self.nodes = {n.id: n for b in graph.blocks.values() for n in b.nodes}
        self.alias = {n.id: n.inputs[0] for n in self.nodes.values() if n.op in ALIASES}
        self.params = parameter_types(graph.descriptor, graph.static)
        result = return_type(graph.descriptor)

        self.constructor = graph.name.endswith(".<init>")
        self.receiver = next((n.id for n in self.nodes.values() if n.op == "Parameter" and n.index == 0), None)
        if self.constructor:
            result = "ref"

        self.renamed: dict[int, str] = {}  # objects a constructor call has initialized, in the block being translated
        # A virtual object goes by the name of the AllocatedObject that gives it out.
        self.allocated = {n.virtual if n.virtual is not None else n.inputs[0]: n.id for n in self.nodes.values() if
                          n.op == "AllocatedObject"}

        self.block_of = {n.id: b.id for b in graph.blocks.values() for n in b.nodes}
        self.token = {p: translation.token_names[p] for p in translation.effects.tokens(graph.name + graph.descriptor)}
        self.tokens = list(self.token.values())

        self.outs = ([("r", result)] if result else []) + [("exc", "ref")] + [(f"{t}out", "heap") for t in self.tokens]
        self.out_types = [t for _, t in self.outs]
        self.calls: dict[str, str] = {}  # the structures this method calls, and the methods they stand for
        self.frames: dict[str, Lambda] = {}

        # The block being translated, which _block sets up for _node, _end and what they call.
        self.block_id = graph.entry
        self.body: list[Instr] = []  # the λ's instructions so far
        self.current: dict[str, str] = {}  # each token's version so far in this λ
        self.versions: dict[str, count] = {}  # the numbers each token's next versions get
        self.throwing: int | None = None  # the node that ends the block and may throw, if any

    def value(self, node_id: int) -> int:
        while node_id in self.alias:
            node_id = self.alias[node_id]
        return node_id

    def ref(self, node_id: int) -> str:
        node = self.nodes[self.value(node_id)]
        if node.type == "void" and node.op not in VIRTUAL:
            raise Unsupported(f"{node.op} as a value, which the export gives no type")

        if node.op in VIRTUAL:
            return f"v{self.allocated.get(node.id, node.id)}"

        if node.id in self.renamed:
            return self.renamed[node.id]

        return f"p{node.index}" if node.op == "Parameter" else f"v{node.id}"

    def type_of(self, node_id: int) -> str:
        return _type(self.nodes[self.value(node_id)])

    def _every_path(self, seed: set[int]) -> set[int]:
        """The blocks from which every path ends in a block of seed, seed included."""
        found = set(seed)
        changed = True

        while changed:
            changed = False
            for b in self.g.blocks.values():
                if b.id not in found and b.succs and all(e.to in found for e in b.succs):
                    found.add(b.id)
                    changed = True

        return found

    def _analyse(self) -> None:
        blocks = self.g.blocks
        self.stops = self._every_path({b.id for b in blocks.values() if b.exit not in (None, "return", "unwind")})
        self.throws = self._every_path({b.id for b in blocks.values() if b.exit == "unwind"} | self.stops)

        # Find reachable blocks (along exception edges too)
        reached, work = {self.g.entry}, [self.g.entry]
        while work:
            b = blocks[work.pop()]
            if b.id in self.stops:
                continue

            for e in b.succs:
                if e.to not in reached:
                    reached.add(e.to)
                    work.append(e.to)

        # A node that may throw ends its block, with an edge to where the exception goes, which
        # starts by taking the exception: the value that node gives back besides its own.
        self.caught: dict[int, int] = {}
        for b in reached - self.stops:
            for e in blocks[b].succs:
                if e.label == "exception":
                    first = blocks[e.to].nodes[0] if blocks[e.to].nodes else None
                    if first is None or first.op != CAUGHT:
                        raise Unsupported(
                            f"an exception edge to a block that doesn't take the exception, bci {blocks[b].end.get('bci')}")
                    self.caught[b] = first.id

        self.order = [b for b in blocks if b in reached]

        # Find which values must come to a block from a different block
        defs, uses = {}, {}
        for b in self.order:
            defs[b], uses[b] = self._defs_and_uses(blocks[b])

        live = {b: set() for b in self.order}
        changed = True

        while changed:
            changed = False
            for b in reversed(self.order):
                if b in self.stops:
                    continue
                out = set()

                for e in blocks[b].succs:
                    out |= live[e.to] - self._phis(e.to)
                new = uses[b] | (out - defs[b])

                if new != live[b]:
                    live[b] = new
                    changed = True

        # Determine the node ids of parameters the blocks receive.
        self.param_ids: dict[int, list[int]] = {}
        for b in self.order:
            block = blocks[b]
            if b in self.stops:
                continue
            if block.end.get("node") == "IfNode":
                true, false = self._branches(block)
                union = sorted(live[true] | live[false])
                self.param_ids[true] = self.param_ids[false] = union
            elif b in self.caught:
                normal, exceptional = self._outcomes(block)
                union = [self.caught[b]] + sorted((live[normal] | live[exceptional]) - {self.caught[b]})
                self.param_ids[normal] = self.param_ids[exceptional] = union

        for b in self.order:
            if b != self.g.entry and b not in self.param_ids:
                phis = [n.id for n in blocks[b].nodes if n.op == "ValuePhi"]
                self.param_ids[b] = phis + sorted(live[b] - set(phis))

    def _defs_and_uses(self, block: Block) -> tuple[set[int], set[int]]:
        defs, uses = set(), set()
        if block.id in self.caught:
            defs.add(self.caught[block.id])
        for n in block.nodes:
            if n.op in ("ValuePhi", CAUGHT):
                defs.add(n.id)
                continue

            if n.op in ALIASES:
                continue

            for i in (*n.inputs, *n.args):
                v = self.value(i)
                if v not in defs and not (
                        v in self.nodes and (self.nodes[v].op in VIRTUAL or self.nodes[v].type == "void")):
                    uses.add(v)

            if n.type != "void" and n.op not in ENDS:
                defs.add(n.id)

        if self.constructor and block.exit == "return" and self.receiver not in defs:
            uses.add(self.receiver)

        for e in block.succs:  # the phi values this block passes on
            for n in self.g.blocks[e.to].nodes:
                if n.op == "ValuePhi":
                    v = self.value(dict(n.phi)[block.id])
                    if v not in defs:
                        uses.add(v)

        return defs, uses

    def _phis(self, block_id: int) -> set[int]:
        """The values a block's predecessors give it on the edge: its phis, and an exception."""
        return {n.id for n in self.g.blocks[block_id].nodes if n.op in ("ValuePhi", CAUGHT)}

    def _branches(self, block: Block) -> tuple[int, int]:
        labels = {e.label: e.to for e in block.succs}
        return labels["true"], labels["false"]

    def _outcomes(self, block: Block) -> tuple[int, int]:
        """Where a block whose last node may throw goes on: normal and exceptional flow."""
        labels = {e.label: e.to for e in block.succs}
        return labels["normal"], labels["exception"]

    def structure(self) -> Structure:
        if self.constructor and self.receiver is None:
            raise Unsupported("a constructor without its receiver")
        self._analyse()
        structure = Structure(self.name, note=self.g.name)

        for b in self.order:
            lam = self._trap(b) if b in self.stops else self._block(b)
            if b in self.throws and b not in self.stops:
                lam.exit = THROWS
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
        # Every path from here deoptimizes, which stops the program: ahead-of-time code never comes back.
        lam = Lambda(self._lambda_name(block_id), self._lambda_params(block_id), list(self.outs), exit=TRAPS)

        for t in self.tokens:
            lam.body.append(Instr("heap", "trap", [t]))

        for name, t in self.outs:
            lam.body.append(Instr(t, "bot", [], [name], [t]))
        return lam

    def _block(self, block_id: int) -> Lambda:
        block = self.g.blocks[block_id]
        self.block_id = block_id
        self.renamed = {}
        lam = Lambda(self._lambda_name(block_id), self._lambda_params(block_id), list(self.outs))
        self.body = lam.body
        self.current = {t: t for t in self.tokens}  # each token's version so far in this λ
        self.versions = {t: count(1) for t in self.tokens}
        self.throwing = next((n.id for n in reversed(block.nodes) if n.op in CALLS or n.op in OPAQUE), None) \
            if block_id in self.caught else None

        for n in block.nodes:
            self._node(n)

        self._end(block)
        return lam

    def _emit(self, type_: str, op: str, ins: list[str], outs: list[str], out_types: list[str], note: str = "",
              at: str = "", field: str = "") -> None:
        self.body.append(Instr(type_, op, ins, outs, out_types, note, at, field))

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
        if op in ("Parameter", "ValuePhi", CAUGHT) or op in ALIASES or op in ENDS:
            return

        if op == "Constant":
            if t in ("int", "long"):
                self._emit(t, "cons_" + n.value.replace("-", "m"), [], [v], [t])
            elif t == "ref" and n.value == "null":
                self._emit("ref", "null", [], [v], ["ref"])
            else:  # an object, a string, a float: a constant of the program's
                k = self.t.program.constant_index(t, n.constant or n.value or "")
                self._emit(t, f"const_{k}", [], [v], [t])

        elif op == "InstanceOf":
            k = self.t.program.class_index(n.cls)
            self._emit("ref", f"instanceof_{k}", [self.ref(n.inputs[0])], [v], ["bool"], note=n.cls)

        elif op == "InstanceOfDynamic":  # Class.isInstance: the class is a value
            self._emit("ref", "isinstance", [self.ref(n.inputs[0]), self.ref(n.inputs[1])], [v], ["bool"])

        elif op in CONVERSIONS:
            source = self.type_of(n.inputs[0])
            if source not in NUMBERS or t not in NUMBERS:
                raise Unsupported(f"{op} from {source} to {t}")
            self._emit(source, f"to_{t}", [self.ref(n.inputs[0])], [v], [t])

        elif op in ("LoadHub", "GetClass", "LoadArrayComponentHub"):  # a class, which never changes
            self._emit("ref", "hub", [self.ref(n.inputs[0])], [v], ["ref"])

        elif op == "Unbox":
            self._emit("ref", f"unbox_{t}", [self.ref(n.inputs[0])], [v], [t])

        elif op == "IntegerTest": 
            x, y = n.inputs[:2]
            t_in = self.type_of(x)
            self._emit(t_in, "and", [self.ref(x), self.ref(y)], [f"{v}_and"], [t_in])
            self._emit(t_in, "cons_0", [], [f"{v}_zero"], [t_in])
            self._emit(t_in, "eq?", [f"{v}_and", f"{v}_zero"], [v], ["bool"])

        elif op == "ShortCircuitOr":
            if len(n.negated) != 2:
                raise Unsupported(op)
            sides = []
            for side, negated in zip(n.inputs[:2], n.negated):
                sides.append(self.ref(side))
                if negated:
                    self._emit("bool", "not", [sides[-1]], [f"{v}_side{len(sides)}"], ["bool"])
                    sides[-1] = f"{v}_side{len(sides)}"
            self._emit("bool", "or", sides, [v], ["bool"])

        elif op in ("IntegerNormalizeCompare", "FloatNormalizeCompare"):
            self._emit(self.type_of(n.inputs[0]), "cmp", [self.ref(i) for i in n.inputs[:2]], [v], ["int"])

        elif op in ("LoadIndexed", "StoreIndexed"):
            self._array(n)

        elif op == "NewArray":
            before, after = self._advance(self._token_for(self.t.effects.partition(REST), f"allocating {n.kind}"))
            self._emit("heap", f"newarray_{_element(n.kind)}", [before, self.ref(n.inputs[0])], [v, after],
                       ["ref", "heap"], note=n.kind)

        elif op == "CommitAllocation":
            self._commit(n)

        elif op in VIRTUAL or op == "AllocatedObject":
            pass  # made by the CommitAllocation

        elif op in OPAQUE:
            self._opaque(n)

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

        elif op == "BytecodeException":
            # A check failed, of a receiver, an index, a divisor or a cast: a new exception, which
            # nothing else has seen. The facts give it no effect, as Native Image's analysis does.
            self._emit("ref", "exception", [], [v], ["ref"], note="a check failed")

        elif op == "FinalFieldBarrier" and self.constructor:
            pass  # ordered by the receiver the constructor returns

        elif op == "MonitorId":
            pass  # names the lock's slot in the frame, which nothing here reads

        elif op in ("MonitorEnter", "MonitorExit"):
            # Taking a lock acquires, leaving it releases: on every token of memory another thread
            # may touch, unless no other thread can reach the objects the lock may be.
            self._emit("ref", "drop", [self.ref(n.inputs[0])], [], [])
            self._synchronize("acquire" if op == "MonitorEnter" else "release", f"{op} at bci {n.bci}", n.receivers)

        elif op == "Membar":
            self._synchronize("release", f"{op} at bci {n.bci}")
            self._synchronize("acquire", f"{op} at bci {n.bci}")

        else:
            raise Unsupported(op)

    def _synchronize(self, kind: str, what: str, objects: tuple[str, ...] | None = None) -> None:
        """An acquire or a release on every token of memory another thread may touch, unless it
        synchronizes on objects no other thread can reach, which orders it with nothing."""
        if not self.t.effects.synchronizes(objects):
            return
        for partition in self.t.effects.partitions:
            if partition in self.token and partition in self.t.effects.shared:
                before, after = self._advance(self.token[partition])
                self._emit("heap", kind, [before], [after], ["heap"], note=what)

    def _field(self, n: Node) -> None:
        if n.ordered and n.op == "LoadField":
            # A volatile read acquires before it reads: what it reads may be another thread's
            # write, and so may anything read after it.
            self._synchronize("acquire", f"volatile read of {n.field} at bci {n.bci}", n.receivers)
        elif n.ordered:
            # A volatile write releases before it writes: another thread that reads the new value
            # may see anything written before it, and the value itself.
            self._synchronize("release", f"volatile write of {n.field} at bci {n.bci}", n.receivers)
        value = _type(n) if n.op == "LoadField" else self.type_of(n.inputs[-1])
        k = self.t.program.field_index(n.field, value)
        try:
            partition = self.t.effects.partition(n.field, None if n.receivers is None else frozenset(n.receivers))
        except ValueError as e:  # objects the facts don't list together
            raise Unsupported(str(e)) from e

        before, after = self._advance(self._token_for(partition, n.field))
        static = "static" if (n.op == "LoadField" and not n.inputs) or (
                n.op == "StoreField" and len(n.inputs) == 1) else ""
        ins = [before, *(self.ref(i) for i in n.inputs)]

        if n.op == "LoadField":
            self._emit("heap", f"get{static}_{k}", ins, [f"v{n.id}", after], [_type(n), "heap"], field=n.field,
                       at=n.at or "")
        else:
            self._emit("heap", f"set{static}_{k}", ins, [after], ["heap"], field=n.field, at=n.at or "")

    def _array(self, n: Node) -> None:
        try:
            partition = self.t.effects.partition(n.kind, None if n.receivers is None else frozenset(n.receivers))
        except ValueError as e:  # objects the facts don't list together
            raise Unsupported(str(e)) from e

        before, after = self._advance(self._token_for(partition, n.kind))
        ins = [before, *(self.ref(i) for i in n.inputs)]

        if n.op == "LoadIndexed":
            self._emit("heap", f"aget_{_element(n.kind)}", ins, [f"v{n.id}", after], [_type(n), "heap"], note=n.kind,
                       at=n.at or "")
        else:
            self._emit("heap", f"aset_{_element(n.kind)}", ins, [after], ["heap"], note=n.kind, at=n.at or "")

    def _commit(self, n: Node) -> None:
        """Makes the objects escape analysis left virtual, then gives their fields and
        elements their values: one object may point to another."""
        if not n.objects:  # an export from before the commits were described
            raise Unsupported("allocation after escape analysis")
        if n.locked:
            raise Unsupported("an allocation escape analysis made, locked as it is made")
        rest = self._token_for(self.t.effects.partition(REST), "allocating")
        objects = [self.nodes[o] for o in n.objects]
        for o in objects:
            if self.block_of.get(self.allocated.get(o.id), self.block_id) != self.block_id:
                raise Unsupported("an allocation escape analysis made, given out in another block")
            before, after = self._advance(rest)
            name = self.ref(o.id)
            if o.op != "VirtualArray":
                self._emit("heap", f"new_{self.t.program.class_index(o.cls)}", [before], [name, after], ["ref", "heap"],
                           note=o.cls)
            else:
                self._emit("int", f"cons_{o.length}", [], [f"{name}_len"], ["int"])
                self._emit("heap", f"newarray_{_element(o.kind)}", [before, f"{name}_len"], [name, after],
                           ["ref", "heap"], note=o.kind)

        start = 0
        for o in objects:
            size = o.length if o.op == "VirtualArray" else len(o.fields)
            name = self.ref(o.id)
            given = self.nodes.get(self.allocated.get(o.id))
            receivers = frozenset(given.receivers) if given is not None and given.receivers is not None else None
            
            for i, value in enumerate(n.entries[start:start + size]):
                field = o.fields[i] if o.op != "VirtualArray" else o.kind
                partition = self._initialized(field, receivers)
                # A part nothing in the method or its callees touches is no ordering's business:
                # the object is new, and the facts leave initializing it out.
                if value is None or partition not in self.token:
                    continue

                before, after = self._advance(self.token[partition])
                
                if o.op != "VirtualArray":
                    k = self.t.program.field_index(field, self.type_of(value))
                    self._emit("heap", f"init_{k}", [before, name, self.ref(value)], [after], ["heap"], field=field)
                else:
                    self._emit("int", f"cons_{i}", [], [f"{name}_at{i}"], ["int"])
                    self._emit("heap", f"aset_{_element(o.kind)}", [before, name, f"{name}_at{i}", self.ref(value)],
                               [after], ["heap"], note=o.kind)
            start += size

    def _initialized(self, field: str, receivers: frozenset | None) -> str | None:
        """The partition of a new object's field: by where the object was allocated, else by
        the field alone; None if the facts have neither, since nothing they list touches it."""
        for objects in (receivers, None):
            try:
                return self.t.effects.partition(field, objects)
            except ValueError:
                continue
        return None

    def _opaque(self, n: Node) -> None:
        """A node the dialect has no operation for, as a call to an external that takes its
        values and every token of the method."""
        structure = f"graal_{n.op}"
        self.calls[structure] = n.op
        result = None if n.type == "void" else _type(n)
        values = [i for i in n.inputs if self.nodes[self.value(i)].op not in VIRTUAL and self.type_of(i) != "void"]
        heaps = ["heap"] * len(self.tokens)
        thrown = self._thrown(n) if n.id == self.throwing else []  # one that Graal says may throw
        ftype = function_type([self.type_of(i) for i in values] + heaps,
                              ([result] if result else []) + [t for _, t in thrown] + heaps)
        
        versions = [self._advance(t) for t in self.tokens]
        k = self._continuation(n.id)
        
        self._emit(structure, "run", [], [k], [ftype])
        self._emit(ftype, "call", [k, *(self.ref(i) for i in values), *(before for before, _ in versions)],
                   ([f"v{n.id}"] if result else []) + [x for x, _ in thrown] + [after for _, after in versions],
                   ([result] if result else []) + [t for _, t in thrown] + heaps, note=n.op)

    def _thrown(self, n: Node) -> list[tuple[str, str]]:
        """The exception the node that ends the block gives back, as the block's exception edge
        names it: the value the handler takes."""
        if n.id != self.throwing:
            raise Unsupported(f"{n.op} at bci {n.bci} whose exception goes nowhere: Graal leaves it implicit")
        return [(self.ref(self.caught[self.block_id]), "ref")]

    def _call(self, n: Node) -> None:
        if len(n.callees) > 1:
            # A dispatch to one of several targets
            callee = n.target
            structure = structure_name("dispatch " + n.target)
            self.calls[structure] = f"one of {', '.join(n.callees)}"
        else:
            callee = n.callees[0] if n.callees else n.target
            structure = self.t.callee_structure(callee)
            self.calls[structure] = callee

        # The callee gets the tokens of its own signature, a dispatch those of every
        # target. A call the analysis found no target for gets every token of the method:
        # all of them, as the method then touches everything, unless the image's analysis
        # found the call dead, when it never runs.
        if n.flow == "ok":
            wanted = set().union(*(self.t.effects.tokens(c) for c in n.callees))
            partitions = [p for p in self.t.effects.partitions if p in wanted]
            # A token no target writes comes back unchanged, which the rules may see through.
            observes = tuple(at - len(partitions) for at, p in enumerate(partitions)
                             if all(self.t.effects.keeps(c, p) for c in n.callees))
        else:
            partitions = [p for p in self.t.effects.partitions if p in self.token]
            observes = ()

        tokens = [self._token_for(p, f"the call to {callee}") for p in partitions]
        heaps = ["heap"] * len(tokens)
        constructs = ".<init>(" in callee

        result = "ref" if constructs else None if n.type == "void" else _type(n)
        thrown = self._thrown(n)
        arg_types = [self.type_of(a) for a in n.args]
        
        out_types = ([result] if result else []) + [t for _, t in thrown] + heaps
        ftype = function_type(arg_types + heaps, out_types)
        versions = [self._advance(t) for t in tokens]
        
        outs = ([f"v{n.id}"] if result else []) + [x for x, _ in thrown] + [after for _, after in versions]
        k = self._continuation(n.id)
        self._emit(structure, "run", [], [k], [ftype])

        self._emit(ftype, "call", [k, *(self.ref(a) for a in n.args), *(before for before, _ in versions)], outs,
                   out_types, note=callee)
        self.body[-1].observes = observes
        if constructs:
            self.renamed[self.value(n.args[0])] = f"v{n.id}"

    def _continuation(self, node_id: int) -> str:
        """A call's callee as a value: k and the node, unless a jump to a block of that number has it."""
        return f"k{node_id}" if node_id not in self.g.blocks else f"kc{node_id}"

    def _end(self, block: Block) -> None:
        if block.end.get("node") == "IfNode":
            if_node = next(n for n in block.nodes if n.op == "If")
            true, false = self._branches(block)
            self._branch(self.ref(if_node.inputs[0]), true, false)

        elif block.id in self.caught:
            # The node that ends the block gave back an exception, null when it didn't throw: go
            # on normally, or where the exception goes, which takes it.
            normal, exceptional = self._outcomes(block)
            exception = self.ref(self.caught[block.id])
            self._emit("ref", "nil?", [exception], [f"{exception}_none"], ["bool"])
            self._branch(f"{exception}_none", normal, exceptional)

        elif block.exit == "return":
            ret = next(n for n in block.nodes if n.op == "Return")
            result = self.ref(self.receiver) if self.constructor else self.ref(ret.inputs[0]) if ret.inputs else None
            self._emit("ref", "null", [], ["exc"], ["ref"])
            self._leave(result)

        elif block.exit == "unwind":  # the method throws: its caller gets the exception
            unwind = next(n for n in block.nodes if n.op == "Unwind")
            self._emit("ref", "move", [self.ref(unwind.inputs[0])], ["exc"], ["ref"])
            self._leave(None)

        elif len(block.succs) == 1:
            self._jump(block.id, block.succs[0].to)
        else:
            raise Unsupported(f"block ending in {block.end.get('node')}")

    def _leave(self, result: str | None) -> None:
        """Gives the caller the result, nothing when the method throws, and every token."""
        first, t = self.outs[0]
        if first == "r":
            if result:
                self._emit(t, "move", [result], ["r"], [t])
            else:
                self._emit(t, "bot", [], ["r"], [t])
        for t in self.tokens:
            self._emit("heap", "move", [self.current[t]], [f"{t}out"], ["heap"])

    def _jump(self, src: int, dst: int) -> None:
        phis = {n.id: dict(n.phi) for n in self.g.blocks[dst].nodes if n.op == "ValuePhi"}
        args = [self.ref(phis[i][src]) if i in phis else self.ref(i) for i in self.param_ids[dst]]
        ftype = function_type([t for _, t in self._lambda_params(dst)], self.out_types)
        self._emit(self.name, self._lambda_name(dst), [], [f"k{dst}"], [ftype])
        self._emit(ftype, "call", [f"k{dst}", *args, *(self.current[t] for t in self.tokens)],
                   [n for n, _ in self.outs], self.out_types)

    def _branch(self, c: str, true: int, false: int) -> None:
        params = self._lambda_params(true)
        ftype = function_type([t for _, t in params], self.out_types)
        frame = self._frame(ftype, params)
        self._emit(self.name, self._lambda_name(true), [], ["kt"], [ftype])
        self._emit(self.name, self._lambda_name(false), [], ["kf"], [ftype])
        self._emit(self.name, frame.name, [], ["frame"], [frame_type(ftype)])
        self._emit("bool", "not", [c], ["cn"], ["bool"])
        self._emit(ftype, "opt", [c, "kt"], ["at"], [ftype])
        self._emit(ftype, "opt", ["cn", "kf"], ["af"], [ftype])
        self._emit(ftype, "join", ["at", "af", "frame"], ["k"], [ftype])
        args = [self.ref(i) for i in self.param_ids[true]]
        self._emit(ftype, "call", ["k", *args, *(self.current[t] for t in self.tokens)], [n for n, _ in self.outs],
                   self.out_types)

    def _frame(self, ftype: str, params: list[tuple[str, str]]) -> Lambda:
        if ftype in self.frames:
            return self.frames[ftype]

        xs = [(f"x{i}", t) for i, (_, t) in enumerate(params[:len(params) - len(self.tokens)])]
        lam = Lambda(f"frame_{len(self.frames)}",
                     [("A", ftype), ("B", ftype), *xs, *((t, "heap") for t in self.tokens)], list(self.outs))
        for t in self.tokens:
            lam.body.append(Instr("heap", "fork", [t], [f"{t}_a", f"{t}_b"], ["heap", "heap"]))
        outs_a = [f"{name}_a" for name, _ in self.outs]
        outs_b = [f"{name}_b" for name, _ in self.outs]
        lam.body.append(
            Instr(ftype, "call", ["A", *(x for x, _ in xs), *(f"{t}_a" for t in self.tokens)], outs_a, self.out_types))
        lam.body.append(
            Instr(ftype, "call", ["B", *(x for x, _ in xs), *(f"{t}_b" for t in self.tokens)], outs_b, self.out_types))

        for (name, t), a, b in zip(self.outs, outs_a, outs_b):
            lam.body.append(Instr(t, "join", [a, b], [name], [t]))

        self.frames[ftype] = lam
        return lam


def _type(n: Node) -> str:
    return "bool" if n.type == "cond" else n.type


def _element(kind: str) -> str:
    """An array kind as the dialect's operations name it: int[] → int, Object[] → Object."""
    return kind.removesuffix("[]")
