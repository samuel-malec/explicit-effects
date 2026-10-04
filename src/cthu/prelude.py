"""Type-checking programs against Graal dialect"""

import re
from dataclasses import dataclass
from pathlib import Path

from . import parser
from .ir import Instr, Lambda, Program, parse_function_type
from .parser import OpType, Signature

JAVA = Path(__file__).with_name("java.ct")

FUNCTION = ("function", "stck", "bool", "frame") # operations a function supports
CONSTANTS = {"int", "long"}  # the structures with cons_<n>
MEMORY = "heap"  # the structure with the field and allocation operations


@dataclass
class Prelude:
    types: set[str]
    signatures: dict[str, Signature]
    structures: dict[str, dict[str, OpType]]
    errors: list[str]

    def operations(self, signature: str, args: list, within: frozenset[str] = frozenset()) -> dict[str, OpType]:
        s = self.signatures.get(signature)
        if s is None or signature in within:  # missing, or extending itself: reported by parse
            return {}
        binding = dict(zip(s.params, args))

        def bind(types: list[str]) -> list[str]:
            bound = []
            for t in types:
                value = binding.get(t, t)
                bound += value if isinstance(value, list) else [value]
            return bound

        ops = {}
        for parent, parent_args in s.parents:
            ops.update(self.operations(parent, [binding.get(a, a) for a in parent_args], within | {signature}))
        ops.update({op: (bind(ins), bind(outs)) for op, (ins, outs) in s.operations.items()})
        return ops


def load(path: Path = JAVA) -> Prelude:
    return parse(path.read_text())


def parse(text: str) -> Prelude:
    module = parser.parse(text)
    prelude = Prelude(set(module.types), module.signatures, {}, [])

    for name, signature in module.signatures.items():
        for parent, args in signature.parents:
            if problem := _reference(module.signatures, parent, args):
                prelude.errors.append(f"signature {name}: {problem}")
        cycle = _cycle(module.signatures, name)
        if cycle:
            prelude.errors.append(f"signature {name} extends itself: {' → '.join(cycle)}")

    if problem := _reference(module.signatures, FUNCTION[0], _function_arguments("F", ["I"], ["O"])):
        prelude.errors.append(f"function types: {problem}")

    for name, structure in module.structures.items():
        ops = {}

        for signature, args in structure.implements:
            if problem := _reference(module.signatures, signature, args):
                prelude.errors.append(f"structure {name}: {problem}")
            ops.update(prelude.operations(signature, args))
        prelude.structures[name] = ops

        bindings = structure.builtins.keys() | structure.lambdas.keys()
        for op in ops.keys() - bindings:
            prelude.errors.append(f"structure {name} does not bind {op}")

        for op in bindings - ops.keys():
            prelude.errors.append(f"structure {name} binds {op}, which none of its signatures has")

        for op, (ins, outs) in ops.items():
            for t in sorted(set(ins + outs) - prelude.types):
                prelude.errors.append(f"structure {name}: {op} uses undeclared type {t}")

    return prelude


def _reference(signatures: dict[str, Signature], name: str, args: list[str]) -> str | None:
    """What is wrong with naming signature `name` with these arguments, if anything."""
    if name not in signatures:
        return f"no signature {name}"
    params = signatures[name].params
    if len(args) != len(params):
        return f"{name}[ {', '.join(params)} ] takes {len(params)} argument(s), given {len(args)}"
    return None


def _cycle(signatures: dict[str, Signature], start: str) -> list[str] | None:
    """A chain of parents leading from `start` back to it, if there is one."""
    work, seen = [[start]], set()
    while work:
        chain = work.pop()
        for parent, _ in signatures[chain[-1]].parents if chain[-1] in signatures else ():
            if parent == start:
                return chain + [start]
            if parent not in seen:
                seen.add(parent)
                work.append(chain + [parent])
    return None


def check(program: Program, prelude: Prelude) -> list[str]:
    errors = [f"prelude: {e}" for e in prelude.errors]
    lambdas = {(s.name, lam.name): lam for s in program.structures for lam in s.lambdas}
    externals = {re.sub(r"\W", "_", name) for name in program.externals}  # the structures graal2ct names them by
    
    for s in program.structures:
        for lam in s.lambdas:
            types = dict(lam.params)

            for instr in lam.body:
                expected = _expected(instr, program, prelude, lambdas, externals)
                given = ([types.get(name, "?") for name in instr.ins], list(instr.out_types))

                if isinstance(expected, str):
                    errors.append(f"{s.name}.{lam.name}: {instr.text()}: {expected}")
                elif given != expected:
                    errors.append(f"{s.name}.{lam.name}: {instr.text()}: takes {_show(expected)}, given {_show(given)}")
                types.update(zip(instr.outs, instr.out_types))

            for name, t in lam.outs:
                if types.get(name, t) != t:
                    errors.append(f"{s.name}.{lam.name}: output {name} is {types[name]}, not {t}")

    return errors


def _expected(instr: Instr, program: Program, prelude: Prelude,
              lambdas: dict[tuple[str, str], Lambda], externals: set[str]) -> OpType | str:
    """The types `instr` must take and give, or why it has none."""
    t, op = instr.type, instr.op
    if t in prelude.structures:
        if op in prelude.structures[t]:
            return prelude.structures[t][op]

        if t in CONSTANTS and re.fullmatch(r"cons_m?\d+", op):
            return [], [t]

        memory = re.fullmatch(r"(get|set|getstatic|setstatic|new)_(\d+)", op)
        if t == MEMORY and memory:
            return _memory(memory.group(1), int(memory.group(2)), program)

        return f"{t} has no {op}"

    if (t, op) in lambdas:
        lam = lambdas[(t, op)]
        frame = any(parse_function_type(pt) for _, pt in lam.params)
        return [], ["frame" if frame else lam.function_type]

    if op == "run" and t in externals:
        return [], list(instr.out_types)  # an external is typed by the calls to it

    function = parse_function_type(t)

    if function:
        ops = prelude.operations(FUNCTION[0], _function_arguments(t, *function))
        return ops.get(op, f"a function has no {op}")

    return f"no structure {t}"


def _function_arguments(t: str, ins: list[str], outs: list[str]) -> list:
    """What the function type `t` ∷ ins → outs gives the function signature: F S B I O G."""
    _, stck, bool_, frame = FUNCTION
    return [t, stck, bool_, ins, outs, frame]


def _memory(kind: str, k: int, program: Program) -> OpType | str:
    if kind == "new":
        return ([MEMORY], ["ref", MEMORY]) if k < len(program.classes) else f"no class {k}"
    
    fields = list(program.fields.values())
    if k >= len(fields):
        return f"no field {k}"
    
    v = fields[k]
    
    return {"get": ([MEMORY, "ref"], [v, MEMORY]), "set": ([MEMORY, "ref", v], [MEMORY]),
            "getstatic": ([MEMORY], [v, MEMORY]), "setstatic": ([MEMORY, v], [MEMORY])}[kind]


def _show(types: OpType) -> str:
    ins, outs = types
    return (" × ".join(ins) or "∅") + " → " + (" × ".join(outs) or "∅")
