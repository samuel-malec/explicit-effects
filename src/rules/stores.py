"""Dead store removal

A store is dead when, on every path, the same field is overwritten through the
same reference before anything can read it. Leaving the method, by returning
or by throwing, counts as a read, since the caller may look.
Examples: deadstores.Adjacent, deadstores.BothArms, deadstores.OtherFieldBetween;
deadstores.CallBetweenKeeps shows why a call between the stores keeps the first."""

from cthu.ir import TRAPS, Instr, Lambda, Structure

from .tokens import ALLOCATION, ENTRY, arms_of, field_access, is_store


def remove_dead_stores(s: Structure) -> list[Instr]:
    """Replace each dead store with a plain move of its token, and return the
    stores that went."""
    lambdas = {lam.name: lam for lam in s.lambdas}
    dead = []
    for lam in s.lambdas:
        for n, i in enumerate(lam.body):
            if is_store(i):
                _, static, index = field_access(i)
                location = (static, index, None if static else i.ins[1])
                if _overwritten(s.name, lambdas, lam, i.outs[0], location, n + 1):
                    dead.append((lam, i))

    for lam, i in dead:
        at = next(n for n, x in enumerate(lam.body) if x is i)
        lam.body[at] = Instr("heap", "move", [i.ins[0]], [i.outs[0]], ["heap"], note=f"dead store to {i.field}")
    return [i for _, i in dead]


def _overwritten(structure: str, lambdas: dict[str, Lambda], lam: Lambda, token: str,
                 location: tuple[bool, int, str | None], start: int) -> bool:
    """Whether every path of the token from the store overwrites the location
    before anything may read it. A load, a call that takes the token, leaving
    the method, or anything that may throw on the way (a guard, an allocation)
    counts as a read.

    Each λ is visited once for each way the token enters it, so loops end."""
    static, k, reference = location
    work = [(lam, token, reference, start)]
    seen: set[tuple[str, int, str | None]] = set()  # (λ, token parameter, reference parameter) already visited
    while work:
        lam, token, reference, start = work.pop()
        while True:  # follow the token through this λ, past moves and trapping guards
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
        if a is not None:
            kind, use_static, use_index = a
            if not (kind == "set" and (use_static, use_index) == (static, k) and (static or use.ins[1] == reference)):
                return False  # read, or written through another reference, which may point to another object
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
            reference_param = None
            if reference in args:
                reference_param, _ = target.params[args.index(reference)]
            if (name, j, reference_param) not in seen:
                seen.add((name, j, reference_param))
                token_param, _ = target.params[j]
                work.append((target, token_param, reference_param, 0))
    return True


def _may_throw(i: Instr) -> bool:
    """Whether the instruction may throw, whatever token it takes: a guard that
    throws, or an allocation (OutOfMemoryError, which Graal IR doesn't show as
    a branch). Other exceptions are branches, which the walk follows."""
    return i.type == "heap" and (bool(ALLOCATION.fullmatch(i.op)) or (i.op == "guard" and i.exit != TRAPS))


def _jump_targets(lam: Lambda, k: str, structure: str) -> list[str] | None:
    """The λs a call goes to, if it is a jump to the next block or a branch into
    two arms; None for a call of a method."""
    defs = {out: i for i in lam.body for out in i.outs}
    d = defs.get(k)
    if d is None:
        return None
    if d.type == structure and d.op != ENTRY:
        return [d.op]
    arms = arms_of(defs, d, structure)
    if arms is None:
        return None
    _, refs = arms
    return [ref.op for ref in refs]
