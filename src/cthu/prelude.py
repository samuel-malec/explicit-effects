""" Representation of the Prelude for Graal dialect in Cthu,
    extended with parsing logic. """

import re
from dataclasses import dataclass
from pathlib import Path

from . import parser
from .ir import Instr, Lambda, Program, frame_type, parse_function_type
from .parser import OpType, Signature

GRAAL = Path(__file__).with_name("graal.ct")

FUNCTION = ("function", "stck", "bool")  # operations a function supports
CONSTANTS = {"int", "long"}  # the structures with cons_<n>
MEMORY = "heap"  # the structure with the field and allocation operations
#: An array kind, as the operations on it name it, and the type of its elements.
ARRAYS = {"byte": "int", "char": "int", "short": "int", "int": "int", "long": "long", "float": "float",
          "double": "double", "Object": "ref"}


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


def load(path: Path = GRAAL) -> Prelude:
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

    function_signature, _, _ = FUNCTION
    if problem := _reference(module.signatures, function_signature, _function_arguments("F", ["I"], ["O"])):
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
    expected = _Expected(program, prelude)

    for s in program.structures:
        for lam in s.lambdas:
            types = dict(lam.params)

            for instr in lam.body:
                wanted = expected(instr)
                given = ([types.get(name, "?") for name in instr.ins], list(instr.out_types))

                if isinstance(wanted, str):
                    errors.append(f"{s.name}.{lam.name}: {instr.text()}: {wanted}")
                elif given != wanted:
                    errors.append(f"{s.name}.{lam.name}: {instr.text()}: takes {_show(wanted)}, given {_show(given)}")
                types.update(zip(instr.outs, instr.out_types))

            for name, t in lam.outs:
                if types.get(name, t) != t:
                    errors.append(f"{s.name}.{lam.name}: output {name} is {types[name]}, not {t}")

    return errors


_CONS = re.compile(r"cons_m?\d+")
_CONST = re.compile(r"const_(\d+)")
_UNBOX = re.compile(r"unbox_(int|long|float|double)")
_INSTANCEOF = re.compile(r"instanceof_(\d+)")
_FIELD = re.compile(r"(get|set|init|getstatic|setstatic|new)_(\d+)")
_ARRAY = re.compile(r"(aget|aset|newarray)_(\w+)")


class _Expected:
    """The types each instruction must take and give, or why it has none. What
    one function type or one λ allows is worked out once: a program has many
    instructions of each."""

    def __init__(self, program: Program, prelude: Prelude):
        self.program, self.prelude = program, prelude
        self.lambdas = {(s.name, lam.name): lam for s in program.structures for lam in s.lambdas}
        self.externals = set(program.externals)
        self.fields = list(program.fields.values())
        self.functions: dict[str, dict[str, OpType]] = {}  # function type → its operations
        self.closures: dict[tuple[str, str], OpType | str] = {}  # (structure, λ) → what taking it as a closure is

    def __call__(self, instr: Instr) -> OpType | str:
        t, op = instr.type, instr.op
        if t in self.prelude.structures:
            return self._builtin(t, op)

        if (t, op) in self.lambdas:
            if (t, op) not in self.closures:
                self.closures[t, op] = self._closure(op, self.lambdas[t, op])
            return self.closures[t, op]

        if op == "run" and t in self.externals:
            return [], list(instr.out_types)  # an external is typed by the calls to it

        function = parse_function_type(t)
        if function:
            if t not in self.functions:
                function_signature, _, _ = FUNCTION
                self.functions[t] = self.prelude.operations(function_signature, _function_arguments(t, *function))
            return self.functions[t].get(op, f"a function has no {op}")

        return f"no structure {t}"

    def _builtin(self, t: str, op: str) -> OpType | str:
        """An operation of one of the prelude's structures, or of its numbered families."""
        program = self.program
        if op in self.prelude.structures[t]:
            return self.prelude.structures[t][op]

        if t in CONSTANTS and _CONS.fullmatch(op):
            return [], [t]

        if constant := _CONST.fullmatch(op):
            k = int(constant.group(1))
            if k >= len(program.constants):
                return f"no {t} constant {k}"
            declared, _ = program.constants[k]
            if declared != t:
                return f"no {t} constant {k}"
            return [], [t]

        if t == "ref" and (box := _UNBOX.fullmatch(op)):
            return ["ref"], [box.group(1)]

        if t == "ref" and (test := _INSTANCEOF.fullmatch(op)):
            return (["ref"], ["bool"]) if int(test.group(1)) < len(program.classes) else f"no class {test.group(1)}"

        memory = _FIELD.fullmatch(op)
        if t == MEMORY and memory:
            return _memory(memory.group(1), int(memory.group(2)), self.fields, len(program.classes))

        array = _ARRAY.fullmatch(op)
        if t == MEMORY and array and array.group(2) in ARRAYS:
            element = ARRAYS[array.group(2)]
            return {"aget": ([MEMORY, "ref", "int"], [element, MEMORY]),
                    "aset": ([MEMORY, "ref", "int", element], [MEMORY]),
                    "newarray": ([MEMORY, "int"], ["ref", MEMORY])}[array.group(1)]

        return f"{t} has no {op}"

    @staticmethod
    def _closure(op: str, lam: Lambda) -> OpType | str:
        """Taking one of the program's λs as a closure: a frame, whose first
        two parameters are its arms, or any other λ."""
        arms = [pt for _, pt in lam.params if parse_function_type(pt)]
        if not arms:
            return [], [lam.function_type]
        if len(arms) == 2:
            first, second = arms
            if first == second:
                return [], [frame_type(first)]
        return f"frame {op} takes arms {' and '.join(arms)}, not two of one type"


def _function_arguments(t: str, ins: list[str], outs: list[str]) -> list:
    """What the function type `t` ∷ ins → outs gives the function signature: F S B I O G,
    where G is the frame for arms of type `t`."""
    _, stck, bool_ = FUNCTION
    return [t, stck, bool_, ins, outs, frame_type(t)]


def _memory(kind: str, k: int, fields: list[str], classes: int) -> OpType | str:
    """A field access or an allocation: `fields` are the program's field types, in order."""
    if kind == "new":
        return ([MEMORY], ["ref", MEMORY]) if k < classes else f"no class {k}"

    if k >= len(fields):
        return f"no field {k}"

    v = fields[k]

    return {"get": ([MEMORY, "ref"], [v, MEMORY]), "set": ([MEMORY, "ref", v], [MEMORY]),
            "init": ([MEMORY, "ref", v], [MEMORY]),
            "getstatic": ([MEMORY], [v, MEMORY]), "setstatic": ([MEMORY, v], [MEMORY])}[kind]


def _show(types: OpType) -> str:
    ins, outs = types
    return (" × ".join(ins) or "∅") + " → " + (" × ".join(outs) or "∅")
