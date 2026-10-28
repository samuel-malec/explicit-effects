"""Straighten translated code (`graal2ct --shape`)

The translation makes a λ of every block Graal has, and Graal splits a block at every call. This pass simplifies the
control flow where that is safe and changes nothing else: no load is forwarded and no store removed.

    a branch to an arm that leaves the method becomes guards, and a λ that one jump reaches joins the λ that jumps,
    so that the code is straight-line and a token can be followed from one operation to the next.

`straighten` is the pass; the rest are its steps, and the helpers that read how a translated method is built."""

import re
from dataclasses import dataclass

from cthu.ir import LINEAR, Instr, Lambda, Program, Structure
from cthu.ssu import linearize


ENTRY = "run"  # the λ a method starts in; taking it as a closure calls the method itself


VALUES = {"int", "long", "float", "double", "bool", "ref"}


# Operations that can't throw and don't touch memory: safe to remove once nothing uses them (drop_unused).
PURE = re.compile(r"cons_m?\d+|const_\d+|null|move|not|neg|add|sub|mul|and|or|xor|shl|shr|ushr|eq\?|lt\?|ult\?|nil\?|opt|join"
                  r"|abs|min|max|sqrt|cmp|to_(int|long|float|double)|instanceof_\d+|isinstance|hub|exception")


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


class Closures:
    """For each λ of a method, the places that take it as a closure (to jump,
    branch or call to it). Build it again after a step changes the jumps."""

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


def unshare(lam: Lambda) -> None:
    """Remove the `dup`s and `drop`s, so that each value has one name in the
    whole λ and two names are equal only when they are the same value, for example
    the same reference. `linearize` puts the copies back at the end."""
    original: dict[str, str] = {}
    body = []

    for i in lam.body:
        i.ins = [original.get(n, n) for n in i.ins]
        if i.op == "dup" and i.type not in LINEAR:
            original.update((out, i.ins[0]) for out in i.outs)
        elif not (i.op == "drop" and i.type not in LINEAR):
            body.append(i)
    lam.body = body


def guard_exits(s: Structure) -> None:
    """Turn a branch to an arm that only throws into guards.

    A null check, or the check after a call whether it threw, branches to code
    that throws. Instead, every token now passes a `guard` that leaves the
    method if the check fails, and the code goes straight on. The guard is
    marked `throws`, or `traps` when the arm deoptimizes.
    Example: conversion.NullCheck."""
    exits = {lam.name: lam.exit for lam in s.lambdas if lam.exit}
    for lam in s.lambdas:
        branch = branch_at(s, lam)
        if branch is None or [r.op in exits for r in branch.refs].count(True) != 1:
            continue

        call, refs = branch.call, branch.refs
        leaving = next(n for n, r in enumerate(refs) if r.op in exits)
        when, how = branch.opts[leaving].ins[0], exits[refs[leaving].op]
        taken, types = names_in(lam), types_in(lam)
        guards, args = [], []
        for a in call.ins[1:]:
            if types[a] == "heap":
                guards.append(Instr("heap", "guard", [a, when], [fresh(taken, f"{a}_g")], ["heap"], exit=how))
                args.append(guards[-1].outs[0])
            else:
                args.append(a)
        gone = {id(i) for i in (call, branch.join, branch.frame, *branch.opts, *refs)}
        lam.body = [i for i in lam.body if id(i) not in gone] + guards + [
            Instr(s.name, refs[1 - leaving].op, [], [call.ins[0]], [call.type]),
            Instr(call.type, "call", [call.ins[0], *args], call.outs, call.out_types)]


def remove_unreferenced(s: Structure) -> None:
    """Remove the λs nothing refers to any more, such as the arms that became
    guards."""
    while True:
        used = {i.op for lam in s.lambdas for i in lam.body if i.type == s.name}
        unused = {lam.name for lam in s.lambdas if lam.name != ENTRY and lam.name not in used}
        if not unused:
            return
        s.lambdas = [lam for lam in s.lambdas if lam.name not in unused]


def fuse(s: Structure) -> None:
    """Join each block that only one jump reaches into the λ that jumps to it.
    Graal splits code into blocks at every call; this makes it one λ again.
    Merges, loop headers and branch arms stay separate λs."""
    closures = Closures(s)
    n = 0
    while n < len(s.lambdas):
        target = s.lambdas[n]
        places = closures.of(target.name)
        if target.name != ENTRY and len(places) == 1 and _jumps_only_to(*places[0], target):
            lam, ref = places[0]
            copies = _inline(lam, ref, lam.body[-1], target)
            del s.lambdas[n], closures.places[target.name]
            for old, new in zip(target.body, copies):  # the block's closures now belong to the λ
                if old.type == s.name:
                    taken = closures.places[old.op]
                    taken[next(k for k, (_, i) in enumerate(taken) if i is old)] = (lam, new)
        else:
            n += 1


def _jumps_only_to(lam: Lambda, ref: Instr, target: Lambda) -> bool:
    """Whether `lam` ends with a plain jump to `target`, giving back whatever
    `target` gives back."""
    jump = lam.body[-1]
    outs = [n for n, _ in lam.outs]
    return lam is not target and jump.op == "call" and jump.ins[:1] == ref.outs and jump.outs == outs \
        and [n for n, _ in target.outs] == outs


def _inline(lam: Lambda, ref: Instr, jump: Instr, target: Lambda) -> list[Instr]:
    """Put the body of `target` in place of the jump at the end of `lam`, and
    return the copied instructions."""
    names = {p: a for (p, _), a in zip(target.params, jump.ins[1:])}
    outs = {n for n, _ in target.outs}

    def rename(n: str) -> str:
        return names.get(n, n if n in outs else f"{n}_{target.name}")

    copies = [i.renamed([rename(n) for n in i.ins], [rename(n) for n in i.outs]) for i in target.body]
    lam.body = [i for i in lam.body if i is not ref and i is not jump] + copies
    return copies


def merge_same_params(s: Structure) -> None:
    """When every caller of a λ passes the same value for two of its
    parameters, keep only the first. Then both names are the same value,
    for example the same reference."""
    closures = Closures(s)
    while True:
        for lam in s.lambdas:
            pair = _same_params(s, lam, closures)
            if pair:
                first, second = pair
                (x, _), (y, _) = lam.params[first], lam.params[second]
                for i in lam.body:
                    i.ins = [x if n == y else n for n in i.ins]
                break
        else:
            return


def _same_params(s: Structure, lam: Lambda, closures: Closures) -> tuple[int, int] | None:
    """The first two parameters (not tokens) that every caller passes the same
    value for, where the body uses the second one; None if there are none."""
    calls = calls_into(s, lam, closures)
    if not calls:
        return None
    first: dict[tuple[str, ...], int] = {}  # (type, what each caller passes) → the first parameter given that
    used = None
    for y, (name, t) in enumerate(lam.params):
        if t == "heap":
            continue
        x = first.setdefault((t, *(args[y] for args in calls)), y)
        if x != y:
            used = used if used is not None else {n for i in lam.body for n in i.ins}
            if name in used:
                return x, y
    return None


def drop_unused(lam: Lambda) -> None:
    """Remove the values nothing uses any more, such as the conditions of the
    branches that became guards."""
    while True:
        used = {n for i in lam.body for n in i.ins} | {n for n, _ in lam.outs}
        body = [i for i in lam.body if not (is_pure(i) and not set(i.outs) & used)]
        if len(body) == len(lam.body):
            return
        lam.body = body


def straighten(program: Program) -> None:
    """Straighten every method of the program, in place: one value per name, the arms that only leave the method
    turned into guards, the blocks one jump reaches joined into the λ that jumps, and what nothing uses any more
    removed, with the copies put back to make the code single-use again."""
    for s in program.structures:
        for lam in s.lambdas:
            unshare(lam)
        guard_exits(s)
        remove_unreferenced(s)
        fuse(s)
        merge_same_params(s)
        remove_unreferenced(s)
        for lam in s.lambdas:
            drop_unused(lam)
            linearize(lam)
