"""Perform Load forwarding transformation."""

from cthu.ir import Instr, Lambda, Structure, frame_type

from .tokens import (
    ENTRY,
    Branch,
    Closures,
    branch_into,
    copy_instr,
    field_access,
    frame_of,
    fresh,
    in_loop,
    is_load,
    is_pure,
    jump_sites,
    jump_to,
    names_in,
    param_origin,
    same_location,
    source_of,
    types_in,
    value_of,
)


def forward_within(lam: Lambda) -> list[str]:
    """Forward within one λ: a load whose token comes straight from a store or
    a load of the same field through the same reference takes its value.
    Examples: forwarding.AcrossCall, forwarding.RepeatedLoad."""
    forwarded = []
    for i in list(lam.body):
        if not is_load(i):
            continue
        a = field_access(i)
        _, static, _ = a
        source = source_of(lam, i.ins[0])
        
        if not same_location(source, a, None if static else i.ins[1]):
            continue
        
        at = next(n for n, x in enumerate(lam.body) if x is i)
        lam.body[at:at + 1] = forwarding(i, value_of(source))
        forwarded.append(i.field)
    
    return forwarded


def forwarding(load: Instr, value: str) -> list[Instr]:
    """The two moves that replace a load whose value is known: the result
    becomes that value, and the token passes on unchanged."""
    t = load.out_types[0]
    return [Instr(t, "move", [value], [load.outs[0]], [t], note=f"forwarded {load.field}"),
            Instr("heap", "move", [load.ins[0]], [load.outs[1]], ["heap"])]


def forward_into_arms(s: Structure) -> list[str]:
    """Forward into a branch arm: when the value was stored or loaded above the
    branch, pass it down to the arm as a new parameter.
    Example: forwarding.IntoBranchArm."""
    forwarded = []
    while True:
        closures = Closures(s)
        for arm in s.lambdas:
            found = next(((load, f) for load in arm.body if (f := _from_above(s, arm, load, closures))), None)
            if found:
                load, (value, hops) = found
                thread(s, value, hops, load)
                forwarded.append(f"{load.field}, into a branch arm")
                break
        else:
            return forwarded


def _from_above(s: Structure, arm: Lambda, load: Instr, closures: Closures) -> tuple[str, list[tuple[Branch, Lambda]]] | None:
    """The value the load reads, if a store or a load above its branches gives
    it, and the branches the value has to pass through on the way down."""
    if not is_load(load):
        return None
    a = field_access(load)
    _, static, _ = a

    lam, token, reference = arm, param_origin(arm, load.ins[0]), None if static else load.ins[1]
    hops: list[tuple[Branch, Lambda]] = []

    while token is not None and all(lam is not l for _, l in hops):
        names = [n for n, _ in lam.params]
        branch = branch_into(s, lam.name, closures)
        if branch is None or (reference is not None and reference not in names):
            return None

        hops.append((branch, lam))
        args = branch.call.ins[1:]
        token, reference = args[names.index(token)], None if reference is None else args[names.index(reference)]
        source = source_of(branch.parent, token)

        if source is not None:
            return (value_of(source), hops[::-1]) if same_location(source, a, reference) else None

        lam, token = branch.parent, param_origin(branch.parent, token)

    return None


def thread(s: Structure, value: str, hops: list[tuple[Branch, Lambda]], load: Instr) -> str:
    """Pass the value down through each branch, as a new parameter of both
    arms, and let the load take it. Return the parameter's name in the
    load's λ."""
    for branch, arm in hops:
        p = next((n for n, (_, t) in enumerate(arm.params) if t == "heap"), len(arm.params))
        given = {}
        for ref in branch.refs:
            target = next(lam for lam in s.lambdas if lam.name == ref.op)
            given[target.name] = fresh(names_in(target), f"{load.outs[0]}_in")
            target.params.insert(p, (given[target.name], load.out_types[0]))

        ftype = arm.function_type

        for i in (*branch.refs, *branch.opts, branch.join):
            if i.op not in ("opt", "join"):
                i.out_types = [ftype]
            else:
                i.type, i.out_types = ftype, [ftype]

        branch.frame.op, branch.frame.out_types = frame_of(s, arm.params, arm.outs), [frame_type(ftype)]
        branch.call.type = ftype
        branch.call.ins = branch.call.ins[:1 + p] + [value] + branch.call.ins[1 + p:]
        value = given[arm.name]

    at = next(n for n, x in enumerate(arm.body) if x is load)
    arm.body[at:at + 1] = forwarding(load, value)
    return value


def split_merge(s: Structure) -> str | None:
    """Forward across a merge: when some of the blocks that jump to a merge
    know the value of its first load, give them their own copy of the merge
    up to that load, which takes the value as a parameter instead of loading
    it. Example: forwarding.AcrossMerge.

    Only outside loops, and only when nothing before the load may throw, since
    that part gets copied. Return which load was forwarded."""
    closures = Closures(s)
    for merge in s.lambdas:
        sites = jump_sites(s, merge.name, closures) if merge.name != ENTRY else None
        if not sites or len(sites) < 2 or in_loop(s, merge.name, sites, closures):
            continue
        params = [n for n, _ in merge.params]
        for at, load in enumerate(merge.body):
            if is_load(load):
                break
            if not (is_pure(load) or (load.type == "heap" and load.op in ("move", "guard"))):
                break
        else:
            continue
        if not is_load(load):
            continue

        a = field_access(load)
        _, static, _ = a
        token = param_origin(merge, load.ins[0])
        reference = None if static else load.ins[1]
        if token is None or (reference is not None and reference not in params):
            continue
        known = []
        for caller, ref, jump in sites:
            args = jump.ins[1:]
            source = source_of(caller, args[params.index(token)])
            if same_location(source, a, None if reference is None else args[params.index(reference)]):
                known.append((ref, jump, value_of(source)))
        if known:
            _split(s, merge, at, known)
            return f"{load.field}, across a merge from {len(known)} of {len(sites)} predecessors"
    return None


def _split(s: Structure, merge: Lambda, at: int, known: list[tuple[Instr, Instr, str]]) -> None:
    """Split the merge at its load: the code after the load moves to a new λ,
    and the predecessors that know the value jump to a copy of the merge that
    takes it as a parameter. Both copies jump to the new λ, so nothing after
    the load is repeated."""
    load = merge.body[at]
    head, rest = merge.body[:at + 1], merge.body[at + 1:]
    types = types_in(merge)
    defined = {o for i in rest for o in i.outs}
    live = list(dict.fromkeys(n for i in rest for n in i.ins if n not in defined))
    live = [n for n in live if types[n] != "heap"] + [n for n in live if types[n] == "heap"]

    lambdas = {lam.name for lam in s.lambdas}
    after = Lambda(fresh(lambdas, f"{merge.name}_after"), [(n, types[n]) for n in live], list(merge.outs), rest)
    jump = jump_to(s, after, live, fresh(names_in(merge), "k_after"))
    merge.body = head + jump

    value = fresh(names_in(merge), f"{load.outs[0]}_in")
    p = next((n for n, (_, t) in enumerate(merge.params) if t == "heap"), len(merge.params))
    copy = Lambda(fresh(lambdas, f"{merge.name}_known"),
                  [*merge.params[:p], (value, load.out_types[0]), *merge.params[p:]], list(merge.outs),
                  [copy_instr(i) for i in head[:-1]] + forwarding(load, value) + [copy_instr(i) for i in jump])
    place = next(n for n, lam in enumerate(s.lambdas) if lam is merge) + 1
    s.lambdas[place:place] = [copy, after]

    for ref, call, v in known:
        ref.op, ref.out_types = copy.name, [copy.function_type]
        call.type = copy.function_type
        call.ins = call.ins[:1 + p] + [v] + call.ins[1 + p:]
