"""Rules that change the shape of a program, not what it does: a branch to
an arm that leaves the method becomes guards, and a λ that one jump reaches
joins the λ that jumps, so that the code is straight-line and the other rules
can follow a token from one operation to the next."""

from dataclasses import replace

from cthu.ir import LINEAR, Instr, Lambda, Structure

from .tokens import branch_at, calls_into, fresh, is_pure, names_in, types_in


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
        unused = {lam.name for lam in s.lambdas if lam.name != "run" and lam.name not in used}
        if not unused:
            return
        s.lambdas = [lam for lam in s.lambdas if lam.name not in unused]


def fuse(s: Structure) -> None:
    """Inline each block that only one jump reaches into the λ that jumps:
    straight-line code, which Graal splits into blocks at every call, becomes
    one λ again. A merge, a loop header and a branch's arms stay λs."""
    while True:
        refs: dict[str, list[tuple[Lambda, Instr]]] = {}
        for lam in s.lambdas:
            for i in lam.body:
                if i.type == s.name:
                    refs.setdefault(i.op, []).append((lam, i))

        for target in s.lambdas:
            places = refs.get(target.name, [])
            if target.name == "run" or len(places) != 1:
                continue
            lam, ref = places[0]
            jump = lam.body[-1]
            outs = [n for n, _ in lam.outs]
            if lam is target or jump.op != "call" or jump.ins[:1] != ref.outs or jump.outs != outs \
                    or [n for n, _ in target.outs] != outs:
                continue
            _inline(lam, ref, jump, target)
            s.lambdas.remove(target)
            break
        else:
            return


def _inline(lam: Lambda, ref: Instr, jump: Instr, target: Lambda) -> None:
    """Replace the jump at the end of `lam` with the body of `target`."""
    names = {p: a for (p, _), a in zip(target.params, jump.ins[1:])}
    outs = {n for n, _ in target.outs}

    def rename(n: str) -> str:
        return names.get(n, n if n in outs else f"{n}_{target.name}")

    lam.body = [i for i in lam.body if i is not ref and i is not jump]
    lam.body += [replace(i, ins=[rename(n) for n in i.ins], outs=[rename(n) for n in i.outs], out_types=list(i.out_types))
                 for i in target.body]


def merge_same_params(s: Structure) -> None:
    """Two parameters of a λ that every place calling it passes the same value
    for are one: the later is replaced by the earlier in its body. Only a λ
    that jumps or one branch call."""
    while True:
        for lam in s.lambdas:
            calls, names = calls_into(s, lam), [n for n, _ in lam.params]
            used = {n for i in lam.body for n in i.ins}
            pair = next(((x, y) for y in range(len(names)) for x in range(y)
                         if calls and names[y] in used and lam.params[x][1] == lam.params[y][1] != "heap"
                         and all(args[x] == args[y] for args in calls)), None)
            if pair:
                for i in lam.body:
                    i.ins = [names[pair[0]] if n == names[pair[1]] else n for n in i.ins]
                break
        else:
            return


def drop_unused(lam: Lambda) -> None:
    """A value the rules left without a use, such as a dead store's, goes, and
    whatever only it used."""
    while True:
        used = {n for i in lam.body for n in i.ins} | {n for n, _ in lam.outs}
        body = [i for i in lam.body if not (is_pure(i) and not set(i.outs) & used)]
        if len(body) == len(lam.body):
            return
        lam.body = body
