"""Memory rules on the token form: a load takes the value of the access its
token comes from, and a store goes when every path its token takes overwrites
the same location first.

Both rules are local. They follow a token from one operation to the next,
through what only passes it on (a move, a guard, a jump to the next block, a
branch to both of its arms), and never past another memory operation, so what
they find depends on the partitioning alone: with one heap token, a store to
another field stands in the way.

First the program takes a shape in which more of it is local: a branch whose
arm only traps becomes a guard on each token, and a block that only one jump
reaches joins the λ that jumps. Two rules then carry a known value past a λ's
edge as a parameter. A load in a branch arm takes the value from above the
branch, which passes it to both arms. A load after a merge whose predecessors
know its value splits the merge: those that know it get a copy, up to the
load, which takes the value as a parameter, like a phi, and both copies go on
to the same λ for the code after the load.

Dead stores rely on the trap model: a path that throws ends in a trap, which
ends the program, so nothing reads the store on it. In Java a handler up the
stack could, so a store removed across a call or a guard is legal there only
if neither can throw. Forwarding a load never depends on it.
"""

import re
from dataclasses import dataclass, field

from cthu.ir import LINEAR, Instr, Lambda, Program, Structure, frame_type, function_type
from cthu.ssu import linearize

ACCESS = re.compile(r"(get|set)(static)?_(\d+)")

VALUES = {"int", "long", "float", "double", "bool", "ref"}

# Operations on values that can't throw: what may sit before a load in the part
# of a merge that splitting copies, and what goes once nothing uses it.
PURE = re.compile(r"cons_m?\d+|null|move|not|neg|add|sub|mul|and|or|xor|shl|shr|ushr|eq\?|lt\?|ult\?|nil\?|opt|join")

SPLITS = 100  # merges split per method, at most


@dataclass
class Rewrites:
    """What the rules did: `structure: field` for each load and store."""
    forwarded: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def apply(program: Program) -> Rewrites:
    """Rewrite the program in place, and say what changed."""
    done = Rewrites()
    for s in program.structures:
        for lam in s.lambdas:
            _unshare(lam)
        _guard_traps(s)
        for _ in range(SPLITS):
            _remove_unreferenced(s)
            _fuse(s)
            for lam in s.lambdas:
                done.forwarded += [f"{s.name}: {note}" for note in _forward(lam)]
            done.forwarded += [f"{s.name}: {note}" for note in _forward_into_arms(s)]
            split = _split_merge(s)
            if split is None:
                break
            done.forwarded.append(f"{s.name}: {split}")
        done.removed += [f"{s.name}: {note}" for note in _remove_dead_stores(s)]
        _remove_unreferenced(s)
        for lam in s.lambdas:
            _drop_unused(lam)
            linearize(lam)
    return done


def _access(i: Instr) -> tuple[str, bool, int] | None:
    """(get or set, static, field index) for a field access."""
    m = ACCESS.fullmatch(i.op) if i.type == "heap" else None
    return (m.group(1), bool(m.group(2)), int(m.group(3))) if m else None


def _pure(i: Instr) -> bool:
    return i.type in VALUES and bool(PURE.fullmatch(i.op))


def _types(lam: Lambda) -> dict[str, str]:
    types = dict(lam.params)
    for i in lam.body:
        types.update(zip(i.outs, i.out_types))
    return types


def _fresh(taken: set[str], base: str) -> str:
    name, n = base, 0
    while name in taken:
        n += 1
        name = f"{base}{n}"
    taken.add(name)
    return name


def _names(lam: Lambda) -> set[str]:
    return {n for n, _ in lam.params} | {n for n, _ in lam.outs} | {o for i in lam.body for o in i.outs}


def _unshare(lam: Lambda) -> None:
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


def _guard_traps(s: Structure) -> None:
    """A branch whose arm traps on every path, such as a null check's, becomes
    a guard on each token, which traps when that arm would have run, and a jump
    to the other arm."""
    traps = {lam.name for lam in s.lambdas if lam.note.startswith("traps")}
    for lam in s.lambdas:
        call = lam.body[-1] if lam.body else None
        defs = {out: i for i in lam.body for out in i.outs}
        join = defs.get(call.ins[0]) if call is not None and call.op == "call" else None
        if join is None or join.op != "join":
            continue
        opts = [defs.get(n) for n in join.ins[:2]]
        refs = [defs.get(o.ins[1]) if o is not None and o.op == "opt" else None for o in opts]
        if not all(r is not None and r.type == s.name for r in refs) or [r.op in traps for r in refs].count(True) != 1:
            continue

        trap = next(n for n, r in enumerate(refs) if r.op in traps)
        when = opts[trap].ins[0]
        taken, types = _names(lam), _types(lam)
        guards, args = [], []
        for a in call.ins[1:]:
            if types[a] == "heap":
                guards.append(Instr("heap", "guard", [a, when], [_fresh(taken, f"{a}_g")], ["heap"]))
                args.append(guards[-1].outs[0])
            else:
                args.append(a)
        gone = {id(i) for i in (call, join, defs.get(join.ins[2]), *opts, *refs)}
        lam.body = [i for i in lam.body if id(i) not in gone] + guards + [
            Instr(s.name, refs[1 - trap].op, [], [call.ins[0]], [call.type]),
            Instr(call.type, "call", [call.ins[0], *args], call.outs, call.out_types)]


def _remove_unreferenced(s: Structure) -> None:
    while True:
        used = {i.op for lam in s.lambdas for i in lam.body if i.type == s.name}
        unused = {lam.name for lam in s.lambdas if lam.name != "run" and lam.name not in used}
        if not unused:
            return
        s.lambdas = [lam for lam in s.lambdas if lam.name not in unused]


def _fuse(s: Structure) -> None:
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
    lam.body += [Instr(i.type, i.op, [rename(n) for n in i.ins], [rename(n) for n in i.outs], list(i.out_types), i.note)
                 for i in target.body]


def _forward(lam: Lambda) -> list[str]:
    """A load whose token comes straight from a store or a load of the same
    field of the same object gives the value that access stored or loaded."""
    forwarded = []
    for i in list(lam.body):
        a = _access(i)
        if not a or a[0] != "get":
            continue
        source = _source(lam, i.ins[0])
        b = _access(source) if source else None
        if not b or b[1:] != a[1:] or (not a[1] and source.ins[1] != i.ins[1]):
            continue
        at = next(n for n, x in enumerate(lam.body) if x is i)
        lam.body[at:at + 1] = _forwarded(i, _value(source))
        forwarded.append(i.note)
    return forwarded


def _forwarded(load: Instr, value: str) -> list[Instr]:
    """What replaces a load whose value is known."""
    t = load.out_types[0]
    return [Instr(t, "move", [value], [load.outs[0]], [t], note=f"forwarded {load.note}"),
            Instr("heap", "move", [load.ins[0]], [load.outs[1]], ["heap"])]


def _value(access: Instr) -> str:
    """The value a store stored or a load loaded."""
    return access.ins[-1] if _access(access)[0] == "set" else access.outs[0]


def _source(lam: Lambda, token: str) -> Instr | None:
    """The instruction that gave the token, past moves and guards."""
    defs = {out: i for i in lam.body for out in i.outs}
    source = defs.get(token)
    while source is not None and source.type == "heap" and source.op in ("move", "guard"):
        source = defs.get(source.ins[0])
    return source


@dataclass
class _Branch:
    """A branch at the end of `parent`: the closures of both arms, the opts and
    the join that make one of them, the frame's closure, and the call."""
    parent: Lambda
    refs: list[Instr]
    opts: list[Instr]
    join: Instr
    frame: Instr
    call: Instr


def _branch_into(s: Structure, name: str) -> _Branch | None:
    """The branch whose arm λ `name` is, if it is the only place that takes
    either arm."""
    def places(n: str) -> list[tuple[Lambda, Instr]]:
        return [(lam, i) for lam in s.lambdas for i in lam.body if i.type == s.name and i.op == n]

    taken = places(name)
    if len(taken) != 1:
        return None
    parent = taken[0][0]
    call = parent.body[-1]
    defs = {out: i for i in parent.body for out in i.outs}
    join = defs.get(call.ins[0]) if call.op == "call" else None
    if join is None or join.op != "join":
        return None
    opts = [defs.get(n) for n in join.ins[:2]]
    refs = [defs.get(o.ins[1]) if o is not None and o.op == "opt" else None for o in opts]
    if not all(r is not None and r.type == s.name for r in refs) or name not in {r.op for r in refs} \
            or any(len(places(r.op)) != 1 for r in refs):
        return None
    return _Branch(parent, refs, opts, join, defs.get(join.ins[2]), call)


def _forward_into_arms(s: Structure) -> list[str]:
    """A load in a branch arm whose token and object come unchanged from above
    the branches it is in, where a store or a load of the same field of the
    same object gave the token, takes that access's value as a parameter."""
    forwarded = []
    while True:
        for arm in s.lambdas:
            found = next(((load, f) for load in arm.body if (f := _from_above(s, arm, load))), None)
            if found:
                load, (value, hops) = found
                _thread(s, value, hops, load)
                forwarded.append(f"{load.note}, into a branch arm")
                break
        else:
            return forwarded


def _from_above(s: Structure, arm: Lambda, load: Instr) -> tuple[str, list[tuple[_Branch, Lambda]]] | None:
    """The value the load reads, in the λ above the branches it is in, and each
    (branch, arm on the way) from there down to the load's λ."""
    a = _access(load)
    if not a or a[0] != "get":
        return None
    lam, token, obj = arm, _param_origin(arm, load.ins[0]), None if a[1] else load.ins[1]
    hops: list[tuple[_Branch, Lambda]] = []
    while token is not None and all(lam is not l for _, l in hops):
        names = [n for n, _ in lam.params]
        branch = _branch_into(s, lam.name)
        if branch is None or (obj is not None and obj not in names):
            return None
        hops.append((branch, lam))
        args = branch.call.ins[1:]
        token, obj = args[names.index(token)], None if obj is None else args[names.index(obj)]
        source = _source(branch.parent, token)
        if source is not None:
            b = _access(source)
            if b and b[1:] == a[1:] and (obj is None or source.ins[1] == obj):
                return _value(source), hops[::-1]
            return None
        lam, token = branch.parent, _param_origin(branch.parent, token)
    return None


def _thread(s: Structure, value: str, hops: list[tuple[_Branch, Lambda]], load: Instr) -> None:
    """Pass the value down each branch, as a new parameter of both of its
    arms, to the load, which takes it."""
    for branch, arm in hops:
        p = next((n for n, (_, t) in enumerate(arm.params) if t == "heap"), len(arm.params))
        given = {}
        for ref in branch.refs:
            target = next(lam for lam in s.lambdas if lam.name == ref.op)
            given[target.name] = _fresh(_names(target), f"{load.outs[0]}_in")
            target.params.insert(p, (given[target.name], load.out_types[0]))
        ftype = arm.function_type
        for i in (*branch.refs, *branch.opts, branch.join):
            if i.op not in ("opt", "join"):
                i.out_types = [ftype]
            else:
                i.type, i.out_types = ftype, [ftype]
        branch.frame.op, branch.frame.out_types = _frame(s, arm.params, arm.outs), [frame_type(ftype)]
        branch.call.type = ftype
        branch.call.ins = branch.call.ins[:1 + p] + [value] + branch.call.ins[1 + p:]
        value = given[arm.name]

    at = next(n for n, x in enumerate(arm.body) if x is load)
    arm.body[at:at + 1] = _forwarded(load, value)


def _frame(s: Structure, params: list[tuple[str, str]], outs: list[tuple[str, str]]) -> str:
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


def _split_merge(s: Structure) -> str | None:
    """Split one merge, whose first load some predecessors know the value of,
    and say which load. Only a merge that jumps reach, outside a loop, with
    nothing before the load but what passes the token on or can't throw: that
    much the copy repeats."""
    for merge in s.lambdas:
        sites = _jump_sites(s, merge.name) if merge.name != "run" else None
        if not sites or len(sites) < 2 or _in_loop(s, merge.name, sites):
            continue
        params = [n for n, _ in merge.params]
        for at, load in enumerate(merge.body):
            a = _access(load)
            if a and a[0] == "get":
                break
            if not (_pure(load) or (load.type == "heap" and load.op in ("move", "guard"))):
                break
        else:
            continue
        if not a or a[0] != "get":
            continue

        token = _param_origin(merge, load.ins[0])
        obj = None if a[1] else load.ins[1]
        if token is None or (obj is not None and obj not in params):
            continue
        known = []
        for caller, ref, jump in sites:
            args = jump.ins[1:]
            source = _source(caller, args[params.index(token)])
            b = _access(source) if source else None
            if b and b[1:] == a[1:] and (obj is None or source.ins[1] == args[params.index(obj)]):
                known.append((ref, jump, _value(source)))
        if known:
            _split(s, merge, at, known)
            return f"{load.note}, across a merge from {len(known)} of {len(sites)} predecessors"
    return None


def _jump_sites(s: Structure, name: str) -> list[tuple[Lambda, Instr, Instr]] | None:
    """Each (λ, closure, jump) that jumps to λ `name`, if only jumps reach it."""
    sites = []
    for lam in s.lambdas:
        for i in lam.body:
            if i.type == s.name and i.op == name:
                jump = lam.body[-1]
                if jump.op != "call" or jump.ins[:1] != i.outs or jump.outs != [n for n, _ in lam.outs]:
                    return None
                sites.append((lam, i, jump))
    return sites


def _in_loop(s: Structure, name: str, sites: list[tuple[Lambda, Instr, Instr]]) -> bool:
    """Whether one of the λs that jump to `name` is reachable from it."""
    refs = {lam.name: {i.op for i in lam.body if i.type == s.name} for lam in s.lambdas}
    seen, work = set(), [name]
    while work:
        for n in refs.get(work.pop(), ()):
            if n not in seen:
                seen.add(n)
                work.append(n)
    return any(lam.name in seen for lam, _, _ in sites)


def _param_origin(lam: Lambda, token: str) -> str | None:
    """The parameter the token comes from, past moves and guards."""
    defs = {out: i for i in lam.body for out in i.outs}
    while token in defs:
        d = defs[token]
        if d.type != "heap" or d.op not in ("move", "guard"):
            return None
        token = d.ins[0]
    return token if token in {n for n, _ in lam.params} else None


def _split(s: Structure, merge: Lambda, at: int, known: list[tuple[Instr, Instr, str]]) -> None:
    """Move the code after the load at `at` into a new λ that the merge jumps
    to, and give the predecessors that know the load's value a copy of the
    merge that takes it as a parameter instead of loading it."""
    load = merge.body[at]
    head, rest = merge.body[:at + 1], merge.body[at + 1:]
    types = _types(merge)
    defined = {o for i in rest for o in i.outs}
    live = list(dict.fromkeys(n for i in rest for n in i.ins if n not in defined))
    live = [n for n in live if types[n] != "heap"] + [n for n in live if types[n] == "heap"]

    lambdas = {lam.name for lam in s.lambdas}
    after = Lambda(_fresh(lambdas, f"{merge.name}_after"), [(n, types[n]) for n in live], list(merge.outs), rest)
    outs, out_types = [n for n, _ in merge.outs], [t for _, t in merge.outs]
    ftype = function_type([types[n] for n in live], out_types)
    k = _fresh(_names(merge), "k_after")
    jump = [Instr(s.name, after.name, [], [k], [ftype]), Instr(ftype, "call", [k, *live], outs, out_types)]
    merge.body = head + jump

    value = _fresh(_names(merge), f"{load.outs[0]}_in")
    p = next((n for n, (_, t) in enumerate(merge.params) if t == "heap"), len(merge.params))
    copy = Lambda(_fresh(lambdas, f"{merge.name}_known"),
                  [*merge.params[:p], (value, load.out_types[0]), *merge.params[p:]], list(merge.outs),
                  [_copy(i) for i in head[:-1]] + _forwarded(load, value) + [_copy(i) for i in jump])
    place = next(n for n, lam in enumerate(s.lambdas) if lam is merge) + 1
    s.lambdas[place:place] = [copy, after]

    for ref, call, v in known:
        ref.op, ref.out_types = copy.name, [copy.function_type]
        call.type = copy.function_type
        call.ins = call.ins[:1 + p] + [v] + call.ins[1 + p:]


def _copy(i: Instr) -> Instr:
    return Instr(i.type, i.op, list(i.ins), list(i.outs), list(i.out_types), i.note)


def _remove_dead_stores(s: Structure) -> list[str]:
    lambdas = {lam.name: lam for lam in s.lambdas}
    dead = []
    for lam in s.lambdas:
        for i in lam.body:
            a = _access(i)
            if a and a[0] == "set":
                location = (a[1], a[2], None if a[1] else i.ins[1])
                if _overwritten(s.name, lambdas, lam, i.outs[0], location, frozenset()):
                    dead.append((lam, i))

    for lam, i in dead:
        at = next(n for n, x in enumerate(lam.body) if x is i)
        lam.body[at] = Instr("heap", "move", [i.ins[0]], [i.outs[0]], ["heap"], note=f"dead store to {i.note}")
    return [i.note for _, i in dead]


def _overwritten(structure: str, lambdas: dict[str, Lambda], lam: Lambda, token: str,
                 location: tuple[bool, int, str | None], seen: frozenset) -> bool:
    """Whether every path the token takes from here overwrites the location,
    (static, field index, object), before anything can read it."""
    static, k, obj = location
    use = next((i for i in lam.body if token in i.ins), None)
    if use is None:
        return False  # it leaves the method: the caller may read it

    a = _access(use)
    if a:
        return a[0] == "set" and a[1:] == (static, k) and (static or use.ins[1] == obj)
    if use.type == "heap" and use.op == "trap":
        return True
    if use.type == "heap" and use.op in ("move", "guard"):
        return _overwritten(structure, lambdas, lam, use.outs[0], location, seen)

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


def _jump_targets(lam: Lambda, k: str, structure: str) -> list[str] | None:
    """The λs a call through `k` goes to, if it is a jump to the next block or
    a branch to both arms, which get the call's arguments in the same order."""
    defs = {out: i for i in lam.body for out in i.outs}
    d = defs.get(k)
    if d is None:
        return None
    if d.type == structure and d.op != "run":
        return [d.op]
    if d.op != "join":
        return None

    arms = []
    for at in d.ins[:2]:
        opt = defs.get(at)
        ref = defs.get(opt.ins[1]) if opt is not None and opt.op == "opt" else None
        if ref is None or ref.type != structure:
            return None
        arms.append(ref.op)
    return arms


def _drop_unused(lam: Lambda) -> None:
    """A value the rules left without a use, such as a dead store's, goes, and
    whatever only it used."""
    while True:
        used = {n for i in lam.body for n in i.ins} | {n for n, _ in lam.outs}
        body = [i for i in lam.body if not (_pure(i) and not set(i.outs) & used)]
        if len(body) == len(lam.body):
            return
        lam.body = body
