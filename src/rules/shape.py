"""Rules that change the shape of a Cthu program

We attempt to simplify the control flow by recognizing common safe patterns, 
where a possible simplification is possible.

We focus on the following situations:
    a branch to an arm that leaves the method becomes guards, and a λ that one jump reaches
    joins the λ that jumps, so that the code is straight-line and the other rules
    can follow a token from one operation to the next."""

from cthu.ir import LINEAR, Instr, Lambda, Structure

from .tokens import ENTRY, Closures, branch_at, calls_into, fresh, is_pure, names_in, types_in

def unshare(lam: Lambda) -> None:
    """Remove the `dup`s and `drop`s, so that each value has one name in the
    whole λ. The rules compare names, for example to see that two accesses
    go through the same reference. `linearize` puts the copies back at the end."""
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
    parameters, keep only the first. Then the rules see that both names are
    the same value, for example the same reference."""
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
    """Remove the values nothing uses any more, such as what a forwarded load
    or a dead store left behind."""
    while True:
        used = {n for i in lam.body for n in i.ins} | {n for n, _ in lam.outs}
        body = [i for i in lam.body if not (is_pure(i) and not set(i.outs) & used)]
        if len(body) == len(lam.body):
            return
        lam.body = body
