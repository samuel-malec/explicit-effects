"""Rules that change the shape of a Cthu program

Since exceptions split control flow, many memory operations lose the explicit
data dependencies that were obvious if the control flow would be trivial.
We attempt to simplify the control flow by recognizing common safe patterns, 
where a possible simplification is possible.

We focus on the following situations:
    a branch to an arm that leaves the method becomes guards, and a λ that one jump reaches
    joins the λ that jumps, so that the code is straight-line and the other rules
    can follow a token from one operation to the next."""

from cthu.ir import LINEAR, Instr, Lambda, Structure

from .tokens import ENTRY, Closures, branch_at, calls_into, fresh, is_pure, names_in, types_in


def unshare(lam: Lambda) -> None:
    """Undo linearize: every copy of a value goes back to its one name, and
    drops go, so the same object has the same name all through the λ."""
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
    """A branch whose arm leaves the method on every path becomes a guard on each
    token, which leaves when that arm would have run, and a jump to the other
    arm: a null check's branch to the exception it throws, a call's branch to
    where its exception goes. The guard says how the arm leaves: `throws`, with
    an exception and every token, or `traps`, stopping the program."""
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
    while True:
        used = {i.op for lam in s.lambdas for i in lam.body if i.type == s.name}
        unused = {lam.name for lam in s.lambdas if lam.name != ENTRY and lam.name not in used}
        if not unused:
            return
        s.lambdas = [lam for lam in s.lambdas if lam.name not in unused]


def fuse(s: Structure) -> None:
    """Inline each block that only one jump reaches into the λ that jumps:
    straight-line code, which Graal splits into blocks at every call, becomes
    one λ again. A merge, a loop header and a branch's arms stay λs.

    One pass in program order is enough: inlining a block moves the closures
    it takes into the λ that jumped to it, which leaves whether any other block
    can be inlined as it was."""
    closures = Closures(s)
    n = 0
    while n < len(s.lambdas):
        target = s.lambdas[n]
        places = closures.of(target.name)
        if target.name != ENTRY and len(places) == 1 and _jumps_only_to(*places[0], target):
            lam, ref = places[0]
            copies = _inline(lam, ref, lam.body[-1], target)
            del s.lambdas[n], closures.places[target.name]
            for old, new in zip(target.body, copies):  # the closures the block took are now the λ's
                if old.type == s.name:
                    taken = closures.places[old.op]
                    taken[next(k for k, (_, i) in enumerate(taken) if i is old)] = (lam, new)
        else:
            n += 1


def _jumps_only_to(lam: Lambda, ref: Instr, target: Lambda) -> bool:
    """Whether `lam` ends by jumping through closure `ref` to `target`, which
    gives what `lam` gives."""
    jump = lam.body[-1]
    outs = [n for n, _ in lam.outs]
    return lam is not target and jump.op == "call" and jump.ins[:1] == ref.outs and jump.outs == outs \
        and [n for n, _ in target.outs] == outs


def _inline(lam: Lambda, ref: Instr, jump: Instr, target: Lambda) -> list[Instr]:
    """Replace the jump at the end of `lam` with the body of `target`, and
    give the copies of target's instructions, in order."""
    names = {p: a for (p, _), a in zip(target.params, jump.ins[1:])}
    outs = {n for n, _ in target.outs}

    def rename(n: str) -> str:
        return names.get(n, n if n in outs else f"{n}_{target.name}")

    copies = [i.renamed([rename(n) for n in i.ins], [rename(n) for n in i.outs]) for i in target.body]
    lam.body = [i for i in lam.body if i is not ref and i is not jump] + copies
    return copies


def merge_same_params(s: Structure) -> None:
    """Two parameters of a λ that every place calling it passes the same value
    for are one: the later is replaced by the earlier in its body. Only a λ
    that jumps or one branch call. Renaming changes no closure, so the closures
    are found once; it can make two arguments of a call the same, so the λs
    are looked at again after each."""
    closures = Closures(s)
    while True:
        for lam in s.lambdas:
            pair = _same_params(s, lam, closures)
            if pair:
                x, y = (lam.params[k][0] for k in pair)
                for i in lam.body:
                    i.ins = [x if n == y else n for n in i.ins]
                break
        else:
            return


def _same_params(s: Structure, lam: Lambda, closures: Closures) -> tuple[int, int] | None:
    """The first two parameters of the λ, other than tokens, that every place
    calling it passes the same value for, the later one used in its body."""
    calls = calls_into(s, lam, closures)
    if not calls:
        return None
    first: dict[tuple[str, ...], int] = {}  # (type, what each call passes) → the first parameter it is
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
    """A value the rules left without a use, such as a dead store's, goes, and
    whatever only it used."""
    while True:
        used = {n for i in lam.body for n in i.ins} | {n for n, _ in lam.outs}
        body = [i for i in lam.body if not (is_pure(i) and not set(i.outs) & used)]
        if len(body) == len(lam.body):
            return
        lam.body = body
