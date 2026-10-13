"""Dead stores: a store goes when every path its token takes overwrites the
same field of the same object before anything may read it. A path that throws
leaves the method, as one that returns does, so the caller may read it."""

from cthu.ir import TRAPS, Instr, Lambda, Structure

from .tokens import ALLOCATION, arms_of, field_access


def remove_dead_stores(s: Structure) -> list[Instr]:
    """Turn each store every path overwrites before anything may read it into a
    move of its token, and give the stores that went."""
    lambdas = {lam.name: lam for lam in s.lambdas}
    dead = []
    for lam in s.lambdas:
        for n, i in enumerate(lam.body):
            a = field_access(i)
            if a and a[0] == "set":
                location = (a[1], a[2], None if a[1] else i.ins[1])
                if _overwritten(s.name, lambdas, lam, i.outs[0], location, frozenset(), n + 1):
                    dead.append((lam, i))

    for lam, i in dead:
        at = next(n for n, x in enumerate(lam.body) if x is i)
        lam.body[at] = Instr("heap", "move", [i.ins[0]], [i.outs[0]], ["heap"], note=f"dead store to {i.field}")
    return [i for _, i in dead]


def _overwritten(structure: str, lambdas: dict[str, Lambda], lam: Lambda, token: str,
                 location: tuple[bool, int, str | None], seen: frozenset, start: int = 0) -> bool:
    """Whether every path the token takes from here overwrites the location,
    (static, field index, object), before anything can read it. A path that
    throws leaves the method, as one that returns does, and the caller or a
    handler may read it; so may one after an allocation from `start` in the λ
    on, which may throw OutOfMemoryError whichever token it takes."""
    static, k, obj = location
    at = next((n for n, i in enumerate(lam.body) if token in i.ins), None)
    if at is None:
        return False  # it leaves the method: the caller may read it
    if any(_may_throw(i) for i in lam.body[start:at]):
        return False  # an exception may leave the method before the overwrite
    use = lam.body[at]

    a = field_access(use)
    if a:
        return a[0] == "set" and a[1:] == (static, k) and (static or use.ins[1] == obj)
    if use.type == "heap" and use.op == "trap":
        return True  # the program stops, and nothing reads it
    if use.type == "heap" and use.op == "guard" and use.exit != TRAPS:
        return False  # the method may leave here, with an exception
    if use.type == "heap" and use.op in ("move", "guard"):
        return _overwritten(structure, lambdas, lam, use.outs[0], location, seen, at + 1)

    targets = _jump_targets(lam, use.ins[0], structure) if use.op == "call" else None
    if targets is None:
        return False  # a call to a method that takes the token may read it

    args = use.ins[1:]
    j = args.index(token)
    for name in targets:
        target = lambdas[name]
        o = target.params[args.index(obj)][0] if obj in args else None
        key = (name, j, o)
        if key in seen:
            continue  # a loop that neither reads nor overwrites it
        if not _overwritten(structure, lambdas, target, target.params[j][0], (static, k, o), seen | {key}):
            return False
    return True


def _may_throw(i: Instr) -> bool:
    """Whether an instruction may leave the method with an exception, whichever
    token it takes: a guard, unless its arm traps, and an allocation, whose
    OutOfMemoryError Graal IR leaves implicit. Every other way to throw is a
    branch to where the exception goes, which the token follows."""
    return i.type == "heap" and (bool(ALLOCATION.fullmatch(i.op)) or (i.op == "guard" and i.exit != TRAPS))


def _jump_targets(lam: Lambda, k: str, structure: str) -> list[str] | None:
    """The λs a call through `k` goes to, if it is a jump to the next block or
    a branch to both arms, which get the call's arguments in the same order."""
    defs = {out: i for i in lam.body for out in i.outs}
    d = defs.get(k)
    if d is None:
        return None
    if d.type == structure and d.op != "run":
        return [d.op]
    arms = arms_of(defs, d, structure)
    return None if arms is None else [ref.op for ref in arms[1]]
