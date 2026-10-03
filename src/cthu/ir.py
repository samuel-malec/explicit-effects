from dataclasses import dataclass, field
 

LINEAR = frozenset({"heap"})

_TYPE_CODES = {"ref": "r", "int": "i", "long": "l", "float": "f", "double": "d", "bool": "b", "heap": "h"}


def function_type(params: list[str], outs: list[str]) -> str:
    """The closure type for these parameter and output types: `f_rrh_h`
    takes two references and the heap and gives back the heap."""
    return "f_" + "".join(_TYPE_CODES[t] for t in params) + "_" + "".join(_TYPE_CODES[t] for t in outs)


@dataclass
class Instr:
    type: str
    op: str
    ins: list[str] = field(default_factory=list)
    outs: list[str] = field(default_factory=list)
    out_types: list[str] = field(default_factory=list)
    note: str = ""

    def text(self) -> str:
        line = " ".join([self.type, self.op, *self.ins])
        if self.outs:
            line += " → " + " ".join(self.outs)
        return line + (f"   ; {self.note}" if self.note else "")


@dataclass
class Lambda:
    name: str
    params: list[tuple[str, str]]  # (name, type)
    outs: list[tuple[str, str]]  # (name, type)
    body: list[Instr] = field(default_factory=list)
    note: str = ""

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
    fields: list[str] = field(default_factory=list)  # `field` declarations: get_i / set_i
    classes: list[str] = field(default_factory=list)  # `class` declarations: new_i
    externals: list[str] = field(default_factory=list)  # external functions called from the analyzed code

    def field_index(self, name: str) -> int:
        if name not in self.fields:
            self.fields.append(name)
        return self.fields.index(name)

    def class_index(self, name: str) -> int:
        if name not in self.classes:
            self.classes.append(name)
        return self.classes.index(name)


def to_text(program: Program, header: str = "") -> str:
    lines = [f"; {line}" for line in header.splitlines()]
    if lines:
        lines.append("")
    for i, name in enumerate(program.fields):
        lines.append(f'field "{name}"   ; get_{i}, set_{i}')
    for i, name in enumerate(program.classes):
        lines.append(f'class "{name}"   ; new_{i}')
    for name in program.externals:
        lines.append(f"; external: {name}")
    if program.fields or program.classes or program.externals:
        lines.append("")

    for structure in program.structures:
        lines.append(f"structure {structure.name}" + (f"   ; {structure.note}" if structure.note else ""))
        lines.append("(")
        for i, lam in enumerate(structure.lambdas):
            if i:
                lines.append("")
            params = " ".join(name for name, _ in lam.params)
            outs = " ".join(name for name, _ in lam.outs)
            types = (" × ".join(t for _, t in lam.params) or "∅") + " → " + (" × ".join(t for _, t in lam.outs) or "∅")
            lines.append(f"    {lam.name} = λ {params} → {outs}   ; {types}" + (f"; {lam.note}" if lam.note else ""))
            lines.append("    (")
            for instr in lam.body:
                lines.append("        " + instr.text())
            lines.append("    )")
        lines.append(")")
        lines.append("")
    return "\n".join(lines)
