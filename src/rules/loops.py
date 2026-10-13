"""Load forwarding into and out of loops: the loop header takes the value
as a new parameter, a loop-carried phi when the body changes it, and a load
whose value no entry knows leaves the loop by peeling its first iteration."""

from dataclasses import dataclass

from cthu.ir import Instr, Lambda, Structure

from .forward import thread
from .shape import merge_same_params
from .tokens import (
    Branch,
    branch_into,
    copy_instr,
    field_access,
    fresh,
    in_loop,
    jump_sites,
    jump_to,
    names_in,
    only_jumps,
    param_origin,
    same_location,
    source_of,
    unchanged,
    value_of,
)

PEEL = 40  # instructions in a loop's header and body that peeling may copy, at most


@dataclass
class _Loop:
    """A loop whose body is one arm of the header's branch and jumps straight
    back: the body's closure of the header and jump to it, and each (λ,
    closure, jump) that enters the loop from outside."""
    header: Lambda
    branch: Branch
    body: Lambda
    back: tuple[Instr, Instr]
    entries: list[tuple[Lambda, Instr, Instr]]


def _loop(s: Structure, header: Lambda) -> _Loop | None:
    """The loop that `header` begins, if it has that shape."""
    sites = jump_sites(s, header.name) if header.name != "run" else None
    back = [site for site in sites or () if in_loop(s, header.name, [site])]

    if len(back) != 1:
        return None
    
    body, ref, jump = back[0]
    branch = branch_into(s, body.name)
    entries = [site for site in sites if site is not back[0]]
    
    if branch is None or branch.parent is not header or not entries:
        return None
    
    return _Loop(header, branch, body, (ref, jump), entries)


@dataclass
class _Carried:
    """A load in a loop's body whose value the back edge brings."""
    load: Instr
    token: str  # the header's parameter for the load's token
    obj: str | None  # the header's parameter for the load's object, None for a static field
    back: Instr | None  # the body's last store or load of the field; None when the value lasts unchanged
    settles: bool  # the object is another on the second iteration, an object the loop keeps, and stays it


def _carried(loop: _Loop) -> list[_Carried]:
    """The body's loads whose token comes from the header before anything in
    the body writes the field, and whose object comes around the loop
    unchanged, when the back edge brings the field's value: the same as the
    header had, when nothing on the way around writes the field, or the value
    of the body's last store or load of it."""
    heads, inside = [n for n, _ in loop.header.params], [n for n, _ in loop.body.params]
    passed, returned = loop.branch.call.ins[1:], loop.back[1].ins[1:]
    found = []
    for load in loop.body.body:
        a = field_access(load)
        token = param_origin(loop.body, load.ins[0]) if a and a[0] == "get" else None
        j = unchanged(loop.header, passed[inside.index(token)]) if token else None
        if j is None:
            continue
        obj, settles = None if a[1] else load.ins[1], False
        if obj is not None:
            if obj not in inside or passed[inside.index(obj)] not in heads:
                continue
            obj = passed[inside.index(obj)]
            again = returned[heads.index(obj)]
            if again != load.ins[1]:
                # another object on the next iteration, which settles if the body
                # passes it back for a parameter that it got unchanged
                settles = again in inside and any(y != obj and returned[heads.index(y)] == again
                                                  and passed[inside.index(again)] == y for y in heads)
                if not settles:
                    continue
        back = returned[heads.index(j)]
        if unchanged(loop.body, back) == token:
            found.append(_Carried(load, j, obj, None, settles))
        elif same_location(last := source_of(loop.body, back), a, None if a[1] else load.ins[1]):
            found.append(_Carried(load, j, obj, last, settles))
    return found


def _known_on_entry(loop: _Loop, load: Instr, j: str, obj: str | None) -> list[tuple[Instr, Instr, str]] | None:
    """(closure, jump, value) for each entry, if every entry knows the value."""
    a, heads = field_access(load), [n for n, _ in loop.header.params]
    known = []
    for caller, ref, jump in loop.entries:
        args = jump.ins[1:]
        source = source_of(caller, args[heads.index(j)])
        if not same_location(source, a, None if obj is None else args[heads.index(obj)]):
            return None
        known.append((ref, jump, value_of(source)))
    return known


def forward_into_loops(s: Structure) -> list[str]:
    """A load in a loop takes the value every entry knows when the back edge
    brings it too: the same value, when nothing in the loop changes it, which
    then lasts, or what the body last stored or loaded, which the header then
    takes as a loop-carried phi."""
    forwarded = []
    while True:
        for header in s.lambdas:
            loop = _loop(s, header)
            found = [(c.load, c.back, known) for c in (_carried(loop) if loop else ())
                     if not c.settles and (known := _known_on_entry(loop, c.load, c.token, c.obj)) is not None]
            if found:
                load, back, known = found[0]
                _carry(s, loop, known, load, back)
                forwarded.append(f"{load.field}, into a loop" + ("" if back is None else ", carried from the iteration before"))
                break
        else:
            return forwarded


def hoist_out_of_loop(s: Structure) -> str | None:
    """A load in a loop whose back edge brings the field's value, but whose
    entries don't know it, leaves the loop: the first iteration is peeled, and
    the loop takes what that iteration leaves for the next. When nothing in the
    loop writes the field, that is what the copy of the load read, which then
    lasts; else what the copy of the body's last store or load gave, which the
    header then takes as a loop-carried phi. A load whose object only settles
    leaves too: the first iteration is peeled before, after which the object's
    parameter and the one it settles on are one. Only a loop whose header and
    body are short, since the copies repeat them; say which load left."""
    for header in s.lambdas:
        loop = _loop(s, header)
        if loop is None or len(header.body) + len(loop.body.body) > PEEL:
            continue
        found = next((c for c in _carried(loop) if c.settles or _known_on_entry(loop, c.load, c.token, c.obj) is None), None)
        if found is None:
            continue
        load, back, settles = found.load, found.back, found.settles
        peeled = "its first iteration peeled"
        if settles:
            _peel(s, loop)
            merge_same_params(s)
            loop = _loop(s, header)
            again = next(c for c in _carried(loop) if c.load is load and not c.settles)
            back = again.back
            known = _known_on_entry(loop, load, again.token, again.obj)
            if known is not None:
                _carry(s, loop, known, load, back)
                return f"{load.field}, out of a loop, {peeled}" + ("" if back is None else ", then carried")
            peeled = "its first two iterations peeled"
        at = next(n for n, i in enumerate(loop.body.body) if i is (load if back is None else back))
        first, ref, jump = _peel(s, loop)
        left = first.body[at].outs[0] if back is None else value_of(first.body[at])
        _carry(s, loop, [(ref, jump, left)], load, back)
        return f"{load.field}, out of a loop, {peeled}" + ("" if back is None else ", then carried")
    return None


def _peel(s: Structure, loop: _Loop) -> tuple[Lambda, Instr, Instr]:
    """Copy the loop's first iteration. Every entry jumps to a copy of the
    header, whose branch goes to a copy of the body, which jumps into the loop,
    or to a copy of the exit; both exits jump to a new λ with the exit's code,
    so it isn't copied. Return the body's copy, its closure of the header, and
    its jump there."""
    header, body = loop.header, loop.body
    exit_ = next(lam for lam in s.lambdas if lam.name in {r.op for r in loop.branch.refs} - {body.name})
    taken = {lam.name for lam in s.lambdas}
    added = []
    if not only_jumps(s, exit_):  # as it does after an earlier peel
        after = Lambda(fresh(taken, f"{exit_.name}_after"), list(exit_.params), list(exit_.outs), exit_.body)
        exit_.body = jump_to(s, after, [n for n, _ in exit_.params], fresh(names_in(exit_), "k_after"))
        added.append(after)

    copies = {lam.name: Lambda(fresh(taken, f"{lam.name}_first"), list(lam.params), list(lam.outs),
                               [copy_instr(i) for i in lam.body], lam.exit)
              for lam in (header, body, exit_)}
    for i in copies[header.name].body:
        if i.type == s.name and i.op in (body.name, exit_.name):
            i.op = copies[i.op].name
    for _, ref, _ in loop.entries:
        ref.op = copies[header.name].name
    s.lambdas += [*copies.values(), *added]

    first = copies[body.name]
    return first, next(i for i in first.body if i.type == s.name and i.op == header.name), first.body[-1]


def _carry(s: Structure, loop: _Loop, entries: list[tuple[Instr, Instr, str]], load: Instr, back: Instr | None) -> None:
    """Give the header a parameter for the value, which each entry passes and
    the body passes back: the value it got, or the value of `back`, the store
    or load it last made. The header's branch passes it to the body, whose
    load takes it."""
    header = loop.header
    p = next((n for n, (_, t) in enumerate(header.params) if t == "heap"), len(header.params))
    value = fresh(names_in(header), f"{load.outs[0]}_in")
    header.params.insert(p, (value, load.out_types[0]))
    ftype = header.function_type
    again = thread(s, value, [(loop.branch, loop.body)], load)
    for ref, jump, v in (*entries, (*loop.back, again if back is None else value_of(back))):
        ref.out_types = [ftype]
        jump.type = ftype
        jump.ins = jump.ins[:1 + p] + [v] + jump.ins[1 + p:]
