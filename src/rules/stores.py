"""Dead stores: a store goes when every path its token takes overwrites the
same field of the same object before anything may read it. A path that throws
leaves the method, as one that returns does, so the caller may read it."""

from cthu.ir import TRAPS, Instr, Lambda, Structure

from .tokens import ALLOCATION, ENTRY, arms_of, field_access


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
                if _overwritten(s.name, lambdas, lam, i.outs[0], location, n + 1):
                    dead.append((lam, i))

    for lam, i in dead:
        at = next(n for n, x in enumerate(lam.body) if x is i)
        lam.body[at] = Instr("heap", "move", [i.ins[0]], [i.outs[0]], ["heap"], note=f"dead store to {i.field}")
    return [i for _, i in dead]


def _overwritten(structure: str, lambdas: dict[str, Lambda], lam: Lambda, token: str,
                 location: tuple[bool, int, str | None], start: int) -> bool:
    """Whether every path the token takes from `start` in the λ on overwrites
    the location, (static, field index, object), before anything can read it.
    A path that throws leaves the method, as one that returns does, and the
    caller or a handler may read it; so may one after an allocation, which may
    throw OutOfMemoryError whichever token it takes.

    The paths are followed with a worklist, not by recursion: a λ gets to the
    next λs through its jumps, and each λ is looked at once for each
    parameter the token and the object come in as, however many paths get
    there. A loop that neither reads nor overwrites the location adds nothing."""
    static, k, obj = location
    work = [(lam, token, obj, start)]
    seen: set[tuple[str, int, str | None]] = set()  # (λ, the token's parameter, the object's) looked at
    while work:
        lam, token, obj, start = work.pop()
        while True:  # along the token through the λ, past what passes it on
            at = next((n for n in range(start, len(lam.body)) if token in lam.body[n].ins), None)
            if at is None:
                return False  # it leaves the method: the caller may read it
            if any(_may_throw(i) for i in lam.body[start:at]):
                return False  # an exception may leave the method before the overwrite
            use = lam.body[at]
            passes_on = use.type == "heap" and (use.op == "move" or (use.op == "guard" and use.exit == TRAPS))
            if not passes_on:
                break
            token, start = use.outs[0], at + 1

        a = field_access(use)
        if a:
            if not (a[0] == "set" and a[1:] == (static, k) and (static or use.ins[1] == obj)):
                return False  # read, or written through a reference that may be another object
            continue
        if use.type == "heap" and use.op == "trap":
            continue  # the program stops, and nothing reads it
        if use.type == "heap" and use.op == "guard":
            return False  # the method may leave here, with an exception

        targets = _jump_targets(lam, use.ins[0], structure) if use.op == "call" else None
        if targets is None:
            return False  # a call to a method that takes the token may read it

        args = use.ins[1:]
        j = args.index(token)
        for name in targets:
            target = lambdas[name]
            o = target.params[args.index(obj)][0] if obj in args else None
            if (name, j, o) not in seen:
                seen.add((name, j, o))
                work.append((target, target.params[j][0], o, 0))
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
    if d.type == structure and d.op != ENTRY:
        return [d.op]
    arms = arms_of(defs, d, structure)
    return None if arms is None else [ref.op for ref in arms[1]]
