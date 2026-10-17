"""Helpers the rules share for reading the token form

Where a token came from, what a field access touches, what a branch or a jump
looks like, and small builders for new names, jumps and frames."""

import re
from dataclasses import dataclass

from cthu.ir import Instr, Lambda, Structure, function_type

ENTRY = "run"  # the λ a method starts in; taking it as a closure calls the method itself

ACCESS = re.compile(r"(get|set|init)(static)?_(\d+)")  # init: the first value of a new object's field

VALUES = {"int", "long", "float", "double", "bool", "ref"}

# Operations that can't throw and don't touch memory: safe to copy (split_merge)
# and to remove once nothing uses them (drop_unused).
PURE = re.compile(r"cons_m?\d+|const_\d+|null|move|not|neg|add|sub|mul|and|or|xor|shl|shr|ushr|eq\?|lt\?|ult\?|nil\?|opt|join"
                  r"|abs|min|max|sqrt|cmp|to_(int|long|float|double)|instanceof_\d+|isinstance|hub|exception")

# An allocation may throw OutOfMemoryError, the one exception Graal IR leaves implicit.
ALLOCATION = re.compile(r"new_\d+|newarray_\w+")


def field_access(i: Instr) -> tuple[str, bool, int] | None:
    """(get or set, is static, field index) if the instruction accesses a field."""
    m = ACCESS.fullmatch(i.op) if i.type == "heap" else None
    return ("get" if m.group(1) == "get" else "set", bool(m.group(2)), int(m.group(3))) if m else None


def is_load(i: Instr) -> bool:
    """Whether the instruction reads a field."""
    access = field_access(i)
    if access is None:
        return False
    kind, _, _ = access
    return kind == "get"


def is_store(i: Instr) -> bool:
    """Whether the instruction writes a field (a store, or a new object's first value)."""
    access = field_access(i)
    if access is None:
        return False
    kind, _, _ = access
    return kind == "set"


def is_pure(i: Instr) -> bool:
    return i.type in VALUES and bool(PURE.fullmatch(i.op))


def types_in(lam: Lambda) -> dict[str, str]:
    types = dict(lam.params)
    for i in lam.body:
        types.update(zip(i.outs, i.out_types))

    return types


def fresh(taken: set[str], base: str) -> str:
    name, n = base, 0
    while name in taken:
        n += 1
        name = f"{base}{n}"

    taken.add(name)
    return name


def names_in(lam: Lambda) -> set[str]:
    return {n for n, _ in lam.params} | {n for n, _ in lam.outs} | {o for i in lam.body for o in i.outs}


def _trace(lam: Lambda, token: str, loads: bool = False) -> tuple[Instr | None, str]:
    """Walk a token back past what passes it on unchanged: moves and guards,
    and with `loads` also loads, which write nothing. Return the instruction
    that made it (None if it came in as a parameter) and its name there."""
    defs = {out: i for i in lam.body for out in i.outs}
    while (d := defs.get(token)) is not None and d.type == "heap" and (
            d.op in ("move", "guard") or (loads and is_load(d))):
        token = d.ins[0]
    return d, token


def source_of(lam: Lambda, token: str) -> Instr | None:
    """The instruction that made the token, past moves and guards; None if it
    came in as a parameter."""
    made, _ = _trace(lam, token)
    return made


def param_origin(lam: Lambda, token: str) -> str | None:
    """The parameter the token came in as, past moves and guards; None if an
    instruction made it."""
    made, token = _trace(lam, token)
    return token if made is None and token in {n for n, _ in lam.params} else None


def unchanged(lam: Lambda, token: str) -> str | None:
    """Like `param_origin`, but also past loads: the parameter the token came
    in as, if nothing on the way wrote memory."""
    made, token = _trace(lam, token, loads=True)
    return token if made is None and token in {n for n, _ in lam.params} else None


def same_location(access: Instr | None, a: tuple[str, bool, int], reference: str | None) -> bool:
    """Whether `access` touches the same location as the load: the same field
    and, unless the field is static, the same reference: the same name, so
    the same object."""
    other = field_access(access) if access is not None else None
    if other is None:
        return False
    _, static, index = a
    _, other_static, other_index = other
    return (other_static, other_index) == (static, index) and (reference is None or access.ins[1] == reference)


def value_of(access: Instr) -> str:
    """The value a store wrote or a load read."""
    return access.ins[-1] if is_store(access) else access.outs[0]


def copy_instr(i: Instr) -> Instr:
    return i.renamed(list(i.ins), list(i.outs))


class Closures:
    """For each λ of a method, the places that take it as a closure (to jump,
    branch or call to it). Build it again after a rule changes the jumps."""

    def __init__(self, s: Structure):
        self.places: dict[str, list[tuple[Lambda, Instr]]] = {}
        for lam in s.lambdas:
            for i in lam.body:
                if i.type == s.name:
                    self.places.setdefault(i.op, []).append((lam, i))
        self._calls: dict[str, set[str]] | None = None

    def of(self, name: str) -> list[tuple[Lambda, Instr]]:
        return self.places.get(name, [])

    def reached_from(self, name: str) -> set[str]:
        """The λs reachable from λ `name`; `name` itself only if it is on a loop."""
        if self._calls is None:
            self._calls = {}
            for target, places in self.places.items():
                for lam, _ in places:
                    self._calls.setdefault(lam.name, set()).add(target)
        seen, work = set(), [name]
        while work:
            for n in self._calls.get(work.pop(), ()):
                if n not in seen:
                    seen.add(n)
                    work.append(n)
        return seen


@dataclass
class Branch:
    """The instructions of a branch at the end of `parent`: the closures of
    both arms, the two opts and the join that pick one, the frame, and the call."""
    parent: Lambda
    refs: list[Instr]
    opts: list[Instr]
    join: Instr
    frame: Instr
    call: Instr


def branch_into(s: Structure, name: str, closures: Closures | None = None) -> Branch | None:
    """The branch that has λ `name` as an arm, if nothing else reaches either arm."""
    closures = closures or Closures(s)
    taken = closures.of(name)
    if len(taken) != 1:
        return None
    parent, _ = taken[0]
    branch = branch_at(s, parent)
    if branch is None or name not in {r.op for r in branch.refs} or any(len(closures.of(r.op)) != 1 for r in branch.refs):
        return None
    return branch


def branch_at(s: Structure, lam: Lambda) -> Branch | None:
    """The branch the λ ends with, if it ends with one."""
    call = lam.body[-1] if lam.body else None
    if call is None or call.op != "call":
        return None
    defs = {out: i for i in lam.body for out in i.outs}
    join = defs.get(call.ins[0])
    arms = arms_of(defs, join, s.name)
    if arms is None:
        return None
    opts, refs = arms
    return Branch(lam, refs, opts, join, defs.get(join.ins[2]), call)


def arms_of(defs: dict[str, Instr], join: Instr | None, structure: str) -> tuple[list[Instr], list[Instr]] | None:
    """The two opts of a join, and the λ closure each one picks."""
    if join is None or join.op != "join":
        return None
    opts = [defs.get(n) for n in join.ins[:2]]
    refs = [defs.get(o.ins[1]) if o is not None and o.op == "opt" else None for o in opts]
    if not all(r is not None and r.type == structure for r in refs):
        return None
    return opts, refs


def jump_sites(s: Structure, name: str, closures: Closures | None = None) -> list[tuple[Lambda, Instr, Instr]] | None:
    """Each (λ, closure, jump) that jumps to λ `name`; None if anything but a
    plain jump reaches it."""
    sites = []
    for lam, i in (closures or Closures(s)).of(name):
        jump = lam.body[-1]
        if jump.op != "call" or jump.ins[:1] != i.outs or jump.outs != [n for n, _ in lam.outs]:
            return None
        sites.append((lam, i, jump))
    return sites


def jump_to(s: Structure, target: Lambda, args: list[str], k: str) -> list[Instr]:
    """The two instructions that end a λ with a jump to `target`."""
    ftype = target.function_type
    return [Instr(s.name, target.name, [], [k], [ftype]),
            Instr(ftype, "call", [k, *args], [n for n, _ in target.outs], [t for _, t in target.outs])]


def in_loop(s: Structure, name: str, sites: list[tuple[Lambda, Instr, Instr]], closures: Closures | None = None) -> bool:
    """Whether λ `name` is on a loop: one of the λs jumping to it is reachable from it."""
    reached = (closures or Closures(s)).reached_from(name)
    return any(lam.name in reached for lam, _, _ in sites)


def only_jumps(s: Structure, lam: Lambda) -> bool:
    """Whether the λ does nothing but jump to another of the method's λs."""
    ref, jump = lam.body if len(lam.body) == 2 else (None, None)
    return (ref is not None and ref.type == s.name and ref.op != ENTRY and jump.op == "call"
            and jump.ins[:1] == ref.outs and jump.outs == [n for n, _ in lam.outs])


def calls_into(s: Structure, lam: Lambda, closures: Closures | None = None) -> list[list[str]] | None:
    """What each caller passes to the λ, if only jumps or one branch reach it."""
    if lam.name == ENTRY:
        return None
    closures = closures or Closures(s)
    sites = jump_sites(s, lam.name, closures)
    if sites:
        return [jump.ins[1:] for _, _, jump in sites]
    branch = branch_into(s, lam.name, closures)
    return [branch.call.ins[1:]] if branch else None


def frame_of(s: Structure, params: list[tuple[str, str]], outs: list[tuple[str, str]]) -> str:
    """The frame for a branch whose arms take these parameters: it splits each
    token in two, gives one half to each arm, and joins what they give
    back. An existing frame of the same type is reused."""
    ftype = function_type([t for _, t in params], [t for _, t in outs])
    for lam in s.lambdas:
        if lam.name.startswith("frame_") and [t for _, t in lam.params[:2]] == [ftype, ftype]:
            return lam.name

    names = [(n if t == "heap" else f"x{i}", t) for i, (n, t) in enumerate(params)]
    halves = {half: [f"{n}_{half}" if t == "heap" else n for n, t in names] for half in "ab"}
    body = [Instr("heap", "fork", [n], [f"{n}_a", f"{n}_b"], ["heap", "heap"]) for n, t in names if t == "heap"]
    for arm, half in (("A", "a"), ("B", "b")):
        body.append(Instr(ftype, "call", [arm, *halves[half]], [f"{n}_{half}" for n, _ in outs], [t for _, t in outs]))
    body += [Instr(t, "join", [f"{n}_a", f"{n}_b"], [n], [t]) for n, t in outs]
    taken = {lam.name for lam in s.lambdas}
    name = next(f"frame_{n}" for n in range(len(taken) + 1) if f"frame_{n}" not in taken)
    s.lambdas.append(Lambda(name, [("A", ftype), ("B", ftype), *names], list(outs), body))
    return name
