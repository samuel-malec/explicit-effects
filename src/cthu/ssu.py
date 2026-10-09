from collections import Counter
from itertools import count

from .ir import LINEAR, Instr, Lambda, Program


class LinearityError(Exception):
    pass

def linearize(lam: Lambda) -> None:
    """Transform a sequence of Cthu instructions, such that the new sequence of instruction adheres to the SSU format"""
    types = dict(lam.params)
    for instr in lam.body:
        types.update(zip(instr.outs, instr.out_types))

    remaining = Counter(name for instr in lam.body for name in instr.ins)
    remaining.update(name for name, _ in lam.outs)

    fresh = count(1)
    current: dict[str, str] = {} 
    body: list[Instr] = []

    def unused(name: str) -> None:
        if types[name] in LINEAR:
            raise LinearityError(f"{lam.name}: linear {name} is never used")
        body.append(Instr(types[name], "drop", [name]))

    for name, _ in lam.params:
        if remaining[name] == 0:
            unused(name)

    for instr in lam.body:
        ins = []
        for name in instr.ins:    
            remaining[name] -= 1
            now = current.get(name, name)

            if remaining[name] > 0:
                if types[name] in LINEAR:
                    raise LinearityError(f"{lam.name}: linear {name} is used more than once")

                first, rest = f"{name}_{next(fresh)}", f"{name}_{next(fresh)}"
                body.append(Instr(types[name], "dup", [now], [first, rest], [types[name]] * 2))
                ins.append(first)
                current[name] = rest
            else:
                ins.append(now)

        instr.ins = ins
        body.append(instr)

        for name in instr.outs:
            if remaining[name] == 0:
                unused(name)

    for name, _ in lam.outs:
        if current.get(name, name) != name:
            raise LinearityError(f"{lam.name}: output {name} is also used inside the λ")

    lam.body = body

def check(program: Program) -> list[str]:
    """Check whether given program conforms to the SSU form""" 
    errors = []
    
    for structure in program.structures:
        for lam in structure.lambdas:
            errors += [f"{structure.name}.{lam.name}: {e}" for e in _check_lambda(lam)]
    
    return errors

def _check_lambda(lam: Lambda) -> list[str]:
    """Check whether a given lambda body conforms to the SSU form"""
    errors = []
    defined: dict[str, str] = {}
    uses: Counter = Counter()

    def define(name: str, type_: str) -> None:
        if name in defined:
            errors.append(f"{name} defined twice")
        defined[name] = type_

    for name, type_ in lam.params:
        define(name, type_)

    for instr in lam.body:
        if instr.op in ("dup", "drop") and instr.type in LINEAR:
            errors.append(f"{instr.op} of linear {' '.join(instr.ins)}")
        for name in instr.ins:
            if name not in defined:
                errors.append(f"{name} used before it is defined")
            uses[name] += 1
        for name, type_ in zip(instr.outs, instr.out_types):
            define(name, type_)
    
    for name, _ in lam.outs:
        if name not in defined:
            errors.append(f"output {name} is never defined")
        uses[name] += 1
    
    for name in defined:
        if uses[name] != 1:
            errors.append(f"{name} used {uses[name]} times")
    
    return errors
