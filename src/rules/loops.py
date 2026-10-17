"""Load forwarding into and out of loops

Into a loop: the loop header gets the value as a new parameter. The entry
passes the known value, and the back edge passes it around again
(forwarding.IntoLoop), or passes what the body stored, a loop-carried phi
(forwarding.LoopCarried).

Out of a loop: when nothing before the loop knows the value, the first
iteration is copied in front of the loop (peeled), and the loop takes the
value from that copy (forwarding.OutOfLoop)."""

from dataclasses import dataclass

from cthu.ir import Instr, Lambda, Structure

from .forward import thread
from .shape import merge_same_params
from .tokens import (
    ENTRY,
    Branch,
    Closures,
    branch_into,
    copy_instr,
    field_access,
    fresh,
    is_load,
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

PEEL = 40  # peel only loops whose header and body have at most this many instructions


@dataclass
class _Loop:
    """A loop of the shape the rules handle: the body is one arm of the
    header's branch and jumps straight back to the header. `back` is that
    jump, and `entries` the jumps that enter the loop from outside."""
    header: Lambda
    branch: Branch
    body: Lambda
    back: tuple[Instr, Instr]
    entries: list[tuple[Lambda, Instr, Instr]]


def _loop(s: Structure, header: Lambda, closures: Closures | None = None) -> _Loop | None:
    """The loop that starts at `header`, or None if there is none of that shape."""
    closures = closures or Closures(s)
    sites = jump_sites(s, header.name, closures) if header.name != ENTRY else None
    reached = closures.reached_from(header.name) if sites else set()
    back = [(lam, ref, jump) for lam, ref, jump in sites or () if lam.name in reached]

    if len(back) != 1:
        return None
    
    body, ref, jump = back[0]
    branch = branch_into(s, body.name, closures)
    entries = [(lam, r, j) for lam, r, j in sites if j is not jump]
    
    if branch is None or branch.parent is not header or not entries:
        return None
    
    return _Loop(header, branch, body, (ref, jump), entries)


@dataclass
class _Carried:
    """A load in the loop body whose value comes back around the loop."""
    load: Instr
    token: str  # the header's parameter for the load's token
    reference: str | None  # the header's parameter for the reference, None for a static field
    back: Instr | None  # the body's last store or load of the field; None if the body never changes it
    settles: bool  # the reference changes once, after the first iteration, then stays the same


def _carried(loop: _Loop) -> list[_Carried]:
    """The loads in the loop body whose value the back edge brings back:
    unchanged, because nothing in the loop writes the field, or as what the
    body last stored or loaded (a loop-carried phi). The load must go through
    the same reference in every iteration, or one that settles after the first."""
    heads, inside = [n for n, _ in loop.header.params], [n for n, _ in loop.body.params]
    _, back_jump = loop.back
    passed, returned = loop.branch.call.ins[1:], back_jump.ins[1:]
    found = []
    for load in loop.body.body:
        token = param_origin(loop.body, load.ins[0]) if is_load(load) else None
        j = unchanged(loop.header, passed[inside.index(token)]) if token else None
        if j is None:
            continue
        a = field_access(load)
        _, static, _ = a
        reference, settles = None if static else load.ins[1], False
        if reference is not None:
            if reference not in inside or passed[inside.index(reference)] not in heads:
                continue
            reference = passed[inside.index(reference)]
            again = returned[heads.index(reference)]
            if again != load.ins[1]:
                # another reference on the next iteration: only fine if it then
                # stays the same (it settles)
                settles = again in inside and any(y != reference and returned[heads.index(y)] == again
                                                  and passed[inside.index(again)] == y for y in heads)
                if not settles:
                    continue
        back = returned[heads.index(j)]
        if unchanged(loop.body, back) == token:
            found.append(_Carried(load, j, reference, None, settles))
        elif same_location(last := source_of(loop.body, back), a, None if static else load.ins[1]):
            found.append(_Carried(load, j, reference, last, settles))
    return found


def _known_on_entry(loop: _Loop, load: Instr, j: str, reference: str | None) -> list[tuple[Instr, Instr, str]] | None:
    """For each jump into the loop, the value it already knows for the load
    (what was just stored or loaded there); None if some entry doesn't know it."""
    a, heads = field_access(load), [n for n, _ in loop.header.params]
    known = []
    for caller, ref, jump in loop.entries:
        args = jump.ins[1:]
        source = source_of(caller, args[heads.index(j)])
        if not same_location(source, a, None if reference is None else args[heads.index(reference)]):
            return None
        known.append((ref, jump, value_of(source)))
    return known


def forward_into_loops(s: Structure) -> list[str]:
    """Forward into a loop: a load in the loop takes its value from a new
    header parameter, when every entry knows the value and the back edge
    brings it back. Examples: forwarding.IntoLoop (the value lasts),
    forwarding.LoopCarried (each iteration passes on what it stored)."""
    forwarded = []
    while True:
        closures = Closures(s)
        for header in s.lambdas:
            loop = _loop(s, header, closures)
            found = [(c.load, c.back, known) for c in (_carried(loop) if loop else ())
                     if not c.settles and (known := _known_on_entry(loop, c.load, c.token, c.reference)) is not None]
            if found:
                load, back, known = found[0]
                _carry(s, loop, known, load, back)
                forwarded.append(f"{load.field}, into a loop" + ("" if back is None else ", carried from the iteration before"))
                break
        else:
            return forwarded


def hoist_out_of_loop(s: Structure) -> str | None:
    """Move a load out of a loop when the loop brings its value back but no
    entry knows it: copy the first iteration in front of the loop (peel it),
    and let the loop take the value from that copy.
    Example: forwarding.OutOfLoop.

    The load can't simply move above the loop, because the loop may not run
    at all. Only short loops are peeled (PEEL), since peeling copies code. If
    the reference only settles after one iteration, two iterations are peeled.
    Return which load left the loop."""
    closures = Closures(s)
    for header in s.lambdas:
        loop = _loop(s, header, closures)
        if loop is None or len(header.body) + len(loop.body.body) > PEEL:
            continue
        found = next((c for c in _carried(loop)
                      if c.settles or _known_on_entry(loop, c.load, c.token, c.reference) is None), None)
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
            known = _known_on_entry(loop, load, again.token, again.reference)
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
    """Copy the loop's first iteration in front of the loop: the entries now go
    to the copy, which then goes on into the loop. Both the copy and the loop
    leave through one shared λ, so the code after the loop isn't copied.
    Return the copied body, with its closure of the header and its jump there."""
    header, body = loop.header, loop.body
    exit_ = next(lam for lam in s.lambdas if lam.name in {r.op for r in loop.branch.refs} - {body.name})
    taken = {lam.name for lam in s.lambdas}
    added = []
    if not only_jumps(s, exit_):  # the exit has code of its own (after an earlier peel): share it
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
    """Add the header parameter that carries the value around the loop. Each
    entry passes the known value; the back edge passes it on, or passes what
    the body last stored or loaded (`back`). The load in the body takes it."""
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
