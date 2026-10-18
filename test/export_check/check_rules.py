from collections import Counter
from pathlib import Path

from cthu import parser, prelude
from cthu.ir import Instr, Lambda, Program, Structure, to_text
from cthu.ssu import check
from effects.signatures import PARTITIONERS, analyse, no_analysis
from graal.graal_import import load
from graal2ct.translate import Translation
from rules import memory, shape, stores, tokens
from rules.compare import accesses, looping
from rules.decisions import dead_stores

DATA = Path(__file__).resolve().parent.parent / "data"
EXAMPLES = DATA / "examples.json"
SIGNATURES = DATA / "signatures.json"
ALIASING = DATA / "aliasing.json"  # exported with allocation sites


def translate(path: Path, partition: str) -> Program:
    facts, graphs = load(path)
    effects = no_analysis() if partition == "none" else analyse(facts, PARTITIONERS[partition](facts))
    return Translation(graphs, effects).translate(sorted(graphs))


def structure(program: Program, name: str) -> Structure:
    return next(s for s in program.structures if s.name == name)


def methods(rewrites: list[str]) -> set[str]:
    """The structures a list of rewrites names."""
    return {line.split(":")[0] for line in rewrites}


def within(rewrites: list[str]) -> list[str]:
    """The loads forwarded inside a λ, not across a merge or into an arm."""
    return [line for line in rewrites if ", " not in line]


def across_merges(rewrites: list[str]) -> dict[str, str]:
    """Structure → `k of n` for each load forwarded across a merge."""
    return {line.split(":")[0]: line.split("from ")[1].removesuffix(" predecessors") for line in rewrites if "merge" in line}


def root(lam: Lambda, name: str) -> str:
    """The value a name is a copy of, past the dups linearize added."""
    defs = {out: i for i in lam.body for out in i.outs}
    while name in defs and defs[name].op == "dup":
        name = defs[name].ins[0]
    return name


def cyclic(s: Structure) -> set[str]:
    """The λs that reach themselves through the λs they take."""
    refs = {l.name: {i.op for i in l.body if i.type == s.name} for l in s.lambdas}
    found = set()
    for start in refs:
        seen, work = set(), list(refs[start])
        while work:
            name = work.pop()
            if name == start:
                found.add(start)
                break
            if name not in seen:
                seen.add(name)
                work.extend(refs.get(name, ()))
    return found


def origin(lam: Lambda, name: str) -> Instr:
    """The instruction that defines a value, past the dups linearize added."""
    defs = {out: i for i in lam.body for out in i.outs}
    while defs[name].op == "dup":
        name = defs[name].ins[0]
    return defs[name]


def check_shape() -> None:
    """Before the rules, the program takes a shape in which more of it is
    local. A branch whose arm throws on every path becomes a guard on each
    token, which leaves the method where that arm would have run: a null
    check's, and a call's on the exception it gave back. A block that only one
    jump reaches joins the λ that jumps: forwardAcrossWritingCall, a null check
    and three blocks split at its call, becomes one λ, with the guards of the
    null check on counter and then those of the call. A merge stays a λ
    (deadStoreBothArms' b5, which both arms jump to), and so does a loop header
    (hoistLoadOutOfLoop keeps a λ that reaches itself)."""
    program = translate(EXAMPLES, "field")
    writing = [l.name for l in structure(program, "Examples_forwardAcrossWritingCall").lambdas]
    memory.apply(program)
    s = structure(program, "Examples_forwardAcrossWritingCall")
    assert {"b1", "b2", "b3"} <= set(writing) and [l.name for l in s.lambdas] == ["run"], (writing, s.lambdas)
    guards = [i for i in s.lambdas[0].body if i.op == "guard"]
    assert len(guards) == 6 and all(g.exit == "throws" for g in guards), guards
    null = origin(s.lambdas[0], guards[0].ins[1])  # it leaves when counter is null, as the arm did
    assert null.op == "nil?" and null.ins[0].split("_")[0] == "p0", null
    thrown = origin(s.lambdas[0], guards[3].ins[1])  # it leaves when the call gave back an exception
    assert thrown.op == "not" and origin(s.lambdas[0], thrown.ins[0]).op == "nil?", thrown

    assert "b5" in {l.name for l in structure(program, "Examples_deadStoreBothArms").lambdas}
    assert cyclic(structure(program, "Examples_hoistLoadOutOfLoop"))
    print("ok   null checks and calls' exceptions become guards, and straight-line blocks one λ; merges and loop headers stay")


def check_forwarding() -> None:
    """With a token per field, a load whose token comes straight from a store
    or a load of the same field of the same object takes that value: the load
    after the call in forwardAcrossCall, forwardAcrossWritingCall, where it is
    the 5 stored before the call, and repeatedLoadAcrossCall, and across the
    dispatch in forwardAcrossVirtualCall, whose two targets write nothing; in Signatures,
    after each call whose signature leaves Counter.value out. Not in the
    controls, whose callee writes Counter.value or whose load goes through
    another reference (forwardMaybeAliasControl), nor after a call that
    touches everything: a monitor, a volatile store, a native, an unresolved
    call. With one heap token every call takes the heap, so nothing is
    forwarded past one."""
    program = translate(EXAMPLES, "field")
    done = memory.apply(program)
    assert methods(within(done.forwarded)) == {"Examples_forwardAcrossCall", "Examples_forwardAcrossWritingCall",
                                               "Examples_repeatedLoadAcrossCall", "Examples_forwardAcrossVirtualCall"}, done.forwarded
    run = structure(program, "Examples_forwardAcrossWritingCall").lambdas[0]
    move = next(i for i in run.body if i.note.startswith("forwarded"))
    assert origin(run, move.ins[0]).op == "cons_5", move.text()

    done = memory.apply(translate(SIGNATURES, "field"))
    across = {f"Signatures_across{name}" for name in ("Field", "Array", "Allocation", "FinalField")}
    assert methods(done.forwarded) == across, done.forwarded

    for path in (EXAMPLES, SIGNATURES):
        done = memory.apply(translate(path, "none"))
        assert not within(done.forwarded), done.forwarded
    print("ok   per field, a load after a call that leaves its field alone takes the stored or loaded value; with one heap, none")


def check_forwarding_into_arms() -> None:
    """A load in a branch arm whose token and object come unchanged from above
    the branch takes the value from there, which the branch passes to both
    arms: in deadStoreReadInArm, the load in the flag arm takes the 1 stored
    before the branch, past a call that leaves Counter.value alone. So does
    the first iteration of forwardIntoLoopAliasControl's second loop, once it
    is peeled: there c is still counter, which was just given 3. Not in
    forwardIntoArmAliasControl, whose load goes through another reference, and
    with one heap token reads past a store to another field; nor in
    deadStoreReadInLoop, whose load is behind a loop header, a merge. With one
    heap token the call in deadStoreReadInArm takes the heap."""
    program = translate(EXAMPLES, "field")
    done = memory.apply(program)
    arms = [line for line in done.forwarded if "into a branch arm" in line]
    assert methods(arms) == {"Examples_deadStoreReadInArm", "Examples_forwardIntoLoopAliasControl"}, done.forwarded

    s = structure(program, "Examples_deadStoreReadInArm")
    arm, move = next((l, i) for l in s.lambdas for i in l.body if i.note.startswith("forwarded"))
    param = root(arm, move.ins[0])
    parent = next(l for l in s.lambdas for i in l.body if i.type == s.name and i.op == arm.name)
    passed = parent.body[-1].ins[1 + [n for n, _ in arm.params].index(param)]
    assert origin(parent, passed).op == "cons_1", (arm.name, param, passed)

    done = memory.apply(translate(EXAMPLES, "none"))
    arms = [line for line in done.forwarded if "into a branch arm" in line]
    assert methods(arms) == {"Examples_forwardIntoLoopAliasControl"}, done.forwarded  # no call in that loop
    print("ok   a load in a branch arm takes the value its token and object bring from above the branch")


def carried(program: Program, name: str) -> tuple[Lambda, str, Lambda, str, str]:
    """For the loop of method `name` whose load was forwarded: the λ that
    enters it and what it passes for the header's new parameter, and the body,
    what its back edge passes for it, and the body's own parameter for it."""
    s = structure(program, name)
    body, move = next((l, i) for l in s.lambdas for i in l.body if i.note.startswith("forwarded"))
    param = root(body, move.ins[0])
    header = next(l for l in s.lambdas if l is not body and any(i.op == body.name for i in l.body))
    at = [n for n, _ in header.params].index(root(header, header.body[-1].ins[1 + [n for n, _ in body.params].index(param)]))
    entry = next(l for l in s.lambdas if l is not body and any(i.op == header.name for i in l.body))
    return entry, entry.body[-1].ins[1 + at], body, root(body, body.body[-1].ins[1 + at]), param


def check_forwarding_into_loops() -> None:
    """A load in a loop takes the value known on entry to the loop when the
    back edge brings the field's value too. The header gets the value as a
    parameter: the entry passes it, the header's branch passes it to the body,
    and the body passes back what the next iteration reads. In
    deadStoreReadInLoop nothing in the loop writes Counter.value, so every
    iteration takes the 1 stored before the loop, and the body passes back
    what it got. In forwardAcrossIterations the body stores i after the load,
    so the header's parameter is a loop-carried phi: the 1 on entry, then the
    i the iteration before stored. Not in forwardAcrossIterationsAliasControl,
    whose loop stores through another reference, nor in
    forwardIntoLoopAliasControl: before its first loop the store goes through
    another reference, followed with one heap token by a store to another
    field, and its second loop's object changes after the first iteration.
    With one heap token, the call in each loop takes the heap."""
    program = translate(EXAMPLES, "field")
    done = memory.apply(program)
    loops = [line for line in done.forwarded if "into a loop" in line]
    assert methods(loops) == {"Examples_deadStoreReadInLoop", "Examples_forwardAcrossIterations"}, done.forwarded

    entry, passed, body, back, param = carried(program, "Examples_deadStoreReadInLoop")
    assert origin(entry, passed).op == "cons_1" and back == param, (passed, back, param)  # passed back unchanged
    entry, passed, body, back, param = carried(program, "Examples_forwardAcrossIterations")
    assert origin(entry, passed).op == "cons_1", passed
    assert back != param and dict(body.params)[back] == "int", (back, param)  # the i the body stored

    done = memory.apply(translate(EXAMPLES, "none"))
    assert not [line for line in done.forwarded if "into a loop" in line], done.forwarded
    print("ok   a load in a loop takes the value known on entry, which lasts or a loop-carried phi updates")


def check_hoisting_out_of_loops() -> None:
    """A load in a loop whose back edge brings the field's value, but whose
    value no entry knows, leaves the loop: the first iteration is peeled, its
    copy of the load runs before the loop, and the loop takes what that
    iteration leaves for the next. In hoistLoadOutOfLoop nothing in the loop
    writes Counter.value, so that is the value the copy of the load read: the
    one load left is the peeled iteration's, outside the loop. In
    forwardAcrossIterationsPeeled the loop stores i, so the loop takes the i
    the peeled iteration stored, as a phi. Each store stays, since the call in
    the next iteration may throw before the store that overwrites it.
    The first loop of forwardIntoLoopAliasControl, which only reads
    Counter.value, leaves too, and so does its second, whose object c is
    counter only in the first iteration and alias after: once that iteration
    is peeled, c and alias are the same parameter of the loop, and the second
    iteration is peeled for its load. Nor do the loops of
    hoistLoadOutOfLoopControl, whose call writes Counter.value,
    and forwardAcrossIterationsAliasControl, which stores through another
    reference, while forwardAcrossIterations' loop keeps no load, and its store.
    With one heap token the call in each takes the heap, and only the first
    loop of forwardIntoLoopAliasControl, with no call in it, leaves."""
    program = translate(EXAMPLES, "field")
    done = memory.apply(program)
    hoisted = [line for line in done.forwarded if "out of a loop" in line]
    assert methods(hoisted) == {"Examples_hoistLoadOutOfLoop", "Examples_forwardIntoLoopAliasControl",
                                "Examples_forwardAcrossIterationsPeeled"}, done.forwarded
    in_loops, left = accesses(program, in_loops=True), accesses(program)
    expected = {"Examples_hoistLoadOutOfLoop": (0, 0), "Examples_forwardIntoLoopAliasControl": (0, 0),
                "Examples_hoistLoadOutOfLoopControl": (0, 1), "Examples_forwardAcrossIterationsAliasControl": (1, 1),
                "Examples_forwardAcrossIterations": (1, 0), "Examples_forwardAcrossIterationsPeeled": (1, 0)}
    assert {name: in_loops[name] for name in expected} == expected, in_loops
    assert left["Examples_hoistLoadOutOfLoop"] == (0, 1), left["Examples_hoistLoadOutOfLoop"]
    assert left["Examples_forwardAcrossIterationsPeeled"] == (3, 1), left["Examples_forwardAcrossIterationsPeeled"]
    settled = [line for line in hoisted if "two iterations" in line]
    assert methods(settled) == {"Examples_forwardIntoLoopAliasControl"} and len(settled) == 1, hoisted

    first, passed, body, back, param = carried(program, "Examples_forwardAcrossIterationsPeeled")
    started = root(first, passed)  # the i the peeled iteration stored, not what it loaded
    peeled = structure(program, "Examples_forwardAcrossIterationsPeeled")
    assert dict(first.params).get(started) == "int" and first.name not in looping(peeled), started
    assert back != param and dict(body.params)[back] == "int", (back, param)  # the i each iteration stored

    s = structure(program, "Examples_hoistLoadOutOfLoop")
    body, move = next((l, i) for l in s.lambdas for i in l.body if i.note.startswith("forwarded"))
    param = root(body, move.ins[0])
    header = next(l for l in s.lambdas if l is not body and any(i.op == body.name for i in l.body))
    at = [n for n, _ in header.params].index(root(header, header.body[-1].ins[1 + [n for n, _ in body.params].index(param)]))
    first = next(l for l in s.lambdas if l is not body and any(i.op == header.name for i in l.body))
    load = origin(first, first.body[-1].ins[1 + at])
    assert load.op.startswith("get_") and first.name not in looping(s), (first.name, load.text())

    done = memory.apply(translate(EXAMPLES, "none"))
    hoisted = [line for line in done.forwarded if "out of a loop" in line]
    assert methods(hoisted) == {"Examples_forwardIntoLoopAliasControl"}, done.forwarded
    print("ok   a load in a loop that nothing in the loop changes leaves it, after the first iteration is peeled")


def check_forwarding_across_merges() -> None:
    """A load after a merge takes the value its predecessors stored or loaded:
    those that know it get a copy of the merge, up to the load, which takes the
    value as a parameter, and both copies go on to the code after the load. In
    forwardAcrossMerge both arms store, and the call in one leaves
    Counter.value alone, so the load goes. In deadStoreReadAfterMerge only the
    arm that stores knows the value, so the load goes on its path and stays on
    the other. That arm's store is then overwritten, but stays: the null check
    after the merge may throw first, though it repeats an earlier one, which
    Graal sees, keeping one store. In forwardAcrossMergeAliasControl the second arm stores
    through another reference, and with one heap token then to another field,
    so its path keeps the load. With one heap token, the call in
    forwardAcrossMerge takes the heap, so only the arm without it knows the
    value."""
    program = translate(EXAMPLES, "field")
    done = memory.apply(program)
    assert across_merges(done.forwarded) == {"Examples_forwardAcrossMerge": "2 of 2",
                                             "Examples_deadStoreReadAfterMerge": "1 of 2",
                                             "Examples_forwardAcrossMergeAliasControl": "1 of 2"}, done.forwarded
    left = accesses(program)
    assert left["Examples_forwardAcrossMerge"][1] == 0, left["Examples_forwardAcrossMerge"]
    assert left["Examples_deadStoreReadAfterMerge"] == (2, 1), left["Examples_deadStoreReadAfterMerge"]
    assert left["Examples_forwardAcrossMergeAliasControl"][1] == 1, left["Examples_forwardAcrossMergeAliasControl"]

    done = memory.apply(translate(EXAMPLES, "none"))
    assert across_merges(done.forwarded) == {"Examples_forwardAcrossMerge": "1 of 2",
                                             "Examples_deadStoreReadAfterMerge": "1 of 2"}, done.forwarded
    print("ok   a load after a merge takes the value of the predecessors that know it, all of them or some")


def check_dead_stores() -> None:
    """A store goes when every path its token takes overwrites the same field
    of the same object before anything can read it. A path that throws leaves
    the method with every token, as one that returns does, and a handler up
    the stack may read the store on it: a guard, where the method may leave so,
    stands in the way, and so does an allocation, which may throw
    OutOfMemoryError. Per field three stores are dead: the first of
    deadStoreOtherField and of deadStoreOtherObject, and the first of
    deadStoreBothArms, which both arms overwrite. Once loads are forwarded, more
    stores are overwritten, but something that may throw comes first:
    length(list) in deadStoreReadInArm, deadStoreReadInLoop and the
    forwardAcrossIterations pairs, the null check after the merge in
    deadStoreReadAfterMerge. Not in the controls: a load through another
    reference may read it (deadStoreMaybeAliasControl), a store through
    another reference may not overwrite it (deadStoreMaybeAliasStoreControl),
    and one arm leaves it to the caller (deadStoreOneArm). With one heap token
    the store to another field stands in the way of the first two.

    Without forwarding the same three are dead, so none needs a load the
    rules took away: rules.decisions gives Graal exactly these, by where they
    are. In Aliasing, with objects told apart, deadStorePastOtherObject's first
    store is dead too. When the arm of deadStoreOneArm that doesn't store
    throws instead, its store stays; when it traps, which stops the program,
    nothing reads the store after, and it goes."""
    dead = {"Examples_deadStoreOtherField", "Examples_deadStoreOtherObject", "Examples_deadStoreBothArms"}
    for forward in (True, False):
        done = memory.apply(translate(EXAMPLES, "field"), forward=forward)
        assert methods(done.removed) == dead and len(done.removed) == 3, (forward, done.removed)
    done = memory.apply(translate(EXAMPLES, "none"))
    assert methods(done.removed) == {"Examples_deadStoreBothArms"}, done.removed

    e = "Examples"
    assert dead_stores(EXAMPLES) == [f"{e}.deadStoreBothArms(L{e}$Counter;Z)V:2\t{e}$Counter.value",
                                     f"{e}.deadStoreOtherField(L{e}$Counter;)V:2\t{e}$Counter.value",
                                     f"{e}.deadStoreOtherObject(L{e}$Counter;L{e}$Logger;)V:7\t{e}$Counter.value"], dead_stores(EXAMPLES)
    done = memory.apply(translate(ALIASING, "object-field"))
    assert methods(done.removed) == {"Aliasing_deadStorePastOtherObject"}, done.removed

    for noted in (False, True):  # as it is, or once the rules make a guard of the branch to it
        assert "Examples_deadStoreOneArm" not in methods(memory.apply(leaving_arm("throws", noted)).removed), noted
        assert "Examples_deadStoreOneArm" in methods(memory.apply(leaving_arm("traps", noted)).removed), noted

    # What may throw stands in the way on any token: a guard, unless its arm
    # traps, and an allocation. The translation's guards take every token, so
    # build one on another token by hand, between the two stores of
    # deadStoreOtherField to Counter.value.
    def between(op: str, how: str = "") -> Structure:
        s = structure(translate(EXAMPLES, "field"), "Examples_deadStoreOtherField")
        for lam in s.lambdas:
            shape.unshare(lam)
        shape.guard_exits(s)
        shape.fuse(s)
        shape.remove_unreferenced(s)
        body = s.lambdas[0].body
        first = next(n for n, i in enumerate(body) if i.op.startswith("set_") and i.field.endswith(".value"))
        other = next(i for i in body if i.op.startswith("set_") and i.field.endswith(".other"))
        cond = next(i for i in body if i.op == "guard").ins[1]
        made = Instr("heap", "guard", [other.ins[0], cond], ["h_other_2"], ["heap"], exit=how) if op == "guard" else \
            Instr("heap", op, [other.ins[0]], ["v_new", "h_other_2"], ["ref", "heap"])
        body.insert(first + 1, made)
        other.ins[0] = "h_other_2"
        return s

    assert stores.remove_dead_stores(between("guard", "throws")) == []
    assert len(stores.remove_dead_stores(between("guard", "traps"))) == 1
    assert stores.remove_dead_stores(between("new_0")) == []
    print("ok   a store every path overwrites goes, unless something that may throw comes first: three per field,"
          " the same without forwarding, which rules.decisions gives Graal by where they are")


def leaving_arm(how: str, noted: bool = False) -> Program:
    """Examples per field, with the arm of deadStoreOneArm that doesn't store
    leaving the method instead: throwing an exception, or trapping. Noted, the
    arm says so, as the translation's do, and the rules make a guard of the
    branch to it."""
    program = translate(EXAMPLES, "field")
    s = structure(program, "Examples_deadStoreOneArm")
    arm = next(l for l in s.lambdas if l.name.startswith("b") and len(l.params) == 2 and not l.exit
               and not any(i.op.startswith("set_") for i in l.body))
    (reference, _), (token, _), (exc, _), (out, _) = *arm.params, *arm.outs
    leave = ([Instr("ref", "exception", [], [exc], ["ref"]), Instr("heap", "move", [token], [out], ["heap"])]
             if how == "throws" else
             [Instr("heap", "trap", [token]), Instr("ref", "bot", [], [exc], ["ref"]), Instr("heap", "bot", [], [out], ["heap"])])
    arm.body = [Instr("ref", "drop", [reference]), *leave]
    arm.exit = how if noted else ""
    assert not check(program), check(program)
    return program


def check_object_partitions_tell_objects_apart() -> None:
    """Each method of Aliasing touches two counters that main allocates apart.
    Per field the rules can't tell them apart and leave every load and store.
    With object partitions, from the allocation-site export, the loads of
    forwardPastOtherObject and forwardAcrossCallOnOtherObject take the stored
    value, forwardIntoLoopPastOtherObject's leaves its loop, and
    deadStorePastOtherObject's first store goes, legal in Java since nothing
    between it and the next store can throw. Each control, also called with
    one counter twice, keeps everything."""
    per_field = {"forwardPastOtherObject": (2, 1), "deadStorePastOtherObject": (2, 2),
                 "forwardIntoLoopPastOtherObject": (2, 1), "forwardAcrossCallOnOtherObject": (1, 1)}
    per_object = {"forwardPastOtherObject": (2, 0), "deadStorePastOtherObject": (1, 2),
                  "forwardIntoLoopPastOtherObject": (2, 0), "forwardAcrossCallOnOtherObject": (1, 0)}
    controls = {"forwardPastAliasControl": (2, 1), "deadStorePastAliasControl": (2, 2),
                "forwardIntoLoopPastAliasControl": (2, 1), "forwardAcrossCallOnAliasControl": (1, 1)}
    for partition in ("field", "object", "object-field"):
        program = translate(ALIASING, partition)
        memory.apply(program)
        left = {name.removeprefix("Aliasing_"): n for name, n in accesses(program).items()}
        expected = (per_field if partition == "field" else per_object) | controls
        assert {m: left[m] for m in expected} == expected, (partition, left)
        loop = accesses(program, in_loops=True)["Aliasing_forwardIntoLoopPastOtherObject"]
        assert loop == ((1, 1) if partition == "field" else (1, 0)), (partition, loop)
    print("ok   object partitions: loads past another object's store, and across a call that writes only other"
          " objects, take the value; a store past another object's load goes; the controls keep everything")


def check_finer_partitions_leave_no_more() -> None:
    """A finer partitioning licenses every rewrite a coarser one does (the
    monotonicity theorem of the thesis's chapter on explicit effects):
    object-field refines field and object, and both refine one heap. The rules
    apply what is licensed under bounds that count instructions, and a finer
    partitioning has more tokens to guard, so this is checked, not given: on
    every fixture, every store and load of a method that a finer partitioning
    keeps, a coarser one keeps too. A store or a load counts as gone only when
    every copy the rules made of it went: peeling copies a loop's first
    iteration, stores included, and a store that the next iteration's call may
    throw before stays in both copies. The loops keep no more under a finer
    partitioning, and every store dead in Java under a coarser one is dead
    under the finer. Each finer partitioning leaves fewer somewhere."""
    def kept(program: Program) -> dict[str, set[str]]:
        """Structure → where the stores and loads are that some copy of is left."""
        return {s.name: {f"{m.group(1)} {i.at}\t{i.field}" for lam in s.lambdas for i in lam.body
                         if i.type == "heap" and (m := tokens.ACCESS.fullmatch(i.op)) and m.group(1) in ("get", "set")}
                for s in program.structures}

    def java_dead(path: Path, partition: str) -> set[str]:
        program = translate(path, partition)
        done = memory.apply(program, forward=False)
        left = {f"{i.at}\t{i.field}" for s in program.structures for lam in s.lambdas for i in lam.body
                if (m := tokens.ACCESS.fullmatch(i.op)) and m.group(1) == "set" and i.at}
        return set(done.dead) - left

    finer = [("field", "none"), ("object", "none"), ("object-field", "field"), ("object-field", "object")]
    fewer: Counter = Counter()
    for path in (EXAMPLES, SIGNATURES, ALIASING):
        left, loops, dead = {}, {}, {}
        for partition in ("none", "field", "object", "object-field"):
            program = translate(path, partition)
            memory.apply(program)
            left[partition], loops[partition] = kept(program), accesses(program, in_loops=True)
            dead[partition] = java_dead(path, partition)
        for fine, coarse in finer:
            for s in left[fine].keys() & left[coarse].keys():
                assert left[fine][s] <= left[coarse][s], (path.name, fine, coarse, s, left[fine][s] - left[coarse][s])
                assert all(a <= b for a, b in zip(loops[fine][s], loops[coarse][s])), \
                    (path.name, fine, coarse, s, loops[fine][s], loops[coarse][s])
                fewer[fine, coarse] += left[fine][s] != left[coarse][s] or loops[fine][s] != loops[coarse][s]
            assert dead[coarse] <= dead[fine], (path.name, fine, coarse, dead[coarse] - dead[fine])
    assert all(fewer[pair] for pair in finer), fewer
    print("ok   a finer partitioning keeps no store or load a coarser one removes, keeps no more in loops, and keeps"
          " every dead store in Java; each leaves fewer somewhere")


def check_rewritten_programs_stay_valid() -> None:
    """After the rules, every program of the fixtures, under every
    partitioning, still passes the single-use and type checks, which include
    that a branch's frame is for arms of its type, and its text parses back. A
    second pass finds nothing more."""
    graal = prelude.load()
    for path in (EXAMPLES, SIGNATURES, ALIASING):
        for partition in ("none", "field", "object", "object-field"):
            program = translate(path, partition)
            memory.apply(program)
            errors = check(program) + prelude.check(program, graal)
            assert not errors, (path.name, partition, errors[:5])
            module = parser.parse(to_text(program))
            assert list(module.structures) == [s.name for s in program.structures]
            again = memory.apply(program)
            assert not again.forwarded and not again.removed, (path.name, partition, again)
    print("ok   rewritten programs pass the single-use and type checks and parse back; a second pass changes nothing")


if __name__ == "__main__":
    check_shape()
    check_forwarding()
    check_forwarding_into_arms()
    check_forwarding_into_loops()
    check_hoisting_out_of_loops()
    check_forwarding_across_merges()
    check_dead_stores()
    check_object_partitions_tell_objects_apart()
    check_finer_partitions_leave_no_more()
    check_rewritten_programs_stay_valid()
    print("all checks passed")
