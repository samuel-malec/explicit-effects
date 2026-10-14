"""Reading the token form: which instruction made a token, what a field
access touches, the shape of a branch or a jump, and small builders the rules
share."""

import re
from dataclasses import dataclass

from cthu.ir import Instr, Lambda, Structure, function_type

ENTRY = "run"  # the λ a method starts in: a closure of it is a call of the method itself

ACCESS = re.compile(r"(get|set|init)(static)?_(\d+)")  # init: a new object's field, as escape analysis left it

VALUES = {"int", "long", "float", "double", "bool", "ref"}

# Operations on values that can't throw: what may sit before a load in the part
# of a merge that splitting copies, and what goes once nothing uses it.
PURE = re.compile(r"cons_m?\d+|const_\d+|null|move|not|neg|add|sub|mul|and|or|xor|shl|shr|ushr|eq\?|lt\?|ult\?|nil\?|opt|join"
                  r"|abs|min|max|sqrt|cmp|to_(int|long|float|double)|instanceof_\d+|isinstance|hub|exception")

# An allocation may throw OutOfMemoryError, the one exception Graal IR leaves implicit.
ALLOCATION = re.compile(r"new_\d+|newarray_\w+")


def field_access(i: Instr) -> tuple[str, bool, int] | None:
    """(get or set, static, field index) for a field access."""
    m = ACCESS.fullmatch(i.op) if i.type == "heap" else None
    return ("get" if m.group(1) == "get" else "set", bool(m.group(2)), int(m.group(3))) if m else None


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
    """Follow a token back past what passes it on unchanged: moves and guards,
    and with `loads` loads too, which write nothing. Give the instruction that
    made it, None if no instruction of the λ did, and its name there."""
    defs = {out: i for i in lam.body for out in i.outs}
    while (d := defs.get(token)) is not None and d.type == "heap" and (
            d.op in ("move", "guard") or (loads and (a := field_access(d)) is not None and a[0] == "get")):
        token = d.ins[0]
    return d, token


def source_of(lam: Lambda, token: str) -> Instr | None:
    """The instruction that gave the token, past moves and guards."""
    return _trace(lam, token)[0]


def param_origin(lam: Lambda, token: str) -> str | None:
    """The parameter the token comes from, past moves and guards."""
    made, token = _trace(lam, token)
    return token if made is None and token in {n for n, _ in lam.params} else None


def unchanged(lam: Lambda, token: str) -> str | None:
    """The parameter a token comes from, past what writes nothing: moves,
    guards and loads."""
    made, token = _trace(lam, token, loads=True)
    return token if made is None and token in {n for n, _ in lam.params} else None


def same_location(access: Instr | None, a: tuple[str, bool, int], obj: str | None) -> bool:
    """Whether `access` stores or loads the location of a load: the same
    field, (static, index) in `a`, of the same object, unless it is static."""
    b = field_access(access) if access is not None else None
    return bool(b) and b[1:] == a[1:] and (obj is None or access.ins[1] == obj)


def value_of(access: Instr) -> str:
    """The value a store stored or a load loaded."""
    return access.ins[-1] if field_access(access)[0] == "set" else access.outs[0]


def copy_instr(i: Instr) -> Instr:
    return i.renamed(list(i.ins), list(i.outs))


class Closures:
    """Where each of a method's λs is taken as a closure: the (λ, instruction)
    of each place, in program order. It describes the program as it was when
    made, so a rule makes it again after it changes which λ takes which."""

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
        """The λs that λ `name` can get to by taking closures, through others;
        itself only if it is on a loop."""
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
    """A branch at the end of `parent`: the closures of both arms, the opts and
    the join that make one of them, the frame's closure, and the call."""
    parent: Lambda
    refs: list[Instr]
    opts: list[Instr]
    join: Instr
    frame: Instr
    call: Instr


def branch_into(s: Structure, name: str, closures: Closures | None = None) -> Branch | None:
    """The branch whose arm λ `name` is, if it is the only place that takes
    either arm."""
    closures = closures or Closures(s)
    taken = closures.of(name)
    if len(taken) != 1:
        return None
    branch = branch_at(s, taken[0][0])
    if branch is None or name not in {r.op for r in branch.refs} or any(len(closures.of(r.op)) != 1 for r in branch.refs):
        return None
    return branch


def branch_at(s: Structure, lam: Lambda) -> Branch | None:
    """The branch the λ ends with, if it ends with one: a call of the join of
    two opts, each of a closure of one of the method's λs."""
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
    """The two opts a join of two arms takes, and the closure each opt makes,
    if both closures are of the method's λs."""
    if join is None or join.op != "join":
        return None
    opts = [defs.get(n) for n in join.ins[:2]]
    refs = [defs.get(o.ins[1]) if o is not None and o.op == "opt" else None for o in opts]
    if not all(r is not None and r.type == structure for r in refs):
        return None
    return opts, refs


def jump_sites(s: Structure, name: str, closures: Closures | None = None) -> list[tuple[Lambda, Instr, Instr]] | None:
    """Each (λ, closure, jump) that jumps to λ `name`, if only jumps reach it."""
    sites = []
    for lam, i in (closures or Closures(s)).of(name):
        jump = lam.body[-1]
        if jump.op != "call" or jump.ins[:1] != i.outs or jump.outs != [n for n, _ in lam.outs]:
            return None
        sites.append((lam, i, jump))
    return sites


def jump_to(s: Structure, target: Lambda, args: list[str], k: str) -> list[Instr]:
    """A jump to `target` through closure `k`, which a λ ends with."""
    ftype = target.function_type
    return [Instr(s.name, target.name, [], [k], [ftype]),
            Instr(ftype, "call", [k, *args], [n for n, _ in target.outs], [t for _, t in target.outs])]


def in_loop(s: Structure, name: str, sites: list[tuple[Lambda, Instr, Instr]], closures: Closures | None = None) -> bool:
    """Whether one of the λs that jump to `name` is reachable from it."""
    reached = (closures or Closures(s)).reached_from(name)
    return any(lam.name in reached for lam, _, _ in sites)


def only_jumps(s: Structure, lam: Lambda) -> bool:
    """Whether the λ does nothing but jump to another of the method's λs."""
    ref, jump = lam.body if len(lam.body) == 2 else (None, None)
    return (ref is not None and ref.type == s.name and ref.op != ENTRY and jump.op == "call"
            and jump.ins[:1] == ref.outs and jump.outs == [n for n, _ in lam.outs])


def calls_into(s: Structure, lam: Lambda, closures: Closures | None = None) -> list[list[str]] | None:
    """What each place that calls the λ passes it, if only jumps or one branch do."""
    if lam.name == ENTRY:
        return None
    closures = closures or Closures(s)
    sites = jump_sites(s, lam.name, closures)
    if sites:
        return [jump.ins[1:] for _, _, jump in sites]
    branch = branch_into(s, lam.name, closures)
    return [branch.call.ins[1:]] if branch else None


def frame_of(s: Structure, params: list[tuple[str, str]], outs: list[tuple[str, str]]) -> str:
    """A frame for arms that take these parameters: it forks each token, gives
    both arms the values and one half of each fork, and joins what they give.
    The method's own, if it has one for them."""
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
