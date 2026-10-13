from dataclasses import dataclass, field

LINEAR = frozenset({"heap"})

# How code leaves the method: with an exception and every token, or by stopping the program.
THROWS, TRAPS = "throws", "traps"

_TYPE_CODES = {"ref": "r", "int": "i", "long": "l", "float": "f", "double": "d", "bool": "b", "heap": "h"}


def function_type(params: list[str], outs: list[str]) -> str:
    return "f_" + "".join(_TYPE_CODES[t] for t in params) + "_" + "".join(_TYPE_CODES[t] for t in outs)


def frame_type(function: str) -> str:
    """The type of a frame for arms of a function type: what a join of two
    closures of that type takes."""
    return f"frame[{function}]"


def parse_function_type(name: str) -> tuple[list[str], list[str]] | None:
    types = {code: t for t, code in _TYPE_CODES.items()}
    parts = name[2:].split("_")
    if not name.startswith("f_") or len(parts) != 2 or not all(c in types for c in "".join(parts)):
        return None
    return [types[c] for c in parts[0]], [types[c] for c in parts[1]]


@dataclass
class Instr:
    type: str
    op: str
    ins: list[str] = field(default_factory=list)
    outs: list[str] = field(default_factory=list)
    out_types: list[str] = field(default_factory=list)
    note: str = ""  # a comment for the reader, which nothing reads back
    at: str = ""  # where in the bytecode it came from, as graal-export names a position
    field: str = ""  # the field a field access reads or writes
    exit: str = ""  # how a guard leaves the method: THROWS or TRAPS

    def text(self) -> str:
        line = " ".join([self.type, self.op, *self.ins])
        if self.outs:
            line += " →  " + " ".join(self.outs)
        # A call's note is its callee, which the closure's structure already names.
        comment = "" if self.op == "call" else self.note or self.field or self.exit
        return line + (f"   ; {comment}" if comment else "")


@dataclass
class Lambda:
    name: str
    params: list[tuple[str, str]]  # (name, type)
    outs: list[tuple[str, str]]  # (name, type)
    body: list[Instr] = field(default_factory=list)
    exit: str = ""  # THROWS or TRAPS when every path from the λ leaves the method that way

    @property
    def function_type(self) -> str:
        return function_type([t for _, t in self.params], [t for _, t in self.outs])


@dataclass
class Structure:
    name: str
    lambdas: list[Lambda] = field(default_factory=list)
    note: str = ""


@dataclass
class Program:
    structures: list[Structure] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)  # `field T "name"` declarations, in order: get_i / set_i
    classes: list[str] = field(default_factory=list)  # `class` declarations: new_i, instanceof_i
    constants: list[tuple[str, str]] = field(default_factory=list)  # `constant T "what"` declarations: const_i
    externals: dict[str, str] = field(default_factory=dict)  # external functions called from the analyzed code

    def field_index(self, name: str, type_: str) -> int:
        if self.fields.setdefault(name, type_) != type_:
            raise ValueError(f"field {name} is both {self.fields[name]} and {type_}")
        return list(self.fields).index(name)

    def class_index(self, name: str) -> int:
        if name not in self.classes:
            self.classes.append(name)
        return self.classes.index(name)

    def constant_index(self, type_: str, what: str) -> int:
        """A constant other than an int, a long or null: an object, a string, a float."""
        what = what.replace('"', "'").replace("\n", " ")
        if (type_, what) not in self.constants:
            self.constants.append((type_, what))
        return self.constants.index((type_, what))


def to_text(program: Program) -> str:
    lines = []
    for i, (name, type_) in enumerate(program.fields.items()):
        lines.append(f'field {type_} "{name}"   ; get_{i}, set_{i}')

    for i, name in enumerate(program.classes):
        lines.append(f'class "{name}"   ; new_{i}')

    for i, (type_, what) in enumerate(program.constants):
        lines.append(f'constant {type_} "{what}"   ; const_{i}')

    for name in program.externals.values():
        lines.append(f"; external: {name}")

    if program.fields or program.classes or program.constants or program.externals:
        lines.append("")

    for structure in program.structures:
        lines.append(f"structure {structure.name}" + (f"   ; {structure.note}" if structure.note else ""))
        lines.append("(")

        for i, lam in enumerate(structure.lambdas):
            if i:
                lines.append("")

            params = " ".join(name for name, _ in lam.params)
            outs = " ".join(name for name, _ in lam.outs)
            types = (" × ".join(t for _, t in lam.params) or "∅") + " →  " + (" × ".join(t for _, t in lam.outs) or "∅")
            # Feel free to comment out the following line to obtain the in/out param types, but note that the output gets really bloated really quickly
            # lines.append(f"    {lam.name} = λ {params} → {outs}   ; {types}" + (f"; {lam.exit}" if lam.exit else ""))
            lines.append(f"    {lam.name} = λ {params} →  {outs} " + (f"; {lam.exit}" if lam.exit else ""))
            lines.append("    (")

            for instr in lam.body:
                lines.append("        " + instr.text())
            lines.append("    )")

        lines.append(")")
        lines.append("")

    return "\n".join(lines)
